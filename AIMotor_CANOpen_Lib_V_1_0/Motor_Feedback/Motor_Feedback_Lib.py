"""Feedback polling over SDO.

One poll_once() call returns everything: state, mode, position, velocity,
torque, current, bus voltage, module temperature, error and fault codes, plus
the heartbeat status when the heartbeat library is attached.
"""

import threading
import time
from typing import Callable, Optional

from ..Housekeeping.Logger_Lib import Logger
from ..Motor_Mapping.mapping import AIMotor_CANopen_Map as Map
from ..Motor_Mapping.objects import OD


class Feedback_Lib():
    def __init__(self, node, node_name: str, canopen_handle, settings, telemetry, io,
                 heartbeat=None):
        self.node = node
        self.Node_ID = node.id
        self.Node_Name = node_name
        self.canopen_handle = canopen_handle
        self.settings = settings
        self.telemetry = telemetry
        self.io = io
        self.heartbeat = heartbeat
        self.units = settings.units
        self.common = canopen_handle.common
        self.log = Logger(node_name, node.id)
        self.DEBUG_FEEDBACK = settings.DEBUG_FEEDBACK

        self.include_extended = settings.feedback.get("include_extended", True)
        self.poll_period_s = float(settings.feedback.get("poll_period_s", 0.1))
        self.callback: Optional[Callable] = None
        self._thread = None
        self._stop_event = threading.Event()

    # ----------------------------------------------------------------- polling

    def poll_once(self) -> dict:
        """Read every feedback object once and update the telemetry store."""
        values = {}

        statusword = self.io.read(OD.STATUSWORD)
        values["statusword"] = statusword
        if statusword is not None:
            state = Map.decode_state(statusword)
            values["state"] = state.name
            values["statusword_hex"] = "0x%04X" % statusword
            values["fault"] = Map.is_faulted(statusword)
            values["flags"] = Map.statusword_flags(statusword)
            values["target_reached"] = bool(
                statusword & (1 << Map.StatuswordBit.TARGET_REACHED))
        else:
            values["state"] = Map.StateMachineState.UNKNOWN.name
            values["fault"] = None

        values["mode_display"] = self.io.read(OD.MODES_DISPLAY)

        position = self.io.read(OD.POSITION_ACTUAL)
        values["position_pul"] = position
        if position is not None:
            values["position_rev"] = round(self.units.pul_to_rev(position), 4)
            values["position_deg"] = round(self.units.pul_to_deg(position), 2)

        velocity = self.io.read(OD.VELOCITY_ACTUAL)
        values["velocity_pulps"] = velocity
        if velocity is not None:
            values["velocity_rpm"] = round(self.units.pulps_to_rpm(velocity), 2)

        torque = self.io.read(OD.TORQUE_ACTUAL)
        values["torque_permille"] = torque
        if torque is not None:
            values["torque_percent"] = round(self.units.permille_to_percent(torque), 2)
            values["torque_nm"] = round(self.units.permille_to_nm(torque), 4)

        values["error_code"] = self.io.read(OD.ERROR_CODE)
        values["error_register"] = self.io.read(OD.ERROR_REGISTER)

        if self.include_extended:
            values["current_actual_raw"] = self.io.read(OD.CURRENT_ACTUAL)
            motor_speed = self.io.read(OD.MOTOR_SPEED_RPM)
            values["motor_speed_rpm"] = motor_speed
            values["internal_torque_permille"] = self.io.read(OD.INTERNAL_TORQUE)
            phase_current = self.io.read(OD.PHASE_CURRENT_RMS)
            values["phase_current_raw"] = phase_current
            if phase_current is not None:
                values["phase_current_a"] = round(self.units.raw_to_amps(phase_current), 2)
            bus_voltage = self.io.read(OD.BUS_VOLTAGE)
            values["bus_voltage_raw"] = bus_voltage
            if bus_voltage is not None:
                values["bus_voltage_v"] = round(self.units.raw_to_volts(bus_voltage), 1)
            values["module_temperature_c"] = self.io.read(OD.MODULE_TEMPERATURE)
            values["fault_code"] = self.io.read(OD.FAULT_CODE)

        if self.heartbeat is not None:
            values.update(self.heartbeat.status())
        else:
            values["heartbeat_alive"] = None
            values["heartbeat_count"] = 0
            values["heartbeat_state"] = "NOT_CONFIGURED"

        self.telemetry.update(values)
        if self.callback is not None:
            try:
                self.callback(self.telemetry.snapshot())
            except Exception as e:
                self.log.print("Feedback callback error: " + str(e), "ERROR", "CALLBACK",
                               "Feedback_Lib", "poll_once")
        return self.telemetry.snapshot()

    def snapshot(self) -> dict:
        """Last polled values, without touching the bus."""
        return self.telemetry.snapshot()

    def read_fault_code(self, record: int = 0) -> Optional[int]:
        """Read a fault record: 0 is the current fault, 1..9 are older ones."""
        self.io.write(OD.FAULT_RECORD_SELECT, int(record))
        return self.io.read(OD.FAULT_CODE)

    # ------------------------------------------------------------- background

    def start(self, period_s: Optional[float] = None):
        """Poll in a background thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self.poll_period_s = float(period_s or self.poll_period_s)
        self._stop_event.clear()

        def loop():
            while not self._stop_event.is_set():
                try:
                    self.poll_once()
                except Exception as e:
                    self.log.print("Poller error: " + str(e), "ERROR", "POLL",
                                   "Feedback_Lib", "start")
                self._stop_event.wait(self.poll_period_s)

        self._thread = threading.Thread(target=loop, name="feedback-" + self.Node_Name,
                                        daemon=True)
        self._thread.start()
        self.log.print("Feedback poller started at " + str(self.poll_period_s) + " s",
                       "FEEDBACK", "POLL", "Feedback_Lib", "start")

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    # ---------------------------------------------------------------- display

    def format_block(self, data: Optional[dict] = None) -> str:
        """Multi-line human readable summary of one snapshot."""
        d = data or self.snapshot()
        lines = []
        lines.append(" state      " + str(d.get("statusword_hex")) + " " + str(d.get("state")) +
                     "   fault=" + str(d.get("fault")) + "   mode=" + str(d.get("mode_display")))
        lines.append(" position   " + str(d.get("position_pul")) + " pul   " +
                     str(d.get("position_rev")) + " rev   " + str(d.get("position_deg")) + " deg")
        lines.append(" velocity   " + str(d.get("velocity_pulps")) + " pul/s   " +
                     str(d.get("velocity_rpm")) + " rpm   (H0B_00 " +
                     str(d.get("motor_speed_rpm")) + " rpm)")
        lines.append(" torque     " + str(d.get("torque_permille")) + " (" +
                     str(d.get("torque_percent")) + " % rated, " + str(d.get("torque_nm")) +
                     " Nm)   H0B_02 internal " + str(d.get("internal_torque_permille")))
        lines.append(" current    0x6078=" + str(d.get("current_actual_raw")) +
                     "   H0B_24 phase " + str(d.get("phase_current_a")) + " A")
        lines.append(" voltage    H0B_26 bus " + str(d.get("bus_voltage_v")) + " V" +
                     "     temp H0B_27 " + str(d.get("module_temperature_c")) + " C")
        error_code = d.get("error_code")
        fault_code = d.get("fault_code")
        healthy = not d.get("fault") and not error_code and not fault_code
        lines.append(" errors     0x603F=" + self._hex(error_code) + "  0x1001=" +
                     self._hex(d.get("error_register"), 2) + "  H0B_34=" + self._hex(fault_code) +
                     "  -> " + ("none" if healthy else "SEE MANUAL"))
        lines.append(" heartbeat  " + str(d.get("heartbeat_state")) + "  count=" +
                     str(d.get("heartbeat_count")) + "  alive=" + str(d.get("heartbeat_alive")))
        return "\n".join(lines)

    @staticmethod
    def _hex(value, width: int = 4) -> str:
        if value is None:
            return "None"
        return ("0x%0" + str(width) + "X") % int(value)

    def print_table(self, data: Optional[dict] = None):
        print(self.format_block(data))
