# GonetemSwarm

Gonetem-based satellite swarm emulation environment. A drop-in replacement for
ConSwarm that uses [gonetem](https://github.com/mroy31/gonetem) for proper network
emulation with OSPF routing via FRR.

## Key Features

| | GonetemSwarm |
|---|---|
| Topology enforcement | Native links; only declared links exist |
| Routing | OSPF (FRR) optional; direct link-IP routing for no-OSPF topologies |
| Link emulation | Declared per-link in `.gnet`; gonetem applies netem |
| Test start | `gonetem-console open <file>.gnet` |
| Algorithm run | `run_test.sh start <algo>` |

## Quick start

### 0. Build the satellite Docker image (once)

```bash
./build_image.sh
```

This extends `mroy31/gonetem-frr:0.6.0` (Debian + FRR with `ospfd`) with
Python 3, NumPy, Matplotlib, and netifaces. `build_image.sh` reads the version
from `../gonetem/VERSION` automatically, so it stays correct after upgrades.

### 1. Start gonetem-server (once per session)

The server requires root. Point it at the local `server.yaml`:

```bash
sudo gonetem-server --conf-file ./server.yaml
```

Leave this running in a dedicated terminal. The console connects to
`localhost:10110` by default, which matches the config.

### 2. Generate a topology

```bash
# 10-node ring, LEO link conditions, OSPF on (default)
python3 generate_topology.py --nodes 10 --topology ring --isl-profile leo

# Same topology but with multicast enabled via PIM
python3 generate_topology.py --nodes 10 --topology ring --isl-profile leo --multicast

# Same topology but no OSPF (only directly-connected peers reachable)
python3 generate_topology.py --nodes 10 --topology ring --isl-profile leo --no-ospf

# Other topologies
python3 generate_topology.py --nodes 6  --topology star
python3 generate_topology.py --nodes 16 --topology grid
python3 generate_topology.py --nodes 10 --topology tree --branch 3
python3 generate_topology.py --nodes 15 --topology clustered --cluster-size 5
python3 generate_topology.py --nodes 30 --topology full-mesh
python3 generate_topology.py --nodes 10 --topology sparse --sparse-distance 3
```

This creates `swarm_<topology>_<N>.gnet` (a tar.gz archive) **and** writes
`shared/algorithms/node_configs.json` with per-node addressing info (useful for
ported algorithms).

### 3. Drop your algorithms in shared/algorithms

All satellite containers mount `shared/algorithms` at `/algorithms` (read-only)
and `shared/logs` at `/logs` (read-write).

### 4. Start the topology in gonetem

In **terminal A**:

```bash
gonetem-console open swarm_ring_10.gnet
```

Gonetem starts all nodes, loads the FRR configs, and begins OSPF convergence.
Wait for the prompt — the topology is ready when you see `[swarm_ring_10]>`.

Optionally verify OSPF:
```
[swarm_ring_10]> exec sat1 "vtysh -c 'show ip ospf neighbor'"
```

### 5. Visually inspect the topology

In **terminal B**:

```bash
# Start Topology Discovery on all nodes
./run_test.sh start topology_discovery

# Check which algorithms are running
./run_test.sh status
```
`topology.png` will appear once the script terminated on each node.

```bash
# Clear the logs directory
./run_test.sh clean
```

### 6. Run a test

In **terminal B**:

```bash
# Satellites only
./run_test.sh start <algorithm>

# Ground stations only
./run_test.sh gndstart <algorithm>

# Both — automatically picks <algorithm>_sat.py for sats and <algorithm>_gnd.py for ground stations
./run_test.sh fullstart <algorithm> [args...]

# Check which algorithms are running
./run_test.sh status

# Tail log files
./run_test.sh logs <algorithm>

# Stop all algorithm processes
./run_test.sh stop

# Clear the logs directory
./run_test.sh clean

# Archive logs to shared/logs/<name>/ for later analysis
./run_test.sh archive <name>
```

For algorithms with payloads larger than ~100 bytes (e.g. CRDT broadcasts), run
this once after opening the topology to widen the ISL token-bucket burst size:

```bash
./run_test.sh isl-tune
```

Without it, packets are silently dropped at the link layer.


---

## SSA catalog dissemination tests

Three experiments that compare the cost of disseminating a Space Situational
Awareness (SSA) catalog update across a 66-satellite Iridium-like swarm.

| Case | Method | GS messages per update |
|---|---|---|
| Control | Direct uplink to every satellite individually | N (one per satellite) |
| CRDT Flood | One uplink to sat1; reliable flood via ISL | 1 |
| CRDT Tree | One uplink to sat1; spanning-tree broadcast via ISL | 1 |

The key claim: CRDTs reduce the required ground communication from N to 1 per
catalog update, regardless of swarm size.

### Topology

The tests use the pre-generated Iridium-graph topology (`swarm_iridium_graph_66.gnet`),
which places one ground station (`gnd1`) with direct links to all 66 satellites.

```bash
gonetem-console open swarm_iridium_graph_66.gnet
```

### Critical: tune ISL burst before running

The default gonetem TBF burst (100 bytes) silently drops CRDT payloads
(400–600 bytes). Run this once after opening the topology:

```bash
./run_test.sh isl-tune
```

### Running the three cases

Each case has paired `_sat` / `_gnd` scripts launched together via `fullstart`.

**Case 1 – Control** (~5 min for 1 update across 66 satellites):

```bash
./run_test.sh clean
./run_test.sh fullstart ssa_control --updates 1
# wait for ground script to finish (5s × 66 satellites per update), then:
./run_test.sh archive control
```

**Case 2 – CRDT Flood** (~110 s for 1 update, configurable):

```bash
./run_test.sh clean
./run_test.sh isl-tune
./run_test.sh fullstart ssa_crdt --updates 1
# wait ~100 s, then:
./run_test.sh archive crdt
```

**Case 3 – CRDT Tree** (~120 s for 1 update; extra time for spanning-tree build):

```bash
./run_test.sh clean
./run_test.sh isl-tune
./run_test.sh fullstart ssa_tree --updates 1
# wait ~110 s, then:
./run_test.sh archive tree
```

### Parameters

| Parameter | Scripts | Default | Description |
|---|---|---|---|
| `--updates N` | all gnd scripts | 1 | Number of catalog entries to send |
| `--update-interval S` | `ssa_crdt_gnd`, `ssa_tree_gnd` | 30 | Seconds between consecutive sends |

`--updates N` cycles through the first N entries of `data/test.json`.  When the
same object ID appears more than once (after the first 5 entries), the ground
increments a per-item counter that becomes the LWW timestamp, so each
re-send strictly wins over the previous version at every satellite.

The `--updates` flag is also accepted (and ignored) by the satellite scripts so
that `fullstart` can pass it to both sides without error.

Example with 3 updates:

```bash
./run_test.sh fullstart ssa_crdt --updates 3 --update-interval 30
```

Total GS messages will be 3 for CRDT cases and 3 × 66 = 198 for the control.

### Generating the results table

After archiving all three cases:

```bash
python3 shared/algorithms/analyze_ssa.py \
    shared/logs/control \
    shared/logs/crdt \
    shared/logs/tree
```

Output includes:

- **Message counts table** — GS messages, ISL messages, and total per case.
  For Case 3 a second row shows ISL messages excluding spanning-tree setup
  traffic (type=8), which is a one-time overhead amortized across many updates.
- **Catalog convergence check** — reads `catalog_sat*.csv` from each archive
  and confirms every satellite converged to the same catalog state (same item
  IDs and LWW versions).  Any divergence is printed item-by-item.

### Output files per node

| File | Location | Contents |
|---|---|---|
| `gnd_ssa_<case>.log` | `shared/logs/` | Ground sends: `SNT\|<target>\|<counter>\|id=…\|ts=…` |
| `journal_<node>.log` | `shared/logs/` | Every RCV / SNT / TRA event with local timestamp |
| `catalog_<node>.csv` | `shared/logs/` | Final catalog snapshot: item_id, object_name, epoch, version |

### Verifying ISL message counts

The ISL counts produced by `analyze_ssa.py` can be verified analytically from
the topology graph alone:

| Case | Formula | Iridium-66 result |
|---|---|---|
| CRDT Flood | `2E − N + 1` | 2 × 121 − 66 + 1 = **177** |
| CRDT Tree (data only) | `N − 1` | 66 − 1 = **65** |

Where `E` = number of undirected ISL edges and `N` = number of satellites.

The flood formula comes from the initiating satellite broadcasting to all its
neighbours, then every other satellite relaying to all neighbours except the one
it received from (`degree − 1` each).  The tree formula is exact by definition:
a spanning tree on N nodes has N − 1 edges, each traversed once.

To compute E for any topology:

```bash
python3 -c "
import json
with open('shared/algorithms/node_configs.json') as f:
    cfg = json.load(f)
sats = {k: v for k, v in cfg.items() if k.startswith('sat')}
N = len(sats)
E = sum(len(v['neighbors']) for v in sats.values()) // 2
print(f'N={N}  E={E}  flood={2*E - N + 1}  tree={N-1}')
"
```

### LWW merge semantics

All satellite scripts implement the same Last-Write-Wins register:

```
update  assign(id, value, timestamp):
    if store[id] is empty or timestamp > store[id].timestamp:
        store[id] = {value, timestamp}
```

The ground is the sole timestamp authority: it increments a per-item counter
each time the same object ID is sent.  Out-of-order ISL delivery is handled
correctly because a lower-timestamp copy arriving late is silently dropped.

---

## Topology reference

| Topology | Description | Key option |
|---|---|---|
| `ring` | Circular chain, 2 neighbours each | – |
| `line` | Linear chain, no wrap-around | – |
| `star` | Node 1 is hub, all others are spokes | – |
| `tree` | k-ary rooted tree (node 1 = root) | `--branch K` |
| `grid` | 2-D mesh, ≈√N × √N | – |
| `clustered` | Full mesh within clusters + inter-cluster chain | `--cluster-size G` |
| `sparse` | Each node connects to nodes within D index positions | `--sparse-distance D` |
| `full-mesh` | All pairs connected | – |

## ISL profiles

| Profile | Delay | Jitter | Loss | Bandwidth |
|---|---|---|---|---|
| `leo` | 125 ms | 25 ms | 0.001 % | 200 Kbit/s |
| `geo` | 250 ms | 25 ms | 0.001 % | 100 Mbit/s |
| `deep-space` | 2000 ms | 100 ms | 0.1 % | 64 kbit/s |
| `none` | – | – | – | – |


## Addressing scheme

```
Loopback  :  10.255.0.N/32       (stable identity for node N)
Link k    :  10.0.X.Y/30         (sequential /30 blocks from 10.0.0.0)
              peer1 → 10.0.X.Y+1
              peer2 → 10.0.X.Y+2
```

The file `shared/algorithms/node_configs.json` (written at generation time)
contains the full per-node addressing map. Algorithms can read it at runtime:

```python
import json, os
with open("/algorithms/node_configs.json") as f:
    all_nodes = json.load(f)
me = all_nodes[os.environ["HOSTNAME"]]  # HOSTNAME is the node name, e.g. "sat3"
# me["loopback_ip"]                – stable identity (use with OSPF)
# me["neighbors"][i]["link_ip"]    – direct link address (used by Transceiver)
# me["neighbors"][i]["name"]       – neighbour node name
```