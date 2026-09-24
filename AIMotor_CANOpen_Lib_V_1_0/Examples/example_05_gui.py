"""Example 5 - desktop GUI for both AIMOTOR drives.

    python example_05_gui.py
    python example_05_gui.py --motors Left Right
    python example_05_gui.py --motor Left          # single panel

Tkinter only, no extra dependencies.

THIS CAN MOVE THE MOTORS. Arming asks for confirmation, the big STOP stops
every motor at any time, and closing the window stops and disarms both.

Design: all CAN work happens on ONE background thread (CanWorker) that owns a
Motor_Group, so both buses are torn down in a known order. The GUI never
touches the bus - it posts commands to a queue and reads results from another
queue, because Tk widgets may only be touched from the main thread. Every
per-motor command and event carries a "motor" key; "*" means all of them.
"""

import argparse
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import _bootstrap  # noqa: F401  (puts the library on sys.path)

POLL_UI_MS = 100

COLOR_BG = "#1e1f22"
COLOR_PANEL = "#2b2d31"
COLOR_TEXT = "#e6e6e6"
COLOR_MUTED = "#9aa0a6"
COLOR_OK = "#3fb950"
COLOR_WARN = "#d29922"
COLOR_FAULT = "#f85149"
COLOR_ACCENT = "#58a6ff"

ALL = "*"


