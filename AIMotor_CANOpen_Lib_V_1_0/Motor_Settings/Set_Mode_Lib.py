"""Mode of operation selection (0x6060), verified against 0x6061.

Dispatches to the matching setup class, as the JS2 library's Mode class does.
"""

from typing import Optional

from ..Housekeeping.Logger_Lib import Logger
from ..Motor_Control.PP_Lib import Position_Setup
from ..Motor_Control.PT_Lib import Torque_Setup
from ..Motor_Control.PV_Lib import Velocity_Setup
from ..Motor_Mapping.mapping import AIMotor_CANopen_Map as Map
from ..Motor_Mapping.objects import OD


class Mode():
    def __init__(self, node, node_name: str, canopen_handle, settings, telemetry, io,
                 mode: Optional[int] = None):
        self.node = node
        self.Node_ID = node.id
        self.Node_Name = node_name
        self.canopen_handle = canopen_handle
        self.settings = settings
        self.telemetry = telemetry
        self.io = io
        self.common = canopen_handle.common
        self.log = Logger(node_name, node.id)
        self.DEBUG_INIT = settings.DEBUG_INIT

        self.velocity = None
        self.position = None
        self.torque = None
        self.active = None

        requested = settings.mode if mode is None else int(mode)
        self.supported = self.get_supported_modes()
        self.current = self.set_mode_of_operation(requested)
        self.select_operational_settings_success = self.select_operational_settings(self.current)

    # ------------------------------------------------------------------ mode

    def get_supported_modes(self) -> list:
        """Decode 0x6502. This drive reads back 0x3AD."""
        value = self.io.read(OD.SUPPORTED_MODES)
        if value is None:
            return []
        modes = Map.decode_supported_modes(value)
        if self.DEBUG_INIT:
            self.log.print("Supported drive modes = 0x%08X -> %s" % (value, " ".join(modes)),
                           "SDO", "0x6502", "Mode", "get_supported_modes")
        return modes

    def set_mode_of_operation(self, mode: int) -> Optional[int]:
        """Write 0x6060 and confirm with 0x6061."""
        try:
            if not self.io.write(OD.MODES_OF_OPERATION, int(mode)):
                return None
            readback = self.io.read(OD.MODES_DISPLAY)
            if readback != int(mode):
                self.log.print("Mode mismatch: wrote " + str(mode) + ", 0x6061 reads " +
                               str(readback), "ERROR", "0x6060", "Mode", "set_mode_of_operation")
                if self.settings.FAILURE_EXIT:
                    raise RuntimeError("Mode of operation could not be set")
                return readback
            name = self._mode_name(readback)
            if self.DEBUG_INIT:
                self.log.print("Mode of operation = " + str(readback) + " (" + name + ")",
                               "SDO", "0x6060", "Mode", "set_mode_of_operation")
            self.telemetry.data["mode"] = readback
            return readback
        except Exception as e:
            self.log.print("Set mode error: " + str(e), "ERROR", "0x6060",
                           "Mode", "set_mode_of_operation")
            return None

    def get_mode_of_operation(self) -> Optional[int]:
        return self.io.read(OD.MODES_DISPLAY)

    @staticmethod
    def _mode_name(value) -> str:
        try:
            return Map.ModesOfOperation(int(value)).name
        except (ValueError, TypeError):
            return "UNKNOWN"

    # -------------------------------------------------------------- dispatch

    def select_operational_settings(self, mode) -> bool:
        """Create the setup object for the active mode."""
        try:
            args = (self.node, self.Node_Name, self.canopen_handle, self.settings,
                    self.telemetry, self.io)
            match mode:
                case Map.ModesOfOperation.PROFILE_VELOCITY_MODE:
                    self.velocity = Velocity_Setup(*args)
                    self.active = self.velocity
                    return self.velocity.set_velocity_parameter_success
                case Map.ModesOfOperation.PROFILE_POSITION_MODE:
                    self.position = Position_Setup(*args)
                    self.active = self.position
                    return self.position.set_position_parameter_success
                case Map.ModesOfOperation.PROFILE_TORQUE_MODE:
                    self.torque = Torque_Setup(*args)
                    self.active = self.torque
                    return self.torque.set_torque_parameter_success
                case _:
                    self.log.print("Unsupported mode " + str(mode) + ". This library "
                                   "implements PV (3), PP (1) and PT (4).", "WARNING",
                                   "MODE", "Mode", "select_operational_settings")
                    return False
        except Exception as e:
            self.log.print("Mode dispatch error: " + str(e), "ERROR", "MODE",
                           "Mode", "select_operational_settings")
            return False

    def switch_to(self, mode: int) -> bool:
        """Change mode at runtime. The drive must be disabled first."""
        self.current = self.set_mode_of_operation(int(mode))
        self.select_operational_settings_success = self.select_operational_settings(self.current)
        return self.select_operational_settings_success
