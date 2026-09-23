"""Example 1 - READ ONLY identity and preflight check. Run this first.

Reads the drive's identity and health. Writes nothing, never enables the
motor, so it is safe with the shaft coupled.

    python example_01_read_identity.py
    python example_01_read_identity.py --profile canalystii
"""

import sys

import _bootstrap


def main() -> int:
    parser = _bootstrap.build_parser("Read AIMOTOR identity and run a preflight check")
    args = parser.parse_args()

    from AIMotor_CANOpen_Lib_V_1_0.Motor_Control.Motor_Lib import Motor_CANopen_Lib
    from AIMotor_CANOpen_Lib_V_1_0.Motor_Mapping.objects import OD

    config, network = _bootstrap.load(args)
    _bootstrap.banner("AIMOTOR identity - read only")

    exit_code = 0
    try:
        # setup_mode=False so nothing is written to 0x6060.
        motor = Motor_CANopen_Lib(args.motor, network, config, setup_mode=False)
        motor.io.debug = args.verbose

        report = motor.preflight()

        print("")
        print("  Device type       0x%08X" % (report["device_type"] or 0))
        print("  Supported modes   0x%08X -> %s" % (report["supported_modes_raw"] or 0,
                                                    " ".join(report["supported_modes"])))
        print("  H02-00            %s (8 = CANopen control mode)" % report["H02_00"])
        print("  Statusword        0x%04X  %s" % (report["statusword"] or 0, report["state"]))
        print("  Position actual   %s pul (%.3f rev)" %
              (report["position_pul"], motor.units.pul_to_rev(report["position_pul"] or 0)))
        print("  Heartbeat 0x1017  %s ms%s" % (report["heartbeat_producer_ms"],
              " (disabled)" if not report["heartbeat_producer_ms"] else ""))
        print("  Error code        %s" % motor.feedback._hex(report["error_code"]))
        print("  Error register    %s" % motor.feedback._hex(report["error_register"], 2))
        print("  Fault code H0B_34 %s" % motor.feedback._hex(report["fault_code"]))
        print("  Hardware version  %s" % motor.io.read(OD.HARDWARE_VERSION))
        print("  Software version  %s" % motor.io.read(OD.SOFTWARE_VERSION))
        print("")

        if report["ok"]:
            print("PREFLIGHT: PASS - drive is ready. Safe to run example_02.")
        else:
            print("PREFLIGHT: FAIL")
            for problem in report["problems"]:
                print("   - " + problem)
            exit_code = 1
    except Exception as e:
        print("ERROR: " + str(e))
        exit_code = 1
    finally:
        network.disconnect()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
