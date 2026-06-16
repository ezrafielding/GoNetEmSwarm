#!/usr/bin/env python3
"""Case 2 (CRDT Flood) – Satellite.

On receiving a direct SSA uplink from the ground (type=9):
  - Apply the LWW-register update locally using the timestamp from the payload.
  - Flood-broadcast the CRDT op to all ISL neighbours (type=1 reliable
    broadcast with deduplication handled by the Transceiver base class).

On receiving a CRDT relay broadcast from an ISL neighbour (type=1, lww_assign):
  - message_handler applies CRDT-aware dedup: forward iff the message updates
    local state (stale and true-duplicate messages are dropped).
  - on_message is not used for this path.

After each successful merge the catalog CSV is overwritten so the final state
is always visible in the logs.
"""

import argparse
import csv
import threading
import time
from tranceiver import Dumped, Transceiver

parser = argparse.ArgumentParser(description="SSA CRDT flood satellite")
parser.add_argument("--updates", type=int, default=1)         # accepted, unused
parser.add_argument("--update-interval", type=int, default=30) # accepted, unused
parser.add_argument("--object-id", type=str, default="1998-067A")  # accepted, unused
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

    def _apply(self, item_id: str, value, timestamp: int, source: str = "") -> bool:
        updated = False
        with self._lock:
            entry = self._store.get(item_id)
            if entry is None or timestamp >= entry["timestamp"]:
                self._store[item_id] = {"value": value, "timestamp": timestamp, "source": source}
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
    # Message handlers
    # ------------------------------------------------------------------

    def message_handler(self, message: dict, addr) -> None:
        if message.get("type") == 1 and message.get("payload", {}).get("type") == _CRDT_TYPE:
            payload   = message["payload"]
            item_id   = payload["id"]
            ts        = payload["timestamp"]
            sender    = message["sender"]

            with self._lock:
                current = self._store.get(item_id)
            local_ts  = current["timestamp"] if current else -1
            local_src = current.get("source", "") if current else ""

            if ts < local_ts:
                self.write_log_debug(
                    f"CRDT_OLD id={item_id} ts={ts}<{local_ts} — dropped", "SsaCrdtSat"
                )
                self.add_dmp_journal(message, addr[0])
                raise Dumped()
            elif ts == local_ts and local_src == sender:
                self.write_log_debug(
                    f"CRDT_DUP id={item_id} ts={ts} origin={sender} — dropped", "SsaCrdtSat"
                )
                self.add_dmp_journal(message, addr[0])
                raise Dumped()
            else:
                self.add_rcv_journal(message, addr[0])
                self._apply(item_id, payload["value"], ts, source=sender)
                self.transmit(message, addr[0])
        else:
            super().message_handler(message, addr)

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
            self._apply(item_id, value, timestamp, source=self.node_name)
            self.send_broadcast({
                "type":      _CRDT_TYPE,
                "id":        item_id,
                "value":     value,
                "timestamp": timestamp,
            })

        # type=1 with lww_assign is fully handled in message_handler (apply + relay)


algo = SsaCrdtSat()
algo.start()
while True:
    time.sleep(10)
