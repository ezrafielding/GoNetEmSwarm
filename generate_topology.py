#!/usr/bin/env python3
"""
Gonetem topology generator for satellite swarm emulation.

Generates .gnet project files for the gonetem network emulator replicating the
topology types from ConSwarm. Each satellite node is a docker.router with FRR,
with optional OSPF routing for full cross-topology reachability.

Supported topologies: full-mesh, ring, line, star, tree, grid, clustered, sparse

Usage:
    python3 generate_topology.py --nodes 10 --topology ring --isl-profile leo
    python3 generate_topology.py --nodes 10 --topology ring --isl-profile leo --no-ospf
    python3 generate_topology.py --nodes 6  --topology star --isl-profile geo -o star_6.gnet
    python3 generate_topology.py --nodes 16 --topology grid --isl-profile leo
    python3 generate_topology.py --nodes 15 --topology clustered --cluster-size 5
    python3 generate_topology.py --nodes 10 --topology tree --branch 3
"""

import argparse
import io
import json
import math
import os
import sys
import tarfile

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Match ConSwarm's ISL profiles; rate is in kbps (gonetem uses kbps)
ISL_PROFILES = {
    "leo":        {"delay": 20,   "jitter": 5,   "loss": 0.01,  "rate": 10240},   # 10 Mbit/s
    "geo":        {"delay": 250,  "jitter": 25,  "loss": 0.001, "rate": 102400},  # 100 Mbit/s
    "deep-space": {"delay": 2000, "jitter": 100, "loss": 0.1,   "rate": 64},      # 64 kbit/s
    "none":       {},
}

TOPOLOGY_CHOICES = [
    "full-mesh", "ring", "line", "star", "tree", "grid", "clustered", "sparse",
]

# Multicast group used for topology-wide "broadcast".
# Chosen from the Organisation-Local scope (239.0.0.0/8).
MCAST_GROUP   = "239.0.1.1"
MCAST_PORT    = 5007

# Resolved at runtime; can be overridden with --algorithms-dir / --logs-dir
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ALGORITHMS_DIR = os.path.join(_THIS_DIR, "shared", "algorithms")
DEFAULT_LOGS_DIR = os.path.join(_THIS_DIR, "shared", "logs")


# ---------------------------------------------------------------------------
# IP addressing helpers
# ---------------------------------------------------------------------------

def node_name(i: int) -> str:
    return f"sat{i}"


def loopback_ip(n: int, with_prefix: bool = True) -> str:
    """Stable per-node identity address: 10.255.0.<n>/32."""
    addr = f"10.255.0.{n}"
    return f"{addr}/32" if with_prefix else addr


def link_addresses(link_idx: int):
    """
    Return (subnet/prefix, peer1_ip/prefix, peer2_ip/prefix) for a link.

    Subnets are carved from 10.0.0.0/8 as sequential /30 blocks:
      link 0  → 10.0.0.0/30  (hosts: .1, .2)
      link 1  → 10.0.0.4/30  (hosts: .5, .6)
      link k  → 10.0.{k//64}.{(k%64)*4}/30
    Supports up to ~4 000 links (more than enough for 30-node full-mesh = 435).
    """
    octet3 = link_idx // 64
    octet4_base = (link_idx % 64) * 4
    subnet = f"10.0.{octet3}.{octet4_base}/30"
    peer1  = f"10.0.{octet3}.{octet4_base + 1}/30"
    peer2  = f"10.0.{octet3}.{octet4_base + 2}/30"
    return subnet, peer1, peer2


# ---------------------------------------------------------------------------
# Topology edge generators
# ---------------------------------------------------------------------------

def topology_full_mesh(n: int):
    return [(i, j) for i in range(1, n + 1) for j in range(i + 1, n + 1)]


def topology_ring(n: int):
    if n < 2:
        return []
    edges = [(i, i + 1) for i in range(1, n)]
    if n > 2:
        edges.append((1, n))  # close the ring
    return edges


