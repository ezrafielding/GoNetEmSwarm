"""
GonetemSwarm Classe Transceiver
    Multicast TX/RX base class. Subclass and override on_message() to handle
    incoming datagrams. Manages a background RX thread and lifecycle.
"""

import json
import os
import socket
import struct
import threading
import traceback

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
            algo.send_broadcast(b"hello")
            time.sleep(5)

    Or manage the lifecycle manually:

        algo.start()
        algo.send_broadcast(b"hello")
        algo.stop()

    node_configs.json keys used:
        loopback_ip     — TX source address (kernel RPF check)
        multicast_group — e.g. "239.0.1.1"
        multicast_port  — e.g. 5007
        neighbors       — list of neighbors, unkown in top level, only for emulating bcast
    """

    _RX_TIMEOUT = 1.0   # recvfrom block duration; also caps stop() wait time

    def __init__(self, config_path: str = "/algorithms/node_configs.json"):
        with open(config_path) as f:
            all_nodes = json.load(f)
        self.node_name: str = os.environ["HOSTNAME"]
        info = all_nodes[self.node_name]

        self.loopback_ip: str = info["loopback_ip"]
        self.mcast_group: str = info["multicast_group"]
        self.mcast_port:  int = info["multicast_port"]
        if self.mcast_port is None :
            self.mcast_port = 5007
        self.neighbors_addr_list = []
        self.lamport_clock = 0
        self.path_to_logs_debug = "/logs/network/trans_"+self.node_name+".log"
        self.write_log_debug("Tranceiver started with lo ip : "+ self.loopback_ip)
        for neig in info["neighbors"] :
            self.neighbors_addr_list.append([neig["loopback_ip"], neig["link_ip"]])
            self.write_log_debug("Neighbors added with lo ip : "+ neig["loopback_ip"] + "| and link ip :"+ neig["link_ip"])

        self.historic_transmission = {}
        self._stop_event = threading.Event()
        self._rx_thread: threading.Thread | None = None
        self._rx_sock:   socket.socket    | None = None
        self._tx_thread: threading.Thread | None = None
        self._tx_sock:   socket.socket    | None = None

    def write_log_debug(self, log_message):
        with open(self.path_to_logs_debug, 'a') as file:
            file.write('\n'+log_message)

    def increment_clock(self):
        self.lamport_clock = lamport_clock +1

    def merge_clock(self, received_clock:int):
        self.lamport_clock = max(self.lamport_clock, received_clock)+1

    def transmit(self, message:dict, addr:str):
        self.write_log_debug("transmitting broadcast")
        """transmit a broadcast message to all neighbors who aren't senders.
        Args:
            message: Dictionaryrepresenting a message like described in send_broadcast comment
            addr: tuple (ip_addr, port) of the previous carrier node of the message

        What is a message : the sent message contains 4 elements:
                - type:bool (true if message is a broadcast, false if unicast)
                - sender: loopback ip address of the original sender (of this node
                        in this case.)
                - sending_time : local logical lamport time of the originating node when
                        message is first send. To be able to recognize multiples instances
                        of a same message.
                - payload: a dictionary containing concrete usefull data used in algorithms
        """
        if not self._tx_sock:
            self._tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._tx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        message = {
            "Bcast": True,
            "sender": message["sender"],
            "clock": message["clock"],
            "payload" : message["payload"]
        }
        # Serialize and send to broadcast address
        data = json.dumps(message).encode('utf-8')
        for neig_addr in self.neighbors_addr_list:
            if (addr == neig_addr[1]):#check link ip at reception, not loopback ip
                self.write_log_debug("message not retransmited to lo : "+ neig_addr[0])
                continue
            self._tx_sock.sendto(data, (neig_addr[0], self.mcast_port))
            self.write_log_debug("message transmited to lo : "+ neig_addr[0])


    def message_handler(self, data, addr):
        self.write_log_debug("Message instance received :")
        message = json.loads(data.decode('utf-8'))
        self.write_log_debug(str(message))
        if (message["Bcast"]):
            if message["sender"] in self.historic_transmission:
                if message["clock"] in self.historic_transmission[message["sender"]]:
                    self.write_log_debug("Message already received, dumped")
                    return #no further action => message is dumped
                else:
                    self.historic_transmission[message["sender"]].append(message["clock"])
            else:
                self.historic_transmission[message["sender"]] = [message["clock"]]
            self.transmit(message, addr[0])
        self.merge_clock(message["clock"])
        self.on_message(message["payload"], addr[0])

    # ------------------------------------------------------------------
    # TX
    # ------------------------------------------------------------------

    def send_broadcast(self, payload: dict):
        """Send a broadcast message to all nodes on the network.
        Args:
            payload: Dictionary to send (will be JSON serialized)

        What is a message : the sent message contains 4 elements:
                - type:bool (true if message is a broadcast, false if unicast)
                - sender: loopback ip address of the original sender (of this node
                        in this case.)
                - sending_time : local logical lamport time of the originating node when
                        message is first send. To be able to recognize multiples instances
                        of a same message.
                - payload: a dictionary containing concrete usefull data used in algorithms
        """
        if not self._tx_sock:
            self._tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._tx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        self.write_log_debug("Sending broadcast")
        message = {
            "Bcast": True,
            "sender": self.loopback_ip,
            "clock": self.lamport_clock,
            "payload" : payload
        }
        # Serialize and send to broadcast address
        data = json.dumps(message).encode('utf-8')
        for neig_addr in self.neighbors_addr_list:
            self._tx_sock.sendto(data, (neig_addr[0], self.mcast_port))

    # ------------------------------------------------------------------
    # RX callback — override in subclasses
    # ------------------------------------------------------------------

    def on_message(self, data: dict, addr: tuple) -> None:
        self.write_log_debug("on_message called")

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
        # mreq = struct.pack("4sL", socket.inet_aton(self.mcast_group), socket.INADDR_ANY)
        # sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
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
                self.message_handler(data, addr)
            except Exception:
                self.write_log_debug(traceback.format_exc())
                pass  # never let a handler crash the RX thread


