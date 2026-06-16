#!/usr/bin/env python3
"""Analyze SSA dissemination test results and print a comparison table.

Usage:
    python3 analyze_ssa.py <control_dir> <crdt_dir> <tree_dir> [<concurrent_dir>]

Each directory should be an archive created by:
    ./run_test.sh archive <name>

Metric definitions
------------------
GS messages  : lines with event=SNT in gnd_ssa_*.log files.
               Each line represents one ground-to-satellite uplink packet.

ISL messages : lines with event=SNT or event=TRA in journal_sat*.log files.
               SNT = satellite originated a new broadcast.
               TRA = satellite relayed an existing broadcast along an ISL link.
               Note: for Case 3 this includes type=8 spanning-tree setup
               messages (one-time overhead; amortized across many updates in
               practice). The "(data only)" row excludes those.

Convergence check
-----------------
Reads catalog_sat*.csv from each archive and verifies that every satellite
that wrote a CSV ended up with an identical catalog (same item_ids, same
versions). Reports any divergence found.
"""

import csv
import glob
import os
import sys
from collections import defaultdict


# ---------------------------------------------------------------------------
# Message counting
# ---------------------------------------------------------------------------

def count_gnd_messages(directory: str, log_glob: str = "gnd_ssa_*.log") -> int:
    count = 0
    for path in glob.glob(os.path.join(directory, log_glob)):
        with open(path) as f:
            for line in f:
                parts = line.strip().split("|")
                if len(parts) >= 2 and parts[1] == "SNT":
                    count += 1
    return count


def count_isl_messages(directory: str, exclude_type8: bool = False) -> int:
    count = 0
    for path in glob.glob(os.path.join(directory, "journal_sat*.log")):
        with open(path) as f:
            for line in f:
                parts = line.strip().split("|")
                if len(parts) < 2:
                    continue
                if parts[1] not in ("SNT", "TRA"):
                    continue
                if exclude_type8 and len(parts) >= 4 and parts[3] == "8":
                    continue
                count += 1
    return count


# ---------------------------------------------------------------------------
# Convergence check
# ---------------------------------------------------------------------------

def load_catalog(path: str) -> dict[str, tuple]:
    """Return {item_id: (object_name, epoch, version)} from a catalog CSV."""
    catalog: dict[str, tuple] = {}
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            catalog[row["item_id"]] = (
                row["object_name"],
                row["epoch"],
                row["version"],
            )
    return catalog


def check_convergence(
    directory: str, csv_prefix: str = "catalog_sat"
) -> tuple[int, int, list[str]]:
    """Check that all satellite catalog CSVs agree.

    Returns (sats_with_csv, total_sats_expected, list_of_discrepancies).
    csv_prefix selects which set of CSVs to check (e.g. "catalog_sat" for the
    baseline tests, "catalog_conc_sat" for the concurrent tree test).
    """
    csv_files = sorted(glob.glob(os.path.join(directory, f"{csv_prefix}*.csv")))
    if not csv_files:
        return 0, 0, ["no catalog CSVs found"]

    catalogs = {}
    for path in csv_files:
        node = os.path.basename(path).replace("catalog_", "").replace(".csv", "")
        try:
            catalogs[node] = load_catalog(path)
        except Exception as e:
            catalogs[node] = {}

    # Use the first non-empty catalog as reference.
    reference_node, reference = next(
        ((n, c) for n, c in catalogs.items() if c), (None, {})
    )

    discrepancies: list[str] = []
    for node, catalog in catalogs.items():
        if node == reference_node:
            continue
        if catalog != reference:
            # Find specific differences.
            all_ids = set(reference) | set(catalog)
            for item_id in sorted(all_ids):
                ref_val = reference.get(item_id)
                got_val = catalog.get(item_id)
                if ref_val != got_val:
                    discrepancies.append(
                        f"  item {item_id}: {reference_node}={ref_val}  {node}={got_val}"
                    )

    return len(catalogs), len(reference), discrepancies


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# Each entry: (label, directory, gnd_log_glob, csv_prefix, is_tree)
# is_tree controls whether the "(data only, excl. tree setup)" ISL row is printed.
cases: list[tuple[str, str, str, str, bool]] = [
    ("Control (direct uplink)", sys.argv[1] if len(sys.argv) > 1 else "shared/logs/control",
     "gnd_ssa_*.log", "catalog_sat", False),
    ("CRDT Flood",              sys.argv[2] if len(sys.argv) > 2 else "shared/logs/crdt",
     "gnd_ssa_*.log", "catalog_sat", False),
    ("CRDT Tree",               sys.argv[3] if len(sys.argv) > 3 else "shared/logs/tree",
     "gnd_ssa_*.log", "catalog_sat", True),
    ("CRDT Concurrent Tree",    sys.argv[4] if len(sys.argv) > 4 else "shared/logs/concurrent",
     "gnd_concurrent_tree.log", "catalog_conc_sat", True),
]

col_w = (30, 14, 14, 10)
header = (
    f"{'Case':<{col_w[0]}}"
    f"{'GS Messages':>{col_w[1]}}"
    f"{'ISL Messages':>{col_w[2]}}"
    f"{'Total':>{col_w[3]}}"
)
sep = "-" * len(header)