class CanWorker(threading.Thread):
    """Owns the Motor_Group. Talks to the GUI by queue."""

    def __init__(self, commands: queue.Queue, events: queue.Queue, config_path=None,
                 profile=None, motor_names=None):
        super().__init__(daemon=True, name="can-worker")
        self.commands = commands
        self.events = events
        self.config_path = config_path
        self.profile = profile
        self.motor_names = motor_names or []

        self.config = None
        self.group = None
        self.connected = False
        self.armed = {}
        self.poll_period = 0.2
        self._running = True

    # ------------------------------------------------------------- plumbing

    def emit(self, kind, payload=None):
        self.events.put((kind, payload))

    def log(self, message, level="info"):
        self.emit("log", {"text": message, "level": level})

    def run(self):
        next_poll = 0.0
        while self._running:
            try:
                command, args = self.commands.get(timeout=0.05)
            except queue.Empty:
                command, args = None, None
            if command:
                try:
                    self.handle(command, args)
                except Exception as e:
                    self.log(str(e), "error")
                    self.emit("busy", False)
            if self.connected and self.group is not None and time.time() >= next_poll:
                next_poll = time.time() + self.poll_period
                for name, motor in list(self.group):
                    try:
                        data = dict(motor.snapshot())
                        data["motor"] = name
                        self.emit("feedback", data)
                    except Exception as e:
                        self.log("Feedback error [" + name + "]: " + str(e), "error")
        self.shutdown()
        self.emit("shutdown_done", None)

    def handle(self, command, args):
        handler = getattr(self, "cmd_" + command, None)
        if handler is None:
            self.log("Unknown command: " + str(command), "error")
            return
        handler(args or {})

    def targets(self, args) -> list:
        """Which motors a command applies to. Missing or '*' means all."""
        if self.group is None:
            return []
        name = (args or {}).get("motor", ALL)
        if name in (ALL, None):
            return self.group.online()
        return [name] if name in self.group else []

    def per_motor(self, args, action, label, level_ok="info"):
        """Run one action per target motor; one failure never blocks the rest."""
        for name in self.targets(args):
            try:
                ok = action(self.group[name], name)
                self.log("[" + name + "] " + label + ("" if ok is not False else " FAILED"),
                         level_ok if ok is not False else "error")
            except Exception as e:
                self.log("[" + name + "] " + label + " error: " + str(e), "error")

    # ------------------------------------------------------------- commands

    def cmd_connect(self, args):
        from AIMotor_CANOpen_Lib_V_1_0.Housekeeping.Config_Lib import Config
        from AIMotor_CANOpen_Lib_V_1_0.Motor_Control.Motor_Group_Lib import Motor_Group

        self.emit("busy", True)
        self.config = Config(self.config_path, profile=self.profile)
        names = self.motor_names or self.config.motor_names(enabled_only=True)
        for warning in getattr(self.config, "warnings", []):
            self.log(warning, "warn")

        self.log("Opening " + str(len(set(self.config.motor_adapter(n, self.profile)
                                          for n in names))) + " bus(es) for " +
                 ", ".join(names))
        self.group = Motor_Group(self.config, names=names, profile=self.profile, strict=False)
        self.connected = True
        self.armed = {name: False for name in self.group.online()}

        periods = [float(self.group[n].settings.feedback.get("poll_period_s", 0.2))
                   for n in self.group.online()] or [0.2]
        self.poll_period = max(0.2, min(periods))

        for name in self.group.online():
            motor = self.group[name]
            self.emit("motor_online", {
                "motor": name,
                "node_id": motor.Node_ID,
                "adapter": self.group.adapter_of(name),
                "max_rpm": float(motor.settings.limits.get("max_velocity_rpm", 3000.0)),
                "mode": motor.mode.current if motor.mode else None,
            })
            self.log("[" + name + "] online: node " + str(motor.Node_ID) + " on " +
                     self.group.adapter_of(name), "ok")
        for name, error in self.group.failures.items():
            self.emit("motor_offline", {"motor": name, "error": str(error)})
            self.log("[" + name + "] offline: " + str(error), "error")

        self.emit("connected", {"motors": self.group.online(),
                                "pairing": self.config.pairing()})
        self.cmd_preflight({"motor": ALL})
        self.emit("busy", False)

    def cmd_preflight(self, args):
        for name in self.targets(args):
            report = self.group[name].preflight()
            for problem in report.get("problems", []):
                self.log("[" + name + "] " + problem, "error")
            self.log("[" + name + "] preflight " + ("PASS" if report["ok"] else "FAIL") +
                     " - state " + str(report["state"]) + ", H02-00 " + str(report["H02_00"]),
                     "ok" if report["ok"] else "error")
            report["motor"] = name
            self.emit("preflight", report)

    def cmd_arm(self, args):
        self.emit("busy", True)
        for name in self.targets(args):
            self.log("[" + name + "] arming - the motor becomes energised", "warn")
            ok = bool(self.group[name].arm())
            self.armed[name] = ok
            self.emit("armed", {"motor": name, "armed": ok})
            self.log("[" + name + "] " + ("ARMED" if ok else "ARM failed"),
                     "ok" if ok else "error")
        self.emit("busy", False)

    def cmd_disarm(self, args):
        self.emit("busy", True)
        for name in self.targets(args):
            try:
                self.group[name].stop()
                ok = self.group[name].disarm()
            except Exception as e:
                ok = False
                self.log("[" + name + "] disarm error: " + str(e), "error")
            self.armed[name] = False
            self.emit("armed", {"motor": name, "armed": False})
            self.emit("target", {"motor": name, "rpm": 0.0})
            self.log("[" + name + "] disarmed" if ok else "[" + name + "] disarm had errors",
                     "ok" if ok else "error")
        self.emit("busy", False)

    def cmd_stop(self, args):
        """Zero the setpoint. Stays enabled, and always works."""
        for name in self.targets(args):
            try:
                self.group[name].stop()
                self.emit("target", {"motor": name, "rpm": 0.0})
                self.log("[" + name + "] STOP - setpoint zeroed", "warn")
            except Exception as e:
                self.log("[" + name + "] STOP error: " + str(e), "error")

    def cmd_quick_stop(self, args):
        for name in self.targets(args):
            self.group[name].quick_stop()
            self.armed[name] = False
            self.emit("armed", {"motor": name, "armed": False})
            self.log("[" + name + "] QUICK STOP", "warn")

    def cmd_fault_reset(self, args):
        self.per_motor(args, lambda m, n: m.fault_reset(), "fault reset", "ok")

    def cmd_velocity(self, args):
        rpm = float(args.get("rpm", 0.0))
        for name in self.targets(args):
            motor = self.group[name]
            if motor.velocity is None:
                self.log("[" + name + "] velocity mode is not active", "error")
                continue
            pulps = motor.velocity.RUN_rpm(rpm)
            if pulps is None:
                self.log("[" + name + "] velocity command failed", "error")
                continue
            actual = motor.units.pulps_to_rpm(pulps)
            self.emit("target", {"motor": name, "rpm": actual})
            self.log("[" + name + "] target %.1f rpm (%d pul/s)" % (actual, pulps))

    def cmd_pair_velocity(self, args):
        """Differential drive: both motors in one worker-side call."""
        forward = float(args.get("forward", 0.0))
        turn = float(args.get("turn", 0.0))
        invert = args.get("invert")
        results = self.group.drive(forward, turn, invert_right=invert)
        for name, pulps in results.items():
            if pulps is None:
                continue
            actual = self.group[name].units.pulps_to_rpm(pulps)
            self.emit("target", {"motor": name, "rpm": actual})
        self.log("Paired drive: forward %.1f rpm, turn %.1f rpm -> %s"
                 % (forward, turn, {k: v for k, v in results.items()}))

    def cmd_mode(self, args):
        mode = int(args.get("mode"))
        for name in self.targets(args):
            if self.armed.get(name):
                self.log("[" + name + "] disarm before changing mode", "error")
                continue
            ok = self.group[name].mode.switch_to(mode)
            self.emit("mode", {"motor": name, "mode": self.group[name].mode.current})
            self.log("[" + name + "] mode set to " + str(self.group[name].mode.current),
                     "ok" if ok else "error")

    def cmd_disconnect(self, args):
        self.shutdown()
        self.emit("disconnected", None)
        self.log("Disconnected")

    def cmd_quit(self, args):
        self._running = False

    # -------------------------------------------------------------- cleanup

    def shutdown(self):
        """Group teardown: every motor disarmed before any bus is closed."""
        try:
            if self.group is not None:
                self.group.close_all()
        except Exception as e:
            self.log("Shutdown error: " + str(e), "error")
        self.group = None
        self.connected = False
        self.armed = {}


