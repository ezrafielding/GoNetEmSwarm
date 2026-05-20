#!/usr/bin/env python3
"""Case 3 (CRDT Tree) – Ground station.

Identical behaviour to ssa_crdt_gnd.py but waits longer before the first send
to give the spanning tree time to fully build across all satellites.

Total GS messages = --updates (one uplink per update regardless of swarm size).

Log format (gnd_ssa_tree.log):
    <wall_clock>|SNT|<target_node>|<counter>|id=<id>|ts=<timestamp>
"""

import argparse
import json
import os
import socket
import time

CONFIG_PATH = "/algorithms/node_configs.json"
DATA_PATH   = "/algorithms/data/test.json"
PORT        = 5007
TARGET_SAT  = "sat1"   # must match _TREE_ROOT in ssa_tree_sat.py

parser = argparse.ArgumentParser(description="SSA CRDT tree ground station")
parser.add_argument("--updates", type=int, default=1,
                    help="number of catalog entries to send (default: 1)")
parser.add_argument("--update-interval", type=int, default=30,
                    help="seconds between consecutive updates to allow propagation (default: 30)")
args = parser.parse_args()

node_name = os.environ["HOSTNAME"]
log_path  = "/logs/gnd_ssa_tree.log"

with open(CONFIG_PATH) as f:
    cfg = json.load(f)
with open(DATA_PATH) as f:
    entries = json.load(f)

target_ip = next(
    n["link_ip"] for n in cfg[node_name]["neighbors"] if n["name"] == TARGET_SAT
)


def log(msg: str) -> None:
    with open(log_path, "a") as f:
        f.write(f"\n{time.time():.4f}|{msg}")


log(f"START|target={TARGET_SAT}|updates={args.updates}|interval={args.update_interval}s")
time.sleep(20)  # extra time for spanning tree negotiation to complete

counters: dict[str, int] = {}

for update_idx in range(args.updates):
    gp_entry = entries[update_idx % len(entries)]
    item_id  = str(gp_entry["OBJECT_ID"])
    counters[item_id] = counters.get(item_id, 0) + 1
    timestamp = counters[item_id]

    msg  = {
        "type":    9,
        "sender":  node_name,
        "counter": update_idx + 1,
        "payload": {
            "msg_type":  "ssa_update",
            "id":        item_id,
            "value":     gp_entry,
            "timestamp": timestamp,
        },
    }
    data = json.dumps(msg).encode()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(data, (target_ip, PORT))

    log(f"SNT|{TARGET_SAT}|{update_idx + 1}|id={item_id}|ts={timestamp}")

    if update_idx < args.updates - 1:
        time.sleep(args.update_interval)

time.sleep(args.update_interval)
log("DONE")
