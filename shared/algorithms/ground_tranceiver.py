
import json
import os
import socket
import struct
import threading
import traceback
import time
import random

# ===========================================================================
# Ground Station : basic implementation
# ===========================================================================

WAKEUP_TIME = 3

def formatted(value):
    return str(value)+"|"

class UnreachableSwarm(Exception):
    def __init__(self):
        self.message = "Swarm is unreachable"
        super().__init__(self.message)


class Ground_transceiver:
    def __init__(self, config_path: str = "/algorithms/node_configs.json"):
        with open(config_path) as f:
            all_nodes = json.load(f)
        self.node_name: str = os.environ["HOSTNAME"]
        self.path_to_logs_debug = "/logs/network/trans_"+self.node_name+".log"
        self.path_to_journal = "/logs/journal_"+self.node_name+".log"

        info = all_nodes[self.node_name]

        self.msg_counter = 0
        self.link_duration = 0
        self.net_port = 5007
        self.satellite_addr_list = []
        self.write_log_debug("Tranceiver started: "+ self.node_name)

        self.neighbors_addr_dict: dict[str, str] = {}
        for neigh in info["neighbors"]:
            self.neighbors_addr_dict[neigh["name"]] = neigh["link_ip"]

        self.linked_name = None
        self._stop_event = threading.Event()
        self._link_thread: threading.Thread | None = None
        self._tx_thread: threading.Thread | None = None
        self._tx_sock:   socket.socket    | None = None

        self.write_log_debug("Ground Transceiver started: " + self.node_name)
        for name, ip in self.neighbors_addr_dict.items():
            self.write_log_debug("Neighbor: " + name + " link_ip=" + ip)

    def get_next_link(self):
        return random.choice(list(self.neighbors_addr_dict.keys()))

    def set_link_duration(self, value: int):
        self.link_duration = value

    def write_log_debug(self, log_message, service_name : str = "Tranceiver"):
        with open(self.path_to_logs_debug, 'a') as log_file:
            log_file.write('\n'+str(self.get_local_time())+" "+service_name+" : "+log_message)

    def send_packets(self, message: dict, name: str, transfert:bool = False):
        ip_addr = self.neighbors_addr_dict[name]
        self.write_log_debug("sending packet packet to " + ip_addr + " with content "+ str(message))
        try:
            data = json.dumps(message).encode('utf-8')
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tx:
                tx.sendto(data, (ip_addr, self.net_port))
            if transfert:
                self.add_tra_journal(message, name)
            else:
                self.add_snt_journal(message, name)
        except Exception:
            self.write_log_debug("Unable to send packets :" + str(traceback.format_exc()) )
            pass  # never let the TX thread crash

    def get_local_time(self):
        return time.process_time()

    def add_fst_line_journal(self) -> None:
        entry = (formatted("Local Time") + formatted("Event") +
                 formatted("Node Name") + formatted("Message Type") +
                 formatted("Message Sender") + formatted("Message Counter") +
                 formatted("Message Payload") )
        with open(self.path_to_journal, "a") as f:
            f.write(entry[:-1])

    def add_snt_journal(self, message: dict, name: str) -> None:
        entry = (formatted(time.process_time()) + formatted("SNT") +
                 formatted(name) + formatted(message["type"]) +
                 formatted(message["sender"]) + formatted(message["counter"]) +
                 formatted(message["payload"]) )
        with open(self.path_to_journal, "a") as f:
            f.write("\n" + entry[:-1])

    def increment_counter(self):
        self.msg_counter = self.msg_counter +1

    def send_unicast(self, payload: dict):
        self.increment_counter()

        self.write_log_debug("Sending Unicast to : "+ self.linked_name)
        message = {
            "type": 9,
            "sender": self.node_name,
            "counter": self.msg_counter,
            "payload" : payload
        }
        try:
            self.send_packets(message, self.linked_name)
        except Exception:
            self.write_log_debug(traceback.format_exc())
            raise UnreachableSwarm

    def start(self) -> None:
        self.add_fst_line_journal()
        self._stop_event.clear()
        self._link_thread = threading.Thread(
            target=self._link_loop, daemon=True, name=f"{self.node_name}-link"
        )
        self.write_log_debug("Waiting " + str(WAKEUP_TIME) + "s for network to settle")
        time.sleep(WAKEUP_TIME)
        self._link_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        """Signal the link update thread to stop and wait for it to finish."""
        if self._link_thread is not None:
            self._link_thread.join(timeout=self.link_duration + 1)
            self._link_thread = None


    def __enter__(self) -> "Transceiver":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()


    def _link_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.linked_name = self.get_next_link()
                self.write_log_debug("new linked satellite : "+ self.linked_name + " | Next satellite update in :" + str(self.link_duration) )

                time.sleep(self.link_duration)


            except Exception:
                self.write_log_debug(traceback.format_exc())

    #
    #
