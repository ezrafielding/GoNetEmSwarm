#!/usr/bin/env bash
# run_test.sh – Run a distributed algorithm across all satellite nodes
#               in a running gonetem topology.
#
# Usage:
#   ./run_test.sh start     <algorithm> [args...]   – satellites only
#   ./run_test.sh gndstart  <algorithm> [args...]   – ground stations only
#   ./run_test.sh fullstart <algorithm> [args...]   – all nodes (sat + gnd)
#   ./run_test.sh topology  [--isl-only]            – run discovery + generate figure
#   ./run_test.sh stop
#   ./run_test.sh status
#   ./run_test.sh logs [algorithm]
#   ./run_test.sh clean
#
# Examples:
#   ./run_test.sh fullstart crdt_ssa                  # gnd1 is ground by default
#   ./run_test.sh fullstart crdt_ssa --ground gnd2    # override ground node
#   ./run_test.sh topology                            # full discovery + figure
#   ./run_test.sh topology --isl-only                 # satellites only
#   ./run_test.sh isl-tune                            # fix TBF burst for large packets (run once after opening topology)
#   ./run_test.sh stop
#   ./run_test.sh logs crdt_ssa
#
# Prerequisites:
#   1. Build the satellite image:    ./build_image.sh
#   2. Generate a topology:          python3 generate_topology.py --nodes 10 --topology ring
#   3. Open it in gonetem (terminal A): gonetem-console open swarm_ring_10.gnet
#   4. Then run tests here (terminal B): ./run_test.sh start crdt_test
#
# How gonetem containers are found:
#   gonetem labels every container with  label=node=<nodeName>.
#   This script uses that label to locate satellite containers.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGS_DIR="$SCRIPT_DIR/shared/logs"
ALGORITHMS_DIR="$SCRIPT_DIR/shared/algorithms"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

die() { echo "ERROR: $*" >&2; exit 1; }

# Return all running sat* container names, sorted naturally.
find_sat_containers() {
    docker ps --format "{{.Names}}" \
      | grep -E '^ntm[^.]+\.sat[0-9]+$' \
      | sort -V
}

find_gnd_containers() {
    docker ps --format "{{.Names}}" \
      | grep -E '^ntm[^.]+\.gnd[0-9]+$' \
      | sort -V
}

# Return the container name for a specific node (e.g. sat3).
find_container_for_node() {
    local node="$1"
    docker ps --format "{{.Names}}" | grep -E "\.${node}$" | head -1
}

# Extract the node name (satN) from a full container name (ntmXXX.satN).
node_from_container() {
    echo "$1" | grep -oE 'sat[0-9]+$'
}

gnd_from_container() {
    echo "$1" | grep -oE 'gnd[0-9]+$'
}


