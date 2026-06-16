#!/usr/bin/env python3
"""Case 4 (Concurrent CRDT Tree) – Ground station.

Injects N sequential updates of the same tracked object into N satellite
start-points with no delay between sends, simulating concurrent mid-dissemination
update pressure.

Start-points are chosen automatically by spreading N indices evenly across the
full satellite range (sat1 … sat66):
  N=1  → sat1
  N=3  → sat1, sat34, sat66
  N=5  → sat1, sat17, sat33, sat49, sat66
  N=10 → sat1, sat8, sat15, sat22, sat29, sat36, sat43, sat50, sat57, sat66

Each start-point receives one type=9 uplink carrying an incrementing version:
  sat_A → ts=1,  sat_B → ts=2,  … , sat_N → ts=N

All sends are fired sequentially with no sleep between them.  Because timestamps
are strictly increasing, the network converges to ts=N everywhere.

Log format (gnd_concurrent_tree.log):
    <wall_clock>|SNT|<target_node>|<msg_counter>|id=<id>|ts=<timestamp>
"""

import argparse
import json
import os
import socket
import time

CONFIG_PATH  = "/algorithms/node_configs.json"
DATA_PATH    = "/algorithms/data/test.json"
PORT         = 5007
TOTAL_SATS   = 66   # sat1 … sat66


def select_endpoints(n: int) -> list[str]:
    """Return n satellite names spread evenly across sat1 … sat{TOTAL_SATS}."""
    if n == 1:
        return ["sat1"]
    return [
        f"sat{1 + round(i * (TOTAL_SATS - 1) / (n - 1))}"
        for i in range(n)
    ]


parser = argparse.ArgumentParser(description="Concurrent SSA CRDT tree ground station")
parser.add_argument("--updates", type=int, default=3,
                    help="number of start-points / updates to inject (default: 3)")
parser.add_argument("--update-interval", type=int, default=30,
                    help="seconds to wait after all sends for propagation (default: 30)")
parser.add_argument("--object-id", type=str, default="1998-067A",
                    help="OBJECT_ID to use from test.json; sequential entries for that "
                         "object are sent in order, one per start-point "
                         "(default: 1998-067A — ISS)")
args = parser.parse_args()

node_name = os.environ["HOSTNAME"]
log_path  = "/logs/gnd_concurrent_tree.log"
endpoints = select_endpoints(args.updates)

with open(CONFIG_PATH) as f:
    cfg = json.load(f)
with open(DATA_PATH) as f:
    all_entries = json.load(f)

object_entries = [e for e in all_entries if str(e["OBJECT_ID"]) == args.object_id]
if not object_entries:
    raise SystemExit(f"ERROR: no entries found for OBJECT_ID '{args.object_id}' in {DATA_PATH}")
if len(object_entries) < args.updates:
    raise SystemExit(
        f"ERROR: only {len(object_entries)} entries for '{args.object_id}', "
        f"but --updates {args.updates} requested"
    )

item_id = args.object_id

endpoint_ips: dict[str, str] = {}
for ep in endpoints:
    try:
        endpoint_ips[ep] = next(
            n["link_ip"] for n in cfg[node_name]["neighbors"] if n["name"] == ep
        )
    except StopIteration:
        raise SystemExit(f"ERROR: {ep} is not a neighbour of {node_name} in node_configs.json")


def log(msg: str) -> None:
    with open(log_path, "a") as f:
        f.write(f"\n{time.time():.4f}|{msg}")


log(
    f"START|endpoints={','.join(endpoints)}"
    f"|updates={args.updates}|interval={args.update_interval}s"
    f"|object={item_id}"
)
time.sleep(20)  # wait for spanning tree to build across all satellites

for update_idx, (ep, ip) in enumerate(endpoint_ips.items()):
    ts          = update_idx + 1                  # ts=1 … ts=N
    gp_entry    = object_entries[update_idx]      # sequential GP entry for this object
    msg_counter = update_idx + 1

    msg = {
        "type":    9,
        "sender":  node_name,
        "counter": msg_counter,
        "payload": {
            "msg_type":  "ssa_update",
            "id":        item_id,
            "value":     gp_entry,
            "timestamp": ts,
        },
    }
    data = json.dumps(msg).encode()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(data, (ip, PORT))
    log(f"SNT|{ep}|{msg_counter}|id={item_id}|ts={ts}|epoch={gp_entry.get('EPOCH', '')}")
    # No sleep between sends — concurrent injection is the point of this test.

time.sleep(args.update_interval)
log(f"DONE|final_version={args.updates}")
