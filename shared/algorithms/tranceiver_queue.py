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
import queue
import time
from tranceiver import Transceiver
# ===========================================================================
# Transceiver
# ===========================================================================
class NotReady(Exception):
    def __init__(self):
        self.message = "Message not ready for treatment, sent back to the end of the queue"
        super().__init__(self.message)


class Transceiver_queue(Transceiver):
    """Multicast transceiver base class.

        neighbors       — list of neighbors, unkown in top level, only for emulating bcast
    """

    _RX_TIMEOUT = 1.0   # recvfrom block duration; also caps stop() wait time

    def __init__(self, queue_max_size:int = 0):
        super().__init__()
        self.msg_queue=queue.Queue(queue_max_size)
        self._tx_thread: threading.Thread | None = None

    def add_lst_journal(self, message, addr):
        journal_entry = formatted(self.get_local_time()) +\
                        formatted("LST") +\
                        formatted(addr) +\
                        formatted(message["type"]) +\
                        formatted(message["sender"]) +\
                        formatted(message["counter"]) +\
                        formatted(message["payload"])
        with open(self.path_to_journal, 'a') as journal:
            journal.write('\n'+journal_entry[:-2])


    def start(self) -> None:
        self.add_fst_line_journal()

        self._tx_thread = threading.Thread(
            target=self._tx_loop, daemon=True, name=f"{self.node_name}-tx"
        )
        self._tx_thread.start()


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
            except OSError as e:
                try:
                    self.write_log_debug("RX socket OSError (continuing): " + str(e), "Transceiver_queue ")
                except Exception:
                    pass
                continue
            try:
                message = json.loads(data.decode('utf-8'))
                self.add_rcv_journal(message, addr[0])
                self.msg_queue.put_nowait((message, addr))
                self.write_log_debug("Adding message to queue  ( " + str(message) + ", " + str(addr) + " )", "Transceiver_queue ")
            except queue.Full:
                try:
                    self.add_lst_journal(message, addr[0])
                    self.write_log_debug("Message queue is full, folowing packet is lost : " + str(message), "Transceiver_queue ")
                except Exception:
                    pass
            except Exception:
                try:
                    self.write_log_debug(traceback.format_exc(), "Transceiver_queue ")
                except Exception:
                    pass  # never let a handler crash the RX thread

    def _tx_loop(self):
         while not self._stop_event.is_set():
            try:
                message, addr = self.msg_queue.get(True, self._RX_TIMEOUT)
                self.write_log_debug("poping message from queue : ( " + str(message) + ", " + str(addr) + " )", "Transceiver_queue ")
                self.msg_queue.task_done()
            except queue.Empty:
                continue
            except OSError:
                break
            try:
                self.message_handler(message, addr)
                self.on_message(message, addr[0])
            except NotReady:
                try:
                    self.msg_queue.put_nowait((message, addr))
                except queue.Full:
                    self.add_lst_journal(message, addr[0])
                    self.write_log_debug("Message queue is full, folowing packet is lost : " + str(message), "Transceiver_queue ")
                    pass
                pass
            except Exception:
                self.write_log_debug(traceback.format_exc(), "Transceiver_queue ")
                pass



