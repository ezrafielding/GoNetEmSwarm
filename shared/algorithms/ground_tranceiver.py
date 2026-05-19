
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
def formatted(value):
    return " "+str(value)+" |"

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
        try:
            self.gnd_id: int = int(os.environ["GND_ID"]) #ADD TO RUN TEST
        except Exception:
            self.write_log_debug("Unable to read GND_ID from environement :" + str(traceback.format_exc()) )
            self.gnd_id = 2

        info = all_nodes[self.node_name]

        self.msg_counter = 0

        self.link_duration = 0

        self.net_port = 5007
        self.satellite_addr_list = []
        self.write_log_debug("Tranceiver started: "+ self.node_name)

        for sat in info["neighbors"] :
            self.satellite_addr_list.append(sat["link_ip"])
            self.write_log_debug("Satellite added: "+ sat["name"] + " | link ip: "+ sat["link_ip"])

        self.linked_address = None
        self._stop_event = threading.Event()
        self._link_thread: threading.Thread | None = None
        self._tx_thread: threading.Thread | None = None
        self._tx_sock:   socket.socket    | None = None

    def get_next_link(self):
        return random.choice(self.satellite_addr_list)

    def set_link_duration(self, value: int):
        self.link_duration = value

    def write_log_debug(self, log_message, service_name : str = "Tranceiver"):
        with open(self.path_to_logs_debug, 'a') as log_file:
            log_file.write('\n'+str(self.get_local_time())+" "+service_name+" : "+log_message)

    def send_packets(self, message: dict, ip_addr: str, transfert:bool = False):
        self.write_log_debug("sending packet packet to " + ip_addr + " with content "+ str(message))
        try:
            data = json.dumps(message).encode('utf-8')
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tx:
                tx.sendto(data, (ip_addr, self.net_port))
            if transfert:
                self.add_tra_journal(message, ip_addr)
            else:
                self.add_snt_journal(message, ip_addr)
        except Exception:
            self.write_log_debug("Unable to send packets :" + str(traceback.format_exc()) )
            pass  # never let the TX thread crash

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
            journal.write(journal_entry[:-2])

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

    def increment_counter(self):
        self.msg_counter = self.msg_counter +1

    def send_unicast(self, payload: dict):
        addr = self.linked_address
        self.increment_counter()

        self.write_log_debug("Sending Unicast to : "+ addr)
        message = {
            "type": 9,
            "sender": self.node_name,
            "counter": self.msg_counter,
            "payload" : payload
        }
        try:
            self.send_packets(message, addr)
        except Exception:
            self.write_log_debug(traceback.format_exc())
            raise UnreachableSwarm

    def start(self) -> None:
        self.add_fst_line_journal()
        self._stop_event.clear()
        self._link_thread = threading.Thread(
            target=self._link_loop, daemon=True, name=f"{self.node_name}-link"
        )
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
                self.write_log_debug("Before")
                self.linked_address = self.get_next_link()
                self.write_log_debug("After")

                self.write_log_debug("new linked satellite : "+ self.linked_address + " | Next satellite update in :" + str(self.link_duration) )

                time.sleep(self.link_duration)


            except Exception:
                self.write_log_debug(traceback.format_exc())

    #
    #
