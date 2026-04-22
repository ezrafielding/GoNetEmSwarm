import os
import sys
import time
import random
from satellite import SatelliteNode




class Broadsat(SatelliteNode):
    """
    Satellite node implementing attempting to send a broadcast message multiple time

    Architecture:
    ------------
    - Inherits from SatelliteNode for networking and broadcast capabilities

    Attributes:
        payload (str) message to send to other satellites.
        attempt (int) number of broadcast attempt
    """

    def __init__(self, node_id: str, test_name:str, message_content:str):

        self.payload = message_content+ "from satellite with id : "+node_id
        self.attempt = 0

        # Initialize parent SatelliteNode with networking enabled
        super().__init__(node_id, test_name, start_recv=True, start_trans=False)


    def setup_logging(self, test_name):
        """
        Initialize logging for this satellite node.

        Extends parent logging setup with CRDT-specific information.

        Args:
            test_name (str): Name of the test for log file naming
        """
        super().setup_logging(test_name)
        self.logger.info(f"broadcast test started for satellite {self.node_id} with message_content : {self.payload}.")

    def on_receive(self, message):
        """
        Handle incoming broadcast messages from other satellites.

        ecrit le contenus du message reçu dans le fichier de log

        Args:
            message (dict): Message containing 'node_id' and 'payload' (message)

        Returns:
            bool: True if message was from another node, False if self-message
        """
        # Filter out self-messages
        not_self = super().on_receive(message)
        if not_self:
            sender_id = message.get('node_id', 'unknown')
            incoming_message = str(message['payload'])

            # Compute set difference to find truly new words
            # This is for metrics only - merge would work without it

            self.logger.info(f"Received from node {sender_id}: + incoming_message +")
            self.request_display_update()
        return not_self
    
    def update_display(self):
        """
        Update terminal display with current G-Set state and metrics.

        Displays:
        - Node ID and convergence progress (X/N words)
        - Contribution breakdown (self vs other nodes)
        - Complete G-Set payload (list of all words)

        Thread-safe: Uses data_lock to create consistent snapshot of state
        before rendering to terminal.
        """
        with self.data_lock:
            # Clear screen for clean display
            sys.stdout.write('\033[2J\033[H')

            # Get current time for timestamp
            current_time = time.strftime("%H:%M:%S")

        print(f"╔═══════════════════════════════════════════════════════════════╗")
        print(f"║                  Broadcast Status - {current_time}                  ║")
        print(f"╠═══════════════════════════════════════════════════════════════╣")
        print(f"║ Node ID:  {self.node_id:<10}         │ Running ... attempt no "+ str(self.attempt) +"       ║")
        print(f"╚═══════════════════════════════════════════════════════════════╝")
        print()

        # Flush output to ensure immediate display
        sys.stdout.flush()
    
    def get_broadcast_data(self):
        """
        Get data to broadcast to other satellites.

        Returns the complete G-Set payload so neighbors can merge with their
        local replicas. Because G-Set merge is idempotent, broadcasting the
        entire set repeatedly is safe and simple.

        Returns:
            dict: Broadcast message containing node_id and G-Set payload
        """
        return super().get_broadcast_data(self.payload)

    def mission(self):
        """
        Main mission loop - send braodcast message every 5 seconds
        """
        self.logger.info("Starting mission - satellite starting broadcast")

        while (self.attempt <= 13) :

            self.attempt= self.attempt+1
            self.logger.info(f"sending broadcast: '{self.payload}' (attempt: {self.attempt})")
            self.request_display_update()
            self.isl.send_broadcast(self.payload)
            # Random sleep simulates time between discoveries
            # sleep_time = random.uniform(1, 10)
            sleep_time = 5
            time.sleep(sleep_time)


        self.logger.info("Broadcast test session ended")

    def stop(self):
        """
        Gracefully stop the satellite node and log final statistics.

        Logs:
        - Total words in final G-Set (should be 100% at convergence)
        - Self-discovered words vs received from others
        - Per-node contribution breakdown
        - Complete final G-Set payload

        These metrics help analyze convergence behavior and network activity.
        """
        super().stop()


def main():
    """
    Main entry point for Broadcast test.

    Configuration:
    - SAT_ID: Unique node identifier (from environment)
    - ALGORITHM_IP: Node IP address (from environment)
    """
    test_name = "broadcast_test"
    message = "hello world !"

    # Get satellite configuration from environment
    sat_id = os.environ.get('SAT_ID', 'ukn')

    # Create satellite node with G-Set CRDT
    node = Broadsat(sat_id, test_name, message)

    print(f"Starting broadcast on Node {sat_id}")

    try:
        # Run mission until convergence
        node.mission()
    except KeyboardInterrupt:
        print(f"\nNode {sat_id}: Shutting down...")
    finally:
        # Allow time for final broadcasts to propagate
        time.sleep(2)
        node.stop()
        print(f"Node {sat_id}: Mission complete!")


if __name__ == '__main__':
    main()
