"""Example 0 - list the CAN adapters and what the config expects.

Opens no bus and touches no motor. Use it to fill in the "serial" fields in
the config so each motor is pinned to its own physical adapter: gs_usb index
order is the USB enumeration order and changes when adapters are replugged.

    python example_00_list_adapters.py
"""

import sys

import _bootstrap


def main() -> int:
    parser = _bootstrap.build_parser("List CAN adapters and the configured motor mapping")
    args = parser.parse_args()

    from AIMotor_CANOpen_Lib_V_1_0.CANopen_Network.Adapter_Resolve_Lib import (
        resolve_adapter_kwargs, scan_gs_usb)
    from AIMotor_CANOpen_Lib_V_1_0.Housekeeping.Config_Lib import Config

    config = Config(args.config, profile=args.profile)
    _bootstrap.banner("CAN adapters - nothing is opened, no motor is touched")

    print("Connected gs_usb adapters:")
    devices = scan_gs_usb()
    if not devices:
        print("   none found")
    for device in devices:
        print("   index %d   bus %s address %s   serial %s"
              % (device["index"], device["bus"], device["address"], device["serial"]))

    print("")
    print("Configured motors:")
    problems = 0
    for name in config.motor_names(enabled_only=False):
        entry = config.motors[name]
        profile = config.motor_adapter(name)
        state = "enabled" if entry.get("enabled", True) else "disabled"
        try:
            kwargs = resolve_adapter_kwargs(config.adapter(profile))
            detail = "%s / %s bps" % (kwargs.get("interface"), kwargs.get("bitrate"))
            if "bus" in kwargs:
                detail += "  pinned to bus %s address %s" % (kwargs["bus"], kwargs["address"])
            else:
                detail += "  index %s (not pinned)" % kwargs.get("index")
        except Exception as e:
            detail = "UNRESOLVED: " + str(e)
            problems += 1
        print("   %-8s node %-3s %-9s adapter %-16s %s"
              % (name, entry.get("node_id"), state, profile, detail))

    if config.warnings:
        print("")
        print("Warnings:")
        for warning in config.warnings:
            print("   - " + warning)

    print("")
    print("Config file: " + config.config_file)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
