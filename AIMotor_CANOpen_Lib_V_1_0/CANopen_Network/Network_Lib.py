"""CANopen network setup for the AIMOTOR library.

Same role as the JS2 library's CANopen_Network, but the adapter settings and
paths come from the JSON config instead of a hardcoded Linux path.
"""

import os
import re
import sys
from typing import Optional

import canopen

from ..Housekeeping.Common_Lib import Common
from ..Housekeeping.Config_Lib import Config
from ..Housekeeping.Logger_Lib import Logger
from .Adapter_Resolve_Lib import resolve_adapter_kwargs


class CANopen_Network():
    def __init__(self, config: Optional[object] = None, node_name: str = "Master",
                 node_id: Optional[int] = None, profile: Optional[str] = None):
        self.config = config if isinstance(config, Config) else Config(config, profile=profile)
        self.Node_Name = node_name or self.config.get("network", "master_node_name", "Master")
        self.Node_ID = node_id if node_id is not None else self.config.get(
            "network", "master_node_id", 127)
        self.log = Logger(self.Node_Name, self.Node_ID)
        self.common = Common(self.Node_Name, self.Node_ID, self.config.timing)
        self.network = None
        self.bus = None
        self.nodes = {}
        self.adapter = self.config.adapter(profile)

        for warning in getattr(self.config, "warnings", []):
            self.log.print(warning, "WARNING", "CONFIG", "CANopen_Network", "__init__")

        self.log.print("Config " + self.config.config_file + " (profile=" +
                       str(self.adapter.get("profile_name")) + ")", "INIT", "CONFIG",
                       "CANopen_Network", "__init__")
        self.setup_network()

    # ---------------------------------------------------------------- setup

    def setup_network(self):
        """Open the CAN bus with the adapter settings from the config."""
        try:
            kwargs = resolve_adapter_kwargs(self.adapter, self.log)
            self.network = canopen.Network()
            self.network.connect(**kwargs)
            self.bus = self.network.bus
            self.log.print("Connected: " + str(kwargs.get("interface")) + " / " +
                           str(kwargs.get("channel")) + " / " + str(kwargs.get("bitrate")) +
                           " bps", "NETWORK", "CONNECT", "CANopen_Network", "setup_network")
            self.common.delay(self.config.get("network", "post_connect_delay_s", 0.2))
            startup = self.config.get("network", "nmt_on_startup", "PRE-OPERATIONAL")
            if startup:
                self.set_nmt_state(startup)
        except Exception as e:
            self.log.print("Network setup failure: " + str(e), "ERROR", "CONNECT",
                           "CANopen_Network", "setup_network")
            raise

    def add_node(self, node_id: int, eds_path: str) -> canopen.RemoteNode:
        """Register a remote node with its EDS so canopen can decode objects."""
        if not os.path.isfile(eds_path):
            raise FileNotFoundError("EDS file not found: " + eds_path)
        node = canopen.RemoteNode(node_id, eds_path)
        self.network.add_node(node)
        self.nodes[node_id] = node
        self.log.print("Added node " + str(node_id) + " with " + os.path.basename(eds_path),
                       "NETWORK", "ADD_NODE", "CANopen_Network", "add_node")
        return node

    # ------------------------------------------------------------------ NMT

    def set_nmt_state(self, state: str):
        try:
            if self.network is None:
                raise RuntimeError("CANopen network not initialized")
            self.network.nmt.state = state
            self.log.print("Network is now " + str(state), "NETWORK", "NMT",
                           "CANopen_Network", "set_nmt_state")
        except Exception as e:
            self.log.print("Failed to set NMT " + str(state) + ": " + str(e), "ERROR", "NMT",
                           "CANopen_Network", "set_nmt_state")

    def network_operational(self):
        self.set_nmt_state("OPERATIONAL")

    def network_preoperational(self):
        self.set_nmt_state("PRE-OPERATIONAL")

    def network_reset(self):
        self.set_nmt_state("RESET")

    # ------------------------------------------------------------- COB-IDs

    def get_canopen_id(self, node_id: Optional[int], message_type: str) -> int:
        """Return the 11-bit CANopen arbitration ID for a message type.

        node_id: 1..127 for node-scoped types; ignored for 'nmt', 'sync', 'time'.
        message_type (case/space/underscore insensitive):
            - 'tpdo1'..'tpdo4', 'rpdo1'..'rpdo4'
            - 'sdo_req' (0x600 + node), 'sdo_res' (0x580 + node)
            - 'emcy' (0x080 + node)
            - 'heartbeat' / 'bootup' (0x700 + node)
            - 'sync' (0x080), 'time' (0x100), 'nmt' (0x000)
        """
        s = re.sub(r"[\s_-]+", "", str(message_type).lower())

        fixed_no_node = {"nmt": 0x000, "sync": 0x080, "time": 0x100}
        if s in fixed_no_node:
            return fixed_no_node[s]

        if not isinstance(node_id, int) or not (1 <= node_id <= 127):
            raise ValueError("node_id must be an int in 1..127 for this message type")

        fixed_with_node = {
            "sdoreq": 0x600, "sdotx": 0x600, "sdotonode": 0x600,
            "sdores": 0x580, "sdorx": 0x580, "sdofromnode": 0x580,
            "emcy": 0x080,
            "heartbeat": 0x700, "nmtstate": 0x700, "bootup": 0x700,
        }
        if s in fixed_with_node:
            return fixed_with_node[s] + node_id

        m = re.fullmatch(r"([tr])pdo([1-4])", s)
        if m:
            n = int(m.group(2))
            bases = ({1: 0x180, 2: 0x280, 3: 0x380, 4: 0x480} if m.group(1) == "t"
                     else {1: 0x200, 2: 0x300, 3: 0x400, 4: 0x500})
            return bases[n] + node_id

        raise ValueError("Unknown message type: " + repr(message_type))

    # -------------------------------------------------------------- recovery

    def recovery(self):
        """Broadcast a disable-voltage controlword to every known node.

        Uses raw frames so it still works when a node object is in a bad state.
        """
        import can
        for node_id in list(self.nodes) or [1]:
            try:
                frame = can.Message(
                    arbitration_id=0x600 + node_id, is_extended_id=False,
                    data=[0x2B, 0x40, 0x60, 0x00, 0x00, 0x00, 0x00, 0x00])
                self.bus.send(frame)
                self.log.print("Raw disarm sent to node " + str(node_id), "RECOVERY",
                               "DISARM", "CANopen_Network", "recovery")
            except Exception as e:
                self.log.print("Raw disarm failed for node " + str(node_id) + ": " + str(e),
                               "ERROR", "RECOVERY", "CANopen_Network", "recovery")

    def disconnect(self, hard_exit: Optional[bool] = None):
        """Leave the bus. Optionally hard-exit to dodge the libusb teardown crash."""
        try:
            state = self.config.get("network", "nmt_before_disconnect", "PRE-OPERATIONAL")
            if self.network is not None:
                if state:
                    self.set_nmt_state(state)
                self.network.disconnect()
                self.log.print("Disconnected from CANopen network", "NETWORK", "DISCONNECT",
                               "CANopen_Network", "disconnect")
        except BaseException as e:
            self.log.print("Disconnect raised (ignored): " + str(e), "WARNING", "DISCONNECT",
                           "CANopen_Network", "disconnect")
        finally:
            self.network = None
            self.bus = None
            if hard_exit is None:
                hard_exit = self.config.get("shutdown", "os_exit_after_disconnect", False)
            if hard_exit:
                # gs_usb / libusb raises an access violation during interpreter
                # teardown on some Windows hosts. The motor is already disarmed
                # by this point, so leaving immediately is safe.
                sys.stdout.flush()
                sys.stderr.flush()
                os._exit(int(self.config.get("shutdown", "os_exit_code", 0)))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.disconnect()
        return False
