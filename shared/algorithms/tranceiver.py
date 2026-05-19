"""
GonetemSwarm Transceiver
    UDP TX/RX base class for direct link-IP routing (no OSPF).
    Subclass and override on_message() to handle incoming datagrams.
"""

import json
import os
import socket
import threading
import traceback
import time

WAKEUP_TIME = 3  # seconds to wait for all nodes to start before using the network

# ===========================================================================
# Helpers
# ===========================================================================

def formatted(value):
    return " " + str(value) + " |"


class Dumped(Exception):
    def __init__(self):
        super().__init__("Message dumped")


# ===========================================================================
# Transceiver
# ===========================================================================

class Transceiver:
    """UDP transceiver base class for direct link-IP satellite mesh networks.

    Subclass and override on_message() to react to incoming datagrams.

    Message structure:
        type:    int   — 0=unicast, 1=reliable broadcast
        sender:  str   — node name of the originating node
        counter: int   — per-node monotonic counter (deduplication key)
        payload: dict  — algorithm-specific data
    """

    _RX_TIMEOUT = 1.0  # recvfrom block duration; also caps stop() wait time

    def __init__(self, config_path: str = "/algorithms/node_configs.json"):
        with open(config_path) as f:
            all_nodes = json.load(f)
        self.node_name: str = os.environ["HOSTNAME"]
        info = all_nodes[self.node_name]

        self.network_initialized = False
        self.network_size = len(all_nodes)
        self.net_port = 5007
        self.msg_counter = 0
        self.historic_transmission: dict[str, list[int]] = {}

        self.neighbors_addr_dict: dict[str, str] = {}
        for neigh in info["neighbors"]:
            self.neighbors_addr_dict[neigh["name"]] = neigh["link_ip"]

        self.path_to_logs_debug = "/logs/network/trans_" + self.node_name + ".log"
        self.path_to_journal   = "/logs/journal_" + self.node_name + ".log"

        self._stop_event = threading.Event()
        self._rx_thread: threading.Thread | None = None
        self._rx_sock:   socket.socket    | None = None
        self._tx_thread: threading.Thread | None = None

        self.write_log_debug("Transceiver started: " + self.node_name)
        for name, ip in self.neighbors_addr_dict.items():
            self.write_log_debug("Neighbor: " + name + " link_ip=" + ip)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def write_log_debug(self, msg: str, service: str = "Transceiver") -> None:
        try:
            with open(self.path_to_logs_debug, "a") as f:
                f.write("\n" + str(time.process_time()) + " " + service + " : " + msg)
        except Exception:
            pass

    def add_fst_line_journal(self) -> None:
        entry = (formatted("Local Time") + formatted("Event") +
                 formatted("Ip Address") + formatted("Message Type") +
                 formatted("Message Sender") + formatted("Message Counter") +
                 formatted("Message Payload"))
        with open(self.path_to_journal, "a") as f:
            f.write(entry[:-2])

    def add_rcv_journal(self, message: dict, addr: str) -> None:
        entry = (formatted(time.process_time()) + formatted("RCV") +
                 formatted(addr) + formatted(message["type"]) +
                 formatted(message["sender"]) + formatted(message["counter"]) +
                 formatted(message["payload"]))
        with open(self.path_to_journal, "a") as f:
            f.write("\n" + entry[:-2])

    def add_snt_journal(self, message: dict, addr: str) -> None:
        entry = (formatted(time.process_time()) + formatted("SNT") +
                 formatted(addr) + formatted(message["type"]) +
                 formatted(message["sender"]) + formatted(message["counter"]) +
                 formatted(message["payload"]))
        with open(self.path_to_journal, "a") as f:
            f.write("\n" + entry[:-2])

    def add_tra_journal(self, message: dict, addr: str) -> None:
        entry = (formatted(time.process_time()) + formatted("TRA") +
                 formatted(addr) + formatted(message["type"]) +
                 formatted(message["sender"]) + formatted(message["counter"]) +
                 formatted(message["payload"]))
        with open(self.path_to_journal, "a") as f:
            f.write("\n" + entry[:-2])

    def get_local_time(self) -> float:
        return time.process_time()

    # ------------------------------------------------------------------
    # TX — fresh socket per send to avoid route-caching across interfaces
    # ------------------------------------------------------------------

    def send_packets(self, message: dict, ip_addr: str, transfert: bool = False) -> None:
        self.write_log_debug("Sending to " + ip_addr + " : " + str(message))
        try:
            data = json.dumps(message).encode("utf-8")
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tx:
                tx.sendto(data, (ip_addr, self.net_port))
            if transfert:
                self.add_tra_journal(message, ip_addr)
            else:
                self.add_snt_journal(message, ip_addr)
        except Exception:
            self.write_log_debug("Send failed: " + traceback.format_exc())

    def increment_counter(self) -> None:
        self.msg_counter += 1

    def send_broadcast(self, payload: dict) -> None:
        self.increment_counter()
        message = {
            "type":    1,
            "sender":  self.node_name,
            "counter": self.msg_counter,
            "payload": payload,
        }
        for node, link_ip in self.neighbors_addr_dict.items():
            self.send_packets(message, link_ip)

    def send_unicast(self, payload: dict, addr: str) -> None:
        self.increment_counter()
        message = {
            "type":    0,
            "sender":  self.node_name,
            "counter": self.msg_counter,
            "payload": payload,
        }
        self.send_packets(message, addr)

    # ------------------------------------------------------------------
    # Relay — forward a reliable broadcast to all neighbours except source
    # ------------------------------------------------------------------

    def transmit(self, message: dict, from_link_ip: str) -> None:
        for node, link_ip in self.neighbors_addr_dict.items():
            if link_ip == from_link_ip:
                self.write_log_debug("Not relaying to " + node + " (source)")
                continue
            self.send_packets(message, link_ip, transfert=True)
            self.write_log_debug("Relayed to " + node)

    # ------------------------------------------------------------------
    # RX handler — called on the RX thread for every received datagram
    # ------------------------------------------------------------------

    def message_handler(self, message: dict, addr: tuple) -> None:
        self.write_log_debug(str(message))
        match message["type"]:
            case 0:
                self.write_log_debug("Unicast received")
            case 1:
                self.write_log_debug("Reliable broadcast received")
                sender  = message["sender"]
                counter = message["counter"]
                seen = self.historic_transmission.setdefault(sender, [])
                if counter in seen:
                    self.write_log_debug("Duplicate — dumped")
                    raise Dumped()
                seen.append(counter)
                self.transmit(message, addr[0])
            case _:
                self.write_log_debug("Unknown message type: " + str(message["type"]))

    # ------------------------------------------------------------------
    # RX callback — override in subclasses
    # ------------------------------------------------------------------

    def on_message(self, data: dict, addr: str) -> None:
        """Called for every received datagram after message_handler."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self.add_fst_line_journal()
        if self._rx_thread is not None and self._rx_thread.is_alive():
            return
        self._stop_event.clear()
        self._rx_sock = self._create_rx_socket()
        self._rx_thread = threading.Thread(
            target=self._rx_loop, daemon=True, name=self.node_name + "-rx"
        )
        self._rx_thread.start()
        self.write_log_debug("Waiting " + str(WAKEUP_TIME) + "s for network to settle")
        time.sleep(WAKEUP_TIME)
        self.network_initialized = True
        self.write_log_debug("Network initialized")

    def stop(self) -> None:
        self._stop_event.set()
        if self._rx_thread is not None:
            self._rx_thread.join(timeout=self._RX_TIMEOUT + 1)
            self._rx_thread = None
        if self._rx_sock is not None:
            try:
                self._rx_sock.close()
            except OSError:
                pass
            self._rx_sock = None

    def __enter__(self) -> "Transceiver":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _create_rx_socket(self) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", self.net_port))
        sock.settimeout(self._RX_TIMEOUT)
        return sock

    def _rx_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                data, addr = self._rx_sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError as e:
                try:
                    self.write_log_debug("RX OSError: " + str(e))
                except Exception:
                    pass
                continue
            try:
                message = json.loads(data.decode("utf-8"))
                self.add_rcv_journal(message, addr[0])
                self.message_handler(message, addr)
                self.on_message(message, addr[0])
            except Dumped:
                pass
            except Exception:
                try:
                    self.write_log_debug(traceback.format_exc())
                except Exception:
                    pass
