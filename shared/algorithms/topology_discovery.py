#!/usr/bin/env python3
"""
Topology discovery and visualisation for GonetemSwarm.

Every satellite node:
  1. Sends UDP PROBE messages to each declared neighbour's link IP.
  2. Listens for PROBE messages from any node.
  3. Writes its discovered-neighbour set to /logs/<name>_discovery.json.

Node sat1 (coordinator) additionally:
  4. Waits for all nodes to finish and write their results.
  5. Reads all JSON files, compares declared vs discovered edges.
  6. Saves a topology graph to /logs/topology.png.

Run via:
  ./run_test.sh start topology_discovery

Output:
  shared/logs/<name>_discovery.json   — per-node probe results
  shared/logs/topology.png            — full-topology graph (from sat1)
"""

import json
import math
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
COLLECT_WAIT   = 30    # extra seconds sat1 waits for all JSON files
MSG_PROBE      = "PROBE"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_config():
    with open("/algorithms/node_configs.json") as f:
        all_nodes = json.load(f)
    my_name = os.environ["SAT_NAME"]
    me = all_nodes[my_name]
    return all_nodes, my_name, me


def log(name, msg):
    print(f"[{name}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Phase 1 – probe and listen
# ---------------------------------------------------------------------------

def run_discovery(my_name, me):
    received_from = set()
    lock = threading.Lock()
    stop_event = threading.Event()

    # Receiver
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

    # Sender
    probe = json.dumps({"type": MSG_PROBE, "name": my_name}).encode()
    tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    deadline = time.time() + DURATION
    while time.time() < deadline:
        for nb in me["neighbors"]:
            try:
                tx_sock.sendto(probe, (nb["link_ip"], PROBE_PORT))
            except Exception:
                pass
        time.sleep(PROBE_INTERVAL)
    tx_sock.close()

    time.sleep(1.0)   # let last probes arrive
    stop_event.set()
    rx.join(timeout=3)

    with lock:
        return sorted(received_from)


# ---------------------------------------------------------------------------
# Phase 2 – write per-node result
# ---------------------------------------------------------------------------

def write_result(my_name, me, discovered):
    result = {
        "name":                 my_name,
        "id":                   me["id"],
        "declared_neighbors":   [nb["name"] for nb in me["neighbors"]],
        "discovered_neighbors": discovered,
    }
    os.makedirs("/logs", exist_ok=True)
    path = f"/logs/{my_name}_discovery.json"
    with open(path, "w") as f:
        json.dump(result, f, indent=2)
    log(my_name, f"wrote {path}")
    log(my_name, f"  declared  : {result['declared_neighbors']}")
    log(my_name, f"  discovered: {result['discovered_neighbors']}")
    return result


# ---------------------------------------------------------------------------
# Phase 3 – coordinator: collect and plot
# ---------------------------------------------------------------------------

def wait_for_all(all_nodes, my_name):
    names = list(all_nodes.keys())
    deadline = time.time() + COLLECT_WAIT
    while time.time() < deadline:
        missing = [n for n in names
                   if not os.path.exists(f"/logs/{n}_discovery.json")]
        if not missing:
            return True
        log(my_name, f"waiting for: {missing}")
        time.sleep(2)
    missing = [n for n in names
               if not os.path.exists(f"/logs/{n}_discovery.json")]
    if missing:
        log(my_name, f"WARNING: timed out waiting for {missing}, plotting with partial data")
    return False


def load_all_results(all_nodes):
    results = {}
    for name in all_nodes:
        path = f"/logs/{name}_discovery.json"
        if os.path.exists(path):
            with open(path) as f:
                results[name] = json.load(f)
    return results


def _node_id(name):
    return int(name[3:])   # "sat7" → 7


def _circular(names):
    n = len(names)
    return {
        name: (math.cos(2 * math.pi * i / n - math.pi / 2),
               math.sin(2 * math.pi * i / n - math.pi / 2))
        for i, name in enumerate(names)
    }


def _hierarchical(root, adj, names):
    """BFS top-down tree layout."""
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
    # Any disconnected nodes get their own level
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
    """
    Greedy maximal-clique clustering.
    Works correctly for the full-mesh-within-cluster structure generated
    by topology_clustered().
    """
    assigned = set()
    clusters = []
    for name in names:          # names are already sorted by id
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
    """Choose a layout that matches the topology shape."""
    topology = next(iter(all_nodes.values())).get("topology", "ring")
    names = sorted(all_nodes.keys(), key=lambda n: all_nodes[n]["id"])
    n = len(names)
    adj = {name: {nb["name"] for nb in info["neighbors"]}
           for name, info in all_nodes.items()}

    # ---- line ---------------------------------------------------------------
    if topology == "line":
        span = 2.0
        return {name: (span * i / max(n - 1, 1) - 1, 0.0)
                for i, name in enumerate(names)}

    # ---- star ---------------------------------------------------------------
    if topology == "star":
        hub = names[0]          # id=1 is the hub
        spokes = names[1:]
        pos = {hub: (0.0, 0.0)}
        for i, name in enumerate(spokes):
            a = 2 * math.pi * i / len(spokes) - math.pi / 2
            pos[name] = (math.cos(a), math.sin(a))
        return pos

    # ---- tree ---------------------------------------------------------------
    if topology == "tree":
        root = names[0]         # id=1 is the root
        return _hierarchical(root, adj, names)

    # ---- grid ---------------------------------------------------------------
    if topology == "grid":
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        pos = {}
        for i, name in enumerate(names):
            col = i % cols
            row = i // cols
            x = (col / max(cols - 1, 1)) * 2 - 1
            y = 1 - (row / max(rows - 1, 1)) * 2
            pos[name] = (x, y)
        return pos

    # ---- clustered ----------------------------------------------------------
    if topology == "clustered":
        clusters = _detect_clusters(names, adj)
        n_cl = len(clusters)
        cl_r = 0.72        # ring radius for cluster centres
        nd_r = 0.22        # radius of each cluster's local circle
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
                    pos[node] = (cx + nd_r * math.cos(na),
                                 cy + nd_r * math.sin(na))
        return pos

    # ---- ring / sparse / full-mesh / fallback -------------------------------
    return _circular(names)


def plot_topology(all_nodes, results, my_name):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.lines as mlines
    import matplotlib.patches as mpatches

    positions = compute_layout(all_nodes)

    # Declared undirected edges (from node_configs)
    declared = set()
    for name, info in all_nodes.items():
        for nb in info["neighbors"]:
            declared.add(tuple(sorted([name, nb["name"]])))

    # Count how many directions each declared edge was confirmed
    # confirmed[edge] = number of endpoints that discovered the other
    confirmed = {e: 0 for e in declared}
    extra_discovered = set()   # edges seen but not declared

    for name, result in results.items():
        for disc in result.get("discovered_neighbors", []):
            edge = tuple(sorted([name, disc]))
            if edge in confirmed:
                confirmed[edge] += 1
            else:
                extra_discovered.add(edge)

    # --- figure -------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(14, 12))
    ax.set_aspect("equal")
    ax.axis("off")

    sample = next(iter(all_nodes.values()))
    topology  = sample.get("topology", "unknown")
    isl       = sample.get("isl_profile", "unknown")
    ospf      = sample.get("ospf_enabled", False)
    n_nodes   = len(all_nodes)
    n_results = len(results)

    ax.set_title(
        f"Discovered topology  |  {topology}  ·  {n_nodes} nodes  ·  ISL: {isl}"
        f"  ·  OSPF: {'on' if ospf else 'off'}"
        f"\n{n_results}/{n_nodes} nodes reported",
        fontsize=13, pad=16,
    )

    # Draw declared edges
    for edge in declared:
        a, b = edge
        xa, ya = positions[a]
        xb, yb = positions[b]
        c = confirmed[edge]
        if c >= 2:
            color, lw, ls, zorder = "#2ecc71", 2.5, "-",  2   # green  – both ways
        elif c == 1:
            color, lw, ls, zorder = "#e67e22", 2.0, "--", 2   # orange – one way
        else:
            color, lw, ls, zorder = "#e74c3c", 1.5, ":",  2   # red    – not found
        ax.plot([xa, xb], [ya, yb],
                color=color, lw=lw, linestyle=ls, zorder=zorder)

    # Draw undeclared but discovered edges
    for edge in extra_discovered:
        a, b = edge
        if a not in positions or b not in positions:
            continue
        xa, ya = positions[a]
        xb, yb = positions[b]
        ax.plot([xa, xb], [ya, yb],
                color="#9b59b6", lw=1.5, linestyle="-.", zorder=2)

    # Draw nodes
    node_r = 0.055
    for name, (x, y) in positions.items():
        reported = name in results
        face = "#2980b9" if reported else "#95a5a6"
        circle = mpatches.Circle((x, y), node_r,
                                  facecolor=face, edgecolor="white",
                                  linewidth=1.5, zorder=3)
        ax.add_patch(circle)
        # Satellite number inside circle
        sat_id = all_nodes[name]["id"]
        ax.text(x, y, str(sat_id),
                ha="center", va="center",
                fontsize=8, fontweight="bold", color="white", zorder=4)
        # Node name: place it away from the nearest edge of the bounding box
        # so labels don't collide with edges running through the middle.
        # Offset direction: away from the centroid of all positions.
        cx_all = sum(px for px, _ in positions.values()) / len(positions)
        cy_all = sum(py for _, py in positions.values()) / len(positions)
        dx = x - cx_all
        dy = y - cy_all
        norm = math.hypot(dx, dy) or 1
        lx = x + (dx / norm) * (node_r + 0.04)
        ly = y + (dy / norm) * (node_r + 0.04)
        ax.text(lx, ly, name,
                ha="center", va="center",
                fontsize=7, color="#2c3e50", zorder=4)

    # Legend
    legend_entries = [
        mlines.Line2D([], [], color="#2ecc71", lw=2.5, label="Confirmed (both directions)"),
        mlines.Line2D([], [], color="#e67e22", lw=2.0, linestyle="--",
                      label="Partial (one direction only)"),
        mlines.Line2D([], [], color="#e74c3c", lw=1.5, linestyle=":",
                      label="Declared but not discovered"),
        mlines.Line2D([], [], color="#9b59b6", lw=1.5, linestyle="-.",
                      label="Discovered but not declared"),
        mpatches.Patch(facecolor="#2980b9", label="Node (reported)"),
        mpatches.Patch(facecolor="#95a5a6", label="Node (no report)"),
    ]
    ax.legend(handles=legend_entries, loc="lower center",
              bbox_to_anchor=(0.5, -0.04), ncol=3, fontsize=9,
              framealpha=0.9)

    # Summary stats
    total  = len(declared)
    full   = sum(1 for v in confirmed.values() if v >= 2)
    partial = sum(1 for v in confirmed.values() if v == 1)
    missing = sum(1 for v in confirmed.values() if v == 0)
    stats = (f"Edges: {total} declared  |  "
             f"{full} confirmed  ·  {partial} partial  ·  {missing} missing"
             + (f"  ·  {len(extra_discovered)} unexpected" if extra_discovered else ""))
    ax.text(0.5, 0.01, stats, transform=ax.transAxes,
            ha="center", va="bottom", fontsize=9, color="#555")

    plt.tight_layout()
    out = "/logs/topology.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    log(my_name, f"saved topology graph → {out}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    all_nodes, my_name, me = load_config()
    my_id = me["id"]

    log(my_name, f"starting discovery  (duration={DURATION}s, "
                 f"neighbours={[nb['name'] for nb in me['neighbors']]})")

    # Phase 1+2: probe and record
    discovered = run_discovery(my_name, me)
    write_result(my_name, me, discovered)

    # Phase 3: coordinator collects results and plots
    if my_id == 1:
        log(my_name, "coordinator: collecting results from all nodes …")
        wait_for_all(all_nodes, my_name)
        results = load_all_results(all_nodes)
        plot_topology(all_nodes, results, my_name)


if __name__ == "__main__":
    main()
