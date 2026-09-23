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
| `profile` | which entry of `adapters` to use | the fixed `socketcan` in `Drive_CAN_Config.json` |
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
  The shipped 0.32 is a placeholder — set it from your motor's data sheet.
- `limits.enforce_in_software`: keep it `true`. This drive has no limit object,
  so nothing else will stop a bad command.
- `heartbeat.enabled`: `false` by default, matching the drive's factory `0x1017 = 0`.
- `abort_if_not_canopen_mode`: stops everything when H02-00 is not 8.
- `shutdown.os_exit_after_disconnect`: `true` for CANable2 to dodge the libusb
  teardown crash; safe because the motor is disarmed first. Set `false` on
  CANalyst-II if you want a normal interpreter exit.

## Adding the second motor

```json
"AIMotor_2": {
    "node_id": 2,
    "enabled": true,
    "limits": { "max_velocity_rpm": 200.0 }
}
```

The entry merges over `motor_defaults`, so list only the differences. Two
enabled motors may not share a node id; the loader raises if they do.

## Moving the library

Set `paths.base_dir` to the new absolute location, or leave it `null` and just
move the whole folder — `null` resolves to wherever the package actually is.