print()
print("=== Message counts ===")
print(header)
print(sep)

for name, directory, log_glob, csv_prefix, is_tree in cases:
    if not os.path.isdir(directory):
        print(
            f"{name:<{col_w[0]}}{'N/A':>{col_w[1]}}{'N/A':>{col_w[2]}}{'N/A':>{col_w[3]}}"
            f"  (not found: {directory})"
        )
        continue

    gnd   = count_gnd_messages(directory, log_glob)
    isl   = count_isl_messages(directory)
    total = gnd + isl

    print(
        f"{name:<{col_w[0]}}{gnd:>{col_w[1]}}{isl:>{col_w[2]}}{total:>{col_w[3]}}"
    )

    if is_tree:
        isl_data = count_isl_messages(directory, exclude_type8=True)
        label    = "(data only, excl. tree setup)"
        print(
            f"  {label:<{col_w[0]-2}}"
            f"{'':>{col_w[1]}}{isl_data:>{col_w[2]}}{gnd + isl_data:>{col_w[3]}}"
        )

print(sep)
print()
print("GS Messages  : ground-to-satellite uplinks (SNT events in gnd_ssa_*.log)")
print("ISL Messages : inter-satellite packets (SNT + TRA events in journal_sat*.log)")

print()
print("=== Catalog convergence ===")

for name, directory, _log_glob, csv_prefix, _is_tree in cases:
    if not os.path.isdir(directory):
        continue

    n_sats, n_items, discrepancies = check_convergence(directory, csv_prefix)
    if n_sats == 0:
        print(f"  {name}: no catalog CSVs")
        continue

    status = "OK" if not discrepancies else "DIVERGED"
    print(f"  {name}: {n_sats} satellites, {n_items} unique items — {status}")
    for d in discrepancies:
        print(d)

print()


# ---------------------------------------------------------------------------
# Concurrent scalability table
# ---------------------------------------------------------------------------

def get_final_version(directory: str) -> str:
    """Return the version string all sats converged to, or '?' if mixed."""
    versions: set[str] = set()
    for path in glob.glob(os.path.join(directory, "catalog_conc_sat*.csv")):
        try:
            with open(path, newline="") as f:
                rows = list(csv.DictReader(f))
                if rows:
                    versions.add(rows[0]["version"])
        except Exception:
            pass
    return versions.pop() if len(versions) == 1 else ("?" if not versions else "mixed")


def print_concurrent_scalability(base_dir: str) -> None:
    update_counts = [1, 5, 10, 20]
    dirs = {n: os.path.join(base_dir, f"concurrent_{n}") for n in update_counts}

    if not any(os.path.isdir(d) for d in dirs.values()):
        return

    print("=== Concurrent update scalability (CRDT Tree) ===")
    print()

    rows = []
    baseline_isl: int | None = None

    for n in update_counts:
        d = dirs[n]
        if not os.path.isdir(d):
            rows.append((n, None, None, None, None, None))
            continue

        gnd     = count_gnd_messages(d, "gnd_concurrent_tree.log")
        isl_d   = count_isl_messages(d, exclude_type8=True)
        n_sats, _, disc = check_convergence(d, "catalog_conc_sat")
        version = get_final_version(d)
        conv    = f"OK ({n_sats} sats @ v{version})" if not disc else f"DIVERGED"

        if baseline_isl is None:
            baseline_isl = isl_d   # N=1 is the reference

        rows.append((n, gnd, isl_d, conv))

    cw = (9, 9, 15, 13, 13, 10)
    hdr = (
        f"{'Updates':>{cw[0]}}"
        f"{'GS Msgs':>{cw[1]}}"
        f"{'ISL Data Msgs':>{cw[2]}}"
        f"{'Naive ISL':>{cw[3]}}"
        f"{'ISL Saving':>{cw[4]}}"
        f"  Convergence"
    )
    sep = "-" * (sum(cw) + 2)
    print(hdr)
    print(sep)

    for row in rows:
        n, gnd, isl_d, conv = row
        if gnd is None:
            print(f"{'N/A':>{cw[0]}}  (not found: {dirs[n]})")
            continue
        naive    = (baseline_isl or 0) * n
        saving   = f"{100*(1 - isl_d/naive):.0f}%" if naive and n > 1 else "—"
        print(
            f"{n:>{cw[0]}}"
            f"{gnd:>{cw[1]}}"
            f"{isl_d:>{cw[2]}}"
            f"{naive:>{cw[3]}}"
            f"{saving:>{cw[4]}}"
            f"  {conv}"
        )

    print(sep)
    print()
    print(f"ISL Data      : ISL messages excl. one-time spanning-tree setup (type=8).")
    print(f"Naive ISL     : expected ISL if each update propagated independently (N × {baseline_isl}).")
    print(f"ISL Saving    : reduction vs naive due to CRDT-aware deduplication.")
    print()


conc_base = sys.argv[5] if len(sys.argv) > 5 else "shared/logs"
print_concurrent_scalability(conc_base)
