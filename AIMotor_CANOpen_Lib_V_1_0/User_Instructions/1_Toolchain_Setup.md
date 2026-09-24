# 1. Toolchain setup (once per PC)

## Python

Python 3.10 or newer. From the library folder:

```bash
pip install -r requirements.txt
```

## CAN adapter driver (Windows)

Both adapters need a WinUSB driver, installed with [Zadig](https://zadig.akeo.ie/).

### CANable2 (gs_usb) — the default profile

1. Plug the adapter in.
2. Zadig → Options → List All Devices.
3. Select **canable2 gs_usb (Interface 0)**. Leave Interface 1 alone; it is the
   firmware update interface and is expected to stay uninstalled.
4. Pick **WinUSB**, then Install Driver.
5. Check it: Device Manager shows `canable2 gs_usb` with no warning icon.

### CANalyst-II — the alternative profile

1. Zadig → Options → List All Devices.
2. Select the `USBCAN/CANalyst-II` device (USB ID `04D8:0053`).
3. Pick **WinUSB**, then Install Driver.

### libusb for pyusb

pyusb must be able to find `libusb-1.0.dll`. If a script reports "No backend
available", or finds no device although Device Manager shows one, copy the DLL
somewhere on PATH:

```bash
python -c "import libusb_package,sys,os,shutil; shutil.copy(libusb_package.get_library_path(), os.path.join(os.path.dirname(sys.executable),'Scripts'))"
```

## Known quirks on this hardware

- **CANable2 at 250 kbps crashes libusb.** The shipped config uses 1000000,
  which is verified working on both adapters.
- **Two adapters in one process** is fine, but a stale process holding a device
  gives `[Errno 13] Access denied` on the next run. Close the old process, or
  replug, and note that the library never hard-exits while a bus is open.
- **gs_usb index order is not stable.** Each adapter profile carries a USB
  `serial` so a replug cannot swap Left and Right. Read the serials with
  `Examples/example_00_list_adapters.py`.
- **CANable2 sometimes raises an access violation when the bus closes.** The
  option `shutdown.os_exit_after_disconnect` side-steps it by leaving the
  process right after the motor is disarmed. It ships **false**, because with
  two motors a hard exit could skip the second motor's disarm. `Motor_Group`
  forces it false and disarms every motor before any bus is closed.