def topology_line(n: int):
    return [(i, i + 1) for i in range(1, n)]


def topology_star(n: int):
    """Node 1 is the hub; all other nodes are spokes."""
    return [(1, i) for i in range(2, n + 1)]


def topology_tree(n: int, branch: int = 2):
    """
    k-ary tree rooted at node 1.
    Parent of node i (i > 1): (i - 2) // branch + 1
    """
    return [((i - 2) // branch + 1, i) for i in range(2, n + 1)]


def topology_grid(n: int):
    """2-D mesh: ceil(√n) columns, ceil(n / cols) rows."""
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)

    def idx(r, c):
        return r * cols + c + 1

    edges = []
    for r in range(rows):
        for c in range(cols):
            if idx(r, c) > n:
                continue
            if c + 1 < cols and idx(r, c + 1) <= n:
                edges.append((idx(r, c), idx(r, c + 1)))
            if r + 1 < rows and idx(r + 1, c) <= n:
                edges.append((idx(r, c), idx(r + 1, c)))
    return edges


def topology_clustered(n: int, cluster_size: int = 5):
    """
    Full mesh within each cluster of `cluster_size` nodes.
    Adjacent clusters are connected by a single inter-cluster link
    (first node of cluster k → first node of cluster k+1).
    """
    k = math.ceil(n / cluster_size)
    edges = []
    for cl in range(k):
        start = cl * cluster_size + 1
        end = min((cl + 1) * cluster_size, n)
        # Intra-cluster full mesh
        for i in range(start, end + 1):
            for j in range(i + 1, end + 1):
                edges.append((i, j))
    # Inter-cluster chain
    for cl in range(k - 1):
        a = cl * cluster_size + 1
        b = (cl + 1) * cluster_size + 1
        if b <= n:
            edges.append((a, b))
    return edges


def topology_sparse(n: int, distance: int = 2):
    """
    Each node connects to every other node within `distance` index positions.
    distance=1 is equivalent to a line topology.
    distance=2 is denser (each interior node has 4 neighbours).
    """
    edges = []
    for i in range(1, n + 1):
        for d in range(1, distance + 1):
            j = i + d
            if j <= n:
                edges.append((i, j))
    return edges


def get_edges(n: int, topology: str, **kwargs):
    dispatch = {
        "full-mesh": lambda: topology_full_mesh(n),
        "ring":      lambda: topology_ring(n),
        "line":      lambda: topology_line(n),
        "star":      lambda: topology_star(n),
        "tree":      lambda: topology_tree(n, branch=kwargs.get("branch", 2)),
        "grid":      lambda: topology_grid(n),
        "clustered": lambda: topology_clustered(n, cluster_size=kwargs.get("cluster_size", 5)),
        "sparse":    lambda: topology_sparse(n, distance=kwargs.get("sparse_distance", 2)),
    }
    if topology not in dispatch:
        raise ValueError(f"Unknown topology: {topology}")
    return dispatch[topology]()


# ---------------------------------------------------------------------------
# NetworkX graph import
# ---------------------------------------------------------------------------

def edges_from_networkx(G) -> tuple[list[tuple[int, int]], dict, dict]:
    """Extract satellite nodes and ISL edges from a SatComTopology NetworkX graph.

    Satellites are sorted by their topology_uniq_id for reproducible ordering,
    then assigned 1-based integer indices (sat1, sat2, …).

    Returns:
        edges     – sorted list of (a, b) int pairs, a < b, 1-based
        node_map  – {nx_node_id: 1-based index}
        positions – {1-based index: {"longitude": float, "latitude": float,
                                     "altitude": float}} (empty if not in graph)
    """
    sat_nodes = sorted(
        [n for n, d in G.nodes(data=True) if d.get("type") == "Satellite"],
        key=lambda n: G.nodes[n].get("topology_uniq_id", 0),
    )
    if not sat_nodes:
        raise ValueError("No nodes with type='Satellite' found in the graph.")

    node_map = {n: i + 1 for i, n in enumerate(sat_nodes)}

    positions = {}
    for n in sat_nodes:
        pos = G.nodes[n].get("position")
        if pos:
            positions[node_map[n]] = {
                "longitude": pos["longitude"],
                "latitude":  pos["latitude"],
                "altitude":  pos.get("altitude", 0),
            }

    seen: set[tuple[int, int]] = set()
    edges: list[tuple[int, int]] = []
    for u, v, d in G.edges(data=True):
        if d.get("type") != "InterSatelliteLink":
            continue
        if u not in node_map or v not in node_map:
            continue
        a, b = node_map[u], node_map[v]
        if a > b:
            a, b = b, a
        if (a, b) not in seen:
            seen.add((a, b))
            edges.append((a, b))

    return sorted(edges), node_map, positions


def load_networkx_graph(path: str):
    """Load a NetworkX graph from a JSON file in node-link format.

    SatComTopology's NetworkXAdapter.adapt() writes this format by default.
    You can also produce it manually with:
        json.dump(networkx.readwrite.json_graph.node_link_data(G), f)
    """
    try:
        import networkx as nx
        from networkx.readwrite import json_graph
    except ImportError:
        raise SystemExit("networkx is required: pip install networkx")
    with open(path) as f:
        data = json.load(f)
    # NetworkX >= 3.x writes "edges"; older versions write "links".
    # Pass the key explicitly so node_link_graph finds it either way.
    edge_key = "edges" if "edges" in data else "links"
    return json_graph.node_link_graph(data, edges=edge_key)


# ---------------------------------------------------------------------------
# Core generator
# ---------------------------------------------------------------------------

def generate(
    n: int,
    nb_gnd_station: int,
    topology: str,
    isl_profile: str,
    ospf: bool = False,
    multicast: bool = False,
    branch: int = 2,
    cluster_size: int = 5,
    sparse_distance: int = 2,
    algorithms_dir: str = DEFAULT_ALGORITHMS_DIR,
    logs_dir: str = DEFAULT_LOGS_DIR,
    edges: list = None,
    node_positions: dict = None,
):
    """
    Build all artefacts for the .gnet archive.

    Returns:
        network_yml   : str  – contents of network.yml
        frr_configs   : dict[str, str]  – {node_name: frr.conf content}
        node_infos    : dict[str, dict] – {node_name: info dict for algorithms}
    """
    nodes = [node_name(i) for i in range(1, n + 1)]
    if edges is None:
        edges = get_edges(n, topology, branch=branch, cluster_size=cluster_size,
                          sparse_distance=sparse_distance)


    # Per-node interface counter and assignment list
    node_iface_counter = {nd: 0 for nd in nodes}
    node_ifaces = {nd: [] for nd in nodes}
    # node_ifaces[nd] = list of (link_idx, is_peer1, eth_idx)

    links_yaml = []
    qos = ISL_PROFILES[isl_profile]

    last_id = 0
    for link_idx, (a, b) in enumerate(edges):
        na, nb = node_name(a), node_name(b)
        a_eth = node_iface_counter[na]
        b_eth = node_iface_counter[nb]

        node_ifaces[na].append((link_idx, True,  a_eth, False))
        node_ifaces[nb].append((link_idx, False, b_eth, False))

        node_iface_counter[na] += 1
        node_iface_counter[nb] += 1

        link_entry = {
            "peer1": f"{na}.{a_eth}",
            "peer2": f"{nb}.{b_eth}",
        }
        if qos:
            link_entry.update(qos)
        links_yaml.append(link_entry)
        last_id = link_idx


    # ---- network.yml -------------------------------------------------------
    nodes_yaml = {}
    for i, nd in enumerate(nodes, start=1):
        nodes_yaml[nd] = {
            "type": "docker.satellite",
            "ipv6": False,
            "volumes": [
                f"{algorithms_dir}:/algorithms:ro",
                f"{logs_dir}:/logs",
            ],
        }

    if (nb_gnd_station > 0):
        station = ["gnd"+str(i) for i in range(1, nb_gnd_station + 1)]
        gnd_iface_counter = {nd: 0 for nd in station}
        gnd_ifaces = {nd: [] for nd in station}
        for id_gnd in range (1, nb_gnd_station + 1):
            for id_sat in range(1, n + 1):
                last_id += 1
                ng, ns = "gnd"+str(id_gnd), node_name(id_sat)
                gnd_eth = gnd_iface_counter[ng]
                sat_eth = node_iface_counter[ns]

                gnd_ifaces[ng].append((last_id, True,  gnd_eth, True))
                node_ifaces[ns].append((last_id, False, sat_eth, True))

                gnd_iface_counter[ng] += 1
                node_iface_counter[ns] += 1

                link_entry = {
                    "peer1": f"{ng}.{gnd_eth}",
                    "peer2": f"{ns}.{sat_eth}",
                }
                if qos:
                    link_entry.update(qos)
                links_yaml.append(link_entry)

        for sta in station:
            nodes_yaml[sta] = {
                "type": "docker.station",
                "ipv6": False,
                "volumes": [
                    f"{algorithms_dir}:/algorithms:ro",
                    f"{logs_dir}:/logs",
                ],
            }

    network = {"nodes": nodes_yaml, "links": links_yaml}
    network_yml = yaml.dump(network, default_flow_style=False, sort_keys=False)

    # ---- frr.conf + node info per satellite --------------------------------
    frr_configs = {}
    node_infos  = {}

    for i, nd in enumerate(nodes, start=1):
        lo_ip   = loopback_ip(i, with_prefix=True)
        lo_addr = loopback_ip(i, with_prefix=False)

        iface_frr_lines = []
        ospf_networks   = [lo_ip]
        neighbors       = []
        gnd_links       = []

        for (link_idx, is_peer1, eth_idx, with_gnd) in node_ifaces[nd]:
            if not with_gnd:
                subnet, peer1_ip, peer2_ip = link_addresses(link_idx)
                my_ip      = peer1_ip if is_peer1 else peer2_ip
                their_ip   = (peer2_ip if is_peer1 else peer1_ip).split("/")[0]

                neighbor_idx = edges[link_idx][1] if is_peer1 else edges[link_idx][0]
                neighbor_nd  = node_name(neighbor_idx)
                neighbor_lo  = loopback_ip(neighbor_idx, with_prefix=False)

                neighbors.append({
                    "name":        neighbor_nd,
                    "id":          neighbor_idx,
                    "eth":         eth_idx,
                    "link_ip":     their_ip,
                    "loopback_ip": neighbor_lo,
                })

                iface_frr_lines += [f"interface eth{eth_idx}", f" ip address {my_ip}"]
                if ospf:
                    iface_frr_lines += [
                        " ip ospf network point-to-point",
                        " ip ospf hello-interval 10",
                        " ip ospf dead-interval 40",
                    ]
                if multicast:
                    iface_frr_lines.append(" ip pim")
                iface_frr_lines.append("!")
                ospf_networks.append(subnet)
            else:
                subnet, peer1_ip, peer2_ip = link_addresses(link_idx)
                my_ip      = peer2_ip
                their_ip   = peer1_ip.split("/")[0]

                station_idx = len(gnd_links)+1
                station_ng  = "gnd"+str(station_idx)
                station_lo  = loopback_ip(station_idx+n, with_prefix=False)

                gnd_links.append({
                    "name":        station_ng,
                    "id":          station_idx,
                    "eth":         eth_idx,
                    "link_ip":     their_ip,
                    "my_ip":       my_ip,
                    "loopback_ip": station_lo,
                })

                iface_frr_lines += [f"interface eth{eth_idx}", f" ip address {my_ip}"]
                if ospf:
                    iface_frr_lines += [
                        " ip ospf network point-to-point",
                        " ip ospf hello-interval 10",
                        " ip ospf dead-interval 40",
                    ]
                if multicast:
                    iface_frr_lines.append(" ip pim")
                iface_frr_lines.append("!")
                ospf_networks.append(subnet)

        # Build frr.conf
        lo_pim_line = [" ip pim"] if multicast else []
        frr_lines = [
            "! -*- frr default configuration -*-",
            "!",
            "service integrated-vtysh-config",
            "!",
            f"hostname {nd}",
            "!",
            "interface lo",
            f" ip address {lo_ip}",
        ] + lo_pim_line + [
            "!",
        ] + iface_frr_lines

        if ospf:
            frr_lines += [
                "router ospf",
                f" ospf router-id {lo_addr}",
                " passive-interface lo",
            ]
            for net in ospf_networks:
                frr_lines.append(f" network {net} area 0")
            frr_lines.append("!")

        if multicast:
            frr_lines += ["ip multicast-routing", "!"]

        frr_lines += ["line vty", "!"]
        frr_configs[nd] = "\n".join(frr_lines) + "\n"


        node_infos[nd] = {
            "id":                i,
            "name":              nd,
            "loopback_ip":       lo_addr,
            "neighbors":         neighbors,
            "ground_communication": gnd_links,
            "ospf_enabled":      ospf,
            "multicast_enabled": multicast,
            "multicast_group":   MCAST_GROUP if multicast else None,
            "multicast_port":    MCAST_PORT  if multicast else None,
            "isl_profile":       isl_profile,
            "topology":          topology,
        }
        if node_positions and i in node_positions:
            node_infos[nd]["position"] = node_positions[i]

    for i, ng in enumerate(station, start=1):
        lo_ip   = loopback_ip(n+i, with_prefix=True)
        lo_addr = loopback_ip(n+i, with_prefix=False)

        iface_frr_lines = []
        ospf_networks   = [lo_ip]
        neighbors       = []

        for (link_idx, is_peer1, eth_idx, with_gnd) in gnd_ifaces[ng]:
            subnet, peer1_ip, peer2_ip = link_addresses(link_idx)
            my_ip      = peer1_ip if is_peer1 else peer2_ip
            their_ip   = (peer2_ip if is_peer1 else peer1_ip).split("/")[0]

            neighbor_idx = len(neighbors)+1
            neighbor_nd  = node_name(neighbor_idx)
            neighbor_lo  = loopback_ip(neighbor_idx, with_prefix=False)

            neighbors.append({
                "name":        neighbor_nd,
                "id":          neighbor_idx,
                "eth":         eth_idx,
                "link_ip":     their_ip,
                "loopback_ip": neighbor_lo,
            })

            iface_frr_lines += [f"interface eth{eth_idx}", f" ip address {my_ip}"]
            if ospf:
                iface_frr_lines += [
                    " ip ospf network point-to-point",
                    " ip ospf hello-interval 10",
                    " ip ospf dead-interval 40",
                ]
            if multicast:
                iface_frr_lines.append(" ip pim")
            iface_frr_lines.append("!")
            ospf_networks.append(subnet)

        # Build frr.conf
        lo_pim_line = [" ip pim"] if multicast else []
        frr_lines = [
            "! -*- frr default configuration -*-",
            "!",
            "service integrated-vtysh-config",
            "!",
            f"hostname {nd}",
            "!",
            "interface lo",
            f" ip address {lo_ip}",
        ] + lo_pim_line + [
            "!",
        ] + iface_frr_lines

        if ospf:
            frr_lines += [
                "router ospf",
                f" ospf router-id {lo_addr}",
                " passive-interface lo",
            ]
            for net in ospf_networks:
                frr_lines.append(f" network {net} area 0")
            frr_lines.append("!")

        if multicast:
            frr_lines += ["ip multicast-routing", "!"]

        frr_lines += ["line vty", "!"]
        frr_configs[ng] = "\n".join(frr_lines) + "\n"

        node_infos[ng] = {
            "id":                i+n,
            "name":              ng,
            "loopback_ip":       lo_addr,
            "neighbors":         neighbors,
            "ospf_enabled":      ospf,
            "multicast_enabled": multicast,
            "multicast_group":   MCAST_GROUP if multicast else None,
            "multicast_port":    MCAST_PORT  if multicast else None,
            "isl_profile":       isl_profile,
        }


    return network_yml, frr_configs, node_infos


# ---------------------------------------------------------------------------
# .gnet packaging
# ---------------------------------------------------------------------------

def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes):
    ti = tarfile.TarInfo(name=name)
    ti.size = len(data)
    tar.addfile(ti, io.BytesIO(data))


