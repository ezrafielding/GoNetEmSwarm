import json
import os

my_id = os.environ["GND_ID"]

all_node = {}
with open("/algorithms/node_configs.json") as f:
    all_nodes = json.load(f)

loopback_ip = all_nodes[list(all_nodes.keys())[0]]["ground_communication"][my_id-1]["loopback_ip"]
os.system("ip a add "+ loopback_ip +" dev lo")

for sat_name in all_node.keys():
    sat_info = all_node[sat_name]
    os.system("ip a add "+ sat_info["ground_communication"][my_id-1]["link_ip"] +" dev eth"+ sat_name[3:] )

