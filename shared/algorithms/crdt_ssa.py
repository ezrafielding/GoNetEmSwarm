from tranceiver import Transceiver
import argparse
import csv
import json
import threading
import time

_CATALOG_MSG_TYPE = "lww_assign"
_GP_UPDATE_INTERVAL = 5  # seconds between CRDT updates from ground node
_DATA_PATH = "/algorithms/data/test.json"


def _fmt(value):
    return " " + str(value) + " |"


class Catalog(Transceiver):
    """CRDT-based distributed key-value catalog.

    Each entry is an op-based Last-Write-Wins Register:

        payload  X x, timestamp t
        initial  ⊥, 0
        query    value()      → x
        update   assign(x')
                   atSource   → t' = t + 1   (per-item integer counter)
                   downstream(x', t') → if t < t' then x, t := x', t'
    """

    def __init__(self):
        super().__init__()
        self._store: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.path_to_crdt_log = "/logs/crdt_" + self.node_name + ".log"
        self.path_to_catalog_csv = "/logs/catalog_" + self.node_name + ".csv"
        self._write_crdt_header()
        self._write_catalog_csv()

    # ------------------------------------------------------------------
    # CRDT metrics log  (separate from the transceiver debug/journal logs)
    # ------------------------------------------------------------------
    # Events:
    #   CRDT_SND  ground node sent a new assign op
    #   CRDT_RCV  this node received a broadcast carrying a CRDT op
    #             (may fire multiple times for the same op if relayed by
    #             several neighbours; use CRDT_UPD for convergence time)
    #   CRDT_UPD  LWW check passed — store was actually updated (first
    #             delivery of a new version; use this for convergence)

    def _write_crdt_header(self):
        with open(self.path_to_crdt_log, 'a') as f:
            f.write('\n' +
                    _fmt("Wall_Clock") +
                    _fmt("Local_Time") +
                    _fmt("Event") +
                    _fmt("Item_ID") +
                    _fmt("CRDT_TS") +
                    _fmt("From_IP"))

    def _write_catalog_csv(self):
        """Overwrite the catalog CSV with the current snapshot of every entry."""
        with self._lock:
            snapshot = sorted(self._store.items())
        with open(self.path_to_catalog_csv, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["item_id", "object_name", "epoch", "version"])
            for item_id, entry in snapshot:
                val = entry["value"]
                obj_name = val.get("OBJECT_NAME", item_id) if isinstance(val, dict) else str(val)
                epoch = val.get("EPOCH", "") if isinstance(val, dict) else ""
                writer.writerow([item_id, obj_name, epoch, entry["timestamp"]])

    def _log_crdt(self, event: str, item_id: str, crdt_ts: int, from_ip: str = "-"):
        entry = (_fmt(f"{time.time():.4f}") +
                 _fmt(self.get_local_time()) +
                 _fmt(event) +
                 _fmt(item_id) +
                 _fmt(crdt_ts) +
                 _fmt(from_ip))
        with open(self.path_to_crdt_log, 'a') as f:
            f.write('\n' + entry[:-2])

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def value(self, item_id: str):
        """Return the current value of *item_id*, or None if not present."""
        with self._lock:
            entry = self._store.get(item_id)
            return entry["value"] if entry else None

    def items(self) -> dict:
        """Return a snapshot of the entire catalog as {id: value}."""
        with self._lock:
            return {k: v["value"] for k, v in self._store.items()}

    def __getitem__(self, item_id: str):
        result = self.value(item_id)
        if result is None and item_id not in self:
            raise KeyError(item_id)
        return result

    def __contains__(self, item_id: str) -> bool:
        with self._lock:
            return item_id in self._store

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def assign(self, item_id: str, value) -> None:
        """Assign *value* to *item_id* and broadcast the op to the swarm.

        The timestamp is a per-item integer incremented at the source;
        it is never derived from wall-clock time.
        """
        with self._lock:
            entry = self._store.get(item_id)
            timestamp = (entry["timestamp"] if entry else 0) + 1
            self._store[item_id] = {"value": value, "timestamp": timestamp}
        self._log_crdt("CRDT_SND", item_id, timestamp)
        self._write_catalog_csv()
        self.write_log_debug(
            "CRDT assign: id=" + item_id + " ts=" + str(timestamp), "Catalog"
        )
        self.send_broadcast({
            "type":      _CATALOG_MSG_TYPE,
            "id":        item_id,
            "value":     value,
            "timestamp": timestamp,
        })

    def __setitem__(self, item_id: str, value) -> None:
        self.assign(item_id, value)

    # ------------------------------------------------------------------
    # Downstream handler (called by Transceiver's RX thread)
    # ------------------------------------------------------------------

    def on_message(self, data: dict, addr: str) -> None:
        # data is the full transceiver message; CRDT fields live in payload
        payload = data.get("payload", {})
        if payload.get("type") != _CATALOG_MSG_TYPE:
            return
        item_id  = payload["id"]
        value    = payload["value"]
        crdt_ts  = payload["timestamp"]
        self._log_crdt("CRDT_RCV", item_id, crdt_ts, addr)
        self.write_log_debug(
            "CRDT received: id=" + item_id + " ts=" + str(crdt_ts) + " from=" + addr,
            "Catalog",
        )
        self._apply(item_id, value, crdt_ts)

    # ------------------------------------------------------------------
    # Internal merge
    # ------------------------------------------------------------------

    def _apply(self, item_id: str, value, timestamp: int) -> None:
        """Apply a downstream op: update only if the incoming timestamp wins."""
        updated = False
        with self._lock:
            entry = self._store.get(item_id)
            if entry is None or timestamp > entry["timestamp"]:
                self._store[item_id] = {"value": value, "timestamp": timestamp}
                updated = True
        if updated:
            self._log_crdt("CRDT_UPD", item_id, timestamp)
            self._write_catalog_csv()
            self.write_log_debug(
                "CRDT store updated: id=" + item_id + " ts=" + str(timestamp),
                "Catalog",
            )


# ===========================================================================
# Entry point
# ===========================================================================

def _load_gp_entries(path: str = _DATA_PATH) -> list:
    with open(path) as f:
        return json.load(f)


parser = argparse.ArgumentParser(description="CRDT SSA catalog")
parser.add_argument(
    "--ground", metavar="NODE", default="gnd1",
    help="name of the ground node that originates GP updates (default: gnd1)",
)
args = parser.parse_args()

catalog = Catalog()
catalog.start()

while not catalog.network_initialized:
    time.sleep(1)

catalog.write_log_debug("Network initialized, catalog ready", "Catalog")

if catalog.node_name == args.ground:
    gp_entries = _load_gp_entries()
    catalog.write_log_debug(
        "Ground node (" + args.ground + "): loaded " + str(len(gp_entries)) +
        " GP entries, sending one every " + str(_GP_UPDATE_INTERVAL) + "s",
        "Catalog",
    )
    idx = 0
    while True:
        entry = gp_entries[idx % len(gp_entries)]
        item_id = str(entry["OBJECT_ID"])
        catalog.assign(item_id, entry)
        idx += 1
        time.sleep(_GP_UPDATE_INTERVAL)
else:
    # Satellite nodes: keep the transceiver alive to relay broadcasts and
    # accumulate CRDT state via on_message / _apply.
    while True:
        time.sleep(5)
