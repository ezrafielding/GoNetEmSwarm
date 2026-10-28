# A Distributed Computing Framework for Satellite Swarms

[![GitHub License](https://img.shields.io/github/license/ezrafielding/GoNetEmSwarm)](https://github.com/ezrafielding/GoNetEmSwarm/blob/main/LICENSE) [![arXiv](https://img.shields.io/badge/arXiv-2609.18839-b31b1b.svg)](https://arxiv.org/abs/2609.18839)

This repository contains the code for reproducing the experiments in [*A Distributed Computing Framework for Satellite Swarms*](https://arxiv.org/abs/2609.18839) (STWiMob'2026).

## Abstract

The rise of large satellite constellations and Distributed Space Systems (DSS) demands generalized frameworks that enable fault-tolerant, autonomous distributed space applications. Conventional ground-centric command and control does not scale to systems of tens or hundreds of satellites, motivating the adoption of distributed computing. This paper introduces a conceptual distributed computing framework for satellite swarms, covering distributed state, command and control, and scientific mission. As a first validation step, a strongly eventually consistent distributed state service is designed and implemented using Conflict-free Replicated Data Types (CRDT), specifically a Last-Write-Wins Register-based key-value store. The service is evaluated in the context of Space Situational Awareness catalog dissemination across a simulated 66-satellite constellation emulated with GoNetEm. Results show that the CRDT-based approach reduces ground-to-satellite communication from 66 messages to a single uplink per update, with tree traversal matching the total message count of direct uplink. Under concurrent updates, sub-linear inter-satellite message growth is observed as nodes discard outdated versions, further reducing network overhead. These results demonstrate the viability of a CRDT-based distributed state as a scalable and fault-tolerant foundation for satellite swarm applications.

## Citation

E. Fielding, C. Demazure, G. Silvestre, F. Alves Suana and P. Queinnec, "A Distributed Computing Framework for Satellite Swarms," in *Nineteen International Workshop on Selected Topics in Mobile and Wireless Computing - 2026 (STWiMob'2026)*, Avignon, France, Oct. 2026.

```bibtex
@INPROCEEDINGS{Fiel2610:Distributed,
  AUTHOR    = "Ezra Fielding and Clement Demazure and Guthemberg Silvestre and Felipe {Alves Suana} and Philippe Queinnec",
  TITLE     = "A Distributed Computing Framework for Satellite Swarms",
  BOOKTITLE = "Nineteen International Workshop on Selected Topics in Mobile and Wireless Computing - 2026 (STWiMob'2026)",
  ADDRESS   = "Avignon, France",
  DAYS      = 14,
  MONTH     = oct,
  YEAR      = 2026,
  KEYWORDS  = "Distributed Space Systems; Distributed Computing; Conflict-free Replicated Data Types"
}
```

## Data

The catalog data in `shared/algorithms/data/test.json` was obtained from [CelesTrak](https://celestrak.org). It contains the general perturbation (GP) data of five tracked objects over one year: the ISS, GOES 14, ZACUBE-1, HORYU-4 and TIANZHOU-9, with epochs from 2025-01-01 to 2026-01-01.

## Requirements

- A Linux host with root access. GoNetEm creates network namespaces and virtual links, which needs root.
- Docker. Your user must be able to run `docker`; if it can't, run `run_test.sh` with `sudo`.
- Go ≥ 1.24, `git` and `make`, to build GoNetEm.
- [uv](https://docs.astral.sh/uv/), for the host-side Python scripts.

The emulation uses the original [GoNetEm](https://github.com/mroy31/gonetem) v0.6.0, not SatGoNetEm. The constellation graph produced with SatComTopology is already included as `iridium_graph.json`.

## Setup

Run all commands from the repository root unless a step says otherwise.

**1. Clone this repository and install the Python environment.**

```bash
git clone https://github.com/ezrafielding/GoNetEmSwarm.git
cd GoNetEmSwarm
uv sync
```

**2. Build and install GoNetEm v0.6.0.** Clone it next to this repository, in a directory named `gonetem`, because `build_image.sh` reads `../gonetem/VERSION`.

```bash
git clone https://github.com/mroy31/gonetem.git ../gonetem
cd ../gonetem
git checkout v0.6.0
make build-amd64            # or build-arm64
sudo cp bin/gonetem-server_amd64  /usr/local/bin/gonetem-server
sudo cp bin/gonetem-console_amd64 /usr/local/bin/gonetem-console
cd ../GoNetEmSwarm
```

**3. Build the satellite and ground-station Docker images.**

```bash
./build_image.sh
```

**4. Generate the 66-satellite topology.**

```bash
uv run python generate_topology.py --from-graph iridium_graph.json --ground-station 1 --isl-profile leo
```

This writes two files: the GoNetEm project `swarm_iridium_graph_66.gnet`, and `shared/algorithms/node_configs.json`, which the algorithms read at runtime. The `.gnet` file contains absolute paths, so generate it on the machine that will run the experiments.

**5. Start the GoNetEm server.** It runs in the foreground, so give it its own terminal and leave it running.

```bash
sudo gonetem-server -conf-file ./config.yaml
```

**6. Pull GoNetEm's Docker images.** Open a second terminal in the repository root and run this command. The server must be running. You only need to do this the first time you use GoNetEm.

```bash
gonetem-console pull
```

**7. Open the topology.** Run this in the second terminal, wait for the `[swarm_iridium_graph_66]>` prompt, then leave the terminal open. Type `quit` at the prompt when you are finished.

```bash
gonetem-console open swarm_iridium_graph_66.gnet
```

**8. Increase the link burst size.** Open a third terminal in the repository root; you'll also run the experiments from here. Run this command once each time you open the topology:

```bash
./run_test.sh isl-tune
```

> This step is required. GoNetEm's default 100-byte burst silently drops the CRDT messages, so updates never propagate.

## Running the experiments

Run every test from the third terminal you opened in step 8, one at a time. Each test follows the same steps:

1. Stop any previous run and clear its logs.
2. Start the test.
3. Wait until the ground log contains a `DONE` line.
4. Stop the satellites and archive the logs to `shared/logs/<name>/`.

The satellite scripts run until they are stopped, so always run `./run_test.sh stop` before you start the next test.

### Single-update tests

| Test | `<case>` | `<name>` | Duration |
|---|---|---|---|
| Direct Uplink (No ISL) | `ssa_control` | `control` | ~6 min |
| CRDT + Flooding | `ssa_crdt` | `crdt` | ~40 s |
| CRDT + Tree Traversal | `ssa_tree` | `tree` | ~50 s |

Run each test with the following commands, substituting `<case>` and `<name>` from the table:

```bash
./run_test.sh stop; ./run_test.sh clean
./run_test.sh fullstart <case> --updates 1
until grep -q DONE shared/logs/gnd_<case>.log 2>/dev/null; do sleep 5; done
./run_test.sh stop
./run_test.sh archive <name>
```

### Multi-update tests

These commands run the concurrent tree test once for each value of N:

```bash
for N in 1 5 10 20; do
    ./run_test.sh stop; ./run_test.sh clean
    ./run_test.sh fullstart concurrent_tree --updates $N
    until grep -q DONE shared/logs/gnd_concurrent_tree.log 2>/dev/null; do sleep 5; done
    ./run_test.sh stop
    ./run_test.sh archive concurrent_$N
done
```

## Analysing the results

This command prints the message counts (Table I), checks that every satellite's catalog converged, and prints the concurrent-update table:

```bash
uv run python shared/algorithms/analyze_ssa.py \
    shared/logs/control shared/logs/crdt shared/logs/tree \
    shared/logs/concurrent_20 shared/logs
```

For the tree cases, use the "data only" row, which excludes the one-time messages that build the spanning tree.

This command plots the multi-update figure (Fig. 4):

```bash
uv run python plot_concurrent.py --base-dir shared/logs --output shared/logs/concurrent_scalability.pdf
```

Both scripts expect all four `concurrent_<N>` archives to be present.

## Optional tools

**Topology check.** Probe every link, then draw the topology to `shared/logs/topology.png`. Run the plotting script with `uv run --with cartopy` instead of `uv run` to draw coastlines on the map.

```bash
./run_test.sh stop; ./run_test.sh clean
./run_test.sh topology && sleep 15
uv run python plot_topology.py
```

**Chronogram.** Plot the message-passing events from the most recent run's journals. The plot is easiest to read on small topologies.

```bash
uv run python plot_chronogram.py --name "Chronogram" --type-to-plot Global
```

## License

This project is released under the [MIT License](LICENSE).
