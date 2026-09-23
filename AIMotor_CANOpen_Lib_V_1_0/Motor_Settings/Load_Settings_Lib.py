"""Per-motor settings.

The JS2 library read these from motor_settings.xlsx with openpyxl. Here they
come from the single JSON config: motor_defaults merged with the motor's own
entry, so a second motor only needs its node_id.
"""

from typing import Optional

from ..Housekeeping.Config_Lib import Config
from ..Housekeeping.Logger_Lib import Logger
from ..Housekeeping.Units_Lib import Units


class Load_Settings():
    def __init__(self, config: Config, node_name: str):
        self.config = config
        self.Node_Name = node_name
        self.log = Logger(node_name, -1)

        motor = config.motor(node_name)
        self.raw = motor
        self.Node_ID = int(motor["node_id"])
        self.log.set_node_id(self.Node_ID)

        self.enabled = motor.get("enabled", True)
        self.description = motor.get("description", "")
        self.eds_file = motor.get("eds_file", "AIMotorV2.3.eds")
        self.eds_path = config.eds_path(self.eds_file)
        self.mode = int(motor.get("mode", 3))
        self.transport = str(motor.get("transport", "SDO")).upper()

        self.pulses_per_rev = int(motor.get("pulses_per_rev", 1000))
        self.gear_ratio = float(motor.get("gear_ratio", 1.0))
        self.rated_torque_nm = float(motor.get("rated_torque_nm", 0.0))
        self.rated_current_a = float(motor.get("rated_current_a", 0.0))
        self.units = Units(self.pulses_per_rev, self.gear_ratio,
                           self.rated_torque_nm, self.rated_current_a)

        self.require_canopen_mode = motor.get("require_canopen_mode", True)
        self.canopen_mode_value = int(motor.get("canopen_mode_value", 8))
        self.abort_if_not_canopen_mode = motor.get("abort_if_not_canopen_mode", True)
        self.clear_fault_on_arm = motor.get("clear_fault_on_arm", True)
        self.abort_if_fault_on_startup = motor.get("abort_if_fault_on_startup", True)

        self.feedback = motor.get("feedback", {})
        self.heartbeat = motor.get("heartbeat", {})
        self.limits = motor.get("limits", {})
        self.profile = motor.get("profile", {})

        logging_cfg = config.logging
        self.DEBUG_INIT = logging_cfg.get("DEBUG_INIT", True)
        self.DEBUG_COMMAND = logging_cfg.get("DEBUG_COMMAND", True)
        self.DEBUG_FEEDBACK = logging_cfg.get("DEBUG_FEEDBACK", True)
        self.DEBUG_HEARTBEAT = logging_cfg.get("DEBUG_HEARTBEAT", True)
        self.DEBUG_CONTROLWORD = logging_cfg.get("DEBUG_CONTROLWORD", True)
        self.FAILURE_EXIT = logging_cfg.get("FAILURE_EXIT", False)

        shutdown_cfg = config.shutdown
        self.stop_before_disarm = shutdown_cfg.get("stop_before_disarm", True)
        self.disarm_on_exit = shutdown_cfg.get("disarm_on_exit", True)

        if self.DEBUG_INIT:
            self.log.print("Settings loaded: node " + str(self.Node_ID) + ", mode " +
                           str(self.mode) + ", transport " + self.transport + ", " +
                           str(self.pulses_per_rev) + " pulses/rev", "INIT", "SETTINGS",
                           "Load_Settings", "__init__")

    def get(self, key: str, default: Optional[object] = None):
        return self.raw.get(key, default)
