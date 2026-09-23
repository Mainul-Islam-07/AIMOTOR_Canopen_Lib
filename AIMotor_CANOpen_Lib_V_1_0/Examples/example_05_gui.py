"""Example 5 - desktop GUI to control the AIMOTOR and watch its feedback.

    python example_05_gui.py
    python example_05_gui.py --profile canalystii

Tkinter only, no extra dependencies.

THIS CAN MOVE THE MOTOR. Arming asks for confirmation first, and closing the
window always stops and disarms.

Design: all CAN work happens on one background thread (CanWorker). The GUI
never touches the bus directly - it posts commands to a queue and reads
results from another queue, because Tk widgets may only be touched from the
main thread.
"""

import argparse
import os
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


class CanWorker(threading.Thread):
    """Owns the CANopen network and the motor. Talks to the GUI by queue."""

    def __init__(self, commands: queue.Queue, events: queue.Queue, config_path=None,
                 profile=None, motor_name="AIMotor_1"):
        super().__init__(daemon=True, name="can-worker")
        self.commands = commands
        self.events = events
        self.config_path = config_path
        self.profile = profile
        self.motor_name = motor_name

        self.config = None
        self.network = None
        self.motor = None
        self.connected = False
        self.armed = False
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
            if self.connected and self.motor is not None and time.time() >= next_poll:
                next_poll = time.time() + self.poll_period
                try:
                    self.emit("feedback", self.motor.snapshot())
                except Exception as e:
                    self.log("Feedback error: " + str(e), "error")
        self.shutdown()

    def handle(self, command, args):
        handler = getattr(self, "cmd_" + command, None)
        if handler is None:
            self.log("Unknown command: " + str(command), "error")
            return
        handler(args)

    # ------------------------------------------------------------- commands

    def cmd_connect(self, args):
        from AIMotor_CANOpen_Lib_V_1_0.CANopen_Network.Network_Lib import CANopen_Network
        from AIMotor_CANOpen_Lib_V_1_0.Housekeeping.Config_Lib import Config
        from AIMotor_CANOpen_Lib_V_1_0.Motor_Control.Motor_Lib import Motor_CANopen_Lib

        self.emit("busy", True)
        self.profile = (args or {}).get("profile", self.profile)
        self.motor_name = (args or {}).get("motor", self.motor_name)

        self.config = Config(self.config_path, profile=self.profile)
        # The GUI closes the bus itself, so never hard-exit the process.
        self.config.shutdown["os_exit_after_disconnect"] = False
        adapter = self.config.adapter()
        self.log("Connecting: %s / %s / %s bps" % (adapter.get("interface"),
                                                   adapter.get("channel"),
                                                   adapter.get("bitrate")))
        self.network = CANopen_Network(self.config)
        self.motor = Motor_CANopen_Lib(self.motor_name, self.network, self.config)
        self.connected = True
        self.poll_period = float(self.motor.settings.feedback.get("poll_period_s", 0.2))

        limits = self.motor.settings.limits
        self.emit("connected", {
            "motor": self.motor_name,
            "node_id": self.motor.Node_ID,
            "max_rpm": float(limits.get("max_velocity_rpm", 500.0)),
            "mode": self.motor.mode.current if self.motor.mode else None,
            "profile": adapter.get("profile_name"),
        })
        self.log("Connected to %s (node %d)" % (self.motor_name, self.motor.Node_ID), "ok")
        self.cmd_preflight(None)
        self.emit("busy", False)

    def cmd_preflight(self, args):
        report = self.motor.preflight()
        for problem in report.get("problems", []):
            self.log(problem, "error")
        self.log("Preflight %s - state %s, H02-00 %s, modes %s"
                 % ("PASS" if report["ok"] else "FAIL", report["state"], report["H02_00"],
                    " ".join(report["supported_modes"])), "ok" if report["ok"] else "error")
        self.emit("preflight", report)

    def cmd_arm(self, args):
        self.emit("busy", True)
        self.log("Arming - the motor becomes energised")
        ok = self.motor.arm()
        self.armed = bool(ok)
        self.emit("armed", self.armed)
        self.log("ARMED" if ok else "ARM failed", "ok" if ok else "error")
        self.emit("busy", False)

    def cmd_disarm(self, args):
        self.emit("busy", True)
        self.motor.stop()
        ok = self.motor.disarm()
        self.armed = False
        self.emit("armed", False)
        self.log("Disarmed" if ok else "Disarm reported errors", "ok" if ok else "error")
        self.emit("busy", False)

    def cmd_stop(self, args):
        """Zero the setpoint but stay enabled."""
        self.motor.stop()
        self.emit("target", 0.0)
        self.log("STOP - setpoint zeroed", "warn")

    def cmd_quick_stop(self, args):
        self.motor.quick_stop()
        self.armed = False
        self.emit("armed", False)
        self.log("QUICK STOP", "warn")

    def cmd_velocity(self, args):
        rpm = float(args.get("rpm", 0.0))
        if self.motor.velocity is None:
            self.log("Velocity mode is not active - switch mode first", "error")
            return
        pulps = self.motor.velocity.RUN_rpm(rpm)
        if pulps is None:
            self.log("Velocity command failed", "error")
            return
        actual_rpm = self.motor.units.pulps_to_rpm(pulps)
        self.emit("target", actual_rpm)
        self.log("Target %.1f rpm (%d pul/s)" % (actual_rpm, pulps))

    def cmd_mode(self, args):
        mode = int(args.get("mode"))
        if self.armed:
            self.log("Disarm before changing mode", "error")
            return
        ok = self.motor.mode.switch_to(mode)
        self.emit("mode", self.motor.mode.current)
        self.log("Mode set to %s" % self.motor.mode.current, "ok" if ok else "error")

    def cmd_fault_reset(self, args):
        ok = self.motor.fault_reset()
        self.log("Fault reset %s" % ("succeeded" if ok else "failed"),
                 "ok" if ok else "error")

    def cmd_disconnect(self, args):
        self.shutdown()
        self.emit("disconnected", None)
        self.log("Disconnected")

    def cmd_quit(self, args):
        self._running = False

    # -------------------------------------------------------------- cleanup

    def shutdown(self):
        try:
            if self.motor is not None:
                self.motor.close()
        except Exception as e:
            self.log("Shutdown error: " + str(e), "error")
        try:
            if self.network is not None:
                self.network.disconnect(hard_exit=False)
        except Exception:
            pass
        self.motor = None
        self.network = None
        self.connected = False
        self.armed = False


