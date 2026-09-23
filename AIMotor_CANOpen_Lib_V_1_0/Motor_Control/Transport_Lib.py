"""Object read/write transport.

Everything else in the library goes through Object_IO, so the PDO path can be
added later without changing any public API. Only SDO_IO exists in v1.0.
"""

import time
from typing import List, Optional

from ..Housekeeping.Logger_Lib import Logger
from ..Motor_Mapping.objects import ODEntry


class Object_IO():
    """Interface: read, write and read_many by object dictionary entry."""

    kind = "NONE"

    def read(self, entry: ODEntry):
        raise NotImplementedError

    def write(self, entry: ODEntry, value: int):
        raise NotImplementedError

    def read_many(self, entries: List[ODEntry]) -> dict:
        return {entry.name: self.read(entry) for entry in entries}


class SDO_IO(Object_IO):
    """Expedited SDO access with retries, addressed by index/subindex."""

    kind = "SDO"

    def __init__(self, node, node_name: str, common, log: Optional[Logger] = None,
                 debug: bool = False):
        self.node = node
        self.Node_Name = node_name
        self.Node_ID = node.id
        self.common = common
        self.log = log or Logger(node_name, node.id)
        self.debug = debug
        self.read_count = 0
        self.write_count = 0
        self.error_count = 0

    def _variable(self, entry: ODEntry):
        """canopen exposes subindex 0 objects directly, others as a record."""
        obj = self.node.sdo[entry.index]
        if entry.sub:
            return obj[entry.sub]
        try:
            return obj[0] if hasattr(obj, "od") and getattr(obj.od, "subindices", None) else obj
        except (KeyError, TypeError):
            return obj

    def read(self, entry: ODEntry):
        """Return the decoded value, or None when the drive does not answer."""
        attempts = max(1, int(self.common.sdo_max_retries))
        for attempt in range(1, attempts + 1):
            try:
                value = self._variable(entry).raw
                self.common.delay_SDO()
                self.read_count += 1
                if self.debug:
                    self.log.print(entry.key + " " + entry.name + " = " + str(value),
                                   "SDO", "READ", "SDO_IO", "read")
                return value
            except Exception as e:
                if attempt >= attempts:
                    self.error_count += 1
                    self.log.print("Read failed " + entry.key + " " + entry.name + ": " + str(e),
                                   "ERROR", "READ", "SDO_IO", "read")
                    return None
                time.sleep(self.common.delay_SDO_S * 4)
        return None

    def write(self, entry: ODEntry, value: int) -> bool:
        """Write a value. Refuses read-only entries, whatever the EDS claims."""
        if entry.access == "ro":
            self.log.print("Refusing to write read-only object " + entry.key + " " + entry.name,
                           "ERROR", "WRITE", "SDO_IO", "write")
            return False
        attempts = max(1, int(self.common.sdo_max_retries))
        for attempt in range(1, attempts + 1):
            try:
                self._variable(entry).raw = int(value)
                self.common.delay_SDO()
                self.write_count += 1
                if self.debug:
                    self.log.print(entry.key + " " + entry.name + " <- " + str(value),
                                   "SDO", "WRITE", "SDO_IO", "write")
                return True
            except Exception as e:
                if attempt >= attempts:
                    self.error_count += 1
                    self.log.print("Write failed " + entry.key + " " + entry.name + " <- " +
                                   str(value) + ": " + str(e), "ERROR", "WRITE",
                                   "SDO_IO", "write")
                    return False
                time.sleep(self.common.delay_SDO_S * 4)
        return False

    def write_verify(self, entry: ODEntry, value: int) -> bool:
        """Write then read back; True only when the drive kept the value."""
        if not self.write(entry, value):
            return False
        readback = self.read(entry)
        if readback != int(value):
            self.log.print(entry.key + " " + entry.name + " readback " + str(readback) +
                           " != " + str(value), "WARNING", "VERIFY", "SDO_IO", "write_verify")
            return False
        return True

    def statistics(self) -> dict:
        return {"transport": self.kind, "reads": self.read_count,
                "writes": self.write_count, "errors": self.error_count}
