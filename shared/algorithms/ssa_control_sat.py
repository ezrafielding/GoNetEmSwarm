#!/usr/bin/env python3
"""Case 1 (Control) – Satellite.

Receives direct SSA uplinks from the ground (type=9).  Applies LWW merge
(keeps the highest-timestamp value per item) and writes a catalog CSV after
each update.  No ISL forwarding occurs.
"""

import argparse
import csv
import os
import threading
import time
from tranceiver import Transceiver

parser = argparse.ArgumentParser(description="SSA control satellite")
parser.add_argument("--updates", type=int, default=1)   # accepted but unused
args = parser.parse_args()


class ControlSat(Transceiver):

    def __init__(self):
        super().__init__()
        self._store: dict[str, dict] = {}
        self._lock  = threading.Lock()
        self._csv_path = "/logs/catalog_" + self.node_name + ".csv"

    def _apply(self, item_id: str, value, timestamp: int) -> None:
        updated = False
        with self._lock:
            entry = self._store.get(item_id)
            if entry is None or timestamp > entry["timestamp"]:
                self._store[item_id] = {"value": value, "timestamp": timestamp}
                updated = True
        if updated:
            self.write_log_debug(f"UPD id={item_id} ts={timestamp}", "ControlSat")
            self._write_csv()

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

    def on_message(self, data: dict, addr: str) -> None:
        if data.get("type") == 9:
            payload = data.get("payload", {})
            self._apply(
                payload["id"],
                payload["value"],
                payload["timestamp"],
            )


algo = ControlSat()
algo.start()
while True:
    time.sleep(10)