def package_gnet(
    output_path: str,
    network_yml: str,
    frr_configs: dict,
    node_infos: dict,
    algorithms_dir: str,
):
    """
    Write a .gnet tar.gz archive containing:
      network.yml
      configs/<node>.frr.conf   (loaded by gonetem into /etc/frr/frr.conf)

    Also writes shared/algorithms/node_configs.json so algorithms can look up
    their own addressing at runtime by reading /algorithms/node_configs.json.
    """
    with open(output_path, "wb") as f:
        with tarfile.open(fileobj=f, mode="w:gz") as tar:
            # Add a configs/ directory entry
            dir_ti = tarfile.TarInfo(name="configs")
            dir_ti.type = tarfile.DIRTYPE
            dir_ti.mode = 0o755
            tar.addfile(dir_ti)

            # network.yml
            _add_bytes(tar, "network.yml", network_yml.encode())

            # Per-node frr.conf
            for nd, conf in frr_configs.items():
                _add_bytes(tar, f"configs/{nd}.frr.conf", conf.encode())

    # Write node_configs.json to the algorithms volume so running containers
    # can read /algorithms/node_configs.json to discover their own addresses.
    os.makedirs(algorithms_dir, exist_ok=True)
    node_cfg_path = os.path.join(algorithms_dir, "node_configs.json")
    with open(node_cfg_path, "w") as f:
        json.dump(node_infos, f, indent=2)
    print(f"Written node_configs.json → {node_cfg_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate a gonetem .gnet topology for satellite swarm emulation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--nodes", "-n", type=int, default=10,
        help="Number of satellite nodes (default: 10)")
    parser.add_argument("--topology", "-t", choices=TOPOLOGY_CHOICES, default="ring",
        help="Network topology (default: ring)")
    parser.add_argument("--isl-profile", "-p", choices=list(ISL_PROFILES.keys()),
        default="leo",
        help="ISL link emulation profile: leo | geo | deep-space | none (default: leo)")
    parser.add_argument("--output", "-o", default=None,
        help="Output .gnet file path (default: swarm_<topology>_<n>[_noospf].gnet)")
    parser.add_argument("--ground-station", "-g", type=int, default=0,
        dest="ground_station",
        help="Number of ground station nodes (default: 0)")

    ospf_group = parser.add_mutually_exclusive_group()
    ospf_group.add_argument("--ospf", dest="ospf", action="store_true", default=False,
        help="Enable OSPF routing – full reachability across the topology")
    ospf_group.add_argument("--no-ospf", dest="ospf", action="store_false",
        help="Disable OSPF – nodes can only reach directly-connected neighbours (default)")

    mcast_group = parser.add_mutually_exclusive_group()
    mcast_group.add_argument("--multicast", dest="multicast", action="store_true", default=False,
        help=f"Enable PIM-DM multicast routing (group {MCAST_GROUP}:{MCAST_PORT})")
    mcast_group.add_argument("--no-multicast", dest="multicast", action="store_false",
        help="Disable multicast/PIM (default)")

    parser.add_argument("--branch", type=int, default=2,
        help="Branching factor for tree topology (default: 2)")
    parser.add_argument("--cluster-size", type=int, default=5,
        help="Nodes per cluster for clustered topology (default: 5)")
    parser.add_argument("--sparse-distance", type=int, default=2,
        help="Max neighbour index distance for sparse topology (default: 2)")
    parser.add_argument("--algorithms-dir", default=DEFAULT_ALGORITHMS_DIR,
        help=f"Host path mounted at /algorithms in each container (default: {DEFAULT_ALGORITHMS_DIR})")
    parser.add_argument("--logs-dir", default=DEFAULT_LOGS_DIR,
        help=f"Host path mounted at /logs in each container (default: {DEFAULT_LOGS_DIR})")
    parser.add_argument("--from-graph", metavar="FILE", default=None,
        help="Path to a NetworkX JSON file (node-link format) to use as the satellite topology. "
             "Satellite nodes and InterSatelliteLink edges are extracted automatically; "
             "--topology and --nodes are ignored when this is set.")

    args = parser.parse_args()

    # ---- resolve edges and node count from graph file if provided -----------
    nx_edges = None
    nx_positions = None
    topology_label = args.topology

    if args.from_graph:
        G = load_networkx_graph(args.from_graph)
        nx_edges, _, nx_positions = edges_from_networkx(G)
        if not nx_edges:
            parser.error(f"No InterSatelliteLink edges found in {args.from_graph}")
        all_indices = {i for edge in nx_edges for i in edge}
        args.nodes = max(all_indices)
        topology_label = os.path.splitext(os.path.basename(args.from_graph))[0]
        print(f"Loaded graph from {args.from_graph}: "
              f"{args.nodes} satellites, {len(nx_edges)} ISLs")

    if args.nodes < 2:
        parser.error("--nodes must be at least 2")
    if args.nodes > 255:
        parser.error("--nodes must be ≤ 255 (loopback IP space)")

    if args.output is None:
        ospf_suffix  = "_ospf" if args.ospf else ""
        mcast_suffix = "_mcast" if args.multicast else ""
        args.output = f"swarm_{topology_label}_{args.nodes}{ospf_suffix}{mcast_suffix}.gnet"

    print(f"Generating {topology_label} topology with {args.nodes} satellite nodes and {args.ground_station} ground stations "
          f"[ISL: {args.isl_profile}] "
          f"[OSPF: {'on' if args.ospf else 'off'}] "
          f"[Multicast: {'on' if args.multicast else 'off'}]")

    network_yml, frr_configs, node_infos = generate(
        n=args.nodes,
        nb_gnd_station=args.ground_station,
        topology=topology_label,
        isl_profile=args.isl_profile,
        ospf=args.ospf,
        multicast=args.multicast,
        branch=args.branch,
        cluster_size=args.cluster_size,
        sparse_distance=args.sparse_distance,
        algorithms_dir=args.algorithms_dir,
        logs_dir=args.logs_dir,
        edges=nx_edges,
        node_positions=nx_positions,
    )

    package_gnet(args.output, network_yml, frr_configs, node_infos, args.algorithms_dir)

    total_links = len(nx_edges) if nx_edges is not None else len(
        get_edges(args.nodes, args.topology,
                  branch=args.branch,
                  cluster_size=args.cluster_size,
                  sparse_distance=args.sparse_distance))
    print(f"Created {args.output}")
    print(f"  Nodes : {args.nodes}")
    print(f"  Links : {total_links}")
    print(f"  OSPF      : {'enabled' if args.ospf else 'disabled'}")
    print(f"  Multicast : {'enabled (' + MCAST_GROUP + ':' + str(MCAST_PORT) + ')' if args.multicast else 'disabled'}")
    print()
    print("Node addressing summary:")
    print(f"  Loopback range : 10.255.0.1/32 – 10.255.0.{args.nodes}/32")
    print(f"  Link subnets   : 10.0.0.0/30 – … (sequential /30 blocks)")
    print()
    for nd, info in node_infos.items():
        nb_names = [nb["name"] for nb in info["neighbors"]]
        print(f"  {nd:8s}  lo=10.255.0.{info['id']}/32  neighbours={nb_names}")


if __name__ == "__main__":
    main()
