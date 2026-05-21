#!/usr/bin/env python3
"""
Topology visualisation for GonetemSwarm.

Reads node_configs.json and per-node *_discovery.json files written by
topology_discovery.py, then generates topology.png in the logs directory.

When node_configs.json contains position data (generated from a NetworkX
graph via --from-graph), a geographic map is produced automatically.
Otherwise a schematic layout is used.

Usage:
    python3 plot_topology.py
    python3 plot_topology.py --isl-only
    python3 plot_topology.py --logs-dir shared/logs --algorithms-dir shared/algorithms
"""

import argparse
import json
import math
import os
import sys

_THIS_DIR          = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ALGORITHMS = os.path.join(_THIS_DIR, "shared", "algorithms")
DEFAULT_LOGS       = os.path.join(_THIS_DIR, "shared", "logs")

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_node_configs(algorithms_dir):
    path = os.path.join(algorithms_dir, "node_configs.json")
    with open(path) as f:
        return json.load(f)


def load_all_results(all_nodes, logs_dir):
    results = {}
    for name in all_nodes:
        path = os.path.join(logs_dir, f"{name}_discovery.json")
        if os.path.exists(path):
            with open(path) as f:
                results[name] = json.load(f)
    return results


# ---------------------------------------------------------------------------
# Schematic layout helpers
# ---------------------------------------------------------------------------

def _node_id(name):
    return int("".join(filter(str.isdigit, name)) or 0)


def _circular(names):
    n = len(names)
    return {
        name: (math.cos(2 * math.pi * i / n - math.pi / 2),
               math.sin(2 * math.pi * i / n - math.pi / 2))
        for i, name in enumerate(names)
    }


def _hierarchical(root, adj, names):
    from collections import deque
    levels = {root: 0}
    level_nodes = {0: [root]}
    queue = deque([root])
    visited = {root}
    while queue:
        node = queue.popleft()
        for nb in sorted(adj[node], key=_node_id):
            if nb not in visited:
                visited.add(nb)
                levels[nb] = levels[node] + 1
                level_nodes.setdefault(levels[nb], []).append(nb)
                queue.append(nb)
    for name in names:
        if name not in levels:
            lv = max(levels.values()) + 1
            levels[name] = lv
            level_nodes.setdefault(lv, []).append(name)

    max_lv = max(levels.values()) or 1
    pos = {}
    for lv, nodes in level_nodes.items():
        nodes_sorted = sorted(nodes, key=_node_id)
        n_at_lv = len(nodes_sorted)
        for i, node in enumerate(nodes_sorted):
            x = (i + 0.5) / n_at_lv * 2 - 1
            y = 1.0 - (lv / max_lv) * 2.0
            pos[node] = (x, y)
    return pos


def _detect_clusters(names, adj):
    assigned = set()
    clusters = []
    for name in names:
        if name in assigned:
            continue
        clique = {name}
        for nb in sorted(adj[name], key=_node_id):
            if nb not in assigned and all(nb in adj[m] for m in clique):
                clique.add(nb)
        clusters.append(sorted(clique, key=_node_id))
        assigned |= clique
    return clusters


def compute_layout(all_nodes):
    sat_infos = {n: info for n, info in all_nodes.items() if not n.startswith("gnd")}
    gnd_infos = {n: info for n, info in all_nodes.items() if n.startswith("gnd")}

    topology = next(iter(sat_infos.values())).get("topology", "ring") if sat_infos else "ring"
    names = sorted(sat_infos.keys(), key=lambda n: sat_infos[n]["id"])
    n = len(names)
    adj = {name: {nb["name"] for nb in info["neighbors"]}
           for name, info in sat_infos.items()}

    if topology == "line":
        pos = {name: (2.0 * i / max(n - 1, 1) - 1, 0.0)
               for i, name in enumerate(names)}

    elif topology == "star":
        hub = names[0]
        pos = {hub: (0.0, 0.0)}
        for i, name in enumerate(names[1:]):
            a = 2 * math.pi * i / len(names[1:]) - math.pi / 2
            pos[name] = (math.cos(a), math.sin(a))

    elif topology == "tree":
        pos = _hierarchical(names[0], adj, names)

    elif topology == "grid":
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        pos = {}
        for i, name in enumerate(names):
            col, row = i % cols, i // cols
            pos[name] = ((col / max(cols - 1, 1)) * 2 - 1,
                         1 - (row / max(rows - 1, 1)) * 2)

    elif topology == "clustered":
        clusters = _detect_clusters(names, adj)
        n_cl, cl_r, nd_r = len(clusters), 0.72, 0.22
        pos = {}
        for ci, cluster in enumerate(clusters):
            ca = 2 * math.pi * ci / n_cl - math.pi / 2
            cx, cy = cl_r * math.cos(ca), cl_r * math.sin(ca)
            m = len(cluster)
            for ni, node in enumerate(cluster):
                if m == 1:
                    pos[node] = (cx, cy)
                else:
                    na = 2 * math.pi * ni / m
                    pos[node] = (cx + nd_r * math.cos(na), cy + nd_r * math.sin(na))

    else:
        pos = _circular(names)

    gnd_names = sorted(gnd_infos.keys(), key=lambda n: gnd_infos[n]["id"])
    if gnd_names:
        min_y = min(y for _, y in pos.values()) if pos else 0.0
        gnd_y = min_y - 0.40
        for i, name in enumerate(gnd_names):
            pos[name] = ((i + 0.5) / len(gnd_names) * 2 - 1, gnd_y)

    return pos


