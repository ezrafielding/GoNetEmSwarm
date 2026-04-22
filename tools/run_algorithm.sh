#!/bin/bash

# Get algorithm name from first argument or default to consensus_test
GONETEM_PREFIX=$1
ALGORITHM=${2:-consensus_test}
ALGORITHM_FILE="/usr/lib/algorithms/${ALGORITHM}.py"
WAKEUP_NODE=${4:-""}

# Auto-detect number of running satellite containers
NUM_NODES=$(docker ps --filter "name=sat[0-9]" --format "{{.Names}}" | wc -l)

if [ "$NUM_NODES" -eq 0 ]; then
    echo "Error: No satellite containers found running"
    echo "Please start containers first: gonetem-console open [topology].gnet"
    exit 1
fi

echo "Starting Distributed Algorithm Test on Satellite Swarm"
echo "Algorithm: $ALGORITHM"
echo "Number of Nodes: $NUM_NODES"
if [ -n "$WAKEUP_NODE" ]; then
    echo "Wakeup Node: $WAKEUP_NODE"
fi
echo "======================================================="

# Function to check if algorithm exists
check_algorithm() {
    if ! docker exec $GONETEM_PREFIX.sat1 test -f "$ALGORITHM_FILE" 2>/dev/null; then
        echo "Error: Algorithm file '${ALGORITHM}.py' not found in algorithms directory"
        echo ""
        echo "Available algorithms:"
        docker exec $GONETEM_PREFIX.sat1 ls /usr/lib/algorithms/*.py 2>/dev/null | sed 's|/usr/lib/algorithms/||g' | sed 's|.py||g' || echo "No algorithms found"
        exit 1
    fi
}

# Function to run algorithm on all satellites
run_algorithm() {
    echo "Launching $ALGORITHM algorithm on all satellites..."

    for i in $(seq 1 $NUM_NODES); do
        echo "Starting $ALGORITHM on satellite-$i"
        if [ -n "$WAKEUP_NODE" ]; then
            # Pass wakeup node as environment variable
            docker exec -d -e WAKEUP_NODE="$WAKEUP_NODE" $GONETEM_PREFIX.sat$i python3 "$ALGORITHM_FILE"
        else
            docker exec -d $GONETEM_PREFIX.sat$i python3 "$ALGORITHM_FILE"
        fi
    done

    echo "$ALGORITHM algorithm launched on all satellites"
}

# Main menu
case "$3" in
    "start")
        #check_algorithm
        run_algorithm
        ;;
    "stop")
        echo "Stopping $ALGORITHM processes..."
        for i in $(seq 1 $NUM_NODES); do
            docker exec $GONETEM_PREFIX.sat$i pkill -f "${ALGORITHM}.py" 2>/dev/null || true
        done
        echo "$ALGORITHM processes stopped"
        ;;
    *)
        echo "Usage: $0 [algorithm_name] {start|stop} [wakeup_node]"
        echo ""
        echo "Arguments:"
        echo "  algorithm_name Algorithm to run (default: consensus_test)"
        echo "  wakeup_node    Node ID to wake up first (optional, for leader_test)"
        echo ""
        echo "Commands:"
        echo "  start                    Start algorithm on all satellites"
        echo "  stop                     Stop algorithm processes"
        echo ""
        echo "Examples:"
        echo "  $0 consensus_test start"
        echo "  $0 leader_test start 2       # Start leader_test with node 2 waking up"
        exit 1
        ;;
esac
