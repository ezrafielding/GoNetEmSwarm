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
import time
# ===========================================================================
# Transceiver
# ===========================================================================
def formatted(value):
    return " "+str(value)+" |"

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
        neighbors       — list of neighbors, unkown in top level, only for emulating bcast
    """

    _RX_TIMEOUT = 1.0   # recvfrom block duration; also caps stop() wait time

    def __init__(self, config_path: str = "/algorithms/node_configs.json"):
        with open(config_path) as f:
            all_nodes = json.load(f)
        self.node_name: str = os.environ["HOSTNAME"]
        info = all_nodes[self.node_name]

        self.ready_neigh = 0
        self.network_initialized = False
        self.network_size = len(all_nodes.keys())
        self.loopback_ip: str = info["loopback_ip"]
        self.net_port = 5007
        self.neighbors_addr_list = []
        self.neigh_to_check = []
        self.msg_counter = 0
        self.path_to_logs_debug = "/logs/network/trans_"+self.node_name+".log"
        self.path_to_journal = "/logs/journal_"+self.node_name+".log"
        self.write_log_debug("Tranceiver started with lo ip : "+ self.loopback_ip)
        for neig in info["neighbors"] :
            self.neighbors_addr_list.append([neig["loopback_ip"], neig["link_ip"]])
            self.write_log_debug("Neighbors added with lo ip : "+ neig["loopback_ip"] + "| and link ip :"+ neig["link_ip"])
            self.neigh_to_check.append(neig["loopback_ip"])

        self.historic_transmission = {}
        self._stop_event = threading.Event()
        self._rx_thread: threading.Thread | None = None
        self._rx_sock:   socket.socket    | None = None
        self._tx_thread: threading.Thread | None = None
        self._tx_sock:   socket.socket    | None = None

    def write_log_debug(self, log_message, service_name : str = "Tranceiver"):
        with open(self.path_to_logs_debug, 'a') as log_file:
            log_file.write('\n'+str(self.get_local_time())+" "+service_name+" : "+log_message)

    def send_packets(self, message: dict, ip_addr: str, transfert:bool = False):
        if not self._tx_sock:
            self._tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._tx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.write_log_debug("sending packet packet to " + ip_addr + " with content "+ str(message))
        try:
            data = json.dumps(message).encode('utf-8')
            self._tx_sock.sendto(data, (ip_addr, self.net_port))
            if transfert:
                self.add_tra_journal(message, ip_addr)
            else:
                self.add_snt_journal(message, ip_addr)
        except Exception:
            self.write_log_debug("Unable to send packets :" + str(traceback.format_exc()) )


    def get_local_time(self):
        return time.process_time()

    def add_fst_line_journal(self):
        journal_entry = formatted("Local Time") +\
                        formatted("Event") +\
                        formatted("Ip Address") +\
                        formatted("Message Type") +\
                        formatted("Message Sender") +\
                        formatted("Message Counter") +\
                        formatted("Message Payload")
        with open(self.path_to_journal, 'a') as journal:
            journal.write('\n'+journal_entry[:-2])

    def add_rcv_journal(self, message, addr):
        journal_entry = formatted(self.get_local_time()) +\
                        formatted("RCV") +\
                        formatted(addr) +\
                        formatted(message["type"]) +\
                        formatted(message["sender"]) +\
                        formatted(message["counter"]) +\
                        formatted(message["payload"])
        with open(self.path_to_journal, 'a') as journal:
            journal.write('\n'+journal_entry[:-2])

    def add_snt_journal(self, message, addr):
        journal_entry = formatted(self.get_local_time()) +\
                        formatted("SNT") +\
                        formatted(addr) +\
                        formatted(message["type"]) +\
                        formatted(message["sender"]) +\
                        formatted(message["counter"]) +\
                        formatted(message["payload"])
        self.write_log_debug(str(self.get_local_time()))
        with open(self.path_to_journal, 'a') as journal:
            journal.write('\n'+journal_entry[:-2])

    def add_tra_journal(self, message, addr):
        journal_entry = formatted(time.process_time()) +\
                        formatted("TRA") +\
                        formatted(addr) +\
                        formatted(message["type"]) +\
                        formatted(message["sender"]) +\
                        formatted(message["counter"]) +\
                        formatted(message["payload"])
        self.write_log_debug(str(time.process_time()))
        with open(self.path_to_journal, 'a') as journal:
            journal.write('\n'+journal_entry[:-2])

    def check_neighbors(self):


        message = {
            "type": 6,
            "sender": self.loopback_ip,
            "counter": self.msg_counter,
            "payload" : {}
        }
        while (not (len(self.neigh_to_check) == 0)):
            for addr in self.neigh_to_check:
                self.send_packets(message, addr)

            time.sleep(1)
        self.write_log_debug("every neighbors are alive and ready")
        message["type"]=7
        for neig_addr in self.neighbors_addr_list:
            self.write_log_debug("sending \"Ready\" to node :" + neig_addr[0])
            self.send_packets(message, neig_addr[0])

    def increment_counter(self):
        self.msg_counter = self.msg_counter +1

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
        message = {
            "type": 1,
            "sender": message["sender"],
            "counter": message["counter"],
            "payload" : message["payload"]
        }
        # Serialize and send to broadcast address
        for neig_addr in self.neighbors_addr_list:
            if (addr == neig_addr[1]):#check link ip at reception, not loopback ip
                self.write_log_debug("message not retransmited to lo : "+ neig_addr[0])
                continue
            self.send_packets(message, neig_addr[0])
            self.write_log_debug("message transmited to lo : "+ neig_addr[0])


    def message_handler(self, data, addr):
        message = json.loads(data.decode('utf-8'))
        self.write_log_debug(str(message))
        self.add_rcv_journal(message, addr[0])
        match message["type"]:
            case 0:
                self.write_log_debug("Message instance received : Unicast")
            case 1:
                self.write_log_debug("Message instance received : Reliable Broadcast")
                if message["sender"] in self.historic_transmission:
                    if message["counter"] in self.historic_transmission[message["sender"]]:
                        self.write_log_debug("Message already received, dumped")
                        return #no further action => message is dumped
                    else:
                        self.historic_transmission[message["sender"]].append(message["counter"])
                else:
                    self.historic_transmission[message["sender"]] = [message["counter"]]
                self.transmit(message, addr[0])

            # case 2:
            #     self.write_log_debug("Message instance received : OSPF Broadcast")
            case 6:
                addr_sender = message["sender"]
                self.write_log_debug("Message instance received : Heartbeat from : " + addr_sender)
                if (addr_sender in self.neigh_to_check):
                    self.write_log_debug("node :" + addr_sender + " is alive and ready")
                    self.neigh_to_check.remove(addr_sender)
                    message = {
                        "type": 6,
                        "sender": self.loopback_ip,
                        "counter": self.msg_counter,
                        "payload" : {}
                    }
                    self.write_log_debug("sending heartbeat answer to : " + addr_sender)
                    self.send_packets(message, addr_sender)
                else:
                    self.write_log_debug("node :" + addr_sender + " redundant heartbeat")
                    self.write_log_debug(str(self.neigh_to_check))


            case 7:
                self.ready_neigh += 1
                self.write_log_debug("Message instance received : Ready from : " + message["sender"] + "(ready number "+ str(self.ready_neigh) +"/" + str(len(self.neighbors_addr_list)) + ")")
                if (self.ready_neigh == len(self.neighbors_addr_list)):
                    self.network_initialized = True
                    self.write_log_debug("network is ready")

            case _:
                self.write_log_debug("Message instance received : Unknown type")

        self.on_message(message, addr[0])

    # ------------------------------------------------------------------
    # TX
    # ------------------------------------------------------------------


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
    def send_broadcast(self, payload: dict):
        self.increment_counter()

        self.write_log_debug("Sending broadcast")
        message = {
            "type": 1,
            "sender": self.loopback_ip,
            "counter": self.msg_counter,
            "payload" : payload
        }
        # Serialize and send to broadcast address
        for neig_addr in self.neighbors_addr_list:
            self.send_packets(message, neig_addr[0])

    #
    # def send_ospf_broadcast(self, payload: dict):
    #     self.increment_counter()
    #
    #     self.write_log_debug("Sending ospf broadcast")
    #     message = {
    #         "type": 2,
    #         "sender": self.loopback_ip,
    #         "counter": self.msg_counter,
    #         "payload" : payload
    #     }
    #     # Serialize and send to broadcast address
    #     self.send_packets(message, "224.0.0.5")


    def send_unicast(self, payload: dict, addr: str):
        self.increment_counter()

        self.write_log_debug("Sending Unicast to : "+ addr)
        message = {
            "type": 0,
            "sender": self.loopback_ip,
            "counter": self.msg_counter,
            "payload" : payload
        }
        self.send_packets(message, addr)

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
        self.add_fst_line_journal()
        """Open the multicast socket and start the background RX thread."""
        if self._rx_thread is not None and self._rx_thread.is_alive():
            return
        self._stop_event.clear()
        self._rx_sock = self._create_rx_socket()
        self._rx_thread = threading.Thread(
            target=self._rx_loop, daemon=True, name=f"{self.node_name}-rx"
        )
        self._rx_thread.start()
        self.check_neighbors()

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
        sock.bind(("", self.net_port))
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


