"""Example 4 - velocity mode with full torque and position feedback.

THIS MOVES THE MOTOR. Nothing moves unless you pass --yes.

Runs the motor in PV mode while printing the complete feedback block every
tick: state, errors, position, velocity, torque, bus voltage, phase current,
temperature and heartbeat. Ends with a min/mean/max summary.

    python example_04_velocity_with_feedback.py --rpm 60 --seconds 4 --yes
    python example_04_velocity_with_feedback.py --rpm 60 --ramp --yes
"""

import sys
import time

import _bootstrap


def summarize(name, values, unit=""):
    clean = [v for v in values if isinstance(v, (int, float))]
    if not clean:
        return "  %-22s no data" % name
    return ("  %-22s min %10.2f   mean %10.2f   max %10.2f  %s"
            % (name, min(clean), sum(clean) / len(clean), max(clean), unit))


def main() -> int:
    parser = _bootstrap.build_parser("Run the AIMOTOR in velocity mode with full feedback")
    parser.add_argument("--rpm", type=float, default=60.0, help="Target speed in rpm")
    parser.add_argument("--seconds", type=float, default=4.0, help="Seconds per phase")
    parser.add_argument("--period", type=float, default=0.5, help="Seconds between readings")
    parser.add_argument("--ramp", action="store_true",
                        help="Step through 0 -> +rpm -> 0 -> -rpm -> 0 to show torque sign")
    parser.add_argument("--yes", action="store_true",
                        help="Required. Confirms the motor is safe to turn.")
    args = parser.parse_args()

    from AIMotor_CANOpen_Lib_V_1_0.Motor_Control.Motor_Lib import Motor_CANopen_Lib

    config, network = _bootstrap.load(args)
    _bootstrap.banner("AIMOTOR velocity + feedback - THE MOTOR WILL TURN")

    motor = None
    exit_code = 0
    history = {"position_pul": [], "velocity_rpm": [], "torque_percent": [],
               "bus_voltage_v": [], "phase_current_a": [], "module_temperature_c": []}
    faults_seen = set()

    try:
        motor = Motor_CANopen_Lib(args.motor, network, config)
        motor.io.debug = args.verbose
        units = motor.units

        report = motor.preflight()
        if not report["ok"]:
            print("Preflight failed: " + "; ".join(report["problems"]))
            return 1

        phases = ([args.rpm, 0.0, -args.rpm, 0.0] if args.ramp else [args.rpm])
        print("")
        print("  Plan: %s for %.1f s each on %s node %d"
              % (" -> ".join("%.0f rpm" % p for p in phases), args.seconds,
                 args.motor, motor.Node_ID))
        if not args.yes:
            print("")
            print("  Not moving. Re-run with --yes once the shaft is clear.")
            return 0

        motor.velocity.RUN(0)
        if not motor.arm():
            print("ARM failed - see the log above.")
            return 1

        for phase_rpm in phases:
            target = motor.velocity.RUN_rpm(phase_rpm)
            print("")
            print("### target %.0f rpm (%s pul/s)" % (phase_rpm, target))
            start = time.time()
            while time.time() - start < args.seconds:
                data = motor.snapshot()
                print("")
                print("--- t=+%.2fs -----------------------------------------" %
                      (time.time() - start))
                print(motor.feedback.format_block(data))
                for key in history:
                    history[key].append(data.get(key))
                if data.get("fault_code"):
                    faults_seen.add(data["fault_code"])
                if data.get("fault"):
                    print("  FAULT reported - stopping.")
                    raise RuntimeError("Drive faulted during the run")
                time.sleep(args.period)

        motor.velocity.RUN(0)
        time.sleep(0.5)

        print("")
        print("=" * 78)
        print("SUMMARY")
        print(summarize("position", history["position_pul"], "pul"))
        print(summarize("velocity", history["velocity_rpm"], "rpm"))
        print(summarize("torque", history["torque_percent"], "% rated"))
        print(summarize("bus voltage", history["bus_voltage_v"], "V"))
        print(summarize("phase current", history["phase_current_a"], "A"))
        print(summarize("module temperature", history["module_temperature_c"], "C"))
        print("  %-22s %s" % ("fault codes seen",
                              sorted(faults_seen) if faults_seen else "none"))
        print("  %-22s %s" % ("heartbeat count", motor.heartbeat.count))
        print("  %-22s %s" % ("SDO statistics", motor.io.statistics()))
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
