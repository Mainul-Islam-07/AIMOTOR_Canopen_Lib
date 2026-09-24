# 3. Library usage

## Order of operations

1. `Config` — find and load the JSON.
2. `CANopen_Network` — open the bus, enter NMT pre-operational.
3. `Motor_CANopen_Lib` — settings, node, transport, telemetry, feedback,
   heartbeat, mode, control word.
4. `preflight()` — read-only health check. Always call it before arming.
5. `arm()` — **the motor becomes energised here.**
6. `velocity.RUN_rpm(...)` / `position.RUN_rev(...)` / `torque.RUN_percent(...)`.
7. `stop()` then `disarm()`, or just leave the `with` block, which does both.

## Minimal script

```python
from AIMotor_CANOpen_Lib_V_1_0 import CANopen_Network, Motor_CANopen_Lib

with CANopen_Network(profile="canable2_left") as net:
    with Motor_CANopen_Lib("Left", net) as motor:
        motor.preflight()
        motor.arm()
        motor.velocity.RUN_rpm(60)
        print(motor.snapshot()["velocity_rpm"])
        motor.stop()
```

## Two motors

Use `Motor_Group`. It opens one bus per adapter, so it covers both a motor per
adapter and two motors sharing one bus, without code changes:

```python
from AIMotor_CANOpen_Lib_V_1_0 import Motor_Group

with Motor_Group() as group:
    group.preflight_all()
    group.arm_all()
    group.drive(forward_rpm=30, turn_rpm=0)     # differential mixer
    print(group.snapshot_all()["Left"]["velocity_rpm"])
    group["Right"].velocity.RUN_rpm(-10)        # or one motor directly
```

Leaving the block stops and disarms **every** motor before closing any bus.
See `7_Two_Motors.md` for the mixer, adapter pinning and shutdown order.

Each motor keeps its own settings, telemetry and feedback poller. At 10 Hz and
1 Mbps, two motors over SDO is comfortable; four would need the PDO transport.

## Changing mode at runtime

Disarm first, because the drive latches the mode when disabled:

```python
motor.disarm()
motor.mode.switch_to(1)        # 1 = PP, 3 = PV, 4 = PT
motor.arm()
motor.position.RUN_rev(2.0)
```

## Feedback

```python
data = motor.snapshot()        # one full read, returns a dict
print(data["position_pul"], data["torque_percent"], data["bus_voltage_v"])
motor.feedback.print_table()   # human readable block

motor.feedback.start(0.1)      # background poller at 10 Hz
motor.feedback.snapshot()      # latest values, no bus traffic
motor.feedback.stop()
```

## Callbacks

```python
from AIMotor_CANOpen_Lib_V_1_0.User_Callback import Feedback_Callback, Heartbeat_Callback

motor.feedback.callback = Feedback_Callback(motor).on_feedback

hb = Heartbeat_Callback(motor)
motor.heartbeat.heartbeat_callback = hb.on_heartbeat
motor.heartbeat.timeout_callback = hb.on_timeout    # disarms by default
motor.heartbeat.enable()
motor.heartbeat.start_watchdog()
```

## Safety rules the library enforces

- Targets are clamped against `limits` before every write, because this drive
  has no `0x6072` / `0x6080` limit object of its own.
- The setpoint is zeroed **before** the drive is enabled, so a stale target
  cannot cause a lurch on arming.
- Every state transition is verified against `0x6041`; a timeout aborts the arm
  and disarms.
- Read-only objects are refused even though the EDS marks `0x6064` writable.
- `close()` runs stop → disarm, and the examples call it from `finally`, so
  Ctrl+C stops the motor.

## Transport

`Object_IO` in `Motor_Control/Transport_Lib.py` is the seam. Today only
`SDO_IO` exists. A future `PDO_IO` implements the same three methods
(`read`, `write`, `read_many`), so `transport: "PDO"` in the config will switch
it over without changing any calling code. Methods named in lower case
(`run`, `arm`, `controlword`) are the PDO-side aliases and currently delegate
to the upper-case SDO versions.
