#!/usr/bin/with-contenv bashio
set -e

_RAKO_BRIDGE_HOST="$(bashio::config 'rako_bridge_host')"
_MQTT_HOST="$(bashio::config 'mqtt_host')"
_MQTT_USER="$(bashio::config 'mqtt_user')"
_MQTT_PASSWORD="$(bashio::config 'mqtt_password')"
_DEBUG="$(bashio::config 'debug')"
_DEFAULT_FADE_RATE="$(bashio::config 'default_fade_rate')"

export RAKO_BRIDGE_HOST=${RAKO_BRIDGE_HOST:-$_RAKO_BRIDGE_HOST}
export MQTT_HOST=${MQTT_HOST:-$_MQTT_HOST}
export MQTT_USER=${MQTT_USER:-$_MQTT_USER}
export MQTT_PASSWORD=${MQTT_PASSWORD:-$_MQTT_PASSWORD}
export DEBUG=${DEBUG:-$_DEBUG}
export DEFAULT_FADE_RATE=${DEFAULT_FADE_RATE:-$_DEFAULT_FADE_RATE}

# Improved logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log "RAKO_BRIDGE_HOST: ${RAKO_BRIDGE_HOST}"
log "MQTT_HOST: ${MQTT_HOST}"

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

# Get default fade rate from environment or use default
DEFAULT_FADE_RATE=${DEFAULT_FADE_RATE:-medium}

log "Using Rako bridge at: $RAKO_BRIDGE_HOST"
log "Default fade rate: $DEFAULT_FADE_RATE"

# Start the bridge with retries
MAX_RETRIES=3
RETRY_COUNT=0
RETRY_DELAY=5

cd /usr/src/app/rakomqtt

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    log "Starting RakoMQTT bridge (attempt $((RETRY_COUNT + 1))/$MAX_RETRIES)..."
    
    # Start the bridge with all parameters
    . /usr/src/app/rakomqtt/venv/bin/activate
    python3 -um rakomqtt \
        ${RAKO_BRIDGE_HOST:+--rako-bridge-host "${RAKO_BRIDGE_HOST}"} \
        --mqtt-host "$MQTT_HOST" \
        --mqtt-user "$MQTT_USER" \
        --mqtt-password "$MQTT_PASSWORD" \
        ${DEBUG:+--debug} \
        "$@" &
    
#        --default-fade-rate "$DEFAULT_FADE_RATE" \
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