class MotorPanel():
    """One motor: its own controls and feedback fields."""

    FIELDS = [
        ("state", "State"),
        ("statusword_hex", "Status word"),
        ("mode_display", "Mode"),
        ("position_pul", "Position [pul]"),
        ("position_rev", "Position [rev]"),
        ("velocity_rpm", "Velocity [rpm]"),
        ("torque_percent", "Torque [% rated]"),
        ("torque_nm", "Torque [Nm]"),
        ("phase_current_a", "Phase current [A]"),
        ("bus_voltage_v", "Bus voltage [V]"),
        ("module_temperature_c", "Temperature [C]"),
        ("error_code", "Error code"),
        ("fault_code", "Fault code"),
        ("heartbeat_state", "Heartbeat"),
    ]

    def __init__(self, parent, name, send):
        self.name = name
        self.send = send
        self.online = False
        self.armed = False
        self.max_rpm = 3000.0
        self.value_labels = {}
        self._last_sent_rpm = None

        self.frame = ttk.LabelFrame(parent, text=name)
        self.info = tk.Label(self.frame, text="not connected", bg=COLOR_PANEL, fg=COLOR_MUTED,
                             font=("Segoe UI", 9))
        self.info.grid(row=0, column=0, columnspan=4, sticky="w", padx=8, pady=(4, 2))

        controls = ttk.Frame(self.frame)
        controls.grid(row=1, column=0, columnspan=4, sticky="we", padx=4, pady=2)
        self.arm_btn = ttk.Button(controls, text="ARM", width=8, command=self.on_arm)
        self.arm_btn.grid(row=0, column=0, padx=2)
        self.disarm_btn = ttk.Button(controls, text="Disarm", width=8,
                                     command=lambda: self.send("disarm", motor=self.name))
        self.disarm_btn.grid(row=0, column=1, padx=2)
        self.fault_btn = ttk.Button(controls, text="Fault reset", width=11,
                                    command=lambda: self.send("fault_reset", motor=self.name))
        self.fault_btn.grid(row=0, column=2, padx=2)
        self.mode_var = tk.StringVar(value="3 - PV velocity")
        self.mode_box = ttk.Combobox(controls, textvariable=self.mode_var, width=15,
                                     state="readonly",
                                     values=["3 - PV velocity", "1 - PP position",
                                             "4 - PT torque"])
        self.mode_box.grid(row=0, column=3, padx=6)
        self.mode_box.bind("<<ComboboxSelected>>", self.on_mode)
        self.armed_label = tk.Label(controls, text="DISARMED", bg=COLOR_PANEL, fg=COLOR_MUTED,
                                    font=("Segoe UI", 10, "bold"))
        self.armed_label.grid(row=0, column=4, padx=8)

        speed = ttk.Frame(self.frame)
        speed.grid(row=2, column=0, columnspan=4, sticky="we", padx=4, pady=2)
        self.speed_var = tk.DoubleVar(value=0.0)
        self.slider = tk.Scale(speed, from_=-self.max_rpm, to=self.max_rpm, resolution=10,
                               orient="horizontal", length=330, variable=self.speed_var,
                               bg=COLOR_PANEL, fg=COLOR_TEXT, highlightthickness=0,
                               troughcolor=COLOR_BG, activebackground=COLOR_ACCENT,
                               sliderlength=26, label="rpm")
        self.slider.grid(row=0, column=0, columnspan=3, sticky="we", padx=4)
        self.slider.bind("<ButtonRelease-1>", lambda e: self.on_slider())
        self.speed_entry = ttk.Entry(speed, width=9)
        self.speed_entry.insert(0, "0")
        self.speed_entry.grid(row=1, column=0, padx=4, sticky="w")
        self.speed_entry.bind("<Return>", lambda e: self.on_entry())
        self.send_btn = ttk.Button(speed, text="Send", width=7, command=self.on_entry)
        self.send_btn.grid(row=1, column=1, sticky="w")
        self.target_label = tk.Label(speed, text="target 0.0 rpm", bg=COLOR_PANEL,
                                     fg=COLOR_ACCENT, font=("Segoe UI", 9))
        self.target_label.grid(row=1, column=2, sticky="w", padx=8)

        fields = ttk.Frame(self.frame)
        fields.grid(row=3, column=0, columnspan=4, sticky="we", padx=4, pady=(4, 6))
        for i, (key, label) in enumerate(self.FIELDS):
            row, col = i % 7, i // 7
            ttk.Label(fields, text=label, foreground=COLOR_MUTED).grid(
                row=row, column=col * 2, sticky="w", padx=(6, 4), pady=1)
            value = tk.Label(fields, text="-", bg=COLOR_PANEL, fg=COLOR_TEXT,
                             font=("Consolas", 9), anchor="w", width=17)
            value.grid(row=row, column=col * 2 + 1, sticky="w", padx=(0, 10))
            self.value_labels[key] = value
        self.update_widget_states()

    # ------------------------------------------------------------- actions

    def on_arm(self):
        if not messagebox.askokcancel(
                "Arm " + self.name,
                "The " + self.name + " motor will be energised and can start turning.\n\n"
                "Check the shaft is clear and the motor is secured.\n\nContinue?"):
            return
        self.send("arm", motor=self.name)

    def on_mode(self, event=None):
        self.send("mode", motor=self.name, mode=int(self.mode_var.get().split(" ")[0]))

    def on_slider(self):
        rpm = float(self.speed_var.get())
        self.speed_entry.delete(0, "end")
        self.speed_entry.insert(0, str(rpm))
        self._send_rpm(rpm)

    def on_entry(self):
        try:
            rpm = float(self.speed_entry.get())
        except ValueError:
            return
        self.speed_var.set(max(-self.max_rpm, min(self.max_rpm, rpm)))
        self._send_rpm(rpm)

    def _send_rpm(self, rpm):
        if not self.armed and rpm != 0:
            self.send("_log", text="[" + self.name + "] arm before commanding a speed",
                      level="warn")
            return
        if rpm == self._last_sent_rpm:
            return
        self._last_sent_rpm = rpm
        self.send("velocity", motor=self.name, rpm=rpm)

    def zero_slider(self):
        self.speed_var.set(0.0)
        self.speed_entry.delete(0, "end")
        self.speed_entry.insert(0, "0")
        self._last_sent_rpm = None

    # -------------------------------------------------------------- display

    def set_online(self, online, info_text="", error=""):
        self.online = bool(online)
        if online:
            self.info.configure(text=info_text, fg=COLOR_OK)
        else:
            self.info.configure(text=("offline: " + error) if error else "not connected",
                                fg=COLOR_FAULT if error else COLOR_MUTED)
            self.clear()
        self.update_widget_states()

    def set_max_rpm(self, value):
        self.max_rpm = float(value)
        self.slider.configure(from_=-self.max_rpm, to=self.max_rpm)

    def set_armed(self, armed):
        self.armed = bool(armed)
        self.armed_label.configure(text="ARMED" if armed else "DISARMED",
                                   fg=COLOR_FAULT if armed else COLOR_MUTED)
        if not armed:
            self._last_sent_rpm = None
        self.update_widget_states()

    def set_target(self, rpm):
        self.target_label.configure(text="target %.1f rpm" % float(rpm))

    def set_mode(self, mode):
        for text in self.mode_box["values"]:
            if text.startswith(str(mode)):
                self.mode_var.set(text)
                return

    def show_feedback(self, data):
        for key, _ in self.FIELDS:
            value = data.get(key)
            if key in ("error_code", "fault_code") and isinstance(value, int):
                text = "0x%04X" % value
            elif isinstance(value, float):
                text = "%.2f" % value
            else:
                text = str(value)
            self.value_labels[key].configure(text=text)
        state_label = self.value_labels["state"]
        if data.get("fault"):
            state_label.configure(fg=COLOR_FAULT)
        elif data.get("state") == "OPERATION_ENABLED":
            state_label.configure(fg=COLOR_OK)
        else:
            state_label.configure(fg=COLOR_TEXT)
        for key in ("error_code", "fault_code"):
            self.value_labels[key].configure(
                fg=COLOR_FAULT if data.get(key) else COLOR_TEXT)

    def clear(self):
        for label in self.value_labels.values():
            label.configure(text="-", fg=COLOR_TEXT)
        self.set_armed(False)
        self.zero_slider()

    def update_widget_states(self):
        on = "normal" if self.online else "disabled"
        for widget in (self.disarm_btn, self.fault_btn, self.send_btn, self.speed_entry):
            widget.configure(state=on)
        self.slider.configure(state=on)
        self.mode_box.configure(state="readonly" if self.online else "disabled")
        self.arm_btn.configure(state="disabled" if (self.armed or not self.online) else "normal")