class MotorGUI():
    FIELDS = [
        ("state", "State"),
        ("statusword_hex", "Status word"),
        ("mode_display", "Mode"),
        ("position_pul", "Position [pul]"),
        ("position_rev", "Position [rev]"),
        ("velocity_rpm", "Velocity [rpm]"),
        ("velocity_pulps", "Velocity [pul/s]"),
        ("torque_percent", "Torque [% rated]"),
        ("torque_nm", "Torque [Nm]"),
        ("phase_current_a", "Phase current [A]"),
        ("bus_voltage_v", "Bus voltage [V]"),
        ("module_temperature_c", "Temperature [C]"),
        ("error_code", "Error code"),
        ("fault_code", "Fault code"),
        ("heartbeat_state", "Heartbeat"),
        ("target_reached", "Target reached"),
    ]

    def __init__(self, root, args):
        self.root = root
        self.args = args
        self.commands = queue.Queue()
        self.events = queue.Queue()
        self.worker = CanWorker(self.commands, self.events, args.config,
                                args.profile, args.motor)
        self.worker.start()

        self.connected = False
        self.armed = False
        self.max_rpm = 500.0
        self.value_labels = {}
        self._last_sent_rpm = None

        root.title("AIMOTOR CANopen control")
        root.configure(bg=COLOR_BG)
        root.minsize(780, 560)
        root.geometry("860x690+60+15")
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._build_styles()
        self._build_connection_row()
        self._build_control_row()
        self._build_velocity_row()
        self._build_feedback_panel()
        self._build_log()
        self._update_widget_states()
        self.root.after(POLL_UI_MS, self._drain_events)

    # ---------------------------------------------------------------- layout

    def _build_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TLabel", background=COLOR_PANEL, foreground=COLOR_TEXT)
        style.configure("TFrame", background=COLOR_PANEL)
        style.configure("TLabelframe", background=COLOR_PANEL, foreground=COLOR_MUTED)
        style.configure("TLabelframe.Label", background=COLOR_PANEL, foreground=COLOR_MUTED)
        style.configure("TButton", padding=6)
        style.configure("TCombobox", padding=4)

    def _panel(self, title=None):
        frame = ttk.LabelFrame(self.root, text=title) if title else ttk.Frame(self.root)
        frame.pack(fill="x", padx=10, pady=6)
        return frame

    def _build_connection_row(self):
        frame = self._panel("Connection")
        ttk.Label(frame, text="Adapter").grid(row=0, column=0, padx=6, pady=8, sticky="w")
        self.profile_var = tk.StringVar(value=self.args.profile or "")
        self.profile_box = ttk.Combobox(frame, textvariable=self.profile_var, width=14,
                                        state="readonly")
        self.profile_box.grid(row=0, column=1, padx=6)

        ttk.Label(frame, text="Motor").grid(row=0, column=2, padx=6, sticky="w")
        self.motor_var = tk.StringVar(value=self.args.motor)
        self.motor_box = ttk.Combobox(frame, textvariable=self.motor_var, width=14,
                                      state="readonly")
        self.motor_box.grid(row=0, column=3, padx=6)

        self.connect_btn = ttk.Button(frame, text="Connect", command=self.on_connect)
        self.connect_btn.grid(row=0, column=4, padx=10)

        self.conn_label = tk.Label(frame, text="disconnected", bg=COLOR_PANEL,
                                   fg=COLOR_MUTED, font=("Segoe UI", 10, "bold"))
        self.conn_label.grid(row=0, column=5, padx=10, sticky="w")
        self._populate_choices()

    def _populate_choices(self):
        """Read the adapter profiles and motor names out of the JSON config."""
        try:
            from AIMotor_CANOpen_Lib_V_1_0.Housekeeping.Config_Lib import Config
            config = Config(self.args.config, profile=self.args.profile)
            self.profile_box["values"] = sorted(config.raw.get("adapters", {}))
            if not self.profile_var.get():
                self.profile_var.set(config.profile)
            self.motor_box["values"] = config.motor_names(enabled_only=False)
            if self.motor_var.get() not in self.motor_box["values"]:
                self.motor_var.set(config.motor_names()[0])
        except Exception as e:
            messagebox.showerror("Config error", str(e))

    def _build_control_row(self):
        frame = self._panel("Drive control")
        self.arm_btn = ttk.Button(frame, text="ARM", command=self.on_arm)
        self.arm_btn.grid(row=0, column=0, padx=6, pady=8)
        self.disarm_btn = ttk.Button(frame, text="Disarm", command=self.on_disarm)
        self.disarm_btn.grid(row=0, column=1, padx=6)

        ttk.Label(frame, text="Mode").grid(row=0, column=2, padx=(20, 6))
        self.mode_var = tk.StringVar(value="3 - PV velocity")
        self.mode_box = ttk.Combobox(frame, textvariable=self.mode_var, width=18,
                                     state="readonly",
                                     values=["3 - PV velocity", "1 - PP position",
                                             "4 - PT torque"])
        self.mode_box.grid(row=0, column=3, padx=6)
        self.mode_box.bind("<<ComboboxSelected>>", self.on_mode)

        self.fault_btn = ttk.Button(frame, text="Fault reset", command=self.on_fault_reset)
        self.fault_btn.grid(row=0, column=4, padx=(20, 6))

        self.armed_label = tk.Label(frame, text="DISARMED", bg=COLOR_PANEL, fg=COLOR_MUTED,
                                    font=("Segoe UI", 11, "bold"))
        self.armed_label.grid(row=0, column=5, padx=16)

    def _build_velocity_row(self):
        frame = self._panel("Velocity command")
        self.speed_var = tk.DoubleVar(value=0.0)
        self.slider = tk.Scale(frame, from_=-self.max_rpm, to=self.max_rpm, resolution=1,
                               orient="horizontal", length=430, variable=self.speed_var, sliderlength=28,
                               bg=COLOR_PANEL, fg=COLOR_TEXT, highlightthickness=0,
                               troughcolor=COLOR_BG, activebackground=COLOR_ACCENT,
                               label="rpm")
        self.slider.grid(row=0, column=0, columnspan=3, padx=8, pady=4, sticky="we")
        self.slider.bind("<ButtonRelease-1>", lambda e: self.on_send_velocity())

        ttk.Label(frame, text="rpm").grid(row=1, column=0, padx=(8, 2), sticky="e")
        self.speed_entry = ttk.Entry(frame, width=10)
        self.speed_entry.insert(0, "0")
        self.speed_entry.grid(row=1, column=1, padx=4, sticky="w")
        self.speed_entry.bind("<Return>", lambda e: self.on_send_entry())
        self.send_btn = ttk.Button(frame, text="Send", command=self.on_send_entry)
        self.send_btn.grid(row=1, column=2, padx=6, sticky="w")

        self.stop_btn = tk.Button(frame, text="STOP", command=self.on_stop,
                                  bg=COLOR_FAULT, fg="white", font=("Segoe UI", 16, "bold"),
                                  width=10, height=2, relief="raised",
                                  activebackground="#ff7b72")
        self.stop_btn.grid(row=0, column=3, rowspan=2, padx=18, pady=6)

        self.target_label = tk.Label(frame, text="target 0.0 rpm", bg=COLOR_PANEL,
                                     fg=COLOR_ACCENT, font=("Segoe UI", 10))
        self.target_label.grid(row=1, column=4, padx=10, sticky="w")

    def _build_feedback_panel(self):
        frame = self._panel("Feedback")
        for i, (key, label) in enumerate(self.FIELDS):
            row, col = i % 8, i // 8
            ttk.Label(frame, text=label, foreground=COLOR_MUTED).grid(
                row=row, column=col * 2, sticky="w", padx=(10, 6), pady=2)
            value = tk.Label(frame, text="-", bg=COLOR_PANEL, fg=COLOR_TEXT,
                             font=("Consolas", 10), anchor="w", width=18)
            value.grid(row=row, column=col * 2 + 1, sticky="w", padx=(0, 16))
            self.value_labels[key] = value

    def _build_log(self):
        frame = self._panel("Log")
        self.log_text = tk.Text(frame, height=6, bg=COLOR_BG, fg=COLOR_TEXT,
                                insertbackground=COLOR_TEXT, font=("Consolas", 9),
                                wrap="word", relief="flat")
        scroll = ttk.Scrollbar(frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=6)
        scroll.pack(side="right", fill="y", pady=6)
        self.log_text.tag_config("ok", foreground=COLOR_OK)
        self.log_text.tag_config("warn", foreground=COLOR_WARN)
        self.log_text.tag_config("error", foreground=COLOR_FAULT)
        self.log_text.tag_config("info", foreground=COLOR_TEXT)

    # --------------------------------------------------------------- actions

    def send(self, command, **args):
        self.commands.put((command, args))

    def on_connect(self):
        if self.connected:
            self.send("disconnect")
            return
        self.log("Connecting...", "info")
        self.send("connect", profile=self.profile_var.get(), motor=self.motor_var.get())

    def on_arm(self):
        if not messagebox.askokcancel(
                "Arm the drive",
                "The motor will be energised and can start turning.\n\n"
                "Check the shaft is clear and the motor is secured.\n\nContinue?"):
            return
        self.send("arm")

    def on_disarm(self):
        self.send("disarm")

    def on_stop(self):
        """Always available: zero the setpoint, then disarm if it was armed."""
        self.speed_var.set(0.0)
        self.speed_entry.delete(0, "end")
        self.speed_entry.insert(0, "0")
        self.send("stop")

    def on_mode(self, event=None):
        mode = int(self.mode_var.get().split(" ")[0])
        self.send("mode", mode=mode)

    def on_fault_reset(self):
        self.send("fault_reset")

    def on_send_velocity(self):
        rpm = float(self.speed_var.get())
        self.speed_entry.delete(0, "end")
        self.speed_entry.insert(0, str(rpm))
        self._send_rpm(rpm)

    def on_send_entry(self):
        try:
            rpm = float(self.speed_entry.get())
        except ValueError:
            self.log("Not a number: " + self.speed_entry.get(), "error")
            return
        self.speed_var.set(max(-self.max_rpm, min(self.max_rpm, rpm)))
        self._send_rpm(rpm)

    def _send_rpm(self, rpm):
        if not self.armed and rpm != 0:
            self.log("Arm the drive before commanding a speed", "warn")
            return
        if rpm == self._last_sent_rpm:
            return
        self._last_sent_rpm = rpm
        self.send("velocity", rpm=rpm)

    def on_close(self):
        if self.armed:
            self.log("Closing - stopping and disarming", "warn")
        self.send("stop")
        self.send("disarm")
        self.send("disconnect")
        self.send("quit")
        self.root.after(600, self.root.destroy)

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
        if kind == "log":
            self.log(payload["text"], payload.get("level", "info"))
        elif kind == "connected":
            self.connected = True
            self.max_rpm = payload["max_rpm"]
            self.slider.configure(from_=-self.max_rpm, to=self.max_rpm)
            self.conn_label.configure(
                text="%s  node %d  via %s" % (payload["motor"], payload["node_id"],
                                              payload["profile"]), fg=COLOR_OK)
            self.connect_btn.configure(text="Disconnect")
            if payload.get("mode") is not None:
                self._set_mode_box(payload["mode"])
            self._update_widget_states()
        elif kind == "disconnected":
            self.connected = False
            self.armed = False
            self.conn_label.configure(text="disconnected", fg=COLOR_MUTED)
            self.connect_btn.configure(text="Connect")
            self._clear_feedback()
            self._update_widget_states()
        elif kind == "armed":
            self.armed = bool(payload)
            self.armed_label.configure(text="ARMED" if self.armed else "DISARMED",
                                       fg=COLOR_FAULT if self.armed else COLOR_MUTED)
            if not self.armed:
                self._last_sent_rpm = None
            self._update_widget_states()
        elif kind == "target":
            self.target_label.configure(text="target %.1f rpm" % float(payload))
        elif kind == "mode":
            self._set_mode_box(payload)
        elif kind == "feedback":
            self._show_feedback(payload)
        elif kind == "preflight":
            if not payload.get("ok"):
                messagebox.showwarning("Preflight failed", "\n".join(payload["problems"]))

    def _set_mode_box(self, mode):
        for text in self.mode_box["values"]:
            if text.startswith(str(mode)):
                self.mode_var.set(text)
                return

    def _show_feedback(self, data):
        for key, _ in self.FIELDS:
            value = data.get(key)
            if key in ("error_code", "fault_code") and isinstance(value, int):
                text = "0x%04X" % value
            elif isinstance(value, float):
                text = "%.2f" % value
            else:
                text = str(value)
            label = self.value_labels[key]
            label.configure(text=text)

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

    def _clear_feedback(self):
        for label in self.value_labels.values():
            label.configure(text="-", fg=COLOR_TEXT)

    def _update_widget_states(self):
        on = "normal" if self.connected else "disabled"
        for widget in (self.arm_btn, self.disarm_btn, self.fault_btn, self.mode_box,
                       self.send_btn, self.speed_entry):
            widget.configure(state=on if widget is not self.mode_box else
                             ("readonly" if self.connected else "disabled"))
        self.slider.configure(state="normal" if self.connected else "disabled")
        self.arm_btn.configure(state="disabled" if (self.armed or not self.connected)
                               else "normal")
        self.profile_box.configure(state="disabled" if self.connected else "readonly")
        self.motor_box.configure(state="disabled" if self.connected else "readonly")

    def log(self, message, level="info"):
        stamp = time.strftime("%H:%M:%S")
        self.log_text.insert("end", "[%s] %s\n" % (stamp, message), level)
        self.log_text.see("end")


def main():
    parser = argparse.ArgumentParser(description="AIMOTOR CANopen control GUI")
    parser.add_argument("--config", default=None, help="Path to aimotor_config.json")
    parser.add_argument("--profile", default=None, help="Adapter profile from the config")
    parser.add_argument("--motor", default="AIMotor_1", help="Motor name from the config")
    parser.add_argument("--self-test", action="store_true",
                        help="Build the window, connect, then close automatically")
    args = parser.parse_args()

    root = tk.Tk()
    gui = MotorGUI(root, args)

    if args.self_test:
        gui.on_connect()
        root.after(6000, gui.on_close)
        root.after(9000, root.destroy)

    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
