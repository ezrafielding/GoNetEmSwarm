#!/bin/bash

echo "======================================"
echo "Initializing Satellite ..............."
echo "======================================"

python3 /usr/lib/scripts/setup-network.py

sat_id=$(cat /usr/local/id)
sat_name=sat$sat_id
export SAT_ID=$sat_id
export SAT_NAME:=$sat_name


# Display environment variables
echo
echo "Environment Configuration:"
echo "  SAT_ID: $SAT_ID"
echo "  SAT_NAME: $SAT_NAME"

# Log satellite startup with network info
echo "$(date): Satellite $SAT_ID started" >> /usr/local/logs/satellite_$SAT_ID.log

echo
echo "======================================"
echo "Satellite $SAT_NAME initialization complete"
echo "Starting algorithm execution"
echo "======================================"

SAT_ID=$sat_id python3 /usr/lib/algorithms/broadcast_test.py
# Keep container running
tail -f /dev/null
