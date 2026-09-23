"""Profile velocity mode (PV, 0x6060 = 3) - the AIMOTOR's velocity mode.

The JS2 motor used CSV (9); this drive documents PV (3) instead.

This drive has no 0x6072 max torque or 0x6080 max motor speed object, so the
velocity ceiling cannot be enforced by the drive. Every target is clamped here
against limits.max_velocity_rpm from the JSON config.
"""

from typing import Optional

from ..Housekeeping.Logger_Lib import Logger
from ..Motor_Mapping.objects import OD


class Velocity_Setup():
    mode_value = 3
    mode_name = "PROFILE_VELOCITY_MODE"

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

        self.log.print("Starting Profile Velocity setup...", "INIT", "PV",
                       "Velocity_Setup", "__init__")
        profile = settings.profile
        self.set_velocity_parameter_success = self.set_velocity_parameter(
            profile.get("maximal_profile_velocity_pulps"),
            profile.get("profile_velocity_pulps"),
            profile.get("profile_acceleration_pulps2"),
            profile.get("profile_deceleration_pulps2"),
            profile.get("quick_stop_deceleration_pulps2"))
        self.configure()

    # ------------------------------------------------------------ parameters

    def set_velocity_parameter(self, max_velocity, profile_velocity, acceleration,
                               deceleration, quick_stop_deceleration=None) -> bool:
        """Write the PV profile objects and read each one back."""
        try:
            writes = [
                (OD.MAX_PROFILE_VELOCITY, max_velocity),
                (OD.PROFILE_VELOCITY, profile_velocity),
                (OD.PROFILE_ACCELERATION, acceleration),
                (OD.PROFILE_DECELERATION, deceleration),
            ]
            if quick_stop_deceleration is not None:
                writes.append((OD.QUICK_STOP_DECELERATION, quick_stop_deceleration))

            ok = True
            for entry, value in writes:
                if value is None:
                    continue
                if not self.io.write_verify(entry, int(value)):
                    ok = False
            if self.DEBUG_INIT:
                self.log.print("Profile set: max_vel=" + str(max_velocity) + " pul/s, " +
                               "profile_vel=" + str(profile_velocity) + " pul/s, accel=" +
                               str(acceleration) + " pul/s^2, decel=" + str(deceleration) +
                               " pul/s^2 -> " + ("OK" if ok else "MISMATCH"),
                               "SDO", "PROFILE", "Velocity_Setup", "set_velocity_parameter")
            return ok
        except Exception as e:
            self.log.print("Velocity profile error: " + str(e), "ERROR", "PROFILE",
                           "Velocity_Setup", "set_velocity_parameter")
            return False

    def configure(self):
        """PDO mapping hook. No-op while the transport is SDO."""
        if self.io.kind != "PDO":
            if self.DEBUG_INIT:
                self.log.print("Transport is SDO, no PDO mapping needed", "INIT", "PDO",
                               "Velocity_Setup", "configure")
            return None
        raise NotImplementedError("PDO transport is planned for v1.1")

    # ---------------------------------------------------------------- limits

    def clamp(self, target_pulps: int) -> int:
        """Software velocity limit. The drive has no object that does this."""
        limits = self.settings.limits
        if not limits.get("enforce_in_software", True):
            self.log.print("Software velocity limits are DISABLED in the config",
                           "WARNING", "LIMIT", "Velocity_Setup", "clamp")
            return int(target_pulps)
        max_pulps = self.units.rpm_to_pulps(limits.get("max_velocity_rpm", 500.0))
        clamped = max(-max_pulps, min(max_pulps, int(target_pulps)))
        if clamped != int(target_pulps):
            self.log.print("Target " + str(target_pulps) + " pul/s clamped to " + str(clamped) +
                           " pul/s (limit " + str(limits.get("max_velocity_rpm")) + " rpm)",
                           "WARNING", "LIMIT", "Velocity_Setup", "clamp")
        return clamped

    # ------------------------------------------------------------------- run

    def RUN(self, target_velocity: int = 0) -> Optional[int]:
        """Set the target velocity in Pul/s over SDO."""
        try:
            target = self.clamp(target_velocity)
            if not self.io.write(OD.TARGET_VELOCITY, target):
                return None
            self.telemetry.data["command_velocity_pulps"] = target
            if self.DEBUG_COMMAND:
                self.log.print("Target velocity = " + str(target) + " pul/s (" +
                               ("%.1f" % self.units.pulps_to_rpm(target)) + " rpm)",
                               "SDO", "0x60FF", "Velocity_Setup", "RUN")
            return target
        except Exception as e:
            self.log.print("Velocity command error: " + str(e), "ERROR", "0x60FF",
                           "Velocity_Setup", "RUN")
            return None

    def run(self, target_velocity: int = 0) -> Optional[int]:
        """PDO alias. Delegates to SDO until the PDO transport exists."""
        return self.RUN(target_velocity)

    def RUN_rpm(self, rpm: float) -> Optional[int]:
        """Convenience wrapper that takes rpm and converts to Pul/s."""
        return self.RUN(self.units.rpm_to_pulps(rpm))

    def halt(self) -> bool:
        """Zero the target velocity. Called before every disarm."""
        return self.io.write(OD.TARGET_VELOCITY, 0)
