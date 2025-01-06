#!/bin/bash
set -e

# Try to find Rako bridge if not provided
if [ -z "$RAKO_BRIDGE_HOST" ]; then
    echo "No RAKO_BRIDGE_HOST provided, trying to discover..."
    RAKO_BRIDGE_IP=`python -m rakomqtt.RakoBridge`
    if [ -z "$RAKO_BRIDGE_IP" ]; then
        echo "Failed to find Rako bridge automatically and no RAKO_BRIDGE_HOST provided"
        exit 1
    fi
    RAKO_BRIDGE_HOST=$RAKO_BRIDGE_IP
fi

echo "Using Rako bridge at: $RAKO_BRIDGE_HOST"

# Start the bridge
set +e
python -um rakomqtt --rako-bridge-host "$RAKO_BRIDGE_HOST" "$@"
