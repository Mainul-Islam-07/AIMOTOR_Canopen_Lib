"""One AIMOTOR drive on a CANopen network.

Composes settings, transport, telemetry, feedback, heartbeat, mode and
control word handling, as the JS2 library's Motor_CANopen_Lib does.

Typical use:

    with CANopen_Network() as net:
        with Motor_CANopen_Lib("AIMotor_1", net) as motor:
            motor.preflight()
            motor.arm()
            motor.mode.velocity.RUN_rpm(100)
            ...
            motor.stop()
"""

from typing import Optional

from ..Housekeeping.Config_Lib import Config
from ..Housekeeping.Logger_Lib import Logger
from ..Motor_Feedback.Motor_Feedback_Lib import Feedback_Lib
from ..Motor_Feedback.Motor_Heartbeat_Lib import Heartbeat_Lib
from ..Motor_Mapping.mapping import AIMotor_CANopen_Map as Map
from ..Motor_Mapping.objects import OD
from ..Motor_Settings.Load_Settings_Lib import Load_Settings
from ..Motor_Settings.Set_Mode_Lib import Mode
from .Controlword import Controlword_Setup
from .Motor_Telemetry_Lib import Motor_Telemetry
from .Transport_Lib import SDO_IO

EXPECTED_DEVICE_TYPE = 0x00020192


