"""Object dictionary entries used by this library.

Objects are addressed by numeric index/subindex, never by EDS name, because
the AIMOTOR EDS names differ from the JS2 EDS names and the manufacturer
group H0B has no CiA names at all. The name field is for logging only.

Manufacturer parameters follow the manual's rule:
    index    = 0x2000 + function code group number
    subindex = in-group offset + 1
so H0B_26 (bus voltage) is 0x200B subindex 0x1B.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ODEntry:
    index: int
    sub: int
    name: str
    dtype: str
    access: str = "rw"
    units: str = ""

    @property
    def key(self) -> str:
        return "0x%04X:%02X" % (self.index, self.sub)

    def __str__(self) -> str:
        return self.key + " " + self.name


class OD():
    """Every object this library reads or writes."""

    # --- communication profile ------------------------------------------
    DEVICE_TYPE = ODEntry(0x1000, 0, "Device type", "u32", "ro")
    ERROR_REGISTER = ODEntry(0x1001, 0, "Error Register", "u8", "ro")
    MANUFACTURER_DEVICE_NAME = ODEntry(0x1008, 0, "Manufacturer Device Name", "str", "ro")
    HARDWARE_VERSION = ODEntry(0x1009, 0, "Manufacturer Hardware Version", "str", "ro")
    SOFTWARE_VERSION = ODEntry(0x100A, 0, "Manufacturer Software Version", "str", "ro")
    HEARTBEAT_PRODUCER = ODEntry(0x1017, 0, "Producer Heartbeat Time", "u16", "rw", "ms")
    VENDOR_ID = ODEntry(0x1018, 1, "Vendor Id", "u32", "ro")
    PRODUCT_CODE = ODEntry(0x1018, 2, "Product Code", "u32", "ro")

    # --- manufacturer: motor nameplate, group H00 (read only) -------------
    # Read live from the drive: 48 V, 19.00 A, 2.39 Nm, 3000 rpm, 3600 rpm.
    RATED_VOLTAGE = ODEntry(0x2000, 0x0A, "H00_09 rated voltage", "u16", "ro", "V")
    RATED_CURRENT = ODEntry(0x2000, 0x0C, "H00_11 rated current", "u16", "ro", "0.01A")
    RATED_TORQUE = ODEntry(0x2000, 0x0D, "H00_12 rated torque", "u16", "ro", "0.001Nm")
    RATED_SPEED = ODEntry(0x2000, 0x0F, "H00_14 rated speed", "u16", "ro", "rpm")
    MAX_SPEED = ODEntry(0x2000, 0x10, "H00_15 max speed", "u16", "ro", "rpm")

    # --- manufacturer: control mode selection ----------------------------
    # H02_00 must be 8 for CANopen control, set with the RS485 tool.
    H02_00_CONTROL_MODE = ODEntry(0x2002, 0x01, "H02_00 control mode", "u16", "rw")

    # --- manufacturer: communication group H0C ----------------------------
    # H0C_00 is the node id (and the RS485 address). H0C_08 is the CAN
    # bitrate code: 5 = 500 kbps, 6 = 1 Mbps. Write H0C_13 = 1 to save to
    # EEPROM, then power-cycle. Changing either one over CAN drops the
    # connection you are using, so set them over RS485.
    NODE_ID = ODEntry(0x200C, 0x01, "H0C_00 node id", "u16", "rw")
    RS485_BAUD = ODEntry(0x200C, 0x03, "H0C_02 RS485 baud", "u16", "rw")
    RS485_FORMAT = ODEntry(0x200C, 0x04, "H0C_03 RS485 data format", "u16", "rw")
    CAN_BITRATE = ODEntry(0x200C, 0x09, "H0C_08 CAN bitrate", "u16", "rw")
    SAVE_TO_EEPROM = ODEntry(0x200C, 0x0E, "H0C_13 save to EEPROM", "u16", "rw")

    # --- manufacturer: monitoring group H0B (read only) -------------------
    MOTOR_SPEED_RPM = ODEntry(0x200B, 0x01, "H0B_00 motor speed", "i16", "ro", "rpm")
    INTERNAL_TORQUE = ODEntry(0x200B, 0x03, "H0B_02 internal torque", "i16", "ro", "0.1%")
    PHASE_CURRENT_RMS = ODEntry(0x200B, 0x19, "H0B_24 phase current", "u16", "ro", "0.01A")
    BUS_VOLTAGE = ODEntry(0x200B, 0x1B, "H0B_26 bus voltage", "u16", "ro", "0.1V")
    MODULE_TEMPERATURE = ODEntry(0x200B, 0x1C, "H0B_27 module temperature", "i16", "ro", "degC")
    FAULT_RECORD_SELECT = ODEntry(0x200B, 0x22, "H0B_33 fault record select", "u16", "rw")
    FAULT_CODE = ODEntry(0x200B, 0x23, "H0B_34 fault code", "u16", "ro")

    # --- CiA402 drive profile --------------------------------------------
    ERROR_CODE = ODEntry(0x603F, 0, "Error code", "u16", "ro")
    CONTROLWORD = ODEntry(0x6040, 0, "Controlword", "u16", "rw")
    STATUSWORD = ODEntry(0x6041, 0, "Statusword", "u16", "ro")
    QUICK_STOP_OPTION = ODEntry(0x605A, 0, "Quick stop option code", "i16", "rw")
    MODES_OF_OPERATION = ODEntry(0x6060, 0, "Modes of operation", "i8", "rw")
    MODES_DISPLAY = ODEntry(0x6061, 0, "Modes of operation display", "i8", "ro")
    POSITION_DEMAND = ODEntry(0x6062, 0, "Position demand value", "i32", "ro", "pul")
    POSITION_ACTUAL_ENC = ODEntry(0x6063, 0, "Position actual value_enc", "i32", "ro", "enc")
    POSITION_ACTUAL = ODEntry(0x6064, 0, "Position actual value", "i32", "ro", "pul")
    VELOCITY_DEMAND = ODEntry(0x606B, 0, "Velocity demand value", "i32", "ro", "pul/s")
    VELOCITY_ACTUAL = ODEntry(0x606C, 0, "Velocity actual value", "i32", "ro", "pul/s")
    TARGET_TORQUE = ODEntry(0x6071, 0, "Target torque", "i16", "rw", "0.1%")
    TORQUE_DEMAND = ODEntry(0x6074, 0, "Torque demand value", "i16", "ro", "0.1%")
    TORQUE_ACTUAL = ODEntry(0x6077, 0, "Torque actual value", "i16", "ro", "0.1%")
    CURRENT_ACTUAL = ODEntry(0x6078, 0, "Current actual value", "i16", "ro")
    TARGET_POSITION = ODEntry(0x607A, 0, "Target position", "i32", "rw", "pul")
    HOME_OFFSET = ODEntry(0x607C, 0, "Home offset", "i32", "rw", "pul")
    POLARITY = ODEntry(0x607E, 0, "Polarity", "u8", "rw")
    MAX_PROFILE_VELOCITY = ODEntry(0x607F, 0, "Maximal profile velocity", "u32", "rw", "pul/s")
    PROFILE_VELOCITY = ODEntry(0x6081, 0, "Profile velocity", "u32", "rw", "pul/s")
    PROFILE_ACCELERATION = ODEntry(0x6083, 0, "Profile acceleration", "u32", "rw", "pul/s^2")
    PROFILE_DECELERATION = ODEntry(0x6084, 0, "Profile deceleration", "u32", "rw", "pul/s^2")
    QUICK_STOP_DECELERATION = ODEntry(0x6085, 0, "Quick stop deceleration", "u32", "rw", "pul/s^2")
    HOMING_METHOD = ODEntry(0x6098, 0, "Homing method", "i8", "rw")
    HOMING_SPEED_SEARCH = ODEntry(0x6099, 0x01, "Homing speed search", "i32", "rw", "pul/s")
    HOMING_SPEED_ZERO = ODEntry(0x6099, 0x02, "Homing speed zero", "i32", "rw", "pul/s")
    HOMING_ACCELERATION = ODEntry(0x609A, 0, "Homing acceleration", "i32", "rw", "pul/s^2")
    TARGET_VELOCITY = ODEntry(0x60FF, 0, "Target velocity", "i32", "rw", "pul/s")
    SUPPORTED_MODES = ODEntry(0x6502, 0, "Supported drive modes", "u32", "ro")
