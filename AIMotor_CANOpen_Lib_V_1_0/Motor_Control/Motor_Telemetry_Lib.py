"""Shared telemetry store for one motor.

A plain dict keyed by signal name, so callers can read the latest values
without another bus transaction.
"""

import time

from ..Housekeeping.Logger_Lib import Logger


class Motor_Telemetry():
    def __init__(self, node, node_name: str):
        self.node = node
        self.Node_ID = node.id
        self.Node_Name = node_name
        self.log = Logger(node_name, node.id)
        self.data = {
            "node_id": node.id,
            "node_name": node_name,
            "statusword": None,
            "state": None,
            "mode": None,
            "command_velocity_pulps": 0,
            "command_position_pul": 0,
            "command_torque_permille": 0,
            "ts": 0.0,
        }
        self.history = []
        self.max_history = 0

    def update(self, values: dict):
        values["ts"] = time.time()
        self.data.update(values)
        if self.max_history:
            self.history.append(dict(self.data))
            if len(self.history) > self.max_history:
                self.history.pop(0)
        return self.data

    def get(self, key, default=None):
        return self.data.get(key, default)

    def snapshot(self) -> dict:
        """Latest values, no bus traffic."""
        return dict(self.data)
