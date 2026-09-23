"""CANopen control structures and states for the AIMOTOR drive.

Mirrors the JS2 library's Avatarrobot_CANopen_Map, with the values the
AIMOTOR manual actually documents. The biggest difference: this drive's
velocity mode is PV (3), not CSV (9).
"""

from enum import IntEnum


class AIMotor_CANopen_Map():

    @staticmethod
    def generate_descriptions(enum_class):
        return {key: key.name.replace("_", " ").title() for key in enum_class}

    class ModesOfOperation(IntEnum):
        """Object 0x6060. Values the AIMOTOR manual documents."""
        NO_MODE = 0
        PROFILE_POSITION_MODE = 1
        PROFILE_VELOCITY_MODE = 3
        PROFILE_TORQUE_MODE = 4
        HOMING_MODE = 6
        CYCLIC_SYNCHRONOUS_POSITION_MODE = 8

    class ControlWord(IntEnum):
        """Object 0x6040. Quick stop (bit 2) is active low on this drive."""
        DISABLE_VOLTAGE = 0x00
        QUICK_STOP = 0x02
        SHUT_DOWN = 0x06
        SWITCH_ON = 0x07
        ENABLE_OPERATION = 0x0F
        START_ABSOLUTE_POSITION = 0x1F
        START_RELATIVE_POSITION = 0x5F
        SET_RELATIVE_POSITION = 0x4F
        RESET_FAULT = 0x80

    class StatuswordValue(IntEnum):
        """Whole-word values listed in the manual's state transition table."""
        NO_FAULT = 0x0250
        READY_TO_SWITCH_ON = 0x0231
        WAIT_ENABLE = 0x0233
        SERVO_RUN = 0x0237
        QUICK_STOP = 0x0217
        FAULT_STOPPING = 0x021F
        FAULT = 0x0218

    class StateMachineState(IntEnum):
        UNKNOWN = 0
        NOT_READY_TO_SWITCH_ON = 1
        SWITCH_ON_DISABLED = 2
        READY_TO_SWITCH_ON = 3
        SWITCHED_ON = 4
        OPERATION_ENABLED = 5
        QUICK_STOP_ACTIVE = 6
        FAULT_REACTION_ACTIVE = 7
        FAULT = 8

    class StatuswordBit(IntEnum):
        READY_TO_SWITCH_ON = 0
        SWITCHED_ON = 1
        OPERATION_ENABLED = 2
        FAULT = 3
        VOLTAGE_ENABLED = 4
        QUICK_STOP = 5
        SWITCH_ON_DISABLED = 6
        WARNING = 7
        REMOTE = 9
        TARGET_REACHED = 10
        HOMING_ATTAINED = 15

    class NMTState(IntEnum):
        BOOT_UP = 0x00
        STOPPED = 0x04
        OPERATIONAL = 0x05
        PRE_OPERATIONAL = 0x7F

    class SupportedModeBit(IntEnum):
        """Bits of object 0x6502. This drive reads back 0x3AD."""
        PP = 0
        VL = 1
        PV = 2
        TQ = 3
        HM = 5
        IP = 6
        CSP = 7
        CSV = 8
        CST = 9

    STATE_MASK = 0x006F

    @classmethod
    def decode_state(cls, statusword: int):
        """Map a statusword to a CiA402 state, ignoring vendor bits 8 and 9."""
        masked = statusword & cls.STATE_MASK
        if masked & 0x004F == 0x0000:
            return cls.StateMachineState.NOT_READY_TO_SWITCH_ON
        if masked & 0x004F == 0x0040:
            return cls.StateMachineState.SWITCH_ON_DISABLED
        if masked & 0x006F == 0x0021:
            return cls.StateMachineState.READY_TO_SWITCH_ON
        if masked & 0x006F == 0x0023:
            return cls.StateMachineState.SWITCHED_ON
        if masked & 0x006F == 0x0027:
            return cls.StateMachineState.OPERATION_ENABLED
        if masked & 0x006F == 0x0007:
            return cls.StateMachineState.QUICK_STOP_ACTIVE
        if masked & 0x004F == 0x000F:
            return cls.StateMachineState.FAULT_REACTION_ACTIVE
        if masked & 0x004F == 0x0008:
            return cls.StateMachineState.FAULT
        return cls.StateMachineState.UNKNOWN

    @classmethod
    def decode_supported_modes(cls, value: int) -> list:
        return [bit.name for bit in cls.SupportedModeBit if value & (1 << bit.value)]

    @classmethod
    def statusword_flags(cls, statusword: int) -> list:
        return [bit.name for bit in cls.StatuswordBit if statusword & (1 << bit.value)]

    @classmethod
    def is_faulted(cls, statusword: int) -> bool:
        return bool(statusword & (1 << cls.StatuswordBit.FAULT))
