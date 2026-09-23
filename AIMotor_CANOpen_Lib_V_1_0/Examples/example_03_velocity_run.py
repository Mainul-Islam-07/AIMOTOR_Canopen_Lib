"""Example 3 - run the motor in velocity mode (PV, 0x6060 = 3).

THIS MOVES THE MOTOR. Clear the shaft and secure the motor before running.
Nothing moves unless you pass --yes.

    python example_03_velocity_run.py --rpm 30 --seconds 2 --yes
    python example_03_velocity_run.py --rpm -60 --seconds 3 --yes

Sequence: preflight, set PV mode, write the profile, zero the setpoint,
arm (0x06 -> 0x07 -> 0x0F), command the speed, poll, then stop and disarm.
The stop and disarm also run from finally, so Ctrl+C stops the motor.
"""

import sys
import time

import _bootstrap


def main() -> int:
    parser = _bootstrap.build_parser("Run the AIMOTOR in profile velocity mode")
    parser.add_argument("--rpm", type=float, default=30.0, help="Target speed in rpm")
    parser.add_argument("--seconds", type=float, default=2.0, help="How long to run")
    parser.add_argument("--accel-rpm-s", type=float, default=None,
                        help="Acceleration in rpm/s (default: from the config)")
    parser.add_argument("--period", type=float, default=0.2, help="Seconds between readings")
    parser.add_argument("--yes", action="store_true",
                        help="Required. Confirms the motor is safe to turn.")
    args = parser.parse_args()

    from AIMotor_CANOpen_Lib_V_1_0.Motor_Control.Motor_Lib import Motor_CANopen_Lib
    from AIMotor_CANOpen_Lib_V_1_0.Motor_Mapping.objects import OD

    config, network = _bootstrap.load(args)
    _bootstrap.banner("AIMOTOR velocity mode - THE MOTOR WILL TURN")

    motor = None
    exit_code = 0
    try:
        motor = Motor_CANopen_Lib(args.motor, network, config)
        motor.io.debug = args.verbose
        units = motor.units

        report = motor.preflight()
        if not report["ok"]:
            print("Preflight failed: " + "; ".join(report["problems"]))
            return 1

        target_pulps = motor.velocity.clamp(units.rpm_to_pulps(args.rpm))
        target_rpm = units.pulps_to_rpm(target_pulps)
        print("")
        print("  Plan: %.1f rpm (%d pul/s) for %.1f s on %s node %d"
              % (target_rpm, target_pulps, args.seconds, args.motor, motor.Node_ID))
        print("  Limit: %.1f rpm from the config" % motor.settings.limits.get("max_velocity_rpm"))
        if not args.yes:
            print("")
            print("  Not moving. Re-run with --yes once the shaft is clear.")
            return 0

        if args.accel_rpm_s:
            accel = units.rpm_s_to_pulps2(args.accel_rpm_s)
            motor.io.write_verify(OD.PROFILE_ACCELERATION, accel)
            motor.io.write_verify(OD.PROFILE_DECELERATION, accel)
            print("  Accel/decel set to %d pul/s^2 (%.0f rpm/s)" % (accel, args.accel_rpm_s))

        motor.velocity.RUN(0)          # zero the setpoint before enabling
        if not motor.arm():
            print("ARM failed - see the log above.")
            return 1

        start_position = motor.io.read(OD.POSITION_ACTUAL)
        motor.velocity.RUN(target_pulps)

        start = time.time()
        while time.time() - start < args.seconds:
            data = motor.snapshot()
            print("  t=+%.2fs  target %d pul/s (%.1f rpm) | actual %s pul/s (%s rpm) "
                  "| pos %s pul | sw %s %s"
                  % (time.time() - start, target_pulps, target_rpm,
                     data.get("velocity_pulps"), data.get("velocity_rpm"),
                     data.get("position_pul"), data.get("statusword_hex"), data.get("state")))
            time.sleep(args.period)

        motor.velocity.RUN(0)
        time.sleep(0.5)
        end_position = motor.io.read(OD.POSITION_ACTUAL)
        if start_position is not None and end_position is not None:
            travelled = end_position - start_position
            print("")
            print("  RESULT: travelled %d pul (%.3f rev) in %.2f s -> mean %.1f rpm"
                  % (travelled, units.pul_to_rev(travelled), args.seconds,
                     units.pul_to_rev(travelled) * 60.0 / max(args.seconds, 0.001)))
    except KeyboardInterrupt:
        print("\nCtrl+C - stopping the motor.")
    except Exception as e:
        print("ERROR: " + str(e))
        exit_code = 1
    finally:
        if motor is not None:
            motor.close()
        network.disconnect()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
