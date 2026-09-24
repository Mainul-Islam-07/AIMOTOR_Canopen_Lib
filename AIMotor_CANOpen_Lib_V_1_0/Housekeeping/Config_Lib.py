"""Configuration loader for the AIMOTOR CANopen library.

Everything the JS2 library hardcoded (Linux paths, adapter, bitrate, node ids,
motor limits) lives in one JSON file. This module finds it, merges the
per-motor settings over the defaults, and resolves every path.
"""

import copy
import json
import os
from typing import Any, Optional

CONFIG_FILE_NAME = "aimotor_config.json"
ENV_CONFIG = "AIMOTOR_CONFIG"
ENV_BASE_DIR = "AIMOTOR_BASE_DIR"
ENV_PROFILE = "AIMOTOR_PROFILE"


def deep_merge(base: dict, override: dict) -> dict:
    """Merge override onto a copy of base; nested dicts merge key by key."""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


class Config():
    """Loads and resolves the single JSON configuration file."""

    def __init__(self, config_path: Optional[str] = None, profile: Optional[str] = None):
        self.package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.config_file = self.find_config_file(config_path)
        with open(self.config_file, "r", encoding="utf-8") as f:
            self.raw = json.load(f)

        self.base_dir = self.resolve_base_dir()
        self.profile = profile or os.environ.get(ENV_PROFILE) or self.raw.get("profile", "canable2")

        self.network = self.raw.get("network", {})
        self.timing = self.raw.get("timing", {})
        self.shutdown = self.raw.get("shutdown", {})
        self.logging = self.raw.get("logging", {})
        self.motor_defaults = self.raw.get("motor_defaults", {})
        self.motors = self.raw.get("motors", {})
        self.validate()

    # ------------------------------------------------------------------ paths

    def find_config_file(self, config_path: Optional[str]) -> str:
        """Discovery order: explicit argument, env var, package Config folder, cwd."""
        candidates = []
        if config_path:
            candidates.append(config_path)
        env_path = os.environ.get(ENV_CONFIG)
        if env_path:
            candidates.append(env_path)
        candidates.append(os.path.join(self.package_dir, "Config", CONFIG_FILE_NAME))
        candidates.append(os.path.join(os.getcwd(), CONFIG_FILE_NAME))

        tried = []
        for candidate in candidates:
            path = os.path.abspath(candidate)
            if os.path.isdir(path):
                path = os.path.join(path, CONFIG_FILE_NAME)
            tried.append(path)
            if os.path.isfile(path):
                return path
        raise FileNotFoundError(
            "Could not find " + CONFIG_FILE_NAME + ". Tried:\n  " + "\n  ".join(tried))

    def resolve_base_dir(self) -> str:
        """base_dir: env var wins, then JSON, then the library folder itself."""
        value = os.environ.get(ENV_BASE_DIR) or (self.raw.get("paths", {}) or {}).get("base_dir")
        if not value:
            return self.package_dir
        if os.path.isabs(value):
            return os.path.abspath(value)
        return os.path.abspath(os.path.join(os.path.dirname(self.config_file), value))

    def resolve_path(self, *parts: str, must_exist: bool = True) -> str:
        """Join path parts against base_dir unless the first one is absolute."""
        parts = tuple(p for p in parts if p)
        if parts and os.path.isabs(parts[0]):
            path = os.path.abspath(os.path.join(*parts))
        else:
            path = os.path.abspath(os.path.join(self.base_dir, *parts))
        if must_exist and not os.path.exists(path):
            raise FileNotFoundError("Path not found: " + path)
        return path

    def eds_path(self, eds_file: str) -> str:
        eds_dir = (self.raw.get("paths", {}) or {}).get("eds_dir", "Motor_Mapping")
        return self.resolve_path(eds_dir, eds_file)

    # ----------------------------------------------------------------- lookup

    def adapter(self, profile: Optional[str] = None) -> dict:
        """Adapter settings for a profile.

        Keeps the meta keys (profile_name, serial) in the dict; they are
        stripped before the settings reach python-can - see
        CANopen_Network.Adapter_Resolve_Lib.resolve_adapter_kwargs.
        """
        name = profile or self.profile
        adapters = self.raw.get("adapters", {})
        if name not in adapters:
            raise KeyError("Unknown adapter profile '" + str(name) + "'. Available: " +
                           ", ".join(sorted(adapters)))
        settings = {k: v for k, v in adapters[name].items() if not k.startswith(("notes", "_"))}
        settings["profile_name"] = name
        return settings

    def motor_adapter(self, name: str, override: Optional[str] = None) -> str:
        """Which adapter profile a motor lives on.

        Precedence: explicit override (--profile), then the motor's own
        "adapter" key, then the global default profile. A motor without an
        "adapter" key keeps the old single-bus behaviour.
        """
        if override:
            return override
        entry = self.motors.get(name, {}) or {}
        return entry.get("adapter") or self.profile

    def motor_adapters(self, enabled_only: bool = True) -> dict:
        """{motor_name: adapter_profile} for the motors in play."""
        return {name: self.motor_adapter(name) for name in self.motor_names(enabled_only)}

    def adapter_names_in_use(self, enabled_only: bool = True) -> list:
        """Distinct adapter profiles needed, in motor order. One bus each."""
        seen = []
        for profile in self.motor_adapters(enabled_only).values():
            if profile not in seen:
                seen.append(profile)
        return seen

    def pairing(self) -> dict:
        """Left/right pairing used by the paired drive controls."""
        return self.raw.get("pairing", {}) or {}

    def motor_names(self, enabled_only: bool = True) -> list:
        names = []
        for name, entry in self.motors.items():
            if enabled_only and not entry.get("enabled", True):
                continue
            names.append(name)
        return names

    def motor(self, name: str) -> dict:
        """Per-motor settings: motor_defaults with the motor's own entry merged on top."""
        if name not in self.motors:
            raise KeyError("Unknown motor '" + str(name) + "'. Available: " +
                           ", ".join(sorted(self.motors)))
        merged = deep_merge(self.motor_defaults, self.motors[name])
        merged["node_name"] = name
        return merged

    def get(self, section: str, key: str, default: Any = None) -> Any:
        return (self.raw.get(section, {}) or {}).get(key, default)

    # --------------------------------------------------------------- checking

    KNOWN_BITRATES = (125000, 250000, 500000, 800000, 1000000)

    def validate(self) -> list:
        """Return a list of warning strings; raise only on unusable configuration."""
        warnings = []
        adapters = self.raw.get("adapters", {})

        for name, entry in self.motors.items():
            node_id = entry.get("node_id")
            if not isinstance(node_id, int) or not (1 <= node_id <= 127):
                raise ValueError("Motor '" + name + "' has an invalid node_id: " + str(node_id))
            profile = entry.get("adapter")
            if profile and profile not in adapters:
                raise ValueError("Motor '" + name + "' names adapter '" + str(profile) +
                                 "', which does not exist. Available: " +
                                 ", ".join(sorted(adapters)))

        # A node id only has to be unique on its own bus. Two motors on two
        # separate adapters may legitimately share one.
        seen = {}
        for name in self.motor_names(enabled_only=True):
            key = (self.motor_adapter(name), self.motors[name].get("node_id"))
            if key in seen:
                raise ValueError("Motors '" + seen[key] + "' and '" + name + "' are both node " +
                                 str(key[1]) + " on adapter '" + str(key[0]) + "'")
            seen[key] = name

        in_use = self.adapter_names_in_use(enabled_only=True)
        gs_usb_slots = {}
        for profile in in_use:
            settings = self.adapter(profile)
            bitrate = settings.get("bitrate")
            if bitrate not in self.KNOWN_BITRATES:
                warnings.append("Adapter '" + profile + "' at " + str(bitrate) +
                                " bps is an unusual bitrate.")
            if settings.get("interface") == "gs_usb":
                if bitrate == 250000:
                    warnings.append("Adapter '" + profile + "' is gs_usb at 250000 bps, which "
                                    "crashes libusb on this PC.")
                slot = settings.get("serial") or ("index:" + str(settings.get("index", 0)))
                if slot in gs_usb_slots:
                    raise ValueError("Adapters '" + gs_usb_slots[slot] + "' and '" + profile +
                                     "' both point at the same physical device (" + str(slot) +
                                     "). Give each one its own index or serial.")
                gs_usb_slots[slot] = profile
                if not settings.get("serial") and len(in_use) > 1:
                    warnings.append("Adapter '" + profile + "' has no serial. gs_usb index "
                                    "order is not stable across replug - set 'serial' to pin "
                                    "each adapter to its motor.")

        if len(self.motor_names(enabled_only=True)) > 1 and \
                self.shutdown.get("os_exit_after_disconnect"):
            warnings.append("shutdown.os_exit_after_disconnect is true with more than one motor: "
                            "exiting during teardown can leave another motor armed. Motor_Group "
                            "disables it.")

        self.warnings = warnings
        return warnings

    def __repr__(self) -> str:
        return ("Config(file=" + self.config_file + ", profile=" + str(self.profile) +
                ", motors=" + str(list(self.motors)) + ")")
