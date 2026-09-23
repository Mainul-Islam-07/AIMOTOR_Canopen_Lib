"""Heartbeat producer setup and monitoring.

The AIMOTOR ships with 0x1017 = 0, meaning the drive sends nothing unless
asked. This class can switch the producer on, watch 0x700+node, and report a
timeout. "Not configured" and "lost" are kept distinct: heartbeat_alive is
None when the producer is off, and False only when a beat was expected and
did not arrive.
"""

import threading
import time
from typing import Callable, Optional

from ..Housekeeping.Logger_Lib import Logger
from ..Motor_Mapping.mapping import AIMotor_CANopen_Map as Map
from ..Motor_Mapping.objects import OD


class Heartbeat_Lib():
    def __init__(self, node, node_name: str, canopen_handle, settings, telemetry, io):
        self.node = node
        self.Node_ID = node.id
        self.Node_Name = node_name
        self.canopen_handle = canopen_handle
        self.settings = settings
        self.telemetry = telemetry
        self.io = io
        self.common = canopen_handle.common
        self.log = Logger(node_name, node.id)
        self.DEBUG = settings.DEBUG_HEARTBEAT

        config = settings.heartbeat or {}
        self.producer_time_ms = int(config.get("producer_time_ms", 200))
        self.timeout_ms = int(config.get("timeout_ms", 1000))
        self.restore_on_exit = config.get("restore_on_exit", True)

        self.cob_id = canopen_handle.get_canopen_id(self.Node_ID, "heartbeat")
        self.enabled = False
        self.count = 0
        self.last_beat_ts = None
        self.last_state = None
        self.timed_out = False
        self.original_producer_time = None

        self.heartbeat_callback: Optional[Callable] = None
        self.timeout_callback: Optional[Callable] = None
        self._watchdog = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------ setup

    def enable(self, producer_time_ms: Optional[int] = None) -> bool:
        """Write 0x1017 and subscribe to the heartbeat COB-ID."""
        period = int(producer_time_ms or self.producer_time_ms)
        self.original_producer_time = self.io.read(OD.HEARTBEAT_PRODUCER)
        if not self.io.write_verify(OD.HEARTBEAT_PRODUCER, period):
            self.log.print("Could not set producer heartbeat time", "ERROR", "0x1017",
                           "Heartbeat_Lib", "enable")
            return False
        self.canopen_handle.network.subscribe(self.cob_id, self._on_heartbeat)
        self.enabled = True
        self.producer_time_ms = period
        self.log.print("Heartbeat producer enabled at " + str(period) + " ms (COB-ID 0x%03X)"
                       % self.cob_id, "HEARTBEAT", "0x1017", "Heartbeat_Lib", "enable")
        return True

    def disable(self) -> bool:
        """Turn the producer off again and leave the drive as we found it."""
        self.stop_watchdog()
        try:
            self.canopen_handle.network.unsubscribe(self.cob_id, self._on_heartbeat)
        except Exception:
            pass
        ok = True
        if self.enabled and self.restore_on_exit:
            restore = self.original_producer_time if self.original_producer_time is not None else 0
            ok = self.io.write(OD.HEARTBEAT_PRODUCER, int(restore))
            self.log.print("Heartbeat producer restored to " + str(restore) + " ms",
                           "HEARTBEAT", "0x1017", "Heartbeat_Lib", "disable")
        self.enabled = False
        return ok

    # --------------------------------------------------------------- receive

    def _on_heartbeat(self, cob_id, data, timestamp):
        """python-can subscription callback for 0x700 + node id."""
        now = time.time()
        interval_ms = None
        if self.last_beat_ts is not None:
            interval_ms = int((now - self.last_beat_ts) * 1000)
        self.last_beat_ts = now
        self.count += 1
        self.timed_out = False
        try:
            raw_state = data[0] & 0x7F
            self.last_state = Map.NMTState(raw_state).name
        except (IndexError, ValueError):
            self.last_state = "UNKNOWN"
        if self.DEBUG:
            self.log.print("HB #" + str(self.count) + " state=" + str(self.last_state) +
                           (" dt=" + str(interval_ms) + " ms" if interval_ms is not None else ""),
                           "HEARTBEAT", "0x%03X" % cob_id, "Heartbeat_Lib", "_on_heartbeat")
        if self.heartbeat_callback is not None:
            try:
                self.heartbeat_callback(self.status())
            except Exception as e:
                self.log.print("Heartbeat callback error: " + str(e), "ERROR", "CALLBACK",
                               "Heartbeat_Lib", "_on_heartbeat")

    # -------------------------------------------------------------- watchdog

    def start_watchdog(self, timeout_ms: Optional[int] = None):
        if self._watchdog is not None and self._watchdog.is_alive():
            return
        self.timeout_ms = int(timeout_ms or self.timeout_ms)
        self._stop_event.clear()

        def loop():
            while not self._stop_event.is_set():
                if self.enabled and self.last_beat_ts is not None:
                    silent_s = time.time() - self.last_beat_ts
                    if silent_s * 1000 > self.timeout_ms and not self.timed_out:
                        self.timed_out = True
                        self.log.print("HEARTBEAT TIMEOUT: no beat for " +
                                       ("%.3f" % silent_s) + " s (limit " +
                                       str(self.timeout_ms) + " ms)", "ERROR", "TIMEOUT",
                                       "Heartbeat_Lib", "start_watchdog")
                        if self.timeout_callback is not None:
                            try:
                                self.timeout_callback(self.status())
                            except Exception as e:
                                self.log.print("Timeout callback error: " + str(e), "ERROR",
                                               "CALLBACK", "Heartbeat_Lib", "start_watchdog")
                self._stop_event.wait(max(0.02, self.timeout_ms / 4000.0))

        self._watchdog = threading.Thread(target=loop, name="heartbeat-" + self.Node_Name,
                                          daemon=True)
        self._watchdog.start()

    def stop_watchdog(self):
        self._stop_event.set()
        if self._watchdog is not None:
            self._watchdog.join(timeout=2.0)
            self._watchdog = None

    # ----------------------------------------------------------------- status

    def status(self) -> dict:
        """Heartbeat fields merged into every feedback snapshot."""
        if not self.enabled:
            alive = None
            state = "DISABLED"
        elif self.last_beat_ts is None:
            alive = None
            state = "WAITING"
        else:
            alive = not self.timed_out
            state = self.last_state or "UNKNOWN"
        return {
            "heartbeat_alive": alive,
            "heartbeat_count": self.count,
            "heartbeat_state": state,
            "heartbeat_age_s": (round(time.time() - self.last_beat_ts, 3)
                                if self.last_beat_ts else None),
        }
