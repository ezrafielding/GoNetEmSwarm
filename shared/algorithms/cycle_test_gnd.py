from ground_tranceiver import Ground_transceiver
import time
import random
import traceback

# ===========================================================================
# A Simple Hello world test for debugging purpose
# ===========================================================================


class cycle_unicast(Ground_transceiver):

    def __init__(self):
        self.path_to_logs = "/logs/"
        try:
            super().__init__()
            self.write_log("Test broadcast service started")
            self.set_link_duration(5)
            self.link_order_list = list(self.neighbors_addr_dict.keys()).copy()
            random.shuffle(self.link_order_list)
            self.write_log("random link order : "+ str(self.link_order_list))
            self.linked_name = self.link_order_list.pop()
            self.write_log("First link : " + str(self.linked_name) )
            self.msg_sent = False
        except Exception:
            self.write_log("Encountered exception during __init__ : " + str(traceback.format_exc()) )

    def write_log(self, log_message):
        with open(self.path_to_logs+self.node_name+".log", 'a') as file:
            file.write('\n'+log_message)

    def get_next_link(self):
        try:
            self.write_log("Get next link called, with msg_sent : "+ str(self.msg_sent))
            if self.msg_sent:
                if len(self.link_order_list) == 0:
                    self.link_order_list = list(self.neighbors_addr_dict.keys()).copy()
                    random.shuffle(self.link_order_list)
                self.msg_sent = False
                return self.link_order_list.pop()
            else:
                return self.linked_name
        except Exception:
            self.write_log("Encountered exception during get_next_link : " + str(traceback.format_exc()) )



    def send_unicast(self, payload):
        try:
            if not self.msg_sent:
                self.msg_sent = True
                super().send_unicast(payload)
            else:
                #Maybe cleaner to raise an exception nd handle it in the algorithme part below, but it works.
                self.write_log("A message has already been sent to the linked satelite, waiting for next link update before retrying...")
                time.sleep(self.link_duration)
                self.send_unicast(payload)
        except Exception:
            self.write_log("Encountered exception during send_unicast : " + str(traceback.format_exc()) )

algo = cycle_unicast()
algo.start()
time.sleep(4)
#For my test their is 5 linked satellites, so range 5 to check if each one is only called once.
algo.write_log("Started !")

for i in range(5):
    try:
        algo.write_log("message number : " + str(i) + " trying to send to : "+ algo.linked_name+ " .")
        algo.send_unicast({"from": algo.node_name, "message": "Hello World "+str(i)+" from : "+ algo.node_name })
        time.sleep(algo.link_duration)
    except Exception:
        algo.write_log_debug("Unable to send message number :" + str(i) + ". Error : " + str(traceback.format_exc()) )

algo.write_log("Finished !")


