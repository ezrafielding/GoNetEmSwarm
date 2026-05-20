#!/usr/bin/env python3
"""Case 2 (CRDT Flood) – Satellite.

On receiving a direct SSA uplink from the ground (type=9):
  - Apply the LWW-register update locally using the timestamp from the payload.
  - Flood-broadcast the CRDT op to all ISL neighbours (type=1 reliable
    broadcast with deduplication handled by the Transceiver base class).

On receiving a CRDT relay broadcast from an ISL neighbour (type=1, lww_assign):
  - Relay was already forwarded by message_handler before on_message is called.
  - Apply LWW merge locally.

After each successful merge the catalog CSV is overwritten so the final state
is always visible in the logs.
"""

import argparse
import csv
import threading
import time
from tranceiver import Transceiver

parser = argparse.ArgumentParser(description="SSA CRDT flood satellite")
parser.add_argument("--updates", type=int, default=1)         # accepted, unused
parser.add_argument("--update-interval", type=int, default=30) # accepted, unused
args = parser.parse_args()

_CRDT_TYPE = "lww_assign"


class SsaCrdtSat(Transceiver):

    def __init__(self):
        super().__init__()
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
            self.write_log_debug(f"CRDT_UPD id={item_id} ts={timestamp}", "SsaCrdtSat")
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
            # Ground uplink: apply locally and flood-broadcast.
            item_id   = payload["id"]
            value     = payload["value"]
            timestamp = payload["timestamp"]
            self.write_log_debug(
                f"Ground SSA uplink: id={item_id} ts={timestamp}", "SsaCrdtSat"
            )
            self._apply(item_id, value, timestamp)
            self.send_broadcast({
                "type":      _CRDT_TYPE,
                "id":        item_id,
                "value":     value,
                "timestamp": timestamp,
            })

        elif payload.get("type") == _CRDT_TYPE:
            # ISL relay: Transceiver already forwarded it; just merge locally.
            self._apply(payload["id"], payload["value"], payload["timestamp"])


algo = SsaCrdtSat()
algo.start()
while True:
    time.sleep(10)
