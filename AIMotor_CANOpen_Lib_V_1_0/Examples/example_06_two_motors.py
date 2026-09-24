"""Example 6 - run both motors together and watch both feedbacks.

THIS MOVES BOTH MOTORS. Nothing moves unless you pass --yes.

Each motor is on its own CAN adapter, so this opens two buses. Both are
armed, driven, then stopped and disarmed together. Ctrl+C stops both.

    python example_06_two_motors.py                       # dry run, no motion
    python example_06_two_motors.py --rpm 30 --yes        # both forward
    python example_06_two_motors.py --rpm 30 --turn 10 --yes
    python example_06_two_motors.py --rpm 30 --ramp --yes

Mixer (differential base):
    left  = forward + turn
    right = (forward - turn) * (-1 if the right motor is mirrored)
Mirroring comes from pairing.invert_right_for_forward in the config;
--same and --opposite override it.
"""

import sys
import time

import _bootstrap

ROWS = [
    ("state", "state", lambda d: "%s %s" % (d.get("state"), d.get("statusword_hex"))),
    ("velocity", "[rpm]", lambda d: d.get("velocity_rpm")),
    ("position", "[pul]", lambda d: d.get("position_pul")),
    ("torque", "[% rated]", lambda d: d.get("torque_percent")),
    ("phase current", "[A]", lambda d: d.get("phase_current_a")),
    ("bus / temp", "", lambda d: "%s V / %s C" % (d.get("bus_voltage_v"),
                                                  d.get("module_temperature_c"))),
    ("errors", "", lambda d: "none" if not (d.get("error_code") or d.get("fault_code"))
     else "0x%04X / 0x%04X" % (d.get("error_code") or 0, d.get("fault_code") or 0)),
]


def format_pair(snapshots, names, targets=None):
    """Side by side block, one column per motor."""
    lines = []
    header = "  %-22s %18s %18s" % ("", names[0], names[1])
    lines.append(header)
    if targets:
        lines.append("  %-22s %18s %18s" % ("target [rpm]",
                                            targets.get(names[0]), targets.get(names[1])))
    for label, unit, getter in ROWS:
        cells = []
        for name in names:
            data = snapshots.get(name) or {}
            try:
                cells.append(str(getter(data)))
            except Exception:
                cells.append("-")
        lines.append("  %-22s %18s %18s" % ((label + " " + unit).strip(), cells[0], cells[1]))
    return "\n".join(lines)


def summarize(label, values, unit=""):
    clean = [v for v in values if isinstance(v, (int, float))]
    if not clean:
        return "%-18s no data" % label
    return ("%-18s min %9.2f  mean %9.2f  max %9.2f %s"
            % (label, min(clean), sum(clean) / len(clean), max(clean), unit))


