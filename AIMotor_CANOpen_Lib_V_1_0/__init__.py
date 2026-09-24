"""AIMOTOR CANopen library.

Quick start:
    from AIMotor_CANOpen_Lib_V_1_0 import CANopen_Network, Motor_CANopen_Lib
"""

from .CANopen_Network.Network_Lib import CANopen_Network
from .Housekeeping.Config_Lib import Config
from .Motor_Control.Motor_Group_Lib import Motor_Group
from .Motor_Control.Motor_Lib import Motor_CANopen_Lib
from .Motor_Mapping.mapping import AIMotor_CANopen_Map
from .Motor_Mapping.objects import OD

__version__ = "1.0"
__all__ = ["CANopen_Network", "Motor_CANopen_Lib", "Motor_Group", "Config",
           "AIMotor_CANopen_Map", "OD"]
