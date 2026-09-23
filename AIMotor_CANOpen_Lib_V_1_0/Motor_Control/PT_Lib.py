"""Profile torque mode (PT, 0x6060 = 4).

Target torque 0x6071 is in 0.1 % of rated torque: 1000 means rated torque.
0x607F caps the speed the drive will reach while producing that torque -
leave it sensible, or an unloaded motor will run away to its speed limit.
"""

from typing import Optional

from ..Housekeeping.Logger_Lib import Logger
from ..Motor_Mapping.objects import OD


class Torque_Setup():
    mode_value = 4
    mode_name = "PROFILE_TORQUE_MODE"

    def __init__(self, node, node_name: str, canopen_handle, settings, telemetry, io):
        self.node = node
        self.Node_ID = node.id
        self.Node_Name = node_name
        self.canopen_handle = canopen_handle
        self.settings = settings
        self.telemetry = telemetry
        self.io = io
        self.units = settings.units
        self.common = canopen_handle.common
        self.log = Logger(node_name, node.id)
        self.DEBUG_INIT = settings.DEBUG_INIT
        self.DEBUG_COMMAND = settings.DEBUG_COMMAND

        self.log.print("Starting Profile Torque setup...", "INIT", "PT",
                       "Torque_Setup", "__init__")
        self.set_torque_parameter_success = self.set_torque_parameter(
            settings.profile.get("maximal_profile_velocity_pulps"))

    def set_torque_parameter(self, max_profile_velocity) -> bool:
        """0x607F is the speed ceiling while running on torque."""
        try:
            if max_profile_velocity is None:
                return False
            ok = self.io.write_verify(OD.MAX_PROFILE_VELOCITY, int(max_profile_velocity))
            if self.DEBUG_INIT:
                self.log.print("Torque speed limit = " + str(max_profile_velocity) +
                               " pul/s -> " + ("OK" if ok else "MISMATCH"), "SDO", "0x607F",
                               "Torque_Setup", "set_torque_parameter")
            return ok
        except Exception as e:
            self.log.print("Torque parameter error: " + str(e), "ERROR", "PROFILE",
                           "Torque_Setup", "set_torque_parameter")
            return False

    def configure(self):
        if self.io.kind != "PDO":
            return None
        raise NotImplementedError("PDO transport is planned for v1.1")

    def clamp(self, permille: int) -> int:
        limits = self.settings.limits
        if not limits.get("enforce_in_software", True):
            return int(permille)
        cap = int(limits.get("max_torque_permille", 300))
        clamped = max(-cap, min(cap, int(permille)))
        if clamped != int(permille):
            self.log.print("Torque " + str(permille) + " clamped to " + str(clamped) +
                           " (0.1% units)", "WARNING", "LIMIT", "Torque_Setup", "clamp")
        return clamped

    def RUN(self, target_torque: int = 0) -> Optional[int]:
        """Set target torque in 0.1 % of rated torque."""
        try:
            target = self.clamp(target_torque)
            if not self.io.write(OD.TARGET_TORQUE, target):
                return None
            self.telemetry.data["command_torque_permille"] = target
            if self.DEBUG_COMMAND:
                self.log.print("Target torque = " + str(target) + " (" +
                               ("%.1f" % self.units.permille_to_percent(target)) + " % rated)",
                               "SDO", "0x6071", "Torque_Setup", "RUN")
            return target
        except Exception as e:
            self.log.print("Torque command error: " + str(e), "ERROR", "0x6071",
                           "Torque_Setup", "RUN")
            return None

    def run(self, target_torque: int = 0) -> Optional[int]:
        return self.RUN(target_torque)

    def RUN_percent(self, percent: float) -> Optional[int]:
        return self.RUN(self.units.percent_to_permille(percent))

    def halt(self) -> bool:
        return self.io.write(OD.TARGET_TORQUE, 0)
