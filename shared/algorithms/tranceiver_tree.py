import time
from tranceiver import Transceiver
from tranceiver_queue import Transceiver_queue
from tranceiver_queue import NotReady


# ===========================================================================
# Tranceiver compatible Spanning Tree implementation
# ===========================================================================
class UnfinishedTreeException(Exception):
    def __init__(self):
        self.message = "Still working on tree creation, please retry later"
        super().__init__(self.message)

class BadlyWritenQuery(Exception):
    def __init__(self):
        self.message = "Still working on tree creation, please retry later"
        super().__init__(self.message)

class Tranceiver_with_mono_tree(Transceiver):


    """
    Introduce the use of 2 new types of messages :
    message["type"] = 8 : tree creation related message (Query and request)
    with the following payload:
    message["payload"] : {
        "Answer": [
            | "Accept" -> Message is a Positive Answer to a previous Query
            | "Reject" -> Message is a Negative answer to a previous Query
            | None     -> Message is a Query]
        }
    """

    def __init__(self, is_root: bool = False):
        super().__init__()
        self.parent_ip = None
        self.childs_ip = []
        self.irrel_ip = []
        self.i_am_root = is_root
        self.neighbors_ip = list(self.neighbors_addr_dict.keys())
        self.indet_ip = list(self.neighbors_ip)
        self.tree_finished = False

    # JE HAIS PYTHON
    # def write_log_debug(self, log_message):
    #     super().write_log_debug(log_message, "Basic_Tree_Mono")

    def terminate(self):
        super().write_log_debug("My work here is done.", "Basic_Tree_Mono")
        super().write_log_debug("Final state : { parent_ip : " + self.parent_ip + "| childs : " + str(self.childs_ip) + "| irrel : "+ str(self.irrel_ip) + "}. ")
        self.tree_finished = True

    def send_query(self, name, ac7pt : str = None):
        self.increment_counter()
        message = {
            "type": 8,
            "sender": self.node_name,
            "counter": self.msg_counter,
            "payload" : {"Accept" : ac7pt}
        }
        self.send_packets(message, self.neighbors_addr_dict[name])

    def _forward_tree(self, message: dict, sender_ip: str) -> None:
        """Relay a type=2 message along tree edges, skipping the interface it arrived on."""
        while not self.tree_finished:
            super().write_log_debug("waiting for tree before relay ...", "Basic_Tree_Mono")
            time.sleep(2)
        for node, link_ip in self.neighbors_addr_dict.items():
            if sender_ip == link_ip:
                super().write_log_debug("message not retransmited to: " + node, "Basic_Tree_Mono")
            elif node == self.parent_ip:
                self.send_packets(message, link_ip, True)
                super().write_log_debug("message transmited to parent : " + node, "Basic_Tree_Mono")
            elif node in self.childs_ip:
                self.send_packets(message, link_ip, True)
                super().write_log_debug("message transmited to child : " + node, "Basic_Tree_Mono")
            else:
                super().write_log_debug("message not retransmited to: " + node, "Basic_Tree_Mono")

    def send_tree_broadcast(self, payload: dict):
        super().write_log_debug("Sending broadcast", "Basic_Tree_Mono")
        while not self.tree_finished:
            raise UnfinishedTreeException()
            super().write_log_debug("unable to send broadcast, tree isn't finished, waiting ...", "Basic_Tree_Mono")
            super().write_log_debug(str(len(self.indet_ip)) + " neighbors with unknown relation remaining", "Basic_Tree_Mono")
            time.sleep(2)
        self.increment_counter()
        message = {
            "type": 2,
            "sender": self.node_name,
            "counter": self.msg_counter,
            "payload" : payload
        }
        if not self.i_am_root:
            self.send_packets(message, self.neighbors_addr_dict[self.parent_ip])
        for name in self.childs_ip:
            self.send_packets(message, self.neighbors_addr_dict[name])


    def start(self):
        super().write_log_debug("started", "Basic_Tree_Mono")
        super().start()
        while (not self.network_initialized):
            super().write_log_debug("waiting for network", "Basic_Tree_Mono")
            time.sleep(2)
        if self.i_am_root:
            super().write_log_debug("I am (g)Root" , "Basic_Tree_Mono")
            for neig_name in self.neighbors_ip:
                self.send_query(neig_name)
            self.parent_ip = self.node_name
            super().write_log_debug("New parent : " + self.node_name, "Basic_Tree_Mono")

    def message_handler(self, message, addr):
        match message["type"]:
            case 8: #Building tree related message
                match message["payload"]["Accept"]:
                    case None:
                        super().write_log_debug("New query received from : " + message["sender"], "Basic_Tree_Mono")
                        if not self.parent_ip:
                            super().write_log_debug("Accepting query", "Basic_Tree_Mono")
                            self.parent_ip = message["sender"]
                            super().write_log_debug("New parent : " + message["sender"], "Basic_Tree_Mono")
                            self.indet_ip.remove(message["sender"])
                            self.send_query(message["sender"], "Accept")
                            for neig_addr in self.neighbors_ip:
                                if (message["sender"] == neig_addr):#check link ip at reception, not loopback ip
                                    continue
                                self.send_query(neig_addr)
                            if not self.indet_ip:
                                self.terminate()
                        else:
                            super().write_log_debug("Refusing query", "Basic_Tree_Mono")
                            self.send_query(message["sender"], "Reject")
                    case "Accept":
                        super().write_log_debug("Query answer received from : " + message["sender"] + " Accepted.", "Basic_Tree_Mono")
                        self.childs_ip.append(message["sender"])
                        self.indet_ip.remove(message["sender"])
                        if not self.indet_ip:
                            self.terminate()
                    case "Reject":
                        super().write_log_debug("Query answer received from : " + message["sender"] + " Refused.", "Basic_Tree_Mono")
                        self.irrel_ip.append(message["sender"])
                        self.indet_ip.remove(message["sender"])
                        if not self.indet_ip:
                            self.terminate()
                    case _:
                        raise BadlyWritenQuery()

            case 2: #More message efficient ,spanning tree based broadcast.
                super().write_log_debug("Message instance received : Tree Based Broadcast, from : " + addr[0], "Basic_Tree_Mono")
                self._forward_tree(message, addr[0])

            case _:
                super().write_log_debug("Message instance received : Unknown type, falling back on tranceiver.py", "Basic_Tree_Mono")
                super().message_handler(message, addr)


