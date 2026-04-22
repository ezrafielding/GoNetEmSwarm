"""
GonetemSwarm shared utilities.

Classes
-------
Transceiver
    Multicast TX/RX base class. Subclass and override on_message() to handle
    incoming datagrams. Manages a background RX thread and lifecycle.

Catalog(Transceiver)
    CRDT-based distributed key-value catalog. Each entry is an op-based
    Last-Write-Wins Register; assigns are broadcast to the swarm via multicast.

Typical import in an algorithm file:

    from utils import Transceiver, Catalog
"""

import json
import os
import socket
import struct
import threading


# ===========================================================================
# Transceiver
# ===========================================================================

class Transceiver:
    """Multicast transceiver base class.

    Subclass and override on_message() to react to incoming datagrams.

    Usage:

        class MyAlgorithm(Transceiver):
            def on_message(self, data: bytes, addr: tuple):
                msg = json.loads(data.decode())
                print(f"got {msg} from {addr}")

        algo = MyAlgorithm()
        with algo:              # starts RX thread, stops on exit
            algo.tx(b"hello")
            time.sleep(5)

    Or manage the lifecycle manually:

        algo.start()
        algo.tx(b"hello")
        algo.stop()

    node_configs.json keys used:
        loopback_ip     — TX source address (kernel RPF check)
        multicast_group — e.g. "239.0.1.1"
        multicast_port  — e.g. 5007
    """

    _RX_TIMEOUT = 1.0   # recvfrom block duration; also caps stop() wait time

    def __init__(self, config_path: str = "/algorithms/node_configs.json"):
        with open(config_path) as f:
            all_nodes = json.load(f)
        self.node_name: str = os.environ["SAT_NAME"]
        info = all_nodes[self.node_name]

        self.loopback_ip: str = info["loopback_ip"]
        self.mcast_group: str = info["multicast_group"]
        self.mcast_port:  int = info["multicast_port"]

        self._stop_event = threading.Event()
        self._rx_thread: threading.Thread | None = None
        self._rx_sock:   socket.socket    | None = None

    # ------------------------------------------------------------------
    # TX
    # ------------------------------------------------------------------

    def tx(self, data: bytes) -> None:
        """Send *data* to the multicast group."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind((self.loopback_ip, 0))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 32)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)
            sock.sendto(data, (self.mcast_group, self.mcast_port))
        finally:
            sock.close()

    # ------------------------------------------------------------------
    # RX callback — override in subclasses
    # ------------------------------------------------------------------

    def on_message(self, data: bytes, addr: tuple) -> None:
        """Called for every multicast datagram received.

        Args:
            data: Raw bytes of the received datagram.
            addr: (ip, port) of the sender.
        """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Open the multicast socket and start the background RX thread."""
        if self._rx_thread is not None and self._rx_thread.is_alive():
            return
        self._stop_event.clear()
        self._rx_sock = self._create_rx_socket()
        self._rx_thread = threading.Thread(
            target=self._rx_loop, daemon=True, name=f"{self.node_name}-rx"
        )
        self._rx_thread.start()

    def stop(self) -> None:
        """Signal the RX thread to stop and wait for it to finish."""
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
        sock.bind(("", self.mcast_port))
        mreq = struct.pack("4sL", socket.inet_aton(self.mcast_group), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.settimeout(self._RX_TIMEOUT)
        return sock

    def _rx_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                data, addr = self._rx_sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self.on_message(data, addr)
            except Exception:
                pass  # never let a handler crash the RX thread


# ===========================================================================
# Catalog
# ===========================================================================

_CATALOG_MSG_TYPE = "lww_assign"


class Catalog(Transceiver):
    """CRDT-based distributed key-value catalog.

    Each entry is an op-based Last-Write-Wins Register:

        payload  X x, timestamp t
        initial  ⊥, 0
        query    value()      → x
        update   assign(x')
                   atSource   → t' = t + 1   (per-item integer counter)
                   downstream(x', t') → if t < t' then x, t := x', t'

    Downstream ops are broadcast to the swarm via multicast (Transceiver).

    Usage:

        class MyAlgorithm(Catalog):
            pass                    # on_message already handles merges

        algo = MyAlgorithm()
        with algo:
            algo.assign("orbit", {"alt": 550, "inc": 53.0})
            time.sleep(1)
            print(algo.value("orbit"))
            print(algo.items())

    Dict-style access:

        algo["orbit"] = {"alt": 550}
        print(algo["orbit"])
        print("orbit" in algo)
        print(len(algo))

    Reacting to incoming updates — override on_message and call super():

        class MyAlgorithm(Catalog):
            def on_message(self, data: bytes, addr: tuple):
                super().on_message(data, addr)   # merge first
                print(f"catalog now: {self.items()}")
    """

    def __init__(self):
        super().__init__()
        # {item_id: {"value": ..., "timestamp": int}}
        self._store: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def value(self, item_id: str):
        """Return the current value of *item_id*, or None if not present."""
        with self._lock:
            entry = self._store.get(item_id)
            return entry["value"] if entry else None

    def items(self) -> dict:
        """Return a snapshot of the entire catalog as {id: value}."""
        with self._lock:
            return {k: v["value"] for k, v in self._store.items()}

    def __getitem__(self, item_id: str):
        result = self.value(item_id)
        if result is None and item_id not in self:
            raise KeyError(item_id)
        return result

    def __contains__(self, item_id: str) -> bool:
        with self._lock:
            return item_id in self._store

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def assign(self, item_id: str, value) -> None:
        """Assign *value* to *item_id* and broadcast the op to the swarm.

        The timestamp is a per-item integer incremented at the source;
        it is never derived from wall-clock time.
        """
        with self._lock:
            entry = self._store.get(item_id)
            timestamp = (entry["timestamp"] if entry else 0) + 1
            self._store[item_id] = {"value": value, "timestamp": timestamp}
        self.tx(json.dumps({
            "type":      _CATALOG_MSG_TYPE,
            "id":        item_id,
            "value":     value,
            "timestamp": timestamp,
        }).encode())

    def __setitem__(self, item_id: str, value) -> None:
        self.assign(item_id, value)

    # ------------------------------------------------------------------
    # Downstream handler (called by Transceiver's RX thread)
    # ------------------------------------------------------------------

    def on_message(self, data: bytes, addr: tuple) -> None:
        try:
            msg = json.loads(data.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        if msg.get("type") != _CATALOG_MSG_TYPE:
            return
        self._apply(msg["id"], msg["value"], msg["timestamp"])

    # ------------------------------------------------------------------
    # Internal merge
    # ------------------------------------------------------------------

    def _apply(self, item_id: str, value, timestamp: int) -> None:
        """Apply a downstream op: update only if the incoming timestamp wins."""
        with self._lock:
            entry = self._store.get(item_id)
            if entry is None or timestamp > entry["timestamp"]:
                self._store[item_id] = {"value": value, "timestamp": timestamp}
