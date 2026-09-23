"""Hook called after every feedback poll.

Attach it with:
    motor.feedback.callback = Feedback_Callback(motor).on_feedback
"""

from ..Housekeeping.Logger_Lib import Logger


class Feedback_Callback():
    def __init__(self, motor=None):
        self.motor = motor
        name = getattr(motor, "Node_Name", "Feedback")
        node_id = getattr(motor, "Node_ID", -1)
        self.log = Logger(name, node_id)

    def on_feedback(self, data: dict):
        """Called with the full snapshot dict after every poll.

        Replace the body with your own handling: publish to ROS, push to a UI,
        trip a safety rule. Keep it quick - it runs on the polling thread.
        """
        if data.get("fault"):
            self.log.print("Fault reported: fault_code=" + str(data.get("fault_code")) +
                           " error_code=" + str(data.get("error_code")), "CALLBACK",
                           "FEEDBACK", "Feedback_Callback", "on_feedback")
