from tranceiver_queue import Transceiver_queue
import time

# ===========================================================================
# A Simple Broadcast test for debugging purpose
# ===========================================================================


class simple_broadcast(Transceiver_queue):
    def __init__(self):

        self.path_to_logs = "/logs/"
        super().__init__()
        self.totalmsg = 3*(self.network_size-1)
        self.brd_counter = 0
        self.write_log("Test broadcast service started")

    def write_log(self, log_message):
        with open(self.path_to_logs+self.node_name+".log", 'a') as file:
            file.write('\n'+log_message)

    def on_message(self, data: dict, addr: tuple):
        if (data["type"] == 1): #message is a broadcast
            self.write_log("Message received with following payload :")
            self.write_log("payload = "+ str(data["payload"]))
            self.write_log("From address :"+str(addr))
            self.brd_counter += 1


algo = simple_broadcast()
algo.start()
while(not algo.network_initialized):
    time.sleep(1)
algo.write_log("Ready.")
algo.send_broadcast({"Origine": algo.node_name, "Message": "Hello World" })
algo.write_log("broadcast sent.")
algo.send_broadcast({"Origine": algo.node_name, "Message": "Hello World 2"})
algo.send_broadcast({"Origine": algo.node_name, "Message": "Hello World 3"})
while (algo.brd_counter< algo.totalmsg):
    time.sleep(4)
    algo.write_log("waiting for all messages, received : " + str(algo.brd_counter) + " / " + str(algo.totalmsg)  )


