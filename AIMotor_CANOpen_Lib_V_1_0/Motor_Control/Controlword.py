"""CiA402 state machine handling for the AIMOTOR drive.

Enable sequence from the manual: 0x00 -> 0x06 -> 0x07 -> 0x0F, with the
statusword walking 0x0231 -> 0x0233 -> 0x0237. Unlike the JS2 library, every
transition here is verified by reading 0x6041 before moving on, and the
setpoint is forced to zero before the drive is enabled so a stale target
cannot cause a lurch.
"""

import time
from typing import Optional

from ..Housekeeping.Logger_Lib import Logger
from ..Motor_Mapping.mapping import AIMotor_CANopen_Map as Map
from ..Motor_Mapping.objects import OD


class Controlword_Setup():
    def __init__(self, node, node_name: str, canopen_handle, settings, telemetry, io, mode=None):
        self.node = node
        self.Node_ID = node.id
        self.Node_Name = node_name
        self.canopen_handle = canopen_handle
        self.settings = settings
        self.telemetry = telemetry
        self.io = io
        self.mode = mode
        self.common = canopen_handle.common
        self.log = Logger(node_name, node.id)
        self.DEBUG = settings.DEBUG_CONTROLWORD

    # ------------------------------------------------------------- primitives

    def CONTROLWORD(self, controlword: int) -> bool:
        """Write object 0x6040 over SDO."""
        ok = self.io.write(OD.CONTROLWORD, int(controlword))
        if self.DEBUG:
            self.log.print("Controlword <- 0x%04X" % int(controlword), "SDO", "0x6040",
                           "Controlword_Setup", "CONTROLWORD")
        return ok

    def controlword(self, controlword: int) -> bool:
        """PDO alias. Delegates to SDO until the PDO transport exists."""
        return self.CONTROLWORD(controlword)

    def read_statusword(self) -> Optional[int]:
        value = self.io.read(OD.STATUSWORD)
        if value is not None:
            self.telemetry.data["statusword"] = value
        return value

    def read_state(self):
        statusword = self.read_statusword()
        if statusword is None:
            return Map.StateMachineState.UNKNOWN
        return Map.decode_state(statusword)

    def is_enabled(self) -> bool:
        return self.read_state() == Map.StateMachineState.OPERATION_ENABLED

    def is_faulted(self) -> bool:
        statusword = self.read_statusword()
        return bool(statusword is not None and Map.is_faulted(statusword))

    def wait_for_state(self, expected, timeout_s: Optional[float] = None) -> bool:
        """Poll the statusword until it reports the expected state."""
        timeout_s = timeout_s if timeout_s is not None else self.common.state_transition_timeout_s
        deadline = time.time() + timeout_s
        statusword = None
        while time.time() < deadline:
            statusword = self.read_statusword()
            if statusword is not None and Map.decode_state(statusword) == expected:
                if self.DEBUG:
                    self.log.print("State " + expected.name + " reached (statusword 0x%04X)"
                                   % statusword, "SDO", "0x6041", "Controlword_Setup",
                                   "wait_for_state")
                return True
            time.sleep(self.common.delay_SDO_S * 20)
        self.log.print("Timeout waiting for " + expected.name + ", statusword " +
                       ("0x%04X" % statusword if statusword is not None else "None"),
                       "ERROR", "0x6041", "Controlword_Setup", "wait_for_state")
        return False

    # ----------------------------------------------------------------- faults

    def fault_reset(self) -> bool:
        """Rising edge on bit 7 clears a latched fault."""
        self.log.print("Fault reset", "CONTROL", "0x6040", "Controlword_Setup", "fault_reset")
        self.CONTROLWORD(Map.ControlWord.DISABLE_VOLTAGE)
        self.CONTROLWORD(Map.ControlWord.RESET_FAULT)
        self.common.delay(0.05)
        self.CONTROLWORD(Map.ControlWord.DISABLE_VOLTAGE)
        self.common.delay(0.05)
        return not self.is_faulted()

    # ------------------------------------------------------------ arm/disarm

    def ARM(self) -> bool:
        """Enable the servo. The motor becomes energised when this returns True."""
        try:
            self.CONTROLWORD(Map.ControlWord.DISABLE_VOLTAGE)

            if self.is_faulted():
                if not self.settings.clear_fault_on_arm:
                    self.log.print("Drive is faulted and clear_fault_on_arm is false",
                                   "ERROR", "ARM", "Controlword_Setup", "ARM")
                    return False
                if not self.fault_reset():
                    self.log.print("Fault could not be cleared, not arming", "ERROR", "ARM",
                                   "Controlword_Setup", "ARM")
                    return False

            # Zero the setpoint BEFORE enabling, so a stale target cannot move
            # the motor the instant the drive is enabled.
            self.CONTROLWORD_HALT()

            self.CONTROLWORD(Map.ControlWord.SHUT_DOWN)
            if not self.wait_for_state(Map.StateMachineState.READY_TO_SWITCH_ON):
                return self._abort_arm()

            self.CONTROLWORD(Map.ControlWord.SWITCH_ON)
            if not self.wait_for_state(Map.StateMachineState.SWITCHED_ON):
                return self._abort_arm()

            self.CONTROLWORD(Map.ControlWord.ENABLE_OPERATION)
            if not self.wait_for_state(Map.StateMachineState.OPERATION_ENABLED):
                return self._abort_arm()

            self.common.delay(self.common.brake_release_delay_s)
            self.log.print("ARMED - motor is energised", "CONTROL", "ARM",
                           "Controlword_Setup", "ARM")
            return True
        except Exception as e:
            self.log.print("ARM failure: " + str(e), "ERROR", "ARM", "Controlword_Setup", "ARM")
            self._abort_arm()
            return False

    def _abort_arm(self) -> bool:
        self.log.print("ARM aborted, disarming", "ERROR", "ARM", "Controlword_Setup", "_abort_arm")
        self.DISARM()
        return False

    def arm(self) -> bool:
        return self.ARM()

    def DISARM(self) -> bool:
        """Stop, then walk the state machine down. Safe to call repeatedly."""
        ok = True
        for step in (Map.ControlWord.SWITCH_ON, Map.ControlWord.SHUT_DOWN,
                     Map.ControlWord.DISABLE_VOLTAGE):
            try:
                if self.settings.stop_before_disarm and step == Map.ControlWord.SWITCH_ON:
                    self.CONTROLWORD_HALT()
                self.CONTROLWORD(step)
            except Exception as e:
                ok = False
                self.log.print("Disarm step 0x%02X failed: %s" % (int(step), str(e)),
                               "ERROR", "DISARM", "Controlword_Setup", "DISARM")
        self.log.print("DISARMED", "CONTROL", "DISARM", "Controlword_Setup", "DISARM")
        return ok

    def disarm(self) -> bool:
        return self.DISARM()

    def quick_stop(self) -> bool:
        """Ramp down on 0x6085. Bit 2 is active low, so the value is 0x02."""
        self.log.print("QUICK STOP", "CONTROL", "0x6040", "Controlword_Setup", "quick_stop")
        return self.CONTROLWORD(Map.ControlWord.QUICK_STOP)

    # ------------------------------------------------------------------ halt

    def CONTROLWORD_HALT(self) -> bool:
        """Zero the active mode's setpoint without changing the state machine."""
        try:
            mode_setup = getattr(self.mode, "active", None) if self.mode else None
            if mode_setup is not None and hasattr(mode_setup, "halt"):
                return mode_setup.halt()
            # No mode object yet: zero the velocity and torque targets directly.
            self.io.write(OD.TARGET_VELOCITY, 0)
            self.io.write(OD.TARGET_TORQUE, 0)
            return True
        except Exception as e:
            self.log.print("Halt failure: " + str(e), "ERROR", "HALT",
                           "Controlword_Setup", "CONTROLWORD_HALT")
            return False

    def controword_halt(self) -> bool:
        """Spelling kept from the JS2 library so existing call sites still work."""
        return self.CONTROLWORD_HALT()
