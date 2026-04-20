# GonetemSwarm

Gonetem-based satellite swarm emulation environment. A drop-in replacement for
ConSwarm that uses [gonetem](https://github.com/mroy31/gonetem) for proper network
emulation with OSPF routing via FRR.

## Key Features

| | GonetemSwarm |
|---|---|
| Topology enforcement | Native links; only declared links exist |
| Routing | OSPF (FRR) – any node reaches any other |
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
# Start the test on all nodes (accepts parameters if needed)
./run_test.sh start test_name

# Check which algorithms are running
./run_test.sh status

# Tail log files
./run_test.sh logs test_name

# Stop all algorithm processes
./run_test.sh stop

# Clear the logs directory
./run_test.sh clean
```

### 7. Verify OSPF convergence

```bash
./run_test.sh ospf-check
```

Or interactively from the gonetem console:
```
[swarm_ring_10]> exec sat1 "vtysh -c 'show ip route'"
[swarm_ring_10]> exec sat1 "vtysh -c 'show ip ospf neighbor'"
```

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

## ISL profiles (Needs revision)

| Profile | Delay | Jitter | Loss | Bandwidth |
|---|---|---|---|---|
| `leo` | 20 ms | 5 ms | 0.01 % | 10 Mbit/s |
| `geo` | 250 ms | 25 ms | 0.001 % | 100 Mbit/s |
| `deep-space` | 2000 ms | 100 ms | 0.1 % | 64 kbit/s |
| `none` | – | – | – | – |

## OSPF vs no-OSPF

**With OSPF** (`--ospf`, default): FRR's `ospfd` runs on every satellite.
Once converged, any node can reach any other using their loopback addresses
(`10.255.0.N`). This is the intended production mode.

**Without OSPF** (`--no-ospf`): Interface IPs are still configured but `ospfd`
is not instructed to form adjacencies. Reachability is limited to
directly-connected neighbours (within the same /30 link subnet). Useful for
testing algorithms that rely purely on neighbour-to-neighbour communication.

## Addressing scheme

```
Loopback  :  10.255.0.N/32       (stable identity for node N)
Link k    :  10.0.X.Y/30         (sequential /30 blocks from 10.0.0.0)
              peer1 → 10.0.X.Y+1
              peer2 → 10.0.X.Y+2
OSPF area :  0 (all links)
```

The file `shared/algorithms/node_configs.json` (written at generation time)
contains the full per-node addressing map including neighbour loopback IPs.
Algorithms can read `/algorithms/node_configs.json` at runtime:

```python
import json, os
with open("/algorithms/node_configs.json") as f:
    all_nodes = json.load(f)
me = all_nodes[os.environ["SAT_NAME"]]
# me["loopback_ip"], me["neighbors"][i]["loopback_ip"], etc.
```

## Directory layout

```
GonetemSwarm/
├── server.yaml            # gonetem-server config (local workdir, localhost:10110)
├── generate_topology.py   # .gnet file generator
├── run_test.sh            # Algorithm runner (uses docker exec via node labels)
├── Dockerfile.satellite   # gonetem-frr + Python 3 / numpy / matplotlib
├── build_image.sh         # docker build helper
└── shared/
    ├── algorithms/        # Drop algorithm .py files here; mounted at /algorithms
    └── logs/              # Algorithm output; mounted at /logs
```

## Porting algorithms from ConSwarm

The main changes needed in algorithm code:

1. **Node identity**: read from `SAT_ID` / `SAT_NAME` env vars (unchanged) or
   from `/algorithms/node_configs.json`.

2. **Neighbour discovery**: already known from `node_configs.json`; no need for
   broadcast discovery unless the algorithm requires it at runtime.

3. **Communication address**: with OSPF, use **loopback IPs** (`10.255.0.N`) for
   unicast — these are reachable from anywhere in the topology regardless of
   which physical links are up. The `SatelliteNode` base class will need updating
   to bind/send to loopback addresses rather than a shared broadcast subnet.

4. **Topology-wide messaging**: UDP broadcast doesn't cross point-to-point OSPF
   links. Two alternatives:

   **Option A — unicast-to-all** (no extra setup, works with any topology):
   ```python
   import json, os, socket
   with open("/algorithms/node_configs.json") as f:
       ALL_NODES = json.load(f)
   MY_NAME = os.environ["SAT_NAME"]

   def send_to_all(data: bytes, port: int = 5007):
       sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
       for name, info in ALL_NODES.items():
           if name != MY_NAME:
               sock.sendto(data, (info["loopback_ip"], port))
       sock.close()
   ```

   **Option B — IP multicast via PIM-DM** (requires `--multicast` flag at
   generation time; `pimd` is already running in the satellite image):
   ```bash
   python3 generate_topology.py --nodes 10 --topology ring --multicast
   ```
   Group address and port are written into `node_configs.json` as
   `multicast_group` / `multicast_port`. Use them in algorithm code:
   ```python
   import json, os, socket, struct
   with open("/algorithms/node_configs.json") as f:
       info = json.load(f)[os.environ["SAT_NAME"]]
   MCAST_GRP  = info["multicast_group"]   # "239.0.1.1"
   MCAST_PORT = info["multicast_port"]    # 5007
   MY_LO      = info["loopback_ip"]

   # Sender — bind to loopback so the kernel RPF check passes
   def send_multicast(data: bytes):
       sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
       sock.bind((MY_LO, 0))
       sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 32)
       sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)
       sock.sendto(data, (MCAST_GRP, MCAST_PORT))
       sock.close()

   # Receiver — call once at startup
   def create_mcast_receiver() -> socket.socket:
       sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
       sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
       sock.bind(("", MCAST_PORT))
       mreq = struct.pack("4sL", socket.inet_aton(MCAST_GRP), socket.INADDR_ANY)
       sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
       return sock
   ```
   Avoid `224.0.0.5` (used internally by OSPF).

5. **Log path**: change `/app/logs/` → `/logs/`.
