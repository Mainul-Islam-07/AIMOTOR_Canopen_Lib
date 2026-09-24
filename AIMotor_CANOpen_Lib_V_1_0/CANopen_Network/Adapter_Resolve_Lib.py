"""Turn an adapter profile into python-can keyword arguments.

Two jobs:

1. Strip the meta keys (profile_name, serial) that belong to this library
   rather than to python-can. Passing them through would raise a TypeError.

2. For gs_usb adapters with a "serial", find that physical device and pass
   its bus/address instead of an index. gs_usb index order is the USB
   enumeration order, which changes when adapters are replugged or powered
   up in a different order - on a two motor machine that would silently
   send Left's commands to the Right motor.

Serial lookup opens the USB device briefly to read its string descriptor,
so it must happen before any bus is opened. Results are cached per process.
"""

META_KEYS = ("profile_name", "serial", "serial_prefix")

_scan_cache = None


def scan_gs_usb(force: bool = False) -> list:
    """Return [{index, bus, address, serial}] for every gs_usb adapter found."""
    global _scan_cache
    if _scan_cache is not None and not force:
        return _scan_cache
    devices = []
    try:
        from gs_usb.gs_usb import GsUsb
        for index, dev in enumerate(GsUsb.scan()):
            try:
                serial = dev.gs_usb.serial_number
            except Exception:
                serial = None
            devices.append({"index": index, "bus": dev.gs_usb.bus,
                            "address": dev.gs_usb.address, "serial": serial})
    except Exception:
        devices = []
    _scan_cache = devices
    return devices


def find_by_serial(serial: str):
    """Match a serial, case-insensitively, allowing a prefix."""
    wanted = str(serial).strip().lower()
    for device in scan_gs_usb():
        found = (device.get("serial") or "").lower()
        if found == wanted or (found and found.startswith(wanted)):
            return device
    return None


def resolve_adapter_kwargs(adapter: dict, log=None) -> dict:
    """python-can kwargs for this adapter profile, with the serial applied."""
    kwargs = {k: v for k, v in adapter.items() if k not in META_KEYS}
    serial = adapter.get("serial")
    profile = adapter.get("profile_name", "?")

    if adapter.get("interface") != "gs_usb" or not serial:
        return kwargs

    device = find_by_serial(serial)
    if device is None:
        found = [d.get("serial") for d in scan_gs_usb()]
        raise RuntimeError(
            "Adapter '" + str(profile) + "': no gs_usb device with serial " + str(serial) +
            ". Connected serials: " + (", ".join(str(f) for f in found) if found else "none") +
            ". Fix the 'serial' value in the config, or clear it to fall back to 'index'.")

    # bus/address pin the physical device; index would be ambiguous.
    kwargs.pop("index", None)
    kwargs["bus"] = device["bus"]
    kwargs["address"] = device["address"]
    if log is not None:
        log.print("Adapter '" + str(profile) + "' -> serial " + str(serial) +
                  " (bus " + str(device["bus"]) + ", address " + str(device["address"]) + ")",
                  "INIT", "ADAPTER", "Adapter_Resolve", "resolve_adapter_kwargs")
    return kwargs
