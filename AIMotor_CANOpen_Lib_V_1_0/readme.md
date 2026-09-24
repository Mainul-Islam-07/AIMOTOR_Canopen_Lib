# AIMotor CANopen Library V1.0

A CANopen library for the **AIMOTOR low voltage servo driver** (CiA301 + CiA402),
built on `python-can` + `canopen`.

Same structure as `JS2_Motor_CANOpen_Lib_V_1_0`, with three deliberate differences:

| | JS2 library | This library |
|---|---|---|
| Settings | `motor_settings.xlsx` + hardcoded Linux paths | **one JSON file**, `Config/aimotor_config.json` |
| Velocity mode | CSV (`0x6060` = 9) | **PV** (`0x6060` = 3), which is what the AIMOTOR documents |
| Transport | PDO | **SDO** now, with an `Object_IO` seam so PDO can be added without changing the API |

## Quick start

```bash
pip install -r requirements.txt
cd Examples
python example_00_list_adapters.py            # which adapter is which
python example_01_read_identity.py            # read only, run this first
python example_02_read_feedback.py            # read only, full feedback
python example_03_velocity_run.py --rpm 30 --seconds 2 --yes   # MOVES THE MOTOR
python example_04_velocity_with_feedback.py --rpm 60 --ramp --yes
python example_06_two_motors.py --rpm 30 --yes # BOTH motors together
python example_05_gui.py                       # desktop GUI, both motors
```

Scripts that move the motor do nothing without `--yes`.

## Configuration

Everything lives in [`Config/aimotor_config.json`](Config/aimotor_config.json).
Nothing is hardcoded in the Python sources.

- `paths.base_dir` relocates the library; `null` means "where this package is"
- `adapters` holds one entry per physical CAN adapter, each pinned by USB `serial`
- `motors` holds one entry per motor, naming the adapter its bus is on:

```json
"motors": {
    "Left":  { "node_id": 1, "enabled": true, "adapter": "canable2_left"  },
    "Right": { "node_id": 2, "enabled": true, "adapter": "canable2_right" }
}
```

This setup runs **two motors on two separate buses**, one CANable2 each, both at
1 Mbps. Motors that name the same adapter share one bus instead - the code is
the same either way.

Anything in `motor_defaults` can be overridden per motor.

Override the config location without editing files:

```bash
set AIMOTOR_CONFIG=D:\my_configs\aimotor_config.json
set AIMOTOR_PROFILE=canalystii
```

## Prerequisite on the drive

**H02-00 must be 8** (CANopen control mode), set with the AIMOTOR RS485 tool.
The factory default is 1, and in that mode the drive ignores CANopen motion
commands. `preflight()` reads `0x2002:01` and refuses to continue if it is wrong.

## Units

This drive counts pulses, not rpm. At the default 1000 pulses/rev:

| Quantity | Object | Unit | Example |
|---|---|---|---|
| Speed | `0x60FF` / `0x606C` | Pul/s | 100 rpm = 1667 Pul/s, 3000 rpm = 50000 Pul/s |
| Acceleration | `0x6083` / `0x6084` | Pul/s² | 500 rpm/s = 8333 Pul/s² |
| Position | `0x607A` / `0x6064` | Pul | 1 rev = 1000 Pul |
| Torque | `0x6071` / `0x6077` | 0.1 % rated | 1000 = rated torque (2.39 Nm) |
| Bus voltage | H0B_26 `0x200B:1B` | 0.1 V | 482 = 48.2 V |
| Phase current | H0B_24 `0x200B:19` | 0.01 A | 55 = 0.55 A |

`Housekeeping/Units_Lib.py` converts in both directions.

## Safety

- This drive has **no `0x6072` max torque or `0x6080` max speed object**, so the
  CANopen profile will not limit a bad command. Limits are enforced **in
  software** from `limits` in the JSON, before every write. The default cap is
  3000 rpm, the motor's rated speed; the drive's own hard ceiling is 3600 rpm
  (H00_15) and preflight warns if the config exceeds it.
- `ARM()` verifies every state transition against `0x6041` instead of firing
  blind writes, and zeroes the setpoint **before** enabling.
- `close()` runs stop → disarm; the examples call it from `finally`, so Ctrl+C
  stops the motor.

## Folder map

| Folder | Contents |
|---|---|
| `Config/` | the single JSON configuration file |
| `Housekeeping/` | `Logger`, `Common` (timing), `Config`, `Units` |
| `CANopen_Network/` | `CANopen_Network`: bus, NMT, COB-ID helper, recovery |
| `Motor_Settings/` | `Load_Settings` (per motor), `Mode` (0x6060 dispatch) |
| `Motor_Control/` | `Motor_CANopen_Lib`, `Motor_Group`, `SDO_IO`, `Controlword_Setup`, `PV/PP/PT` |
| `Motor_Feedback/` | `Feedback_Lib` (polling), `Heartbeat_Lib` |
| `Motor_Mapping/` | `OD` object table, `AIMotor_CANopen_Map` enums, the EDS file |
| `User_Callback/` | hooks for feedback, heartbeat and heartbeat loss |
| `Examples/` | seven runnable scripts, including the two-motor run and the GUI |
| `User_Instructions/` | setup, usage and data parsing notes |

## Library usage

Both motors, each on its own bus:

```python
from AIMotor_CANOpen_Lib_V_1_0 import Motor_Group

with Motor_Group() as group:                 # opens one bus per adapter
    group.preflight_all()
    group.arm_all()                          # both motors energised
    group.drive(forward_rpm=30)              # differential mixer
    print(group.snapshot_all()["Left"]["velocity_rpm"])
    group.stop_all()                         # leaving the block disarms both,
                                             # then closes both buses
```

One motor on its own:

```python
from AIMotor_CANOpen_Lib_V_1_0 import CANopen_Network, Motor_CANopen_Lib

with CANopen_Network(profile="canable2_left") as net:
    with Motor_CANopen_Lib("Left", net) as motor:
        if not motor.preflight()["ok"]:
            raise SystemExit("drive not ready")

        motor.arm()                          # motor becomes energised
        motor.velocity.RUN_rpm(60)           # PV mode, clamped by the config

        data = motor.snapshot()
        print(data["position_pul"], data["torque_percent"], data["bus_voltage_v"])

        motor.stop()                         # leaving the with block also
                                             # stops and disarms
```
