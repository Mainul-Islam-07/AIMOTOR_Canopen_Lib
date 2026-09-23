"""Timestamped logging, same call signature as the JS2 library's Logger."""

import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(message)s")


class Logger():
    """Log with a UTC timestamp and up to four category levels.

    type_level_1 - message type in aspect of the CANopen service (SDO, PDO, NMT)
    type_level_2 - message type in aspect of the object or system area
    type_level_3 - message type in aspect of the calling class
    type_level_4 - message type in aspect of the calling function
    """

    def __init__(self, Node_Name: str, Node_ID: int):
        self.Node_Name = Node_Name
        self.Node_ID = Node_ID
        self.Node_Name_ID = "[" + str(Node_ID) + ":" + str(Node_Name) + "]"
        self.ID_SET = isinstance(Node_ID, int) and Node_ID > 0

    def print(self, msg: str, type_level_1: str = "", type_level_2: str = "",
              type_level_3: str = "", type_level_4: str = ""):
        now = datetime.now()
        line = ("[" + now.strftime("%Y-%m-%d %H:%M:%S.%f") + "] " + self.Node_Name_ID +
                " [" + str(type_level_1) + "] [" + str(type_level_2) + "] [" +
                str(type_level_3) + "] [" + str(type_level_4) + "] " + str(msg))
        logging.info(line)
        return line, now

    def set_node_id(self, node_id: int):
        """Called once the node id is known, so later lines carry it."""
        self.Node_ID = node_id
        self.Node_Name_ID = "[" + str(node_id) + ":" + str(self.Node_Name) + "]"
        self.ID_SET = isinstance(node_id, int) and node_id > 0
