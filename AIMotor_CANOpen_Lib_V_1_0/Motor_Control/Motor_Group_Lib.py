"""Several motors as one unit.

Builds one CANopen_Network per DISTINCT adapter profile and one
Motor_CANopen_Lib per enabled motor. That covers both layouts:

  two adapters  Left -> canable2_left, Right -> canable2_right  (two buses)
  one adapter   Left and Right both -> canable2                 (one bus)

The layout comes from the config; no code changes either way.

Shutdown order matters more than anything else here. With two motors,
disconnecting the first bus while the second motor is still spinning would
leave that motor enabled with a live setpoint. close_all() therefore stops
every poller, disarms every motor, and only then closes any bus.

    with Motor_Group() as group:
        group.preflight_all()
        group.arm_all()
        group.drive(forward_rpm=30)
        print(group.snapshot_all()["Left"]["velocity_rpm"])
"""

import os
import sys
from typing import Dict, List, Optional

from ..CANopen_Network.Network_Lib import CANopen_Network
from ..Housekeeping.Config_Lib import Config
from ..Housekeeping.Logger_Lib import Logger
from ..Motor_Mapping.objects import OD
from .Motor_Lib import Motor_CANopen_Lib


class Motor_Group():
    def __init__(self, config: Optional[object] = None, names: Optional[List[str]] = None,
                 profile: Optional[str] = None, setup_mode: bool = True,
                 strict: bool = False, connect: bool = True, allow_os_exit: bool = False):
        self.config = config if isinstance(config, Config) else Config(config, profile=profile)
        self.profile_override = profile
        self.setup_mode = setup_mode
        self.strict = strict
        self.allow_os_exit = allow_os_exit
        self.log = Logger("Group", -1)

        self.names_wanted = names or self.config.motor_names(enabled_only=True)
        self.networks: Dict[str, CANopen_Network] = {}
        self.motors: Dict[str, Motor_CANopen_Lib] = {}
        self.failures: Dict[str, Exception] = {}
        self._closed = False

        # A hard exit during teardown would skip the remaining motors' disarm.
        if self.config.shutdown.get("os_exit_after_disconnect"):
            self.config.shutdown["os_exit_after_disconnect"] = False
            self.log.print("Disabled shutdown.os_exit_after_disconnect: with several motors it "
                           "could exit before the others are disarmed", "INIT", "SAFETY",
                           "Motor_Group", "__init__")
        if connect:
            self.open()

    @classmethod
    def from_config(cls, config, names=None, **kwargs) -> "Motor_Group":
        return cls(config, names=names, **kwargs)

    # ------------------------------------------------------------------ open

    def open(self) -> "Motor_Group":
        """Open one bus per adapter, then build every motor on its own bus."""
        wanted = {name: self.config.motor_adapter(name, self.profile_override)
                  for name in self.names_wanted}
        profiles = []
        for profile in wanted.values():
            if profile not in profiles:
                profiles.append(profile)

        self.log.print("Opening " + str(len(profiles)) + " bus(es) for " +
                       str(len(wanted)) + " motor(s): " +
                       ", ".join(n + "->" + p for n, p in wanted.items()),
                       "INIT", "GROUP", "Motor_Group", "open")

        for profile in profiles:
            try:
                self.networks[profile] = CANopen_Network(self.config, profile=profile)
            except Exception as e:
                self.log.print("Adapter '" + profile + "' failed: " + str(e), "ERROR",
                               "GROUP", "Motor_Group", "open")
                for name, wanted_profile in wanted.items():
                    if wanted_profile == profile:
                        self.failures[name] = e
                if self.strict:
                    self.close_all()
                    raise

        for name, profile in wanted.items():
            if profile not in self.networks:
                continue
            try:
                self.motors[name] = Motor_CANopen_Lib(name, self.networks[profile], self.config,
                                                      setup_mode=self.setup_mode)
            except Exception as e:
                self.failures[name] = e
                self.log.print("Motor '" + name + "' failed: " + str(e), "ERROR", "GROUP",
                               "Motor_Group", "open")
                if self.strict:
                    self.close_all()
                    raise
        return self

    # ---------------------------------------------------------------- access

    def names(self) -> List[str]:
        return list(self.names_wanted)

    def online(self) -> List[str]:
        return list(self.motors)

    def __getitem__(self, name: str) -> Motor_CANopen_Lib:
        return self.motors[name]

    def get(self, name: str, default=None):
        return self.motors.get(name, default)

    def __contains__(self, name: str) -> bool:
        return name in self.motors

    def __len__(self) -> int:
        return len(self.motors)

    def __iter__(self):
        return iter(self.motors.items())

    def adapter_of(self, name: str) -> str:
        return self.config.motor_adapter(name, self.profile_override)

    def network_of(self, name: str) -> Optional[CANopen_Network]:
        return self.networks.get(self.adapter_of(name))

    def _targets(self, names: Optional[List[str]] = None) -> List[str]:
        return [n for n in (names or self.online()) if n in self.motors]

    def _fan_out(self, method: str, names=None, **kwargs) -> dict:
        """Call one motor method on each motor; one failure never stops the rest."""
        results = {}
        for name in self._targets(names):
            try:
                results[name] = getattr(self.motors[name], method)(**kwargs)
            except Exception as e:
                results[name] = None
                self.log.print("[" + name + "] " + method + " failed: " + str(e), "ERROR",
                               "GROUP", "Motor_Group", method)
        return results

    # ------------------------------------------------------------ operations

    def preflight_all(self, raise_on_fail: bool = False, names=None) -> dict:
        reports = self._fan_out("preflight", names=names, raise_on_fail=False)
        if raise_on_fail:
            bad = [n for n, r in reports.items() if not (r or {}).get("ok")]
            if bad or self.failures:
                raise RuntimeError("Preflight failed for: " +
                                   ", ".join(bad + list(self.failures)))
        return reports

    def verify_topology(self) -> dict:
        """Check each bus answers on its own node id and not on another motor's.

        Catches swapped adapters, which would otherwise send Left's commands
        to the Right motor.
        """
        results = {}
        for name, motor in self.motors.items():
            ok = motor.io.read(OD.DEVICE_TYPE) is not None
            others = [m for n, m in self.motors.items()
                      if n != name and self.network_of(n) is self.network_of(name)]
            if ok and not others:
                # Nothing else should answer on a dedicated bus.
                for other_name, other in self.motors.items():
                    if other_name == name or self.network_of(other_name) is self.network_of(name):
                        continue
                    stray = motor.canopen_handle.nodes.get(other.Node_ID)
                    if stray is not None:
                        ok = False
            results[name] = ok
            if not ok:
                self.log.print("[" + name + "] topology check failed - is the adapter for "
                               "this motor the right one?", "ERROR", "GROUP",
                               "Motor_Group", "verify_topology")
        return results

    def arm_all(self, names=None) -> dict:
        return self._fan_out("arm", names=names)

    def disarm_all(self, names=None) -> dict:
        return self._fan_out("disarm", names=names)

    def stop_all(self, names=None) -> dict:
        return self._fan_out("stop", names=names)

    def quick_stop_all(self, names=None) -> dict:
        return self._fan_out("quick_stop", names=names)

    def fault_reset_all(self, names=None) -> dict:
        return self._fan_out("fault_reset", names=names)

    def snapshot_all(self, names=None) -> dict:
        return self._fan_out("snapshot", names=names)

    def set_nmt_all(self, state: str) -> None:
        """NMT is a broadcast per bus, so this is done once per network."""
        for profile, network in self.networks.items():
            try:
                network.set_nmt_state(state)
            except Exception as e:
                self.log.print("NMT " + state + " failed on '" + profile + "': " + str(e),
                               "ERROR", "GROUP", "Motor_Group", "set_nmt_all")

    # -------------------------------------------------------------- movement

    def run_rpm(self, targets: dict) -> dict:
        """{motor_name: rpm}. Each motor clamps against its own config limits."""
        results = {}
        for name, rpm in targets.items():
            motor = self.motors.get(name)
            if motor is None or motor.velocity is None:
                results[name] = None
                continue
            try:
                results[name] = motor.velocity.RUN_rpm(rpm)
            except Exception as e:
                results[name] = None
                self.log.print("[" + name + "] velocity command failed: " + str(e), "ERROR",
                               "GROUP", "Motor_Group", "run_rpm")
        return results

    def drive(self, forward_rpm: float = 0.0, turn_rpm: float = 0.0,
              invert_right: Optional[bool] = None) -> dict:
        """Differential mixer: forward plus turn, mapped onto the two motors."""
        pairing = self.config.pairing()
        left = pairing.get("left_motor", "Left")
        right = pairing.get("right_motor", "Right")
        if invert_right is None:
            invert_right = pairing.get("invert_right_for_forward", True)
        left_rpm = float(forward_rpm) + float(turn_rpm)
        right_rpm = (float(forward_rpm) - float(turn_rpm)) * (-1.0 if invert_right else 1.0)
        return self.run_rpm({left: left_rpm, right: right_rpm})

    # --------------------------------------------------------------- cleanup

    def close_all(self, disconnect: bool = True, hard_exit: Optional[bool] = False) -> None:
        """Stop pollers, disarm every motor, then close the buses. Idempotent."""
        if self._closed:
            return
        self._closed = True

        # 1. pollers on every bus first, so nothing is still issuing SDOs
        for name, motor in self.motors.items():
            try:
                motor.feedback.stop()
            except Exception:
                pass

        # 2. every motor stopped and disarmed BEFORE any bus is closed
        for name, motor in self.motors.items():
            try:
                motor.close()
            except Exception as e:
                self.log.print("[" + name + "] shutdown failed, sending raw disarm: " + str(e),
                               "ERROR", "GROUP", "Motor_Group", "close_all")
                network = self.network_of(name)
                if network is not None:
                    try:
                        network.recovery()
                    except Exception:
                        pass

        # 3. only now close the buses
        if disconnect:
            for profile, network in self.networks.items():
                try:
                    network.disconnect(hard_exit=False)
                except Exception as e:
                    self.log.print("Disconnect of '" + profile + "' raised: " + str(e),
                                   "WARNING", "GROUP", "Motor_Group", "close_all")
        self.motors = {}
        self.networks = {}

        # 4. everything is down, so a hard exit is safe if it was asked for
        if hard_exit or (self.allow_os_exit and
                         self.config.shutdown.get("os_exit_after_disconnect")):
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(int(self.config.shutdown.get("os_exit_code", 0)))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close_all()
        return False