# Extract the numeric ID from a node name.
id_from_node() {
    echo "$1" | grep -oE '[0-9]+$'
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

cmd_topology() {
    local isl_only=false
    for arg in "$@"; do
        [[ "$arg" == "--isl-only" ]] && isl_only=true
    done

    # Start discovery on the right set of containers
    if $isl_only; then
        cmd_start "topology_discovery" "$@"
        mapfile -t _topo_containers < <(find_sat_containers)
    else
        cmd_fullstart "topology_discovery" "$@"
        mapfile -t _sat < <(find_sat_containers)
        mapfile -t _gnd < <(find_gnd_containers)
        _topo_containers=("${_sat[@]}" "${_gnd[@]}")
    fi
}

cmd_fullstart() {
    local algorithm="${1:-}"
    [[ -n "$algorithm" ]] || die "Usage: $0 fullstart <algorithm> [args...]"
    shift

    # Support paired _sat / _gnd scripts (e.g. ssa_control_sat.py + ssa_control_gnd.py)
    if [[ -f "$ALGORITHMS_DIR/${algorithm}_sat.py" ]]; then
        cmd_start    "${algorithm}_sat" "$@"
        cmd_gndstart "${algorithm}_gnd" "$@"
    else
        cmd_start    "$algorithm" "$@"
        cmd_gndstart "$algorithm" "$@"
    fi
}

cmd_start() {
    local algorithm="${1:-}"
    [[ -n "$algorithm" ]] || die "Usage: $0 start <algorithm> [args...]"
    shift

    # Resolve script path (try .py first, then bare name)
    local algo_file
    if [[ -f "$ALGORITHMS_DIR/${algorithm}.py" ]]; then
        algo_file="/algorithms/${algorithm}.py"
    elif [[ -f "$ALGORITHMS_DIR/$algorithm" ]]; then
        algo_file="/algorithms/$algorithm"
    else
        echo "WARNING: ${algorithm}.py not found in $ALGORITHMS_DIR – make sure"
        echo "         you have copied your algorithm there before running."
        algo_file="/algorithms/${algorithm}.py"
    fi

    mapfile -t containers < <(find_sat_containers)
    [[ ${#containers[@]} -gt 0 ]] || \
        die "No satellite containers found. Open a .gnet topology in gonetem first."

    mkdir -p "$LOGS_DIR"
    echo "Starting '$algorithm' on ${#containers[@]} nodes${*:+ (args: $*)}…"

    for container in "${containers[@]}"; do
        local node
        node="$(node_from_container "$container")"
        local sat_id
        sat_id="$(id_from_node "$node")"

        docker exec -d \
            -e SAT_ID="$sat_id" \
            -e SAT_NAME="$node" \
            -e LOG_DIR="/logs" \
            -e CONFIG_FILE="/algorithms/node_configs.json" \
            "$container" \
            python3 "$algo_file" "$@" \
          && echo "  ✓ $node  ($container)"  \
          || echo "  ✗ $node  ($container)  [exec failed]"
    done

    echo ""
    echo "Algorithm running. Monitor with:"
    echo "  $0 logs $algorithm"
    echo "  $0 status"
}

cmd_gndstart() {
    local algorithm="${1:-}"
    [[ -n "$algorithm" ]] || die "Usage: $0 gndstart <algorithm> [args...]"
    shift

    # Resolve script path (try .py first, then bare name)
    local algo_file
    if [[ -f "$ALGORITHMS_DIR/${algorithm}.py" ]]; then
        algo_file="/algorithms/${algorithm}.py"
    elif [[ -f "$ALGORITHMS_DIR/$algorithm" ]]; then
        algo_file="/algorithms/$algorithm"
    else
        echo "WARNING: ${algorithm}.py not found in $ALGORITHMS_DIR – make sure"
        echo "         you have copied your algorithm there before running."
        algo_file="/algorithms/${algorithm}.py"
    fi

    mapfile -t containers < <(find_gnd_containers)
    [[ ${#containers[@]} -gt 0 ]] || \
        die "No ground station containers found. Open a compatible .gnet topology in gonetem first."

    mkdir -p "$LOGS_DIR"
    echo "Starting '$algorithm' on ${#containers[@]} ground station nodes${*:+ (args: $*)}…"

    for container in "${containers[@]}"; do
        local node
        node="$(gnd_from_container "$container")"
        local gnd_id
        gnd_id="$(id_from_node "$node")"

        docker exec -d \
            -e GND_ID="$gnd_id" \
            -e GND_NAME="$node" \
            -e LOG_DIR="/logs" \
            -e CONFIG_FILE="/algorithms/node_configs.json" \
            "$container" \
            python3 "$algo_file" "$@" \
          && echo "  ✓ $node  ($container)"  \
          || echo "  ✗ $node  ($container)  [exec failed]"
    done

    echo ""
    echo "Algorithm running. Monitor with:"
    echo "  $0 logs $algorithm"
    echo "  $0 status"
}

cmd_stop() {
    mapfile -t containers < <(find_sat_containers)
    [[ ${#containers[@]} -gt 0 ]] || { echo "No satellite containers running."; return; }

    echo "Stopping Python algorithm processes on ${#containers[@]} satellites nodes…"
    for container in "${containers[@]}"; do
        docker exec "$container" \
            pkill -f "python3 /algorithms" 2>/dev/null \
          && echo "  stopped on $(node_from_container "$container")" \
          || echo "  (nothing running on $(node_from_container "$container"))"
    done

    mapfile -t containers < <(find_gnd_containers)
    [[ ${#containers[@]} -gt 0 ]] || { echo "No satellite containers running."; return; }

    echo "Stopping Python algorithm processes on ${#containers[@]} ground station nodes…"
    for container in "${containers[@]}"; do
        docker exec "$container" \
            pkill -f "python3 /algorithms" 2>/dev/null \
          && echo "  stopped on $(gnd_from_container "$container")" \
          || echo "  (nothing running on $(gnd_from_container "$container"))"
    done
}

cmd_status() {
    mapfile -t containers < <(find_sat_containers)
    if [[ ${#containers[@]} -eq 0 ]]; then
        echo "No satellite containers found."
        return
    fi

    echo "Satellite containers (${#containers[@]}):"
    printf "  %-20s  %-10s  %s\n" "CONTAINER" "NODE" "ALGORITHM RUNNING"
    for container in "${containers[@]}"; do
        local node
        node="$(node_from_container "$container")"
        local proc
        proc="$(docker exec "$container" pgrep -a -f "python3 /algorithms" 2>/dev/null \
                | awk '{$1=""; print $0}' | xargs || echo "(none)")"
        printf "  %-20s  %-10s  %s\n" "$container" "$node" "$proc"
    done

    mapfile -t containers < <(find_gnd_containers)
    if [[ ${#containers[@]} -eq 0 ]]; then
        echo "No ground station containers found."
        return
    fi

    echo "Ground station containers (${#containers[@]}):"
    printf "  %-20s  %-10s  %s\n" "CONTAINER" "NODE" "ALGORITHM RUNNING"
    for container in "${containers[@]}"; do
        local node
        node="$(gnd_from_container "$container")"
        local proc
        proc="$(docker exec "$container" pgrep -a -f "python3 /algorithms" 2>/dev/null \
                | awk '{$1=""; print $0}' | xargs || echo "(none)")"
        printf "  %-20s  %-10s  %s\n" "$container" "$node" "$proc"
    done

}

cmd_logs() {
    local algorithm="${1:-}"
    mkdir -p "$LOGS_DIR"

    if [[ -n "$algorithm" ]]; then
        # Tail all log files matching the algorithm name
        local log_files=("$LOGS_DIR"/*"${algorithm}"*)
        if [[ ${#log_files[@]} -gt 0 && -f "${log_files[0]}" ]]; then
            echo "Tailing logs for $algorithm (Ctrl-C to stop):"
            tail -f "${log_files[@]}"
        else
            echo "No log files for '$algorithm' in $LOGS_DIR yet."
        fi
    else
        # Print all log files
        if ls "$LOGS_DIR"/*.log 2>/dev/null | head -1 | read -r; then
            echo "Log files in $LOGS_DIR:"
            ls -lh "$LOGS_DIR"
        else
            echo "No log files in $LOGS_DIR yet."
        fi
    fi
}

cmd_clean() {
    echo "Cleaning logs directory: $LOGS_DIR"
    rm -f "$LOGS_DIR"/*.log 2>/dev/null || true #"$LOGS_DIR"/*.json
    rm -f "$LOGS_DIR"/*.json 2>/dev/null || true
    rm -f "$LOGS_DIR"/*.csv 2>/dev/null || true
    rm -f "$LOGS_DIR"/network/*.log  2>/dev/null || true
    rm -f "$LOGS_DIR"/*.json 2>/dev/null || true #"$LOGS_DIR"/*.json
    echo "Done."
}

cmd_archive() {
    local name="${1:-}"
    [[ -n "$name" ]] || die "Usage: $0 archive <name>  (e.g. control | broadcast | tree)"
    local dest="$LOGS_DIR/$name"
    mkdir -p "$dest"
    cp "$LOGS_DIR"/*.log "$dest/" 2>/dev/null || true
    cp "$LOGS_DIR"/*.csv "$dest/" 2>/dev/null || true
    echo "Archived logs to $dest"
}

# ---------------------------------------------------------------------------
# ISL link tuning — widen TBF burst so full-size UDP packets are delivered.
# The default gonetem TBF burst (100 bytes) drops anything larger, which
# breaks CRDT broadcasts (~400–600 bytes). Run once after opening a topology.
# ---------------------------------------------------------------------------

cmd_isl_tune() {
    local burst="${1:-10240}"   # bytes; 10 KB is safe for ~1 KB payloads
    mapfile -t containers < <(find_sat_containers)
    [[ ${#containers[@]} -gt 0 ]] || die "No satellite containers found."

    echo "Tuning ISL TBF burst to ${burst}b on ${#containers[@]} satellite nodes…"
    for container in "${containers[@]}"; do
        local node
        node="$(node_from_container "$container")"
        for iface in eth0 eth1 eth2 eth3; do
            docker exec "$container" bash -c "
                if ip link show $iface &>/dev/null; then
                    tc qdisc show dev $iface | grep -q tbf || exit 0
                    rate=\$(tc qdisc show dev $iface | grep -oP 'rate \K\S+')
                    lat=\$(tc qdisc show dev $iface | grep -oP 'lat \K\S+')
                    tc qdisc change dev $iface parent 1:1 handle 10: tbf rate \${rate} burst ${burst}b lat \${lat} 2>/dev/null || true
                fi
            " 2>/dev/null
        done
        echo "  ✓ $node"
    done
    echo "Done. ISL links now support packets up to ~${burst} bytes."
}

# ---------------------------------------------------------------------------
# OSPF convergence helper
# ---------------------------------------------------------------------------

cmd_ospf_check() {
    # Run 'vtysh -c "show ip ospf neighbor"' on all nodes and summarise.
    mapfile -t containers < <(find_sat_containers)
    [[ ${#containers[@]} -gt 0 ]] || die "No satellite containers found."

    echo "OSPF neighbour summary:"
    for container in "${containers[@]}"; do
        local node
        node="$(node_from_container "$container")"
        local count
        count="$(docker exec "$container" vtysh -c "show ip ospf neighbor" 2>/dev/null \
                 | grep -cE 'Full|2-Way' || echo 0)"
        echo "  $node: $count Full/2-Way neighbours"
    done
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

COMMAND="${1:-help}"
shift || true

case "$COMMAND" in
    start)      cmd_start "$@" ;;
    gndstart)   cmd_gndstart "$@" ;;
    fullstart)  cmd_fullstart "$@" ;;
    topology)   cmd_topology "$@" ;;
    stop)       cmd_stop ;;
    status)     cmd_status ;;
    logs)       cmd_logs "$@" ;;
    clean)      cmd_clean ;;
    archive)    cmd_archive "$@" ;;
    ospf-check) cmd_ospf_check ;;
    isl-tune)   cmd_isl_tune "$@" ;;
    help|--help|-h)
        sed -n '/^# Usage/,/^# -----------/p' "$0" | grep -v '^# ---' | sed 's/^# //'
        ;;
    *)
        die "Unknown command '$COMMAND'. Try: start | stop | status | logs | clean | archive | ospf-check"
        ;;
esac
