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

## Node id and bitrate

Factory default is **node 1, 500 kbps**. Change them on the drive with H0C_00
(node id) and H0C_08 (CAN bitrate), then set `motors.<name>.node_id` in
`Config/aimotor_config.json` to match.

## Startup checklist

1. Drive powered, no alarm on its display.
2. CAN wiring and termination as above.
3. Adapter plugged in, WinUSB driver healthy in Device Manager.
4. `python example_01_read_identity.py` prints PREFLIGHT: PASS.

If step 4 fails with no SDO response, the drive is not reaching the adapter
electrically. Check power, wiring and termination before suspecting software.
