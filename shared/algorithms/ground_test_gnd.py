from ground_tranceiver import Ground_transceiver
import time

# ===========================================================================
# A Simple Hello world test for debugging purpose
# ===========================================================================


class simple_unicast(Ground_transceiver):

    def __init__(self):

        self.path_to_logs = "/logs/"
        super().__init__()
        self.write_log("Test broadcast service started")
        self.set_link_duration(5)

    def write_log(self, log_message):
        with open(self.path_to_logs+self.node_name+".log", 'a') as file:
            file.write('\n'+log_message)


algo = simple_unicast()
algo.start()
time.sleep(4)
for i in range(5):
    time.sleep(algo.link_duration)
    algo.send_unicast({"from": algo.node_name, "message": "Hello World "+str(i)+" from : "+ algo.node_name })
    algo.write_log("message number : " + str(i) + " sent.")