# ---------------------------------------------------------------------------
# Schematic plot
# ---------------------------------------------------------------------------

def _build_edge_sets(all_nodes, results):
    declared = set()
    for name, info in all_nodes.items():
        for nb in info["neighbors"]:
            declared.add(tuple(sorted([name, nb["name"]])))
        for nb in info.get("ground_communication", []):
            declared.add(tuple(sorted([name, nb["name"]])))

    confirmed = {e: 0 for e in declared}
    extra_discovered = set()
    for name, result in results.items():
        for disc in result.get("discovered_neighbors", []):
            edge = tuple(sorted([name, disc]))
            if edge in confirmed:
                confirmed[edge] += 1
            else:
                extra_discovered.add(edge)

    return declared, confirmed, extra_discovered


def plot_topology(all_nodes, results, out_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    positions = compute_layout(all_nodes)
    declared, confirmed, extra_discovered = _build_edge_sets(all_nodes, results)

    fig, ax = plt.subplots(figsize=(14, 12))
    ax.set_aspect("equal")
    ax.axis("off")

    for edge in declared:
        a, b = edge
        if a not in positions or b not in positions:
            continue
        xa, ya = positions[a]
        xb, yb = positions[b]
        c = confirmed[edge]
        if c >= 2:
            color, lw, ls = "#2ecc71", 2.5, "-"
        elif c == 1:
            color, lw, ls = "#e67e22", 2.0, "--"
        else:
            color, lw, ls = "#e74c3c", 1.5, ":"
        ax.plot([xa, xb], [ya, yb], color=color, lw=lw, linestyle=ls, zorder=2)

    for edge in extra_discovered:
        a, b = edge
        if a not in positions or b not in positions:
            continue
        xa, ya = positions[a]
        xb, yb = positions[b]
        ax.plot([xa, xb], [ya, yb], color="#9b59b6", lw=1.5, linestyle="-.", zorder=2)

    node_r = 0.055
    for name, (x, y) in positions.items():
        reported = name in results
        is_gnd = name.startswith("gnd")
        node_id = all_nodes[name]["id"]

        if is_gnd:
            face = "#27ae60" if reported else "#95a5a6"
            half = node_r * 1.1
            ax.add_patch(mpatches.FancyBboxPatch(
                (x - half, y - half), half * 2, half * 2,
                boxstyle="square,pad=0",
                facecolor=face, edgecolor="white", linewidth=1.5, zorder=3))
            label_inside = f"G{_node_id(name)}"
        else:
            face = "#2980b9" if reported else "#95a5a6"
            ax.add_patch(mpatches.Circle(
                (x, y), node_r,
                facecolor=face, edgecolor="white", linewidth=1.5, zorder=3))
            label_inside = str(node_id)

        ax.text(x, y, label_inside,
                ha="center", va="center",
                fontsize=8, fontweight="bold", color="white", zorder=4)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved schematic topology → {out_path}")


# ---------------------------------------------------------------------------
# Geographic map plot
# ---------------------------------------------------------------------------

def _antimeridian_segments(lon_a, lat_a, lon_b, lat_b):
    """Split a lon/lat edge at ±180° if the shortest path crosses the antimeridian.

    Returns a list of ([lons], [lats]) pairs, each safe to plot as a single line.
    Without splitting, Matplotlib draws a straight line in projected coordinates
    from e.g. 170° to -170°, which spans the entire map instead of the short hop.
    """
    dlon = lon_b - lon_a
    if dlon > 180:
        dlon -= 360
    elif dlon < -180:
        dlon += 360

    lon_b_eff = lon_a + dlon

    if lon_b_eff > 180:
        t = (180.0 - lon_a) / dlon
        lat_x = lat_a + t * (lat_b - lat_a)
        return [([lon_a, 180.0], [lat_a, lat_x]),
                ([-180.0, lon_b], [lat_x, lat_b])]
    elif lon_b_eff < -180:
        t = (-180.0 - lon_a) / dlon
        lat_x = lat_a + t * (lat_b - lat_a)
        return [([lon_a, -180.0], [lat_a, lat_x]),
                ([180.0, lon_b], [lat_x, lat_b])]
    else:
        return [([lon_a, lon_b], [lat_a, lat_b])]


def plot_topology_map(all_nodes, results, out_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    try:
        import cartopy.crs as ccrs
        import cartopy.feature as cfeature
        HAS_CARTOPY = True
    except ImportError:
        HAS_CARTOPY = False
        print("cartopy not available — using plain lat/lon axes (no landmasses)")

    positions = {
        name: (info["position"]["longitude"], info["position"]["latitude"])
        for name, info in all_nodes.items()
        if "position" in info
    }

    declared, confirmed, extra_discovered = _build_edge_sets(all_nodes, results)

    transform = ccrs.PlateCarree() if HAS_CARTOPY else None

    if HAS_CARTOPY:
        fig = plt.figure(figsize=(20, 10))
        ax = fig.add_subplot(1, 1, 1, projection=ccrs.Robinson())
        ax.set_global()
        ax.add_feature(cfeature.LAND,      facecolor="#e8e4d9")
        ax.add_feature(cfeature.OCEAN,     facecolor="#cfe2f3")
        ax.add_feature(cfeature.COASTLINE, linewidth=0.4, edgecolor="#888888")
        ax.add_feature(cfeature.BORDERS,   linewidth=0.2, edgecolor="#aaaaaa")
        ax.gridlines(linewidth=0.2, color="#bbbbbb", linestyle="--")
        plot_kw = {"transform": transform}
    else:
        fig, ax = plt.subplots(figsize=(20, 10))
        ax.set_facecolor("#cfe2f3")
        ax.set_xlim(-180, 180)
        ax.set_ylim(-90, 90)
        ax.grid(True, linewidth=0.2, color="#bbbbbb", linestyle="--")
        plot_kw = {}

    fig.patch.set_facecolor("white")

    for edge in declared:
        a, b = edge
        if a not in positions or b not in positions:
            continue
        xa, ya = positions[a]
        xb, yb = positions[b]
        c = confirmed[edge]
        if c >= 2:
            color, lw, ls = "#2ca02c", 1.0, "-"
        elif c == 1:
            color, lw, ls = "#ff7f0e", 0.8, "--"
        else:
            color, lw, ls = "#d62728", 0.7, ":"
        for lons, lats in _antimeridian_segments(xa, ya, xb, yb):
            ax.plot(lons, lats, color=color, lw=lw, linestyle=ls,
                    alpha=0.8, zorder=2, **plot_kw)

    for edge in extra_discovered:
        a, b = edge
        if a not in positions or b not in positions:
            continue
        xa, ya = positions[a]
        xb, yb = positions[b]
        for lons, lats in _antimeridian_segments(xa, ya, xb, yb):
            ax.plot(lons, lats, color="#9467bd", lw=0.7, linestyle="-.",
                    alpha=0.7, zorder=2, **plot_kw)

    sat_rep   = [(lon, lat) for n, (lon, lat) in positions.items()
                 if not n.startswith("gnd") and n in results]
    sat_norep = [(lon, lat) for n, (lon, lat) in positions.items()
                 if not n.startswith("gnd") and n not in results]
    gnd_rep   = [(lon, lat) for n, (lon, lat) in positions.items()
                 if n.startswith("gnd") and n in results]
    gnd_norep = [(lon, lat) for n, (lon, lat) in positions.items()
                 if n.startswith("gnd") and n not in results]

    scatter_kw = {"zorder": 5, **({"transform": transform} if HAS_CARTOPY else {})}
    if sat_rep:
        ax.scatter([p[0] for p in sat_rep],   [p[1] for p in sat_rep],
                   s=70, color="#1f77b4", **scatter_kw)
    if sat_norep:
        ax.scatter([p[0] for p in sat_norep], [p[1] for p in sat_norep],
                   s=70, color="#aaaaaa", **scatter_kw)
    if gnd_rep:
        ax.scatter([p[0] for p in gnd_rep],   [p[1] for p in gnd_rep],
                   s=40, color="#d62728", marker="^", zorder=6,
                   **({"transform": transform} if HAS_CARTOPY else {}))
    if gnd_norep:
        ax.scatter([p[0] for p in gnd_norep], [p[1] for p in gnd_norep],
                   s=40, color="#aaaaaa", marker="^", zorder=6,
                   **({"transform": transform} if HAS_CARTOPY else {}))

    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close()
    print(f"Saved geographic topology map → {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate topology figure from discovery results")
    parser.add_argument("--algorithms-dir", default=DEFAULT_ALGORITHMS,
        help=f"Directory containing node_configs.json (default: {DEFAULT_ALGORITHMS})")
    parser.add_argument("--logs-dir", default=DEFAULT_LOGS,
        help=f"Directory containing *_discovery.json files and where topology.png is written "
             f"(default: {DEFAULT_LOGS})")
    parser.add_argument("--isl-only", action="store_true",
        help="Exclude ground station nodes from the figure")
    args = parser.parse_args()

    all_nodes = load_node_configs(args.algorithms_dir)

    if args.isl_only:
        all_nodes = {n: info for n, info in all_nodes.items()
                     if not n.startswith("gnd")}

    results = load_all_results(all_nodes, args.logs_dir)

    missing = [n for n in all_nodes if n not in results]
    if missing:
        print(f"WARNING: no discovery file for {missing} — plotting with partial data")

    out_path = os.path.join(args.logs_dir, "topology.png")
    has_positions = any("position" in info for info in all_nodes.values())
    if has_positions:
        plot_topology_map(all_nodes, results, out_path)
    else:
        plot_topology(all_nodes, results, out_path)


if __name__ == "__main__":
    main()
