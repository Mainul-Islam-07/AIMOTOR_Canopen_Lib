# 7. Two motors

This setup runs **Left** and **Right** on **separate CAN buses**, one CANable2
adapter each, both at **1 Mbps**.

| Motor | Node id (H0C_00) | Adapter profile | USB serial |
|---|---|---|---|
| Left | 1 | `canable2_left` | 002900573945501820303651 |
| Right | 2 | `canable2_right` | 003E00354845500F20303750 |

## Which register holds the node id

**H0C_00.** Same register whether you reach it over RS485 or CAN:

| Reached over | Address |
|---|---|
| RS485 / Modbus | register `0x0C00` (3072 decimal) |
| CANopen SDO | object `0x200C` subindex `0x01` |

The CAN bitrate is the neighbouring **H0C_08** (`0x200C:09`), where **5 = 500 kbps
and 6 = 1 Mbps**. After changing either, write **H0C_13 = 1** (`0x200C:0E`) to
save to EEPROM and power-cycle the drive.

Set them over **RS485**, not CAN: changing the node id or bitrate over CANopen
drops the very connection carrying the command.

## Pinning an adapter to a motor

`gs_usb` index order is USB enumeration order, so replugging can swap index 0
and 1 — which would send Left's commands to the Right motor. Each adapter
profile therefore carries a USB `serial`, and the library converts it to a
stable bus/address at connect time.

```bash
python Examples/example_00_list_adapters.py
```

Copy each serial into the matching adapter profile in the config. To double
check at runtime, `Motor_Group.verify_topology()` confirms each bus answers on
the node id that motor expects.

## Running both

```bash
python example_06_two_motors.py                        # dry run, nothing moves
python example_06_two_motors.py --rpm 30 --yes         # both forward
python example_06_two_motors.py --rpm 30 --turn 10 --yes
python example_06_two_motors.py --rpm 30 --ramp --yes
python example_06_two_motors.py --rpm 30 --same --yes  # no mirroring
```

## The mixer

```
left  = forward + turn
right = (forward - turn) * (-1 if the right motor is mirrored else 1)
```

`pairing.invert_right_for_forward` in the config sets the default. Mirroring
suits a differential base, where the right wheel faces the opposite way, so a
positive forward command drives straight. `--same` and `--opposite` override it
per run; the GUI has a radio pair for the same choice.

## From Python

```python
from AIMotor_CANOpen_Lib_V_1_0 import Motor_Group

with Motor_Group() as group:            # one bus per adapter, opened in order
    group.preflight_all()
    group.arm_all()                     # both motors energised
    group.drive(forward_rpm=30, turn_rpm=0)
    print(group.snapshot_all()["Left"]["velocity_rpm"])
    group["Right"].velocity.RUN_rpm(-10)   # or address one motor directly
```

Useful members: `group.online()`, `group.failures`, `group.adapter_of(name)`,
`group.run_rpm({"Left": 30, "Right": -30})`, `group.stop_all()`,
`group.disarm_all()`, `group.fault_reset_all()`, `group.set_nmt_all(state)`.

## Shutdown order, and why it matters

`close_all()` runs three phases, and the order is the safety property:

1. stop every feedback poller, on every bus
2. stop and disarm **every** motor
3. only then close the buses

Disconnecting one bus while the other motor is still spinning would leave that
motor enabled with a live setpoint and nothing left to disarm it. For the same
reason `Motor_Group` forces `shutdown.os_exit_after_disconnect` to false: a
hard exit part-way through teardown would skip the remaining disarms.

## If only one motor is present

`Motor_Group` is not strict by default: a motor whose adapter is missing lands
in `group.failures` and the rest still run. In the GUI that motor's panel shows
"offline" with the error, its controls are disabled, and the paired drive strip
is disabled — driving one wheel of a pair unexpectedly is worse than a greyed
out button. STOP still works on whichever motor is live.

Pass `strict=True` (as `example_06` does) when a partial setup should abort
instead.

## Single bus instead

Nothing above requires two adapters. Daisy-chain both drives onto one bus
(CAN_H to CAN_H, CAN_L to CAN_L, 120 ohm at each end) and point both motors at
the same adapter:

```json
"Left":  { "node_id": 1, "adapter": "canable2" },
"Right": { "node_id": 2, "adapter": "canable2" }
```

`Motor_Group` then opens one bus and puts both nodes on it. No code changes.
Node ids must be unique on a shared bus; the config loader rejects duplicates
per adapter, and allows them across different adapters.
