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

- **CANable2 at 250 kbps crashes libusb.** Only 500000 is in the shipped config.
- **CANable2 sometimes raises an access violation when the bus closes.** The
  option `shutdown.os_exit_after_disconnect` leaves the process immediately
  after the motor is disarmed, which side-steps it. Set it `false` when using
  the CANalyst-II, which shuts down cleanly.
