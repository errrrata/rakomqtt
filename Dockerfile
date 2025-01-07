ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.19
FROM ${BUILD_FROM}

# Set shell
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Set workdir
WORKDIR /usr/src/app

# Install system dependencies
RUN \
    apk add --no-cache \
        python3 \
        py3-pip \
        gcc \
        musl-dev \
        linux-headers \
        curl

# Copy root filesystem
COPY rootfs /

# Copy application files
COPY requirements.txt .
COPY start.sh .
COPY ./rakomqtt ./rakomqtt/

# Install Python packages and set permissions
RUN \
    pip3 install --no-cache-dir -r requirements.txt && \
    chmod a+x start.sh

# Set environment variables
ENV \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/usr/src/app

# Labels
LABEL \
    io.hass.name="Rako MQTT Bridge" \
    io.hass.description="Bridge between Rako lighting system and MQTT" \
    io.hass.type="addon" \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.arch="armhf|armv7|aarch64|amd64|i386" \
    maintainer="Bogdan Augustin Dobran <bad@nod.cc>"