def main() -> int:
    parser = _bootstrap.build_parser("Run both AIMOTOR drives together")
    parser.add_argument("--motors", nargs=2, default=None, metavar=("LEFT", "RIGHT"),
                        help="Motor names (default: from pairing in the config)")
    parser.add_argument("--rpm", type=float, default=30.0, help="Forward speed in rpm")
    parser.add_argument("--turn", type=float, default=0.0,
                        help="Turn component in rpm: added to left, subtracted from right")
    parser.add_argument("--seconds", type=float, default=4.0, help="Seconds per phase")
    parser.add_argument("--period", type=float, default=0.5, help="Seconds between readings")
    parser.add_argument("--ramp", action="store_true",
                        help="Step through 0 -> +rpm -> 0 -> -rpm -> 0")
    parser.add_argument("--opposite", action="store_true",
                        help="Mirror the right motor (differential base)")
    parser.add_argument("--same", action="store_true",
                        help="Do not mirror the right motor; both spin the same way")
    parser.add_argument("--yes", action="store_true",
                        help="Required. Confirms both motors are safe to turn.")
    args = parser.parse_args()

    from AIMotor_CANOpen_Lib_V_1_0.Housekeeping.Config_Lib import Config
    from AIMotor_CANOpen_Lib_V_1_0.Motor_Control.Motor_Group_Lib import Motor_Group

    config = Config(args.config, profile=args.profile)
    pairing = config.pairing()
    names = args.motors or [pairing.get("left_motor", "Left"),
                            pairing.get("right_motor", "Right")]
    invert = pairing.get("invert_right_for_forward", True)
    if args.opposite:
        invert = True
    if args.same:
        invert = False

    _bootstrap.banner("AIMOTOR two motor run - BOTH MOTORS WILL TURN")

    group = None
    exit_code = 0
    history = {name: {"velocity_rpm": [], "torque_percent": [], "bus_voltage_v": [],
                      "phase_current_a": [], "position_pul": []} for name in names}
    try:
        group = Motor_Group(config, names=names, profile=args.profile, strict=True)
        for name in names:
            motor = group[name]
            motor.io.debug = args.verbose
            print("  %-6s node %d on %s" % (name, motor.Node_ID, group.adapter_of(name)))

        topology = group.verify_topology()
        if not all(topology.values()):
            print("Topology check failed: " + str(topology))
            return 1

        reports = group.preflight_all()
        for name in names:
            report = reports.get(name) or {}
            if not report.get("ok"):
                print("Preflight failed for %s: %s" % (name, "; ".join(report.get("problems", []))))
                return 1
        print("  Preflight: both PASS")

        left_rpm = args.rpm + args.turn
        right_rpm = (args.rpm - args.turn) * (-1.0 if invert else 1.0)
        print("")
        print("  Plan: %s %.1f rpm, %s %.1f rpm for %.1f s%s"
              % (names[0], left_rpm, names[1], right_rpm, args.seconds,
                 " (ramped)" if args.ramp else ""))
        print("  Right motor is %s" % ("MIRRORED (differential base)" if invert else "not mirrored"))
        print("  Limit: %.0f rpm per motor from the config"
              % group[names[0]].settings.limits.get("max_velocity_rpm"))
        if not args.yes:
            print("")
            print("  Not moving. Re-run with --yes once both shafts are clear.")
            return 0

        group.run_rpm({name: 0 for name in names})      # zero before enabling
        armed = group.arm_all()
        if not all(armed.values()):
            print("ARM failed: %s - stopping and disarming both" % armed)
            return 1

        phases = [args.rpm, 0.0, -args.rpm, 0.0] if args.ramp else [args.rpm]
        for phase_rpm in phases:
            targets = group.drive(phase_rpm, args.turn, invert_right=invert)
            target_rpm = {name: round(group[name].units.pulps_to_rpm(targets.get(name) or 0), 1)
                          for name in names}
            print("")
            print("### forward %.0f rpm, turn %.0f rpm" % (phase_rpm, args.turn))
            start = time.time()
            while time.time() - start < args.seconds:
                snapshots = group.snapshot_all()
                print("")
                print("  t=+%.2fs" % (time.time() - start))
                print(format_pair(snapshots, names, target_rpm))
                for name in names:
                    snap = snapshots.get(name) or {}
                    for key in history[name]:
                        history[name][key].append(snap.get(key))
                    if snap.get("fault"):
                        raise RuntimeError("%s reported a fault" % name)
                time.sleep(args.period)

        group.drive(0, 0, invert_right=invert)
        time.sleep(0.5)

        print("")
        print("=" * 78)
        print("SUMMARY")
        for name in names:
            print("  %s (node %d)" % (name, group[name].Node_ID))
            print("    " + summarize("velocity", history[name]["velocity_rpm"], "rpm"))
            print("    " + summarize("torque", history[name]["torque_percent"], "% rated"))
            print("    " + summarize("phase current", history[name]["phase_current_a"], "A"))
            print("    " + summarize("bus voltage", history[name]["bus_voltage_v"], "V"))
            print("    SDO " + str(group[name].io.statistics()))
    except KeyboardInterrupt:
        print("\nCtrl+C - stopping both motors.")
    except Exception as e:
        print("ERROR: " + str(e))
        exit_code = 1
    finally:
        if group is not None:
            group.close_all()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
