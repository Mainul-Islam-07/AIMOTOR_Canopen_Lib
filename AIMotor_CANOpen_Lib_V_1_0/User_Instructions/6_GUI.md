# 6. The control GUI

```bash
cd Examples
python example_05_gui.py
python example_05_gui.py --motors Left Right
python example_05_gui.py --motor Left          # single panel
```

Tkinter only, no extra dependencies.

## Panels

**Connection** — pick the adapter profile and the motor, both read from the
JSON config, then press Connect. Connecting also runs the preflight check and
pops up a warning if it fails. The label turns green and shows
`AIMotor_1 node 1 via canable2`.

**Drive control** — ARM (asks for confirmation first, because the motor becomes
energised), Disarm, the mode selector, and Fault reset. The mode selector is
refused while armed; disarm first.

**Velocity command** — a slider limited to `limits.max_velocity_rpm` from the
config, an rpm entry box (Enter or Send applies it), and the **STOP** button.
STOP zeroes the setpoint at any time; it does not need the drive to be armed.
A speed command while disarmed is refused with a message in the log.

**Feedback** — updates at `feedback.poll_period_s` from the config. State turns
green when the drive is enabled and red on a fault; error and fault codes turn
red when non-zero.

**Log** — timestamped, colour coded: green for success, amber for warnings,
red for errors.

## Safety behaviour

- Arming asks for confirmation.
- Closing the window stops, disarms and disconnects before the window goes away.
- All CAN work runs on one background thread. The GUI only exchanges messages
  with it through queues, so a slow bus never freezes the window, and Tk
  widgets are only touched from the main thread.
- The GUI forces `shutdown.os_exit_after_disconnect` off for its own session,
  because it closes the bus itself rather than ending the process.

## Typical session

1. Connect. Check the log shows `Preflight PASS`.
2. Confirm the feedback panel shows a sensible bus voltage and no fault.
3. ARM. The state should become `OPERATION_ENABLED`.
4. Drag the slider to a low speed, e.g. 30 rpm, and release. Watch velocity and
   torque respond.
5. STOP, then Disarm.

## Self test

```bash
python example_05_gui.py --self-test
```

Builds the window, connects, polls for a few seconds, then stops, disarms,
disconnects and closes. It never arms the motor, so nothing moves. Useful for
checking a machine end to end without touching the controls.
