import socket
import os
import threading
import time
import json
import logging
from datetime import datetime
from typing import Callable, Optional
from queue import Queue
from udpservices import UDPCommunicationService

class SatelliteNode:
    """
    High-level satellite node abstraction for distributed algorithms.

    Provides a complete framework for implementing distributed algorithms
    in a satellite swarm. Handles networking, message queuing, threading,
    logging, and display updates. Algorithm implementations subclass this
    and override key methods.

    Key Design Patterns:
    -------------------
    1. Message Queue: Decouples network I/O from algorithm logic
    2. Deferred Messages: Allows algorithms to postpone message processing
    3. Thread-Safe Display: Separate display thread with event-driven updates
    4. Structured Logging: Per-node log files for analysis

    Threading Model:
    ---------------
    - Network receiver thread: Receives UDP packets, enqueues messages
    - Network transmitter thread: Periodically broadcasts state
    - Message processor thread: Processes queued messages sequentially
    - Display thread: Updates terminal display on request
    - Main thread: Runs algorithm mission() method

    Message Flow:
    ------------
    UDP packet → receiver thread → message queue → processor thread → on_receive()

    Deferred Message Flow:
    ---------------------
    on_receive() → defer_message() → back of queue → on_receive() (later)

    Usage Pattern:
    -------------
    1. Subclass SatelliteNode
    2. Override on_receive() to handle messages
    3. Override mission() for algorithm logic
    4. Optionally override update_display() for custom UI
    5. Use self.isl.send_unicast() for point-to-point messages
    6. Use defer_message() to postpone messages

    Attributes:
        node_id (str): Unique node identifier
        node_ip (str): Node IP address (for unicast)
        test_name (str): Test name (for logging)
        logger: Structured logger for this node
        display_thread: Background display thread
        display_event: Event for signaling display updates
        data_lock: Lock for thread-safe data access
        message_queue: Queue for incoming/deferred messages
        message_processor_thread: Thread processing message queue
        isl: UDP broadcast service for networking
    """

    def __init__(self, node_id: str, test_name: str, start_recv: bool = True, start_trans: bool = False):
        """
        Initialize a satellite node.

        Sets up logging, threading, and networking. The node can be configured
        for different modes:
        - Receive-only: For passive algorithms that only listen
        - Transmit-only: For beacon nodes
        - Full duplex: For typical interactive algorithms (default)

        Args:
            node_id (str): Unique node identifier (e.g., "1", "2", "3")
            node_ip (str): Node IP address (e.g., "172.20.0.10")
            test_name (str): Test name for logging (e.g., "crdt_test")
            start_recv (bool): Start receiver and message processor (default: True)
            start_trans (bool): Start transmitter for periodic broadcasts (default: False)
        """
        self.node_id = node_id
        self.test_name = test_name

        # Setup structured logging for this node
        self.setup_logging(self.test_name)

        # Display thread management
        self.display_thread = None
        self.display_running = False
        self.display_event = threading.Event()  # Event for signaling updates
        self.data_lock = threading.Lock()  # Lock for thread-safe data access

        # Message queue (handles both incoming and deferred messages)
        self.message_queue = Queue()
        self.message_processor_running = False
        self.message_processor_thread = None

        # Start message processor thread (if receiving)
        if start_recv:
            self.start_message_processor()

        # ISL (Inter-Satellite Link) networking setup
        self.isl = UDPCommunicationService()
        if start_recv:
            # Start receiver: UDP packets → queue
            self.isl.start_receiver(callback=self._queue_message)
        if start_trans:
            # Start transmitter: periodic broadcast of state
            self.isl.start_transmitter(callback=self.get_broadcast_data, interval=2.0)

        # Start display thread for terminal UI updates
        self.start_display_thread()

    def setup_logging(self, test_name: str):
        """
        Setup structured logging for this satellite node.

        Creates a per-node log file with timestamp for analysis and debugging.
        Log format includes timestamp, node name, level, and message.

        Log files are used by analysis tools (e.g., tools/crdt_report.py).

        Args:
            test_name (str): Test name for log file naming
        """
        # Create logs directory if it doesn't exist
        os.makedirs('logs', exist_ok=True)

        # Create log filename: sat_{id}_{test}_{timestamp}.log
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = f"logs/sat_{self.node_id}_{test_name}_{timestamp}.log"

        # Setup logger with node-specific name
        self.logger = logging.getLogger(f"sat_{self.node_id}")
        self.logger.setLevel(logging.INFO)

        # Clear any existing handlers (for repeated initialization)
        self.logger.handlers.clear()

        # Create file handler for persistent logging
        file_handler = logging.FileHandler(log_filename)
        file_handler.setLevel(logging.INFO)

        # Create formatter: timestamp - name - level - message
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)

        # Attach handler to logger
        self.logger.addHandler(file_handler)

    def _queue_message(self, message: dict):
        """
        Add incoming message to queue (called by UDP receiver thread).

        This is the callback invoked by UDPCommunicationService when a message
        arrives. It simply enqueues the message for processing by the
        message processor thread, decoupling network I/O from algorithm logic.

        Args:
            message (dict): Incoming message (JSON deserialized)
        """
        self.message_queue.put(message)

    def defer_message(self, message: dict):
        """
        Defer a message for later processing.

        Critical for distributed algorithms that need to postpone message
        handling until certain conditions are met. The message is placed
        at the back of the queue and will be reprocessed later.

        Example use cases:
        - GHS: Defer CONNECT if edge state is still basic
        - GHS: Defer REPORT if still in find state
        - Consensus: Defer vote if not in correct round

        Args:
            message (dict): Message to defer
        """
        self.message_queue.put(message)

    def start_message_processor(self):
        """
        Start the message processor thread.

        Spawns a daemon thread that continuously processes messages from
        the queue. This provides sequential message processing, important
        for algorithms that require message ordering guarantees.

        The sequential processing also simplifies algorithm logic by
        eliminating race conditions from concurrent message handling.
        """
        self.message_processor_running = True
        self.message_processor_thread = threading.Thread(target=self._message_processor_loop, daemon=True)
        self.message_processor_thread.start()

    def _message_processor_loop(self):
        """
        Background thread that processes messages from the queue.

        Continuously pulls messages from the queue (with timeout for clean
        shutdown) and invokes on_receive() for each message. This ensures
        sequential processing of messages, avoiding race conditions.

        The timeout allows the thread to check the running flag periodically
        for graceful shutdown.
        """
        while self.message_processor_running:
            try:
                # Get message from queue (blocks up to timeout)
                message = self.message_queue.get(timeout=1.0)
                # Process message in algorithm-specific handler
                self.on_receive(message)
            except:
                # Queue was empty (timeout) - check running flag and continue
                continue

    def on_receive(self, message: dict) -> bool:
        """
        Handle incoming message (override in subclass).

        Default implementation filters out self-messages. Subclasses should
        call super().on_receive(message) first to get the not_self flag,
        then process the message accordingly.

        Args:
            message (dict): Received message with at least 'node_id' field

        Returns:
            bool: True if message is from another node, False if self-message
        """
        # Ignore messages from our own node
        return message.get('node_id') != self.node_id

    def start_display_thread(self):
        """
        Start the display update thread.

        Spawns a daemon thread that handles terminal display updates.
        Display updates are event-driven (triggered via request_display_update())
        or periodic (every 5 seconds) for status monitoring.

        The separate display thread prevents display rendering from blocking
        algorithm execution or message processing.
        """
        self.display_running = True
        self.display_thread = threading.Thread(target=self._display_loop, daemon=True)
        self.display_thread.start()

    def _display_loop(self):
        """
        Background thread that handles display updates.

        Waits for display update requests via threading.Event or times out
        every 5 seconds for periodic refresh. Event-driven updates provide
        immediate feedback while timeout ensures display stays current.
        """
        # Initial display render
        self.update_display()

        while self.display_running:
            # Wait for update request or timeout (5 seconds)
            if self.display_event.wait(timeout=5.0):
                # Event was set - clear it and update display
                self.display_event.clear()
                self.update_display()

    def request_display_update(self):
        """
        Request a display update from other threads.

        Sets the display event to wake up the display thread and trigger
        an immediate update. Safe to call from any thread.

        Use this after significant state changes (e.g., received new data,
        algorithm state change) to provide immediate visual feedback.
        """
        self.display_event.set()

    def update_display(self):
        """
        Update the terminal display with current status (override in subclass).

        Default implementation does nothing. Subclasses should override to
        render algorithm-specific status information.

        Thread Safety:
        -------------
        This method runs in the display thread. Use self.data_lock to
        safely read shared state:

        Example:
            with self.data_lock:
                data_copy = copy.copy(self.data)
            # Render data_copy without holding lock
        """
        pass

    def get_broadcast_data(self, payload) -> dict:
        """
        Prepare data for broadcast transmission (override in subclass).

        Called periodically by the transmitter thread if start_trans=True.
        Default implementation wraps payload with node_id.

        Args:
            payload: Algorithm-specific data to broadcast

        Returns:
            dict: Message to broadcast (must be JSON-serializable)
        """
        return {
            'node_id': self.node_id,
            'payload': list(payload)
        }

    def mission(self):
        """
        Main algorithm execution loop (override in subclass).

        This is where the algorithm logic lives. Typically runs in the
        main thread while background threads handle networking, message
        processing, and display.

        Example pattern:
            while not done:
                # Perform algorithm work
                # State changes trigger display updates via request_display_update()
                # Algorithm reacts to messages via on_receive()
        """
        pass

    def stop(self):
        """
        Gracefully stop the satellite node and all background threads.

        Shutdown sequence:
        1. Stop message processor thread
        2. Stop display thread
        3. Stop UDP networking service

        Each thread is signaled to stop and given a timeout to finish.
        This ensures clean shutdown without hanging or resource leaks.

        Safe to call from signal handlers (e.g., KeyboardInterrupt).
        """
        self.logger.info("Stopping satellite node services")

        # Stop message processor thread
        self.message_processor_running = False
        if self.message_processor_thread:
            self.message_processor_thread.join(timeout=2.0)

        # Stop display thread
        self.display_running = False
        self.display_event.set()  # Wake up the display thread
        if self.display_thread:
            self.display_thread.join(timeout=2.0)

        # Stop UDP networking service (receiver and transmitter)
        self.isl.stop()