class MotorGUI():
    def __init__(self, root, args):
        self.root = root
        self.args = args
        self.commands = queue.Queue()
        self.events = queue.Queue()

        self.motor_names = self._configured_motors()
        self.worker = CanWorker(self.commands, self.events, args.config, args.profile,
                                self.motor_names)
        self.worker.start()

        self.connected = False
        self.panels = {}
        self.pairing = {}
        self._closing = False

        root.title("AIMOTOR CANopen control")
        root.configure(bg=COLOR_BG)
        root.minsize(1150, 700)
        root.geometry("1240x820+30+10")
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._build_styles()
        self._build_connection_row()
        self._build_panels()
        self._build_pair_row()
        self._build_log()
        self._update_widget_states()
        self.root.after(POLL_UI_MS, self._drain_events)

    def _configured_motors(self):
        if self.args.motors:
            return list(self.args.motors)
        if self.args.motor:
            return [self.args.motor]
        try:
            from AIMotor_CANOpen_Lib_V_1_0.Housekeeping.Config_Lib import Config
            return Config(self.args.config, profile=self.args.profile).motor_names()
        except Exception as e:
            messagebox.showerror("Config error", str(e))
            return []

    # ---------------------------------------------------------------- layout

    def _build_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TLabel", background=COLOR_PANEL, foreground=COLOR_TEXT)
        style.configure("TFrame", background=COLOR_PANEL)
        style.configure("TLabelframe", background=COLOR_PANEL, foreground=COLOR_ACCENT)
        style.configure("TLabelframe.Label", background=COLOR_PANEL, foreground=COLOR_ACCENT)
        style.configure("TButton", padding=4)
        style.configure("TRadiobutton", background=COLOR_PANEL, foreground=COLOR_TEXT)

    def _build_connection_row(self):
        frame = ttk.LabelFrame(self.root, text="Connection")
        frame.pack(fill="x", padx=10, pady=(8, 4))
        self.connect_btn = ttk.Button(frame, text="Connect", command=self.on_connect)
        self.connect_btn.grid(row=0, column=0, padx=8, pady=6)
        self.conn_label = tk.Label(frame, text="disconnected", bg=COLOR_PANEL, fg=COLOR_MUTED,
                                   font=("Segoe UI", 10, "bold"))
        self.conn_label.grid(row=0, column=1, padx=10, sticky="w")
        tk.Label(frame, text="motors: " + ", ".join(self.motor_names), bg=COLOR_PANEL,
                 fg=COLOR_MUTED, font=("Segoe UI", 9)).grid(row=0, column=2, padx=20)

    def _build_panels(self):
        holder = ttk.Frame(self.root)
        holder.pack(fill="both", expand=False, padx=6, pady=2)
        for column, name in enumerate(self.motor_names):
            panel = MotorPanel(holder, name, self.send)
            panel.frame.grid(row=0, column=column, sticky="nsew", padx=4)
            holder.grid_columnconfigure(column, weight=1)
            self.panels[name] = panel

    def _build_pair_row(self):
        frame = ttk.LabelFrame(self.root, text="Paired drive (both motors)")
        frame.pack(fill="x", padx=10, pady=4)

        self.forward_var = tk.DoubleVar(value=0.0)
        self.forward_slider = tk.Scale(frame, from_=-3000, to=3000, resolution=10,
                                       orient="horizontal", length=330,
                                       variable=self.forward_var, label="forward rpm",
                                       bg=COLOR_PANEL, fg=COLOR_TEXT, highlightthickness=0,
                                       troughcolor=COLOR_BG, activebackground=COLOR_ACCENT,
                                       sliderlength=26)
        self.forward_slider.grid(row=0, column=0, rowspan=2, padx=8, pady=4)
        self.forward_slider.bind("<ButtonRelease-1>", lambda e: self.on_pair_drive())

        self.turn_var = tk.DoubleVar(value=0.0)
        self.turn_slider = tk.Scale(frame, from_=-1000, to=1000, resolution=10,
                                    orient="horizontal", length=260, variable=self.turn_var,
                                    label="turn rpm", bg=COLOR_PANEL, fg=COLOR_TEXT,
                                    highlightthickness=0, troughcolor=COLOR_BG,
                                    activebackground=COLOR_ACCENT, sliderlength=26)
        self.turn_slider.grid(row=0, column=1, rowspan=2, padx=8, pady=4)
        self.turn_slider.bind("<ButtonRelease-1>", lambda e: self.on_pair_drive())

        self.invert_var = tk.BooleanVar(value=True)
        ttk.Radiobutton(frame, text="Opposite (differential base)", variable=self.invert_var,
                        value=True, command=self.on_pair_drive).grid(row=0, column=2,
                                                                     sticky="w", padx=8)
        ttk.Radiobutton(frame, text="Same direction", variable=self.invert_var, value=False,
                        command=self.on_pair_drive).grid(row=1, column=2, sticky="w", padx=8)

        self.arm_both_btn = ttk.Button(frame, text="ARM BOTH", command=self.on_arm_both)
        self.arm_both_btn.grid(row=0, column=3, padx=8, pady=2, sticky="we")
        self.disarm_both_btn = ttk.Button(frame, text="DISARM BOTH",
                                          command=lambda: self.send("disarm", motor=ALL))
        self.disarm_both_btn.grid(row=1, column=3, padx=8, pady=2, sticky="we")

        self.stop_btn = tk.Button(frame, text="STOP\nBOTH", command=self.on_stop_all,
                                  bg=COLOR_FAULT, fg="white", font=("Segoe UI", 15, "bold"),
                                  width=9, height=2, activebackground="#ff7b72")
        self.stop_btn.grid(row=0, column=4, rowspan=2, padx=16, pady=4)

    def _build_log(self):
        frame = ttk.LabelFrame(self.root, text="Log")
        frame.pack(fill="both", expand=True, padx=10, pady=(4, 8))
        self.log_text = tk.Text(frame, height=7, bg=COLOR_BG, fg=COLOR_TEXT,
                                insertbackground=COLOR_TEXT, font=("Consolas", 9),
                                wrap="word", relief="flat")
        scroll = ttk.Scrollbar(frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=4)
        scroll.pack(side="right", fill="y", pady=4)
        for tag, color in (("ok", COLOR_OK), ("warn", COLOR_WARN), ("error", COLOR_FAULT),
                           ("info", COLOR_TEXT)):
            self.log_text.tag_config(tag, foreground=color)

    # --------------------------------------------------------------- actions

    def send(self, command, **args):
        if command == "_log":                     # panels log without a round trip
            self.log(args.get("text", ""), args.get("level", "info"))
            return
        self.commands.put((command, args))

    def on_connect(self):
        if self.connected:
            self.send("disconnect")
            return
        self.log("Connecting...")
        self.send("connect")

    def on_arm_both(self):
        live = [n for n, p in self.panels.items() if p.online]
        if len(live) < 2:
            self.log("ARM BOTH needs both motors online", "warn")
            return
        if not messagebox.askokcancel(
                "Arm both motors",
                "BOTH motors will be energised and can start turning.\n\n"
                "Check both shafts are clear and both motors are secured.\n\nContinue?"):
            return
        self.send("arm", motor=ALL)

    def on_stop_all(self):
        """Always available. Zeroes every setpoint and every slider."""
        self.forward_var.set(0.0)
        self.turn_var.set(0.0)
        for panel in self.panels.values():
            panel.zero_slider()
        self.send("stop", motor=ALL)

    def on_pair_drive(self):
        live = [n for n, p in self.panels.items() if p.online]
        if len(live) < 2:
            self.log("Paired drive needs both motors online", "warn")
            return
        armed = [n for n, p in self.panels.items() if p.armed]
        forward, turn = float(self.forward_var.get()), float(self.turn_var.get())
        if len(armed) < 2 and (forward or turn):
            self.log("Arm both motors before driving them together", "warn")
            return
        self.send("pair_velocity", forward=forward, turn=turn, invert=bool(self.invert_var.get()))

    def on_close(self):
        if self._closing:
            return
        self._closing = True
        self.log("Closing - stopping and disarming every motor", "warn")
        self.send("stop", motor=ALL)
        self.send("disarm", motor=ALL)
        self.send("disconnect")
        self.send("quit")
        self.root.after(4000, self.root.destroy)     # backstop if the worker hangs

    # ---------------------------------------------------------------- events

    def _drain_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                self._handle_event(kind, payload)
        except queue.Empty:
            pass
        self.root.after(POLL_UI_MS, self._drain_events)

    def _handle_event(self, kind, payload):
        panel = None
        if isinstance(payload, dict) and payload.get("motor") in self.panels:
            panel = self.panels[payload["motor"]]

        if kind == "log":
            self.log(payload["text"], payload.get("level", "info"))
        elif kind == "motor_online" and panel:
            panel.set_max_rpm(payload["max_rpm"])
            panel.set_online(True, "node %d on %s" % (payload["node_id"], payload["adapter"]))
            if payload.get("mode") is not None:
                panel.set_mode(payload["mode"])
        elif kind == "motor_offline" and panel:
            panel.set_online(False, error=payload.get("error", ""))
        elif kind == "connected":
            self.connected = True
            self.pairing = payload.get("pairing", {})
            self.invert_var.set(bool(self.pairing.get("invert_right_for_forward", True)))
            live = payload.get("motors", [])
            self.conn_label.configure(text="connected: " + ", ".join(live) if live
                                      else "connected, no motor online",
                                      fg=COLOR_OK if live else COLOR_FAULT)
            self.connect_btn.configure(text="Disconnect")
            limits = [p.max_rpm for p in self.panels.values() if p.online]
            if limits:
                bound = min(limits)
                self.forward_slider.configure(from_=-bound, to=bound)
                self.turn_slider.configure(from_=-bound / 3.0, to=bound / 3.0)
            self._update_widget_states()
        elif kind == "disconnected":
            self.connected = False
            for name, p in self.panels.items():
                p.set_online(False)
            self.conn_label.configure(text="disconnected", fg=COLOR_MUTED)
            self.connect_btn.configure(text="Connect")
            self._update_widget_states()
        elif kind == "armed" and panel:
            panel.set_armed(payload.get("armed"))
            self._update_widget_states()
        elif kind == "target" and panel:
            panel.set_target(payload.get("rpm", 0.0))
        elif kind == "mode" and panel:
            panel.set_mode(payload.get("mode"))
        elif kind == "feedback" and panel:
            panel.show_feedback(payload)
        elif kind == "preflight" and panel and not payload.get("ok"):
            self.log("[" + payload["motor"] + "] preflight failed", "error")
        elif kind == "shutdown_done":
            if self._closing:
                self.root.destroy()

    def _update_widget_states(self):
        live = [n for n, p in self.panels.items() if p.online]
        both = len(live) >= 2
        for widget in (self.forward_slider, self.turn_slider):
            widget.configure(state="normal" if both else "disabled")
        self.arm_both_btn.configure(state="normal" if both else "disabled")
        self.disarm_both_btn.configure(state="normal" if live else "disabled")
        self.stop_btn.configure(state="normal" if live else "disabled")
        for panel in self.panels.values():
            panel.update_widget_states()

    def log(self, message, level="info"):
        self.log_text.insert("end", "[%s] %s\n" % (time.strftime("%H:%M:%S"), message), level)
        self.log_text.see("end")


def main():
    parser = argparse.ArgumentParser(description="AIMOTOR CANopen control GUI")
    parser.add_argument("--config", default=None, help="Path to aimotor_config.json")
    parser.add_argument("--profile", default=None, help="Override the adapter profile")
    parser.add_argument("--motors", nargs="*", default=None,
                        help="Motor names to show (default: every enabled motor)")
    parser.add_argument("--motor", default=None, help="Show a single motor only")
    parser.add_argument("--self-test", action="store_true",
                        help="Build the window, connect, then close automatically")
    args = parser.parse_args()

    root = tk.Tk()
    gui = MotorGUI(root, args)

    if args.self_test:
        gui.on_connect()
        root.after(8000, gui.on_close)
        root.after(14000, root.destroy)

    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
