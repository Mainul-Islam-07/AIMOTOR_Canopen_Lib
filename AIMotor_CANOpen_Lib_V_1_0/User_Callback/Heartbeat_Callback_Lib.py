"""Hooks for heartbeat reception and heartbeat loss.

Attach them with:
    cb = Heartbeat_Callback(motor)
    motor.heartbeat.heartbeat_callback = cb.on_heartbeat
    motor.heartbeat.timeout_callback = cb.on_timeout
"""

from ..Housekeeping.Logger_Lib import Logger


class Heartbeat_Callback():
    def __init__(self, motor=None):
        self.motor = motor
        name = getattr(motor, "Node_Name", "Heartbeat")
        node_id = getattr(motor, "Node_ID", -1)
        self.log = Logger(name, node_id)

    def on_heartbeat(self, status: dict):
        """Called on every heartbeat frame from the drive."""
        pass

    def on_timeout(self, status: dict):
        """Called once when the heartbeat stops arriving.

        The default is to disarm: losing the heartbeat means the drive or the
        bus is gone, and a spinning motor with no feedback is the thing to
        avoid. Change it if your application needs different behaviour.
        """
        self.log.print("Heartbeat lost after " + str(status.get("heartbeat_count")) +
                       " beats - disarming", "CALLBACK", "TIMEOUT",
                       "Heartbeat_Callback", "on_timeout")
        if self.motor is not None:
            try:
                self.motor.stop()
                self.motor.disarm()
            except Exception as e:
                self.log.print("Disarm on heartbeat loss failed: " + str(e), "ERROR",
                               "TIMEOUT", "Heartbeat_Callback", "on_timeout")
