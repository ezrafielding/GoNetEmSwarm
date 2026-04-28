from tranceiver import Transceiver
import time
import traceback

# ===========================================================================
# A Simple Broadcast test for debugging purpose
# ===========================================================================


class simple_ospf_broadcast(Transceiver):
    """CRDT-based distributed key-value catalog.

    Each entry is an op-based Last-Write-Wins Register:

        payload  X x, timestamp t
        initial  ⊥, 0
        query    value()      → x
        update   assign(x')
                   atSource   → t' = t + 1   (per-item integer counter)
                   downstream(x', t') → if t < t' then x, t := x', t'

    Downstream ops are broadcast to the swarm via multicast (Transceiver).

    Usage:

        class MyAlgorithm(Catalog):
            pass                    # on_message already handles merges

        algo = MyAlgorithm()
        with algo:
            algo.assign("orbit", {"alt": 550, "inc": 53.0})
            time.sleep(1)
            print(algo.value("orbit"))
            print(algo.items())

    Dict-style access:

        algo["orbit"] = {"alt": 550}
        print(algo["orbit"])
        print("orbit" in algo)
        print(len(algo))

    Reacting to incoming updates — override on_message and call super():

        class MyAlgorithm(Catalog):
            def on_message(self, data: bytes, addr: tuple):
                super().on_message(data, addr)   # merge first
                print(f"catalog now: {self.items()}")
    """

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
        if (data["type"] == 2): #message is a ospf broadcast
            self.write_log("Message received with following payload :")
            self.write_log("payload = "+ str(data["payload"]))
            self.write_log("From address :"+str(addr))
            self.brd_counter += 1


algo = simple_ospf_broadcast()
algo.start()
while(not algo.network_initialized):
    time.sleep(1)
algo.write_log("Ready.")
try:
    algo.send_ospf_broadcast({"Origine": algo.node_name, "Message": "Hello World" })
except Exception:
    algo.write_log(traceback.format_exc())


algo.write_log("broadcast sent.")
algo.send_ospf_broadcast({"Origine": algo.node_name, "Message": "Hello World 2"})
algo.send_ospf_broadcast({"Origine": algo.node_name, "Message": "Hello World 3"})
while (algo.brd_counter< algo.totalmsg):
    time.sleep(4)
    algo.write_log("waiting for all messages, received : " + str(algo.brd_counter) + " / " + str(algo.totalmsg)  )


