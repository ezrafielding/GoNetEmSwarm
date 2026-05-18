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
            self.link_order_list = self.satellite_addr_list.copy()
            random.shuffle(self.link_order_list)
            self.write_log("random link order : "+ str(self.link_order_list))
            self.linked_address = self.link_order_list.pop()
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
                    self.link_order_list = self.satellite_addr_list.copy()
                    random.shuffle(self.link_order_list)
                self.msg_sent = False
                self.write_log("AAAAAAAAAAAAAAAAAAAAAAA")
                return self.link_order_list.pop()
            else:
                self.write_log("BBBBBBBBBBBBBBBB")
                return self.linked_address
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
                self.write_log("Get next link called, with msg_sent : "+ str(self.msg_sent))
                if self.msg_sent:
                    if not self.link_order_list:
                        self.link_order_list = self.satellite_addr_list
                        random.shuffle(self.link_order_list)
                    self.msg_sent = False
                    return self.link_order_list.pop()
                else:
                    return self.linked_address
        except Exception:
            self.write_log("Encountered exception during send_unicast : " + str(traceback.format_exc()) )

algo = cycle_unicast()
algo.start()
time.sleep(4)
#For my test their is 5 linked satellites, so range 5 to check if each one is only called once.
algo.write_log("Started !")

for i in range(5):
    try:
        algo.write_log("message number : " + str(i) + " trying to send to : "+ algo.linked_address+ " .")
        algo.send_unicast({"from": algo.node_name, "message": "Hello World "+str(i)+" from : "+ algo.node_name })
        time.sleep(algo.link_duration)
    except Exception:
        algo.write_log_debug("Unable to send message number :" + str(i) + ". Error : " + str(traceback.format_exc()) )

algo.write_log("Finished !")


