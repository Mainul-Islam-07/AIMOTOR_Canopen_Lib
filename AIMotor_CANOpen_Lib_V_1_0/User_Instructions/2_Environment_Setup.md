# 2. Environment setup (once per power-up)

## Wiring

The drive's communication socket carries both buses:

| Pin | Signal |
|---|---|
| 1 | CAN_H |
| 2 | CAN_L |
| 3 | CAN GND |
| 4 | RS485 A |
| 5 | RS485 B |
| 6 | GND |

- Adapter CAN_H to pin 1, CAN_L to pin 2, GND to pin 3.
- The bus needs **120 Ω termination**. With the adapter's terminator on and the
  drive connected you should measure about **60 Ω** across CAN_H/CAN_L with
  everything powered off. About 120 Ω means only one terminator is active; open
  circuit means the wires are not reaching the drive.
- With the drive powered, pins 1 and 2 each sit at about **2.5 V** measured
  against pin 3. 0 V means the drive's CAN port is not active.

## Drive prerequisite: H02-00 = 8

The drive ignores CANopen motion commands unless its control mode is CANopen.
The factory default is 1 (pulse/direction).

1. Connect the RS485 adapter. Defaults: 57600 baud, 8N2, Modbus address 1.
2. Set **H02-00 = 8** with the AIMOTOR RS485 tool.
3. Set **H0C_13 = 1** to save parameters to EEPROM.
4. Power-cycle the drive.

Confirm from the CAN side with `Examples/example_01_read_identity.py`, which
reads `0x2002:01` and prints the value.

## Node id and bitrate - which register is which

| Parameter | Register | Modbus address | CANopen object | This setup |
|---|---|---|---|---|
| **Node id** | **H0C_00** | 0x0C00 | **0x200C:01** | Left = 1, Right = 2 |
| CAN bitrate | H0C_08 | 0x0C08 | 0x200C:09 | 6 = 1 Mbps (5 = 500 kbps) |
| RS485 address | H0C_00 | 0x0C00 | 0x200C:01 | same register as the node id |
| RS485 baud | H0C_02 | 0x0C02 | 0x200C:03 | 5 = 57600 |
| Save to EEPROM | H0C_13 | 0x0C0D | 0x200C:0E | write 1 after any change |

Change them with the AIMOTOR RS485 tool, write **H0C_13 = 1** to save, then
power-cycle. Afterwards set `motors.<name>.node_id` in the config to match.

Reading them back over CAN is a quick sanity check:

```python
motor.io.read(OD.NODE_ID)       # 0x200C:01, H0C_00
motor.io.read(OD.CAN_BITRATE)   # 0x200C:09, H0C_08
```

## Two motors, two buses

This setup gives each motor its own CANable2 and its own bus:

| Motor | Node id | Adapter profile | USB serial |
|---|---|---|---|
| Left | 1 | `canable2_left` | 002900573945501820303651 |
| Right | 2 | `canable2_right` | 003E00354845500F20303750 |

Each bus needs its own 120 ohm termination at both ends. Node ids only have to
be unique per bus, so two motors on separate buses could both be node 1 - these
are 1 and 2, which also keeps a future single-bus rewire trouble free.

## Startup checklist

1. Drive powered, no alarm on its display.
2. CAN wiring and termination as above.
3. Adapter plugged in, WinUSB driver healthy in Device Manager.
4. `python example_01_read_identity.py` prints PREFLIGHT: PASS.

If step 4 fails with no SDO response, the drive is not reaching the adapter
electrically. Check power, wiring and termination before suspecting software.