class Motor_CANopen_Lib():
    def __init__(self, node_name: str, canopen_handle, config: Optional[Config] = None,
                 setup_mode: bool = True):
        self.Node_Name = node_name
        self.canopen_handle = canopen_handle
        self.config = config or canopen_handle.config
        self.log = Logger(node_name, -1)

        if self.canopen_handle is None or self.canopen_handle.network is None:
            raise RuntimeError("canopen_handle is not connected")

        self.settings = Load_Settings(self.config, node_name)
        self.Node_ID = self.settings.Node_ID
        self.log.set_node_id(self.Node_ID)
        self.units = self.settings.units

        self.node = self.canopen_handle.add_node(self.Node_ID, self.settings.eds_path)
        self.io = SDO_IO(self.node, node_name, self.canopen_handle.common, self.log,
                         debug=False)
        self.telemetry = Motor_Telemetry(self.node, node_name)

        self.heartbeat = Heartbeat_Lib(self.node, node_name, self.canopen_handle,
                                       self.settings, self.telemetry, self.io)
        if (self.settings.heartbeat or {}).get("enabled", False):
            self.heartbeat.enable()
            self.heartbeat.start_watchdog()

        self.feedback = Feedback_Lib(self.node, node_name, self.canopen_handle, self.settings,
                                     self.telemetry, self.io, self.heartbeat)

        self.mode = Mode(self.node, node_name, self.canopen_handle, self.settings,
                         self.telemetry, self.io, self.settings.mode) if setup_mode else None
        self.control = Controlword_Setup(self.node, node_name, self.canopen_handle,
                                         self.settings, self.telemetry, self.io, self.mode)

        self.log.print("Motor ready: " + node_name + " node " + str(self.Node_ID),
                       "INIT", "MOTOR", "Motor_CANopen_Lib", "__init__")

    # -------------------------------------------------------------- preflight

    def preflight(self, raise_on_fail: bool = False) -> dict:
        """Read-only health check. Never writes, never energises the motor."""
        report = {"ok": True, "problems": []}

        device_type = self.io.read(OD.DEVICE_TYPE)
        report["device_type"] = device_type
        if device_type != EXPECTED_DEVICE_TYPE:
            self.log.print("Device type 0x%08X, expected 0x%08X" %
                           (device_type or 0, EXPECTED_DEVICE_TYPE), "WARNING", "0x1000",
                           "Motor_CANopen_Lib", "preflight")

        supported = self.io.read(OD.SUPPORTED_MODES)
        report["supported_modes"] = Map.decode_supported_modes(supported or 0)
        report["supported_modes_raw"] = supported

        control_mode = self.io.read(OD.H02_00_CONTROL_MODE)
        report["H02_00"] = control_mode
        if self.settings.require_canopen_mode and control_mode != self.settings.canopen_mode_value:
            message = ("H02-00 = " + str(control_mode) + ", expected " +
                       str(self.settings.canopen_mode_value) + " (CANopen). Set H02-00 = 8 "
                       "with the AIMOTOR RS485 tool, then power-cycle the drive.")
            report["ok"] = False
            report["problems"].append(message)
            self.log.print(message, "ERROR", "0x2002:01", "Motor_CANopen_Lib", "preflight")

        # Motor nameplate, and a cross-check of the configured speed limit
        # against the drive's own hard limit (H00_15, highest priority).
        rated_speed = self.io.read(OD.RATED_SPEED)
        max_speed = self.io.read(OD.MAX_SPEED)
        rated_torque = self.io.read(OD.RATED_TORQUE)
        rated_current = self.io.read(OD.RATED_CURRENT)
        report["rated_speed_rpm"] = rated_speed
        report["max_speed_rpm"] = max_speed
        report["rated_torque_nm"] = (rated_torque / 1000.0) if rated_torque else None
        report["rated_current_a"] = (rated_current / 100.0) if rated_current else None

        configured_limit = float(self.settings.limits.get("max_velocity_rpm", 0) or 0)
        report["configured_limit_rpm"] = configured_limit
        if max_speed and configured_limit > max_speed:
            message = ("Configured max_velocity_rpm %.0f exceeds the drive's own limit "
                       "H00_15 = %d rpm. The drive will cap it." % (configured_limit, max_speed))
            report["problems"].append(message)
            self.log.print(message, "WARNING", "LIMIT", "Motor_CANopen_Lib", "preflight")

        statusword = self.io.read(OD.STATUSWORD)
        report["statusword"] = statusword
        report["state"] = Map.decode_state(statusword or 0).name
        report["fault"] = Map.is_faulted(statusword or 0)
        report["error_code"] = self.io.read(OD.ERROR_CODE)
        report["error_register"] = self.io.read(OD.ERROR_REGISTER)
        report["fault_code"] = self.io.read(OD.FAULT_CODE)
        report["position_pul"] = self.io.read(OD.POSITION_ACTUAL)
        report["heartbeat_producer_ms"] = self.io.read(OD.HEARTBEAT_PRODUCER)

        if report["fault"]:
            message = ("Drive is in a fault state: statusword 0x%04X, error code %s, "
                       "fault code %s" % (statusword or 0, report["error_code"],
                                          report["fault_code"]))
            report["problems"].append(message)
            if self.settings.abort_if_fault_on_startup:
                report["ok"] = False
            self.log.print(message, "ERROR", "0x6041", "Motor_CANopen_Lib", "preflight")

        if report["ok"]:
            self.log.print("PREFLIGHT PASS - drive is ready", "INIT", "PREFLIGHT",
                           "Motor_CANopen_Lib", "preflight")
        else:
            self.log.print("PREFLIGHT FAIL - " + "; ".join(report["problems"]), "ERROR",
                           "PREFLIGHT", "Motor_CANopen_Lib", "preflight")
            if raise_on_fail:
                raise RuntimeError("Preflight failed: " + "; ".join(report["problems"]))
        return report

    # ------------------------------------------------------------ operations

    def arm(self) -> bool:
        """Energise the motor."""
        return self.control.ARM()

    def disarm(self) -> bool:
        return self.control.DISARM()

    def stop(self) -> bool:
        """Zero the active setpoint but stay enabled."""
        return self.control.CONTROLWORD_HALT()

    def quick_stop(self) -> bool:
        return self.control.quick_stop()

    def fault_reset(self) -> bool:
        return self.control.fault_reset()

    def snapshot(self) -> dict:
        """One full feedback read."""
        return self.feedback.poll_once()

    @property
    def velocity(self):
        """Shortcut to the PV setup object, when PV is the active mode."""
        return getattr(self.mode, "velocity", None) if self.mode else None

    @property
    def position(self):
        return getattr(self.mode, "position", None) if self.mode else None

    @property
    def torque(self):
        return getattr(self.mode, "torque", None) if self.mode else None

    # --------------------------------------------------------------- cleanup

    def close(self):
        """Stop the motor and release threads. Safe to call more than once."""
        try:
            self.feedback.stop()
        except Exception:
            pass
        try:
            if self.settings.disarm_on_exit:
                self.stop()
                self.disarm()
        except Exception as e:
            self.log.print("Shutdown error: " + str(e), "ERROR", "CLOSE",
                           "Motor_CANopen_Lib", "close")
        try:
            if self.heartbeat is not None and self.heartbeat.enabled:
                self.heartbeat.disable()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False
