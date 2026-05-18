#!/usr/bin/env python3
"""
Topology discovery for GonetemSwarm.

Every node:
  1. Sends UDP PROBE messages to each declared neighbour's link IP.
  2. Listens for PROBE messages from any node.
  3. Writes its discovered-neighbour set to /logs/<name>_discovery.json.

Figure generation is done separately on the host via plot_topology.py.

Run via:
  ./run_test.sh topology [--isl-only]

Output:
  shared/logs/<name>_discovery.json   — per-node probe results
"""

import argparse
import json
import os
import socket
import threading
import time

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROBE_PORT     = 5100
PROBE_INTERVAL = 0.4   # seconds between outgoing probe bursts
DURATION       = 10    # seconds of active probing
MSG_PROBE      = "PROBE"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_config():
    with open("/algorithms/node_configs.json") as f:
        all_nodes = json.load(f)
    my_name = (os.environ.get("SAT_NAME")
               or os.environ.get("GND_NAME")
               or os.environ["HOSTNAME"])
    me = all_nodes[my_name]
    return all_nodes, my_name, me


def log(name, msg):
    print(f"[{name}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Phase 1 – probe and listen
# ---------------------------------------------------------------------------

def run_discovery(my_name, me, isl_only=False):
    received_from = set()
    lock = threading.Lock()
    stop_event = threading.Event()

    def receiver():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", PROBE_PORT))
        sock.settimeout(1.0)
        while not stop_event.is_set():
            try:
                data, _ = sock.recvfrom(1024)
                msg = json.loads(data.decode())
                if msg.get("type") == MSG_PROBE:
                    with lock:
                        received_from.add(msg["name"])
            except socket.timeout:
                continue
            except Exception:
                continue
        sock.close()

    rx = threading.Thread(target=receiver, daemon=True)
    rx.start()

    probe = json.dumps({"type": MSG_PROBE, "name": my_name}).encode()
    tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    all_links = me["neighbors"] + ([] if isl_only else me.get("ground_communication", []))
    deadline = time.time() + DURATION
    while time.time() < deadline:
        for nb in all_links:
            try:
                tx_sock.sendto(probe, (nb["link_ip"], PROBE_PORT))
            except Exception:
                pass
        time.sleep(PROBE_INTERVAL)
    tx_sock.close()

    time.sleep(1.0)
    stop_event.set()
    rx.join(timeout=3)

    with lock:
        return sorted(received_from)


# ---------------------------------------------------------------------------
# Phase 2 – write per-node result
# ---------------------------------------------------------------------------

def write_result(my_name, me, discovered, isl_only=False):
    declared = ([nb["name"] for nb in me["neighbors"]]
                + ([] if isl_only else [nb["name"] for nb in me.get("ground_communication", [])]))
    result = {
        "name":                 my_name,
        "id":                   me["id"],
        "declared_neighbors":   declared,
        "discovered_neighbors": discovered,
    }
    os.makedirs("/logs", exist_ok=True)
    path = f"/logs/{my_name}_discovery.json"
    with open(path, "w") as f:
        json.dump(result, f, indent=2)
    log(my_name, f"wrote {path}")
    log(my_name, f"  declared  : {result['declared_neighbors']}")
    log(my_name, f"  discovered: {result['discovered_neighbors']}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="GonetemSwarm topology discovery")
    parser.add_argument("--isl-only", action="store_true",
        help="Probe ISL links only; ignore ground-station links")
    args = parser.parse_args()

    all_nodes, my_name, me = load_config()

    log(my_name, f"starting discovery (duration={DURATION}s, isl_only={args.isl_only}, "
                 f"neighbours={[nb['name'] for nb in me['neighbors']]})")

    discovered = run_discovery(my_name, me, isl_only=args.isl_only)
    write_result(my_name, me, discovered, isl_only=args.isl_only)
    log(my_name, "discovery complete")


if __name__ == "__main__":
    main()
