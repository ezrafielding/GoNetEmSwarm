from tranceiver_tree import Tranceiver_with_mono_tree
from tranceiver_tree import UnfinishedTreeException

import time
import traceback
import os
# ===========================================================================
# A Simple Broadcast test for debugging purpose
# ===========================================================================


class simple_tree_broadcast(Tranceiver_with_mono_tree):
    def __init__(self):
        self.sent_bcast = 0
        self.path_to_logs = "/logs/"
        super().__init__(os.environ["HOSTNAME"]=="sat1")
        self.totalmsg = 2*(self.network_size-1)
        self.brd_counter = 0
        self.write_log("Test broadcast service started")

    def write_log(self, log_message):
        with open(self.path_to_logs+self.node_name+".log", 'a') as file:
            file.write('\n'+log_message)

    def on_message(self, data: dict, addr: tuple):
        if (data["type"] == 2): #message is a tree_based broadcast
            self.write_log("Message received via tree-based broadcast :")
            self.write_log("message content : "+ str(data))
            self.write_log("From address :"+str(addr))
            self.brd_counter += 1

    def send_bcast(self, payload: dict):
        try:
            super().send_tree_broadcast({"Origine": algo.node_name, "Message": "Hello World"+ str(self.sent_bcast)})
            algo.write_log("tree-based broadcast successfully sent")
            self.sent_bcast += 1
        except UnfinishedTreeException:
            algo.write_log(traceback.format_exc())



algo = simple_tree_broadcast()
algo.start()
while(not algo.network_initialized):
    time.sleep(1)
algo.write_log("Ready.")

try:
    while (algo.sent_bcast < 2):
        algo.send_bcast({"Origine": algo.node_name, "Message": "Hello World" })
        time.sleep(2)
    while (algo.brd_counter< algo.totalmsg):
        time.sleep(4)
        algo.write_log("waiting for all messages, received : " + str(algo.brd_counter) + " / " + str(algo.totalmsg)  )
except Exception:
    algo.write_log("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAHHHhhhh")
    algo.write_log(traceback.format_exc())

