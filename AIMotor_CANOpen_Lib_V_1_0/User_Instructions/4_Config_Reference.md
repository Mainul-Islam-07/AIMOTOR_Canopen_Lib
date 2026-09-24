# 4. Configuration reference

One file: `Config/aimotor_config.json`. Discovery order:

1. `--config PATH` on any example
2. environment variable `AIMOTOR_CONFIG` (a file, or a folder holding it)
3. `<library>/Config/aimotor_config.json`
4. `aimotor_config.json` in the current working directory

Two more overrides exist so a second machine needs no file edits:
`AIMOTOR_BASE_DIR` beats `paths.base_dir`, and `AIMOTOR_PROFILE` beats `profile`.

## Sections

| Key | Meaning | What it replaced in JS2 |
|---|---|---|
| `profile` | default adapter for motors that do not name one | the fixed `socketcan` in `Drive_CAN_Config.json` |
| `adapters.<name>.serial` | USB serial that pins a profile to one physical adapter | nothing - gs_usb index order is not stable |
| `motors.<name>.adapter` | which adapter (bus) this motor is on | nothing - JS2 had one bus |
| `pairing` | which motor is left/right, and whether the right one is mirrored | nothing |
| `paths.base_dir` | library root; `null` means this package. Relative paths resolve against the config file | the hardcoded `/home/jontro_soinik_2_0-2/...` paths |
| `paths.eds_dir` | folder holding the EDS file | `file_navigator("Motor_Mapping", eds_file)` |
| `adapters.<name>` | python-can keyword arguments, passed to `canopen.Network.connect` | `{socketcan, can_drive, 1000000}` |
| `network.nmt_on_startup` | NMT state entered after connecting | hardcoded literals |
| `timing.delay_SDO_s` | pause after each SDO transaction | hardcoded `0.0005` in `Common_Lib` |
| `timing.state_transition_timeout_s` | how long `ARM()` waits for each statusword | nothing — JS2 never verified transitions |
| `shutdown.*` | stop/disarm/disconnect policy, plus the libusb exit workaround | nothing |
| `logging.DEBUG_*` | per-area verbosity, and `FAILURE_EXIT` | the xlsx debug columns |
| `motor_defaults.*` | defaults merged under every motor | the ~34 xlsx columns |
| `motors.<name>` | per-motor overrides; only `node_id` is required | the xlsx `nodes` sheet rows |

## Fields worth knowing

- `mode`: `3` = PV velocity (default), `1` = PP position, `4` = PT torque.
- `transport`: `"SDO"` today. `"PDO"` is reserved for v1.1.
- `pulses_per_rev`: 1000 unless H05-07 / H05-09 were changed on the drive.
  Every rpm conversion depends on it.
- `rated_torque_nm`: only used to print Nm. Leave it 0 to report % of rated only.
  Shipped as 2.39, read from the drive itself (H00_12 = 2390 in 0.001 Nm units).
- `limits.max_velocity_rpm`: shipped as 3000, the motor's **rated** speed
  (H00_14). The drive's own hard ceiling is 3600 rpm (H00_15), which it
  enforces itself and which preflight warns about if you exceed it. Running
  continuously above rated speed is what the nameplate is warning you about.
- `limits.enforce_in_software`: keep it `true`. CiA402 `0x6072`/`0x6080` do not
  exist on this drive, so nothing in the CANopen profile stops a bad command.
- `heartbeat.enabled`: `false` by default, matching the drive's factory `0x1017 = 0`.
- `abort_if_not_canopen_mode`: stops everything when H02-00 is not 8.
- `shutdown.os_exit_after_disconnect`: `true` for CANable2 to dodge the libusb
  teardown crash; safe because the motor is disarmed first. Set `false` on
  CANalyst-II if you want a normal interpreter exit.

## Two motors on two adapters

```json
"motors": {
    "Left":  { "node_id": 1, "enabled": true, "adapter": "canable2_left"  },
    "Right": { "node_id": 2, "enabled": true, "adapter": "canable2_right",
               "limits": { "max_velocity_rpm": 2000.0 } }
}
```

Each entry merges over `motor_defaults`, so list only the differences. A node
id has to be unique **per adapter**: two motors on the same bus may not share
one and the loader raises, while two motors on different buses legitimately
can.

Omit `adapter` and the motor falls back to the top-level `profile`, which is
how a single-bus setup keeps working unchanged.

## Pinning an adapter by USB serial

`gs_usb` index order follows USB enumeration, so a replug can swap two
adapters and send Left's commands to the Right motor. Give each profile the
adapter's `serial` (from `Examples/example_00_list_adapters.py`) and the
library resolves it to a stable bus/address at connect time; `index` is then
ignored. Leave `serial` out and it falls back to `index`.

## Moving the library

Set `paths.base_dir` to the new absolute location, or leave it `null` and just
move the whole folder — `null` resolves to wherever the package actually is.
