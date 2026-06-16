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
| Concurrent CRDT Tree | K uplinks to K spread-out satellites simultaneously; tree broadcast | K |

The key claim: CRDTs reduce the required ground communication from N to 1 per
catalog update, regardless of swarm size.  The concurrent test additionally shows
that CRDT-aware deduplication keeps ISL traffic sub-linear even when multiple
updates are injected simultaneously from different network endpoints.

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

**Case 4 – Concurrent CRDT Tree** (N start-point satellites, no delay between sends):

This case injects N versions of the same tracked object into N different satellites
simultaneously, with no delay between sends.  The goal is to show that CRDT-aware
deduplication keeps ISL traffic sub-linear even when multiple conflicting updates
are in flight across the network at the same time.

Satellite endpoints are selected by spreading N indices evenly across the 66-satellite
pool using the formula:

```
endpoint[i] = sat{ 1 + round(i × (66 − 1) / (N − 1)) }   for i = 0 … N−1
```

Examples:
- N=1  → [sat1]
- N=3  → [sat1, sat34, sat66]
- N=5  → [sat1, sat17, sat33, sat50, sat66]
- N=10 → [sat1, sat8, sat15, sat23, sat30, sat37, sat44, sat52, sat59, sat66]

Each endpoint receives a strictly newer version than the previous one: endpoint[0]
gets ts=1, endpoint[1] gets ts=2, …, endpoint[N−1] gets ts=N.  Each send uses a
different sequential GP entry for the chosen object from `data/test.json`, so the
value (orbital data) differs across sends as well.  In the end the whole network
converges to ts=N.

The sends are logically simultaneous: the ground script issues all N uplinks with no
`sleep` between them.  Because ISL propagation is much slower than the ground
uplink rate, the earlier updates are still spreading through the network when later
ones are injected, creating genuine in-flight conflicts for the dedup logic to resolve.

Archive each run into `shared/logs/concurrent_N/`:

```bash
./run_test.sh clean && ./run_test.sh isl-tune
./run_test.sh fullstart concurrent_tree --updates 1
# wait ~120 s, then:
./run_test.sh archive concurrent_1

./run_test.sh clean && ./run_test.sh isl-tune
./run_test.sh fullstart concurrent_tree --updates 5
./run_test.sh archive concurrent_5

./run_test.sh clean && ./run_test.sh isl-tune
./run_test.sh fullstart concurrent_tree --updates 10
./run_test.sh archive concurrent_10

./run_test.sh clean && ./run_test.sh isl-tune
./run_test.sh fullstart concurrent_tree --updates 20
./run_test.sh archive concurrent_20
```

Results for the 66-satellite Iridium-graph topology:

| N updates | GS msgs | ISL data msgs | Naive ISL | Saving | Convergence |
|-----------|---------|---------------|-----------|--------|-------------|
| 1         | 1       | 65            | 65        | —      | OK (v1)     |
| 5         | 5       | 197           | 325       | 39%    | OK (v5)     |
| 10        | 10      | 235           | 650       | 64%    | OK (v10)    |
| 20        | 20      | 346           | 1300      | 73%    | OK (v20)    |

Naive ISL = N × 65 (what N independent non-deduplicating floods would cost).
ISL data excludes the one-time spanning-tree setup overhead (type=8, 354 messages).

Generate the scalability bar chart:

```bash
python3 plot_concurrent.py \
    --base-dir shared/logs \
    --output shared/logs/concurrent_scalability.pdf
```

### Parameters

| Parameter | Scripts | Default | Description |
|---|---|---|---|
| `--updates N` | all gnd scripts | 1 | Number of catalog entries / start points to send |
| `--update-interval S` | `ssa_crdt_gnd`, `ssa_tree_gnd` | 30 | Seconds between consecutive sends |
| `--object-id ID` | `ssa_tree_gnd`, `concurrent_tree_gnd` | `1998-067A` | NORAD object ID to use (ISS by default) |

For Cases 1–3, `--updates N` sends N sequential GP entries cycling through
`data/test.json`.  For Case 4 (concurrent tree), `--updates N` selects N
start-point satellites and sends one GP entry per start point (ts=1…ts=N),
with no delay between sends.

`--object-id` filters `data/test.json` to a specific tracked object so that
each sequential send uses genuinely different orbital data for the same NORAD ID.

The `--updates` and `--object-id` flags are accepted (and ignored) by all
satellite scripts so that `fullstart` can pass them to both sides without error.

Example with 3 updates:

```bash
./run_test.sh fullstart ssa_crdt --updates 3 --update-interval 30
```

Total GS messages will be 3 for CRDT cases and 3 × 66 = 198 for the control.

### Generating the results table

After archiving all cases:

```bash
python3 shared/algorithms/analyze_ssa.py \
    shared/logs/control \
    shared/logs/crdt \
    shared/logs/tree \
    shared/logs/concurrent \
    shared/logs
```

The 4th argument is the Case 4 archive directory; the 5th is the base directory
containing the `concurrent_1/`, `concurrent_5/`, `concurrent_10/`, and
`concurrent_20/` subdirectories used for the scalability table.  Both are
optional — omit them to compare only the first three cases.

Output includes:

- **Message counts table** — GS messages, ISL messages, and total per case.
  For Cases 3 and 4 a second row shows ISL messages excluding spanning-tree
  setup traffic (type=8), which is a one-time overhead amortized across many
  updates.
- **Catalog convergence check** — reads `catalog_sat*.csv` (or
  `catalog_conc_sat*.csv` for Case 4) from each archive and confirms every
  satellite converged to the same catalog state (same item IDs and LWW
  versions).  Any divergence is printed item-by-item.
- **Concurrent update scalability table** — ISL data messages vs N for
  N=1/5/10/20, including naive baseline and saving percentage.

### Output files per node

| File | Location | Contents |
|---|---|---|
| `gnd_ssa_<case>.log` | `shared/logs/` | Ground sends (Cases 1–3): `SNT\|<target>\|<counter>\|id=…\|ts=…` |
| `gnd_concurrent_tree.log` | `shared/logs/` | Ground sends (Case 4): same format, one line per start-point |
| `journal_<node>.log` | `shared/logs/` | Every RCV / SNT / TRA event with local timestamp |
| `catalog_<node>.csv` | `shared/logs/` | Final catalog snapshot (Cases 1–3): item_id, object_name, epoch, version |
| `catalog_conc_<node>.csv` | `shared/logs/` | Final catalog snapshot (Case 4): same columns |

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
update  assign(id, value, timestamp, source):
    if store[id] is empty or timestamp >= store[id].timestamp:
        store[id] = {value, timestamp, source}
```

`source` is the satellite that first injected this broadcast (the ground-uplink
recipient), not the current relay hop.  It is preserved unchanged as the message
travels across the tree.

The `>=` rule means a same-timestamp message from a *different* source always
replaces the local copy (last writer wins on ties).  ISL forwarding drops a
message only in two cases:

1. `incoming_ts < local_ts` — stale; a newer version is already stored.
2. `incoming_ts == local_ts` **and** `incoming_source == local_source` — true
   duplicate; the same broadcast wave has already passed through this node.

The ground is the sole timestamp authority: it assigns ts=1 to the first
start-point, ts=2 to the second, and so on, so each new send strictly wins at
every satellite that has not yet received it.

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