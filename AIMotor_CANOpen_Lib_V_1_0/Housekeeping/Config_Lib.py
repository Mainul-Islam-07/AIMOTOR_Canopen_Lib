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
        """python-can keyword arguments for the selected adapter profile."""
        name = profile or self.profile
        adapters = self.raw.get("adapters", {})
        if name not in adapters:
            raise KeyError("Unknown adapter profile '" + str(name) + "'. Available: " +
                           ", ".join(sorted(adapters)))
        settings = {k: v for k, v in adapters[name].items() if not k.startswith(("notes", "_"))}
        settings["profile_name"] = name
        return settings

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

    def validate(self) -> list:
        """Return a list of warning strings; raise only on unusable configuration."""
        warnings = []
        adapter = self.adapter()
        if adapter.get("interface") == "gs_usb" and adapter.get("bitrate") != 500000:
            warnings.append("gs_usb adapter at " + str(adapter.get("bitrate")) +
                            " bps: only 500000 is known to work on this PC.")
        for name, entry in self.motors.items():
            node_id = entry.get("node_id")
            if not isinstance(node_id, int) or not (1 <= node_id <= 127):
                raise ValueError("Motor '" + name + "' has an invalid node_id: " + str(node_id))
        node_ids = [e.get("node_id") for e in self.motors.values() if e.get("enabled", True)]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Two enabled motors share the same node_id: " + str(node_ids))
        self.warnings = warnings
        return warnings

    def __repr__(self) -> str:
        return ("Config(file=" + self.config_file + ", profile=" + str(self.profile) +
                ", motors=" + str(list(self.motors)) + ")")
