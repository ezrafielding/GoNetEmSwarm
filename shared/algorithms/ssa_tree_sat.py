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
from tranceiver import Dumped
from tranceiver_tree import Tranceiver_with_mono_tree

parser = argparse.ArgumentParser(description="SSA CRDT tree satellite")
parser.add_argument("--updates", type=int, default=1)         # accepted, unused
parser.add_argument("--update-interval", type=int, default=30) # accepted, unused
parser.add_argument("--object-id", type=str, default="1998-067A")  # accepted, unused
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

    def _apply(self, item_id: str, value, timestamp: int, source: str = "") -> bool:
        """Apply a LWW update.  Uses >= so same-timestamp ties replace (last writer wins).
        Returns True if local state changed."""
        updated = False
        with self._lock:
            entry = self._store.get(item_id)
            if entry is None or timestamp >= entry["timestamp"]:
                self._store[item_id] = {"value": value, "timestamp": timestamp, "source": source}
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
    # Message handlers
    # ------------------------------------------------------------------

    def message_handler(self, message: dict, addr) -> None:
        """Override for type=2: decide whether to forward before touching local state.

        Forward if incoming_ts >= local_ts, EXCEPT when it is a true duplicate
        (same version from the same broadcast origin).  Drop stale updates
        (incoming_ts < local_ts) so a node already at version 3 never re-forwards
        version 2.
        """
        if message.get("type") == 2 and message.get("payload", {}).get("type") == _CRDT_TYPE:
            payload = message["payload"]
            item_id = payload["id"]
            ts      = payload["timestamp"]
            sender  = message["sender"]

            with self._lock:
                current = self._store.get(item_id)
            local_ts  = current["timestamp"] if current else -1
            local_src = current.get("source", "") if current else ""

            if ts < local_ts:
                # Stale — already superseded, no node needs this version.
                self.write_log_debug(
                    f"CRDT_OLD id={item_id} ts={ts}<{local_ts} — dropped", "SsaTreeSat"
                )
                raise Dumped()
            elif ts == local_ts and local_src == sender:
                # True duplicate — same version, same broadcast origin.
                self.write_log_debug(
                    f"CRDT_DUP id={item_id} ts={ts} origin={sender} — dropped", "SsaTreeSat"
                )
                raise Dumped()
            else:
                # ts > local_ts  →  new version; apply and forward.
                # ts == local_ts, different origin  →  LWW tie: replace and forward.
                self._apply(item_id, payload["value"], ts, source=sender)
                self._forward_tree(message, addr[0])
        else:
            super().message_handler(message, addr)

    def on_message(self, data: dict, addr: str) -> None:
        msg_type = data.get("type")
        payload  = data.get("payload", {})

        if msg_type == 9:
            # Ground uplink: apply locally; only tree-broadcast if this is a new update.
            item_id   = payload["id"]
            value     = payload["value"]
            timestamp = payload["timestamp"]
            self.write_log_debug(
                f"Ground SSA uplink: id={item_id} ts={timestamp}", "SsaTreeSat"
            )
            if not self._apply(item_id, value, timestamp, source=self.node_name):
                self.write_log_debug(
                    f"type=9 stale/dup id={item_id} ts={timestamp} — skipping broadcast",
                    "SsaTreeSat",
                )
                return

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

        # type=2 with lww_assign is fully handled in message_handler (apply + forward)


algo = SsaTreeSat()
algo.start()
while True:
    time.sleep(10)
