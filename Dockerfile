FROM ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.19

WORKDIR /app

# Install system dependencies
RUN apk add --no-cache \
        gcc \
        musl-dev \
        linux-headers \
        curl

COPY requirements.txt .
COPY start.sh .
RUN pip3 install --no-cache-dir -r requirements.txt && \
    chmod +x /app/start.sh

# Copy application code
COPY ./rakomqtt ./rakomqtt/

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

RUN mkdir -p /data

LABEL \
    io.hass.version="0.2.0" \
    io.hass.type="addon" \
    io.hass.arch="armhf|armv7|aarch64|amd64|i386"

# Set healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:9761 || exit 1

ENTRYPOINT ["/app/start.sh"]
