from tranceiver import Transceiver
import time
import traceback

# ===========================================================================
# A Simple Broadcast test for debugging purpose
# ===========================================================================

class ExecutionError(Exception):
    def __init__(self, msg_type):
        self.message = "Received to much of a single type of cummunication : " + msg_type
        super().__init__(self.message)


class cycle_recepter(Transceiver):

    def __init__(self):

        self.path_to_logs = "/logs/"
        super().__init__()
        self.brd_counter = 0
        self.gnd_counter = 0
        self.write_log("Test simple_recepter service started")

    def write_log(self, log_message):
        with open(self.path_to_logs+self.node_name+".log", 'a') as file:
            file.write('\n'+log_message)

    def on_message(self, data: dict, addr: tuple):

        if (data["type"] == 1): #message is a broadcast,
            if self.brd_counter >= 1:
                raise ExecutionError("Broadcast")
            self.write_log("Message from other satellite received with following payload :")
            self.write_log("payload = "+ str(data["payload"]))
            self.write_log("From address :"+str(addr))
            self.brd_counter += 1

        if (data["type"] == 9): #message is sent by a ground station
            if self.gnd_counter >= 1:
                raise ExecutionError("Ground communication")
            self.write_log("Message from the ground received with following payload :")
            self.write_log("payload = "+ str(data["payload"]))
            self.write_log("From address :"+str(addr))
            self.send_broadcast(data["payload"])
            self.gnd_counter += 1

algo = cycle_recepter()
algo.start()
while(not algo.network_initialized):
    time.sleep(1)
algo.write_log("Ready.")

while not( (algo.brd_counter == 1) or  (algo.gnd_counter == 1) ):
    try:
        time.sleep(4)
        algo.write_log("waiting for all messages, message received : " + str(algo.brd_counter) +  str(algo.gnd_counter) + " / 4"  )
    except Exception:
        algo.write_log(traceback.format_exc())
#
# while True:
#     time.sleep(15)
#     algo.write_log("Finished, waiting for manunal interuption...")
