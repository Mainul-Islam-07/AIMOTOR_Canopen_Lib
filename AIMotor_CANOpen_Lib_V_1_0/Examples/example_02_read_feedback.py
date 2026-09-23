"""Example 2 - READ ONLY feedback loop.

Polls everything the drive reports: state, errors, position, velocity,
torque, bus voltage, phase current, temperature and heartbeat status.
The motor is never enabled, so it cannot move.

    python example_02_read_feedback.py --duration 10 --period 0.5
"""

import sys
import time

import _bootstrap


def main() -> int:
    parser = _bootstrap.build_parser("Poll AIMOTOR feedback, read only")
    parser.add_argument("--period", type=float, default=0.5, help="Seconds between polls")
    parser.add_argument("--duration", type=float, default=10.0,
                        help="Seconds to run, 0 = until Ctrl+C")
    args = parser.parse_args()

    from AIMotor_CANOpen_Lib_V_1_0.Motor_Control.Motor_Lib import Motor_CANopen_Lib

    config, network = _bootstrap.load(args)
    _bootstrap.banner("AIMOTOR feedback - read only, motor never enabled")

    exit_code = 0
    try:
        motor = Motor_CANopen_Lib(args.motor, network, config, setup_mode=False)
        motor.io.debug = args.verbose
        report = motor.preflight()
        if not report["ok"]:
            print("Preflight failed: " + "; ".join(report["problems"]))
            return 1

        start = time.time()
        while True:
            data = motor.snapshot()
            elapsed = time.time() - start
            print("")
            print("--- %s  t=+%.2fs %s" % (args.motor, elapsed, "-" * 40))
            print(motor.feedback.format_block(data))
            if args.duration and elapsed >= args.duration:
                break
            time.sleep(args.period)
    except KeyboardInterrupt:
        print("\nStopped by user.")
    except Exception as e:
        print("ERROR: " + str(e))
        exit_code = 1
    finally:
        network.disconnect()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
