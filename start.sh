#!/bin/bash
set -e

# Improved logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Function to handle cleanup on exit
cleanup() {
    EXIT_CODE=$1
    log "Cleanup triggered with exit code: $EXIT_CODE"
    if [ ! -z "$PID" ]; then
        log "Sending SIGTERM to process $PID"
        kill -TERM "$PID" 2>/dev/null || true
        wait "$PID" 2>/dev/null || true
    fi
    log "Cleanup completed"
    exit "${EXIT_CODE:-0}"
}

# Set up trap handlers
trap 'cleanup $?' EXIT
trap 'log "Received SIGINT"; cleanup 1' INT
trap 'log "Received SIGTERM"; cleanup 1' TERM

# Configure logging
export PYTHONUNBUFFERED=1

# Try to find Rako bridge if not provided
if [ -z "$RAKO_BRIDGE_HOST" ]; then
    log "No RAKO_BRIDGE_HOST provided, trying to discover..."
    RAKO_BRIDGE_IP=$(python -m rakomqtt.RakoBridge)
    if [ -z "$RAKO_BRIDGE_IP" ]; then
        log "Failed to find Rako bridge automatically and no RAKO_BRIDGE_HOST provided"
        exit 1
    fi
    RAKO_BRIDGE_HOST=$RAKO_BRIDGE_IP
fi

# Get default fade rate from environment or use default
DEFAULT_FADE_RATE=${DEFAULT_FADE_RATE:-medium}

log "Using Rako bridge at: $RAKO_BRIDGE_HOST"
log "Default fade rate: $DEFAULT_FADE_RATE"

# Start the bridge with retries
MAX_RETRIES=3
RETRY_COUNT=0
RETRY_DELAY=5

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    log "Starting RakoMQTT bridge (attempt $((RETRY_COUNT + 1))/$MAX_RETRIES)..."
    
    # Start the bridge with all parameters
    python -um rakomqtt \
        --rako-bridge-host "$RAKO_BRIDGE_HOST" \
        --mqtt-host "$MQTT_HOST" \
        --mqtt-user "$MQTT_USER" \
        --mqtt-password "$MQTT_PASSWORD" \
        --default-fade-rate "$DEFAULT_FADE_RATE" \
        "$@" &
    
    PID=$!
    log "Bridge started with PID: $PID"
    
    # Wait for the process
    wait $PID
    EXIT_CODE=$?
    
    # Check if exit was clean (0) or due to SIGTERM (143)
    if [ $EXIT_CODE -eq 0 ] || [ $EXIT_CODE -eq 143 ]; then
        log "Bridge exited normally with code $EXIT_CODE"
        exit 0
    fi
    
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
        log "Bridge exited with code $EXIT_CODE. Retrying in $RETRY_DELAY seconds..."
        sleep $RETRY_DELAY
    else
        log "Bridge failed after $MAX_RETRIES attempts. Exiting."
        exit $EXIT_CODE
    fi
done
