#!/usr/bin/env python3
"""Case 1 (Control) – Ground station.

Sends --updates catalog entries to EVERY satellite, one satellite at a time
with INTERVAL seconds between each.  Each entry carries a per-item monotonic
timestamp so the satellites can apply LWW correctly when the same object ID
appears more than once.

Total GS messages = --updates × number_of_satellites.

Log format (gnd_ssa_control.log):
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
INTERVAL    = 5   # seconds between satellite uplinks

parser = argparse.ArgumentParser(description="SSA control ground station")
parser.add_argument("--updates", type=int, default=1,
                    help="number of catalog entries to send to each satellite (default: 1)")
args = parser.parse_args()

node_name = os.environ["HOSTNAME"]
log_path  = "/logs/gnd_ssa_control.log"

with open(CONFIG_PATH) as f:
    cfg = json.load(f)
with open(DATA_PATH) as f:
    entries = json.load(f)

neighbors = cfg[node_name]["neighbors"]


def log(msg: str) -> None:
    with open(log_path, "a") as f:
        f.write(f"\n{time.time():.4f}|{msg}")


log(f"START|neighbors={len(neighbors)}|updates={args.updates}")
time.sleep(5)  # let satellites initialize their transceivers

# Per-item monotonic counter – incremented each time the same object ID is sent.
# This is the LWW timestamp the satellites will use for merging.
counters: dict[str, int] = {}
total_sent = 0

# For each update round, send that entry to every satellite in order.
for update_idx in range(args.updates):
    gp_entry = entries[update_idx % len(entries)]
    item_id  = str(gp_entry["OBJECT_ID"])
    counters[item_id] = counters.get(item_id, 0) + 1
    timestamp = counters[item_id]

    for neigh in neighbors:
        target_ip   = neigh["link_ip"]
        target_name = neigh["name"]
        total_sent += 1

        msg  = {
            "type":    9,
            "sender":  node_name,
            "counter": total_sent,
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

        log(f"SNT|{target_name}|{total_sent}|id={item_id}|ts={timestamp}")
        time.sleep(INTERVAL)

log(f"DONE|total_sent={total_sent}")
