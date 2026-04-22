import socket
import os
import netifaces
import threading
import time
import json
import logging
from datetime import datetime
from typing import Callable, Optional
from queue import Queue

class UDPCommunicationService:
    """
    Low-level UDP networking service for broadcast and unicast communication.

    Provides following services:
    1. Receiver: Listens for UDP broadcasts and invokes callback
    2. Transmitter: Periodically broadcasts data from callback
    3. send_broadcast: send a messsage to the whole network using Multi-interface UDP Broadcast
    4. send_unicast: send a message to a specific node identified by ann ip addresse

    TODO
    5. reliable_diffusion: send a message to the whole network ensuring reliable diffusion (either the whole network get it, or nobody) [chap 4 generique p 37]

    Network Configuration:
    ---------------------
    - Port 5007: ISL (Inter-Satellite Link) communication
    - 172.20.255.255: Broadcast address for satellite network
    - JSON serialization for all messages

    Thread Safety:
    -------------
    - Receiver runs in separate thread with message callback
    - Transmitter runs in separate thread with data callback
    - Both threads use daemon mode for clean shutdown

    Attributes:
        port (int): UDP port for communication (default: 5007)
        running (bool): Receiver thread running flag
        broadcast_addr_list (list of the broadcasts addresses of each interfaces.)
        transmitting (bool): Transmitter thread running flag
        receiver_thread: Background receiver thread
        transmitter_thread: Background transmitter thread
        sender_sock: Socket for sending messages
        receiver_sock: Socket for receiving messages
        message_callback: Function called when message received
        transmit_callback: Function called to get data to transmit
        transmit_interval: Seconds between broadcasts
        path_to_logs (string): the directory where the file used to store networks logs for debugging purpose will be.
    """

    def __init__(self, port: int = 5007, path_to_log_dir = "/usr/local/logs/"):
        """
        Initialize UDP broadcast service. use netiface to initialize broadcast_addr_list

        Args:
            port (int): UDP port number (default: 5007 for ISL)
        """
        self.port = port
        self.running = False
        self.receiver_thread: Optional[threading.Thread] = None
        self.transmitter_thread: Optional[threading.Thread] = None
        self.sender_sock: Optional[socket.socket] = None
        self.receiver_sock: Optional[socket.socket] = None
        self.message_callback: Optional[Callable] = None
        self.transmit_callback: Optional[Callable] = None
        self.transmit_interval: float = 1.0
        self.transmitting = False
        self.broadcast_addr_list = []
        self.path_to_logs = path_to_log_dir+"net_"+os.getenv("SAT_ID", "UKN")+".log"

        #use netiface to gather broadcast adresses of every interfaces in a single list.
        #more information about this piece of code here: https://linuxvox.com/blog/udp-broadcast-on-all-interfaces/#method-2-python-implementation-simpler-workflow
        for iface in netifaces.interfaces():
            if iface == "lo":
                continue
            addrs = netifaces.ifaddresses(iface)
            if netifaces.AF_INET not in addrs:  # Skip non-IPv4 interfaces
                continue
            ipv4_info = addrs[netifaces.AF_INET][0]
            if "broadcast" in ipv4_info:  # Skip interfaces without broadcast (e.g., VPN)
                self.broadcast_addr_list.append(ipv4_info["broadcast"])
                #PYTHON IS FUCKING RACIST AS FUCK
                self.write_log("broadcast_addr_list updated, adding : "+ ipv4_info["broadcast"])

    def write_log(self, log_message):
        with open(self.path_to_logs, 'a') as file:
            file.write('\n'+log_message)

    def start_receiver(self, callback: Callable[[dict, tuple], None]):
        """
        Start the background receiver thread to listen for UDP broadcasts.

        Creates a UDP socket bound to the ISL port and spawns a daemon thread
        that continuously listens for incoming messages. Messages are JSON-
        deserialized and passed to the callback function.

        The socket uses SO_REUSEADDR to allow multiple processes to bind to
        the same port (useful for testing). A 1-second timeout enables clean
        shutdown by periodically checking the running flag.

        Args:
            callback: Function to call when a message is received.
                     Signature: callback(data: dict)
        """
        if self.running:
            self.write_log("Receiver already running when start_receiver is called")
            return

        self.message_callback = callback
        self.running = True

        # Create UDP receiver socket
        self.receiver_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.receiver_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.receiver_sock.bind(('', self.port))  # Bind to all interfaces
        self.receiver_sock.settimeout(1.0)  # Timeout for clean shutdown

        # Start background receiver thread (daemon for automatic cleanup)
        self.receiver_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self.receiver_thread.start()
        self.write_log(f"UDP Broadcast receiver started on port {self.port}")

    def _receive_loop(self):
        """
        Internal receiver loop that runs in background thread.

        Continuously receives UDP packets, deserializes JSON, and invokes
        the message callback. Handles socket timeouts gracefully to check
        the running flag for shutdown. Invalid JSON is logged but doesn't
        crash the receiver.
        """
        while self.running:
            try:
                # Receive UDP packet (blocks up to timeout)
                data, addr = self.receiver_sock.recvfrom(4096)
                try:
                    # Deserialize JSON message
                    message = json.loads(data.decode('utf-8'))
                    if self.message_callback:
                        self.message_callback(message)
                        self.write_log("received a message, content : "+ message)
                except json.JSONDecodeError:
                    self.write_log(f"Received invalid JSON from {addr}")
            except socket.timeout:
                # Timeout - check running flag and continue
                continue
            except Exception as e:
                if self.running:  # Only self.write_log if not shutting down
                    self.write_log(f"Error receiving data: {e}")

    def start_transmitter(self, callback: Callable[[], dict], interval: float = 1.0):
        """
        Start the background transmitter thread for periodic broadcasts.

        Spawns a daemon thread that periodically calls the callback function
        to get data and broadcasts it to the network. This enables state
        propagation without explicit send calls from the algorithm.

        Typical use: Broadcasting CRDT state, heartbeats, or algorithm state.

        Args:
            callback: Function to call to get the data to transmit.
                     Signature: callback() -> dict
            interval: Broadcast interval in seconds (default: 1.0)
        """
        if self.transmitting:
            self.write_log("Transmitter already running when start_transmitter is called")
            return

        self.transmit_callback = callback
        self.transmit_interval = interval
        self.transmitting = True

        # Start background transmitter thread (daemon for automatic cleanup)
        self.transmitter_thread = threading.Thread(target=self._transmit_loop, daemon=True)
        self.transmitter_thread.start()
        self.write_log(f"UDP Broadcast transmitter started with {interval}s interval")

    def _transmit_loop(self):
        """
        Internal transmitter loop that runs in background thread.
        Periodically invokes the transmit callback to get data and broadcasts
        it to the network. Sleep between broadcasts to control rate.
        Errors are logged but don't crash the transmitter.
        """
        while self.transmitting:
            try:
                if self.transmit_callback:
                    # Get data from callback
                    message = self.transmit_callback()
                    # Broadcast to network
                    self.send_broadcast(message)
                # Wait before next broadcast
                time.sleep(self.transmit_interval)
            except Exception as e:
                if self.transmitting:  # Only print if not shutting down
                    self.write_log(f"Error in transmit loop: {e}")

    def send_broadcast(self, message: dict):
        """
        Send a broadcast message to all nodes on the network.
        Args:
            message: Dictionary to send (will be JSON serialized)
        """
        # Creation of sender socket on first use (lazy initialization).
        if not self.sender_sock:
            self.sender_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sender_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        # Serialize and send to broadcast address
        data = json.dumps(message).encode('utf-8')
        for broadcast_addr in self.broadcast_addr_list:
            self.write_log("trying to send broadcast to : "+ broadcast_addr)
            self.sender_sock.sendto(data, (broadcast_addr, self.port))

    def send_unicast(self, message: dict, dest_addr: str):
        """
        Send a unicast message to a specific node.
        Args:
            message: Dictionary to send (will be JSON serialized)
            dest_addr: Destination IP address
        """
        # Lazy socket creation (reuses broadcast socket)
        if not self.sender_sock:
            self.sender_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sender_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        # Serialize and send to specific address
        data = json.dumps(message).encode('utf-8')
        self.sender_sock.sendto(data, (dest_addr, self.port))

    def stop(self):
        """
        Stop the receiver and transmitter threads and close sockets.
        The timeout prevents hanging if threads are blocked.
        """
        # Signal threads to stop
        self.running = False
        self.transmitting = False

        # Wait for threads to finish (with timeout)
        if self.receiver_thread:
            self.receiver_thread.join(timeout=2.0)

        if self.transmitter_thread:
            self.transmitter_thread.join(timeout=2.0)

        # Close sockets
        if self.receiver_sock:
            self.receiver_sock.close()

        if self.sender_sock:
            self.sender_sock.close()

        self.write_log("UDP Broadcast service stopped")
