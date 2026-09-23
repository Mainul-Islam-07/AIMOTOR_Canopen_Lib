"""Profile position mode (PP, 0x6060 = 1).

A move needs a rising edge on control word bit 4 to latch the new setpoint:
absolute 0x0F -> 0x1F, relative 0x4F -> 0x5F. Forgetting that edge is the
classic reason a position command is accepted but nothing moves.
"""

from typing import Optional

from ..Housekeeping.Logger_Lib import Logger
from ..Motor_Mapping.mapping import AIMotor_CANopen_Map as Map
from ..Motor_Mapping.objects import OD


class Position_Setup():
    mode_value = 1
    mode_name = "PROFILE_POSITION_MODE"

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

        self.log.print("Starting Profile Position setup...", "INIT", "PP",
                       "Position_Setup", "__init__")
        profile = settings.profile
        self.set_position_parameter_success = self.set_position_parameter(
            profile.get("profile_velocity_pulps"),
            profile.get("profile_acceleration_pulps2"),
            profile.get("profile_deceleration_pulps2"))

    def set_position_parameter(self, profile_velocity, acceleration, deceleration) -> bool:
        """Profile velocity must be non-zero or a position command will not move."""
        try:
            ok = True
            for entry, value in ((OD.PROFILE_VELOCITY, profile_velocity),
                                 (OD.PROFILE_ACCELERATION, acceleration),
                                 (OD.PROFILE_DECELERATION, deceleration)):
                if value is None:
                    continue
                if not self.io.write_verify(entry, int(value)):
                    ok = False
            if not profile_velocity:
                self.log.print("Profile velocity is 0 - the motor will not move",
                               "WARNING", "PROFILE", "Position_Setup", "set_position_parameter")
            if self.DEBUG_INIT:
                self.log.print("Position profile set: vel=" + str(profile_velocity) +
                               " pul/s, accel=" + str(acceleration) + ", decel=" +
                               str(deceleration) + " -> " + ("OK" if ok else "MISMATCH"),
                               "SDO", "PROFILE", "Position_Setup", "set_position_parameter")
            return ok
        except Exception as e:
            self.log.print("Position profile error: " + str(e), "ERROR", "PROFILE",
                           "Position_Setup", "set_position_parameter")
            return False

    def configure(self):
        if self.io.kind != "PDO":
            return None
        raise NotImplementedError("PDO transport is planned for v1.1")

    def clamp(self, target_pul: int) -> int:
        limits = self.settings.limits
        if not limits.get("enforce_in_software", True):
            return int(target_pul)
        low = int(limits.get("min_position_pul", -2147483647))
        high = int(limits.get("max_position_pul", 2147483647))
        clamped = max(low, min(high, int(target_pul)))
        if clamped != int(target_pul):
            self.log.print("Target " + str(target_pul) + " pul clamped to " + str(clamped),
                           "WARNING", "LIMIT", "Position_Setup", "clamp")
        return clamped

    def RUN(self, target_position: int = 0, relative: bool = False) -> Optional[int]:
        """Move to a position in pulses. Absolute by default."""
        try:
            target = self.clamp(target_position)
            if not self.io.write(OD.TARGET_POSITION, target):
                return None
            # Rising edge on bit 4 latches the setpoint.
            base = (Map.ControlWord.SET_RELATIVE_POSITION if relative
                    else Map.ControlWord.ENABLE_OPERATION)
            start = (Map.ControlWord.START_RELATIVE_POSITION if relative
                     else Map.ControlWord.START_ABSOLUTE_POSITION)
            self.io.write(OD.CONTROLWORD, int(base))
            self.io.write(OD.CONTROLWORD, int(start))
            self.io.write(OD.CONTROLWORD, int(base))
            self.telemetry.data["command_position_pul"] = target
            if self.DEBUG_COMMAND:
                self.log.print("Target position = " + str(target) + " pul (" +
                               ("%.3f" % self.units.pul_to_rev(target)) + " rev, " +
                               ("relative" if relative else "absolute") + ")",
                               "SDO", "0x607A", "Position_Setup", "RUN")
            return target
        except Exception as e:
            self.log.print("Position command error: " + str(e), "ERROR", "0x607A",
                           "Position_Setup", "RUN")
            return None

    def run(self, target_position: int = 0, relative: bool = False) -> Optional[int]:
        return self.RUN(target_position, relative)

    def RUN_rev(self, revolutions: float, relative: bool = False) -> Optional[int]:
        return self.RUN(self.units.rev_to_pul(revolutions), relative)

    def halt(self) -> bool:
        """Hold position: command the place the motor is already at."""
        actual = self.io.read(OD.POSITION_ACTUAL)
        if actual is None:
            return False
        return self.io.write(OD.TARGET_POSITION, int(actual))
