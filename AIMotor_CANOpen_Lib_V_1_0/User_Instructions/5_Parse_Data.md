# 5. Parsing the data

## Statusword 0x6041

| Bit | Meaning |
|---|---|
| 0 | ready to switch on |
| 1 | switched on |
| 2 | operation enabled |
| 3 | **fault** |
| 4 | voltage enabled |
| 5 | quick stop not active |
| 6 | switch on disabled |
| 7 | warning |
| 9 | remote |
| 10 | target reached |
| 15 | origin found (homing) |

Whole-word values from the manual's state transition table:

| Value | State |
|---|---|
| `0x0250` | servo no fault |
| `0x0231` | servo ready |
| `0x0233` | wait for enable |
| `0x0237` | servo running |
| `0x0217` | quick stop |
| `0x021F` | fault stopping |
| `0x0218` | fault |

`AIMotor_CANopen_Map.decode_state()` masks to the state bits, so vendor bits
8 and 9 (the `0x02xx` part) do not affect matching.

## Control word 0x6040

| Value | Action |
|---|---|
| `0x00` | disable voltage |
| `0x02` | quick stop — bit 2 is **active low** |
| `0x06` | shut down |
| `0x07` | switch on |
| `0x0F` | enable operation |
| `0x1F` | start absolute move (PP) |
| `0x4F` / `0x5F` | set / start relative move (PP) |
| `0x80` | fault reset, on the rising edge |

## Feedback objects

| Object | Meaning | Unit |
|---|---|---|
| `0x6064` | position actual | Pul |
| `0x606C` | velocity actual | Pul/s |
| `0x6077` | torque actual | 0.1 % rated |
| `0x6078` | current actual | drive units |
| `0x603F` | error code | — |
| `0x1001` | error register | bitfield |
| `0x200B:01` (H0B_00) | motor speed | rpm |
| `0x200B:03` (H0B_02) | internal torque | 0.1 % |
| `0x200B:19` (H0B_24) | phase current RMS | 0.01 A |
| `0x200B:1B` (H0B_26) | bus voltage | 0.1 V |
| `0x200B:1C` (H0B_27) | module temperature | °C |
| `0x200B:22` (H0B_33) | fault record select | 0 = current, 1–9 = history |
| `0x200B:23` (H0B_34) | fault code | see the drive manual |

Manufacturer parameters follow the rule: index = `0x2000 + group number`,
subindex = `in-group offset + 1`. So H0B_26 is `0x200B` subindex `0x1B`.

## Motor nameplate, group H00 (read only)

| Object | Meaning | Unit | This motor |
|---|---|---|---|
| `0x2000:0A` (H00_09) | rated voltage | V | 48 |
| `0x2000:0C` (H00_11) | rated current | 0.01 A | 19.0 A |
| `0x2000:0D` (H00_12) | rated torque | 0.001 Nm | 2.39 Nm |
| `0x2000:0F` (H00_14) | rated speed | rpm | 3000 |
| `0x2000:10` (H00_15) | **max speed** | rpm | 3600 |

H00_15 is the drive's own speed ceiling and has the highest priority, so it
applies whatever you write over CANopen. `preflight()` reads these and warns
when `limits.max_velocity_rpm` exceeds H00_15.

## Reading fault history

```python
for record in range(0, 10):
    print(record, hex(motor.feedback.read_fault_code(record) or 0))
```

Record 0 is the current fault; 1–9 are progressively older.

## Heartbeat 0x700 + node id

One data byte carries the NMT state: `0x00` boot-up, `0x04` stopped,
`0x05` operational, `0x7F` pre-operational.

The producer is off by default (`0x1017 = 0`), so the library reports
`heartbeat_alive = None` for "not configured" and `False` only for "expected a
beat and it did not arrive". Do not treat `None` as a fault.

## The snapshot dictionary

`motor.snapshot()` returns raw and converted values side by side:

```python
{"statusword": 567, "statusword_hex": "0x0237", "state": "OPERATION_ENABLED",
 "fault": False, "flags": [...], "mode_display": 3,
 "position_pul": 2364, "position_rev": 2.364, "position_deg": 850.9,
 "velocity_pulps": 1655, "velocity_rpm": 99.3, "motor_speed_rpm": 99,
 "torque_permille": 42, "torque_percent": 4.2, "torque_nm": 0.0134,
 "current_actual_raw": 55, "phase_current_a": 0.55,
 "bus_voltage_v": 48.2, "module_temperature_c": 31,
 "error_code": 0, "error_register": 0, "fault_code": 0,
 "heartbeat_alive": None, "heartbeat_count": 0, "heartbeat_state": "DISABLED",
 "ts": 1758600000.123}
```
