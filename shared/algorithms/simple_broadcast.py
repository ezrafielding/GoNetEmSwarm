from tranceiver import Transceiver
import time

# ===========================================================================
# A Simple Broadcast test for debugging purpose
# ===========================================================================


class simple_broadcast(Transceiver):
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
        self.write_log("Test broadcast service started")

    def write_log(self, log_message):
        with open(self.path_to_logs+self.node_name+".log", 'a') as file:
            file.write('\n'+log_message)

    def on_message(self, data: dict, addr: tuple):
        self.write_log("Message received with following payload :")
        self.write_log("payload = "+ str(data))
        self.write_log("From address :"+str(addr))

algo = simple_broadcast()
algo.start()
algo.write_log("Ready.")
time.sleep(15) # to try to ensure that other nodes are alive when sending the broadcast
algo.send_broadcast({"Origine": algo.node_name, "Message": "Hello World" })
algo.write_log("broadcast sent.")
time.sleep(5)

