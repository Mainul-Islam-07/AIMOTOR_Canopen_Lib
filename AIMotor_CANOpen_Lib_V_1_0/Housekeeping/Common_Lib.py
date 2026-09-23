"""Timing helpers and file lookup, mirroring the JS2 library's Common class.

Delays come from the JSON config instead of being hardcoded.
"""

import os
import time
from datetime import datetime
from typing import Optional


class Common():
    def __init__(self, Node_Name: str = "", Node_ID: int = -1, timing: Optional[dict] = None):
        self.Node_Name = Node_Name
        self.Node_ID = Node_ID
        timing = timing or {}
        self.delay_SDO_S = timing.get("delay_SDO_s", 0.0005)
        self.delay_PDO_S = timing.get("delay_PDO_s", 0.0002)
        self.sdo_response_timeout_s = timing.get("sdo_response_timeout_s", 0.5)
        self.sdo_max_retries = timing.get("sdo_max_retries", 3)
        self.state_transition_timeout_s = timing.get("state_transition_timeout_s", 1.0)
        self.brake_release_delay_s = timing.get("brake_release_delay_s", 0.5)

    def time_now(self):
        return datetime.now()

    def delay_SDO(self):
        time.sleep(self.delay_SDO_S)

    def delay_PDO(self):
        time.sleep(self.delay_PDO_S)

    def delay(self, delay_time_s: float):
        time.sleep(delay_time_s)

    def file_navigator(self, folder_name: str, file_name: str) -> str:
        """Locate a file inside the library, relative to this package."""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.abspath(os.path.join(base_dir, folder_name, file_name))
        if not os.path.isfile(path):
            raise FileNotFoundError("File not found: " + path)
        return path
