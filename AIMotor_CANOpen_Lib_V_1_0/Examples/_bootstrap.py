"""Shared setup for the example scripts.

Puts the folder above the library on sys.path so the examples run from any
working directory, and builds the common argument parser.
"""

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_LIB_ROOT = os.path.dirname(_HERE)
_PARENT = os.path.dirname(_LIB_ROOT)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

PACKAGE = os.path.basename(_LIB_ROOT)


def build_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--config", default=None,
                        help="Path to aimotor_config.json (default: the library's Config folder)")
    parser.add_argument("--profile", default=None,
                        help="Adapter profile from the config: canable2, canalystii, virtual")
    parser.add_argument("--motor", default="AIMotor_1", help="Motor name from the config")
    parser.add_argument("--verbose", action="store_true", help="Log every SDO transaction")
    return parser


def load(args):
    """Return (Config, CANopen_Network) for the parsed arguments."""
    from AIMotor_CANOpen_Lib_V_1_0.CANopen_Network.Network_Lib import CANopen_Network
    from AIMotor_CANOpen_Lib_V_1_0.Housekeeping.Config_Lib import Config

    config = Config(args.config, profile=args.profile)
    network = CANopen_Network(config)
    return config, network


def banner(title: str):
    print("=" * 78)
    print(title)
    print("=" * 78)
