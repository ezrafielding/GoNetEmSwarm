"""Bar chart: ISL message count vs number of concurrent updates (CRDT Tree).

Shows actual ISL data messages (with CRDT-aware deduplication) compared to the
naive expected count (no dedup), for 1, 5, and 10 concurrent start-point updates.

Usage:
    python3 plot_concurrent.py [--base-dir shared/logs] [--output concurrent_scalability.pdf]
"""

import argparse
import glob
import os

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

# ---------------------------------------------------------------------------
# Counting helpers (mirrors analyze_ssa.py)
# ---------------------------------------------------------------------------

def count_gnd_messages(directory: str) -> int:
    count = 0
    for path in glob.glob(os.path.join(directory, "gnd_concurrent_tree.log")):
        with open(path) as f:
            for line in f:
                parts = line.strip().split("|")
                if len(parts) >= 2 and parts[1] == "SNT":
                    count += 1
    return count


def count_isl_data(directory: str) -> int:
    """Count ISL messages (SNT + TRA), excluding type=8 spanning-tree setup."""
    count = 0
    for path in glob.glob(os.path.join(directory, "journal_sat*.log")):
        with open(path) as f:
            for line in f:
                parts = line.strip().split("|")
                if len(parts) < 4:
                    continue
                if parts[1] not in ("SNT", "TRA"):
                    continue
                if parts[3] == "8":
                    continue
                count += 1
    return count


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

parser = argparse.ArgumentParser(description="Plot concurrent CRDT update scalability")
parser.add_argument("--base-dir", default="shared/logs",
                    help="directory containing concurrent_1/, concurrent_5/, concurrent_10/ "
                         "(default: shared/logs)")
parser.add_argument("--output", default="shared/logs/concurrent_scalability.pdf",
                    help="output file path (default: shared/logs/concurrent_scalability.pdf)")
args = parser.parse_args()

# ---------------------------------------------------------------------------
# Collect data
# ---------------------------------------------------------------------------

update_counts = [1, 5, 10, 20]
actual_gnd  = []
actual_isl  = []

for n in update_counts:
    d = os.path.join(args.base_dir, f"concurrent_{n}")
    if not os.path.isdir(d):
        raise SystemExit(f"ERROR: directory not found: {d}")
    actual_gnd.append(count_gnd_messages(d))
    actual_isl.append(count_isl_data(d))


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

fig, ax = plt.subplots(figsize=(7, 4.5), layout="constrained")

x      = np.arange(len(update_counts))
width  = 0.35
colour_actual = "#2c7bb6"
colour_gnd    = "#abdda4"

bars_actual = ax.bar(x, actual_isl, width,
                     label="ISL data msgs", color=colour_actual, zorder=3)

# GS uplink messages stacked on top of the actual bars (tiny but visible)
ax.bar(x, actual_gnd, width,
       bottom=actual_isl, label="GS uplink msgs",
       color=colour_gnd, zorder=3)

# Value labels on top of each bar
for i, (isl, gnd) in enumerate(zip(actual_isl, actual_gnd)):
    ax.annotate(
        f"{isl + gnd}",
        xy=(x[i], isl + gnd),
        xytext=(0, 5), textcoords="offset points",
        ha="center", va="bottom", fontsize=11, fontweight="bold",
    )

# Axes styling
ax.set_xticks(x)
ax.set_xticklabels([f"{n}" for n in update_counts], fontsize=12)
ax.set_xlabel("Number of concurrent updates", fontsize=12)
ax.set_ylabel("Message count", fontsize=12)

ax.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))
ax.yaxis.grid(True, linestyle="--", linewidth=0.6, alpha=0.7, zorder=0)
ax.set_axisbelow(True)
ax.spines[["top", "right"]].set_visible(False)

ax.legend(fontsize=10, framealpha=0.9)

# ---------------------------------------------------------------------------
# Save & show
# ---------------------------------------------------------------------------

os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
fig.savefig(args.output, dpi=150, bbox_inches="tight")
print(f"Figure saved to {args.output}")
plt.show()