#############################################################################################################################################
#                                                       WORK IN PROGRESS                                                                    #
#############################################################################################################################################
#
# class Tranceiver_with_scored_mono_tree(Transceiver_queue):
#     """
#     Like Tranceiver_with_mono_tree but with a few subtelities :
#     - Rather than only the node named 1, a arbitrary amount of nodes can attempt to create a tree
#     - Nodes get an 'selection_score:float', Merging conflict are handled by keeping the node with best 'selection_score' as root.
#     """
#
#     def __init__(self,init_score:float, is_root: bool = False):
#         super().__init__()
#         self.parent_ip = None
#         self.childs_ip = []
#         self.irrel_ip = []
#         self.i_am_root = is_root
#         self.neighbors_ip = [addrs[0] for addrs in self.neighbors_addr_list]
#         self.indet_ip = self.neighbors_ip
#         self.tree_finished = False
#         self.selection_score = init_score
#         self.parent_score = init_score
#
#     def set_selection_score(self, new_score:float):
#         self.selection_score = new_score
#
#     def get_selection_score(self):
#         return self.selection_score
#
#     def terminate(self):
#         super().write_log_debug("My work here is done.", "Tranceiver_with_scored_mono_tree")
#         super().write_log_debug("Final state : { parent_ip : " + self.parent_ip + "| childs : " + str(self.childs_ip) + "| irrel : "+ str(self.irrel_ip) + "}. ", "Tranceiver_with_scored_mono_tree")
#         super().write_log_debug("my score : " + str(self.selection_score) + "| parent score: " + str(self.parent_score) + "Correctly placed : " + str(self.parent_score>=self.selection_score) , "Tranceiver_with_scored_mono_tree")
#         self.tree_finished = True
#
#     def send_query(self, addr, ac7pt : str = None):
#         self.increment_counter()
#         message = {
#             "type": 8,
#             "sender": self.loopback_ip,
#             "counter": self.msg_counter,
#             "payload" : {"Accept" : ac7pt, "My_score":self.selection_score}
#         }
#         self.send_packets(message, addr)
#
#     def send_tree_broadcast(self, payload: dict):
#         super().write_log_debug("Sending broadcast", "Tranceiver_with_scored_mono_tree")
#         while not self.tree_finished:
#             raise UnfinishedTreeException()
#             super().write_log_debug("unable to send broadcast, tree isn't finished, waiting ...", "Tranceiver_with_scored_mono_tree")
#             super().write_log_debug(str(len(self.indet_ip)) + " neighbors with unknown relation remaining", "Tranceiver_with_scored_mono_tree")
#             time.sleep(2)
#         self.increment_counter()
#         message = {
#             "type": 2,
#             "sender": self.loopback_ip,
#             "counter": self.msg_counter,
#             "payload" : payload
#         }
#         if not self.i_am_root:
#             self.send_packets(message, self.parent_ip)
#         for addr in self.childs_ip:
#             self.send_packets(message, addr)
#
#
#     def start(self):
#         super().write_log_debug("started", "Tranceiver_with_scored_mono_tree")
#         super().start()
#         while (not self.network_initialized):
#             super().write_log_debug("waiting for network", "Tranceiver_with_scored_mono_tree")
#             time.sleep(2)
#         if self.i_am_root:
#             super().write_log_debug("I am (g)Root" , "Tranceiver_with_scored_mono_tree")
#             for neig_addr in self.neighbors_ip:
#                 self.send_query(neig_addr)
#                 super().write_log_debug("New parent : " + self.loopback_ip, "Tranceiver_with_scored_mono_tree")
#
#     def query_indet(self):
#         if self.indet_ip:
#             for addr in self.indet_ip:
#                 self.send_query(addr)
#
#     def waiting_parent(self):
#         super().write_log_debug("need to wait before handeling message : " + str(self.parent_ip == "Work In Progress"))
#         if (self.parent_ip == "Work In Progress"):
#             raise NotReady()
#
#
#     def message_handler(self, message, addr):
#         match message["type"]:
#             case 8: #Building tree related message
#                 super().write_log_debug("treating : " + str(message), "Tranceiver_with_scored_mono_tree")
#                 match message["payload"]["Accept"]:
#                     case None:
#                         self.waiting_parent()
#                         super().write_log_debug("New query received from : " + message["sender"], "Tranceiver_with_scored_mono_tree")
#                         if not self.parent_ip:
#                             super().write_log_debug("Accepting query", "Tranceiver_with_scored_mono_tree")
#                             self.send_query(message["sender"], "Accept")
#                             self.parent_ip = "Work In Progress"
#                         else:
#                             super().write_log_debug("Refusing query", "Tranceiver_with_scored_mono_tree")
#                             self.send_query(message["sender"], "Reject")
#                     case "Adopted":
#                         super().write_log_debug("Adoption query received from : " + message["sender"] + " he is my new parent.", "Tranceiver_with_scored_mono_tree")
#                         self.parent_ip = message["sender"]
#                         self.indet_ip.remove(message["sender"])
#                         self.parent_score = message["payload"]["My_score"]
#                         self.query_indet()
#                     case "Rooted":
#                         #Need to be modified in order to accept merging differents tree (precedent parent possible)
#                         self.i_am_root = True
#                         self.parent_ip = self.loopback_ip
#                         self.childs_ip.append(message["sender"])
#                         self.query_indet()
#                     case "Accept":
#                         super().write_log_debug("Query answer received from : " + message["sender"] + " Accepted.", "Tranceiver_with_scored_mono_tree")
#                         node_score = message["payload"]["My_score"]
#                         self.indet_ip.remove(message["sender"])
#                         if node_score <= self.selection_score:
#                             self.childs_ip.append(message["sender"])
#                             self.send_query(message["sender"], "Adopted")
#                         elif self.i_am_root:
#                             self.send_query(message["sender"], "Rooted")
#                             self.i_am_root = False
#                             self.parent_ip = message["sender"]
#                             self.parent_score = node_score
#                         else:
#                             self.waiting_parent()
#                             self.send_packets(message, self.parent_ip)
#                             if self.parent_score >= message["payload"]["My_score"]:
#                                 self.parent_ip = message["sender"]
#                                 self.parent_score = node_score
#                             else:
#                                 self.irrel_ip.append(message["sender"])
#                     case "Reject":
#                         super().write_log_debug("Query answer received from : " + message["sender"] + " Refused.", "Tranceiver_with_scored_mono_tree")
#                         self.irrel_ip.append(message["sender"])
#                         self.indet_ip.remove(message["sender"])
#
#                     case _:
#                         raise BadlyWritenQuery()
#
#                 if not self.indet_ip:
#                     self.terminate()
#
#             case 2: #More message efficient ,spanning tree based broadcast.
#                 super().write_log_debug("Message instance received : Tree Based Broadcast, from : " + addr[0], "Tranceiver_with_scored_mono_tree")
#                 if not self.tree_finished:
#                     super().write_log_debug("unable to transfert broadcast, tree isn't finished, sending brd message back into queue", "Tranceiver_with_scored_mono_tree")
#                     super().write_log_debug(str(len(self.indet_ip)) + " neighbors with unknown relation remaining", "Tranceiver_with_scored_mono_tree")
#                     raise NotReady()
#                 for neig_addr in self.neighbors_addr_list:
#                     if (addr[0] == neig_addr[1]):#check link ip at reception, not loopback ip
#                         super().write_log_debug("message not retransmited to lo : "+ neig_addr[0], "Tranceiver_with_scored_mono_tree")
#                     elif (neig_addr[0] == self.parent_ip):
#                         self.send_packets(message, neig_addr[0], True)
#                         super().write_log_debug("message transmited to parent : "+ neig_addr[0], "Tranceiver_with_scored_mono_tree")
#                     elif (neig_addr[0] in self.childs_ip):
#                         self.send_packets(message, neig_addr[0], True)
#                         super().write_log_debug("message transmited to child : "+ neig_addr[0], "Tranceiver_with_scored_mono_tree")
#                     else:
#                         super().write_log_debug("message not retransmited to lo : "+ neig_addr[0], "Tranceiver_with_scored_mono_tree")
#
#             case _:
#                 super().write_log_debug("Message instance received : Unknown type, falling back on tranceiver.py", "Tranceiver_with_scored_mono_tree")
#                 super().message_handler(message, addr)
#
