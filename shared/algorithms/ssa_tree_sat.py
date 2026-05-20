#!/usr/bin/env python3
"""Case 3 (CRDT Tree) – Satellite.

At startup all satellites participate in building a spanning tree rooted at
sat1 (type=8 query/accept/reject messages handled by Tranceiver_with_mono_tree).

On receiving a direct SSA uplink from the ground (type=9, sat1 only):
  - Apply LWW update locally using the timestamp from the payload.
  - Tree-broadcast the CRDT op via send_tree_broadcast (type=2 messages routed
    only along parent/child tree edges – no redundant copies).

On receiving a tree-relay message (type=2, lww_assign payload):
  - Tranceiver_with_mono_tree.message_handler has already forwarded it down the
    tree before on_message is called.
  - Apply LWW merge locally.

After each successful merge the catalog CSV is overwritten.
"""

import argparse
import csv
import os
import threading
import time
from tranceiver_tree import Tranceiver_with_mono_tree

parser = argparse.ArgumentParser(description="SSA CRDT tree satellite")
parser.add_argument("--updates", type=int, default=1)         # accepted, unused
parser.add_argument("--update-interval", type=int, default=30) # accepted, unused
args = parser.parse_args()

_CRDT_TYPE = "lww_assign"
_TREE_ROOT = "sat1"   # must match TARGET_SAT in ssa_tree_gnd.py
_TREE_WAIT = 30       # max seconds to wait for tree before aborting


class SsaTreeSat(Tranceiver_with_mono_tree):

    def __init__(self):
        is_root = os.environ["HOSTNAME"] == _TREE_ROOT
        super().__init__(is_root=is_root)
        self._store: dict[str, dict] = {}
        self._lock  = threading.Lock()
        self._csv_path = "/logs/catalog_" + self.node_name + ".csv"

    # ------------------------------------------------------------------
    # LWW merge
    # ------------------------------------------------------------------

    def _apply(self, item_id: str, value, timestamp: int) -> bool:
        updated = False
        with self._lock:
            entry = self._store.get(item_id)
            if entry is None or timestamp > entry["timestamp"]:
                self._store[item_id] = {"value": value, "timestamp": timestamp}
                updated = True
        if updated:
            self.write_log_debug(f"CRDT_UPD id={item_id} ts={timestamp}", "SsaTreeSat")
            self._write_csv()
        return updated

    def _write_csv(self) -> None:
        with self._lock:
            snapshot = sorted(self._store.items())
        with open(self._csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["item_id", "object_name", "epoch", "version"])
            for item_id, entry in snapshot:
                val      = entry["value"]
                obj_name = val.get("OBJECT_NAME", item_id) if isinstance(val, dict) else str(val)
                epoch    = val.get("EPOCH", "")            if isinstance(val, dict) else ""
                writer.writerow([item_id, obj_name, epoch, entry["timestamp"]])

    # ------------------------------------------------------------------
    # Message handler
    # ------------------------------------------------------------------

    def on_message(self, data: dict, addr: str) -> None:
        msg_type = data.get("type")
        payload  = data.get("payload", {})

        if msg_type == 9:
            # Ground uplink to root: wait for tree then tree-broadcast.
            item_id   = payload["id"]
            value     = payload["value"]
            timestamp = payload["timestamp"]
            self.write_log_debug(
                f"Ground SSA uplink: id={item_id} ts={timestamp}", "SsaTreeSat"
            )
            self._apply(item_id, value, timestamp)

            deadline = time.monotonic() + _TREE_WAIT
            while not self.tree_finished:
                if time.monotonic() > deadline:
                    self.write_log_debug(
                        "Tree not ready after timeout – aborting broadcast",
                        "SsaTreeSat",
                    )
                    return
                time.sleep(0.5)

            self.send_tree_broadcast({
                "type":      _CRDT_TYPE,
                "id":        item_id,
                "value":     value,
                "timestamp": timestamp,
            })

        elif payload.get("type") == _CRDT_TYPE:
            # Tree relay (type=2): already forwarded; just merge locally.
            self._apply(payload["id"], payload["value"], payload["timestamp"])


algo = SsaTreeSat()
algo.start()
while True:
    time.sleep(10)
