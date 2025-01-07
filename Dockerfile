ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.19
FROM ${BUILD_FROM}
#FROM ghcr.io/home-assistant/amd64-base:3.15

# Set workdir
WORKDIR /usr/src/app

# Install build dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    gcc \
    musl-dev \
    python3-dev \
    linux-headers

# Copy application files
COPY requirements.txt .
COPY start.sh .
COPY ./rakomqtt ./rakomqtt/

# Install Python packages and set permissions
RUN python3 -m venv /usr/src/app/rakomqtt/venv && \
    . /usr/src/app/rakomqtt/venv/bin/activate && \
    ./rakomqtt/venv/bin/pip install --no-cache-dir -r requirements.txt

RUN chmod a+x start.sh

# Copy root filesystem
COPY rootfs /

# Set environment variables
ENV \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/usr/src/app

# Labels
#LABEL \
#    io.hass.name="Rako MQTT Bridge" \
#    io.hass.description="Bridge between Rako lighting system and MQTT" \
#    io.hass.type="addon" \
#    io.hass.version="${BUILD_VERSION}" \
#    io.hass.arch="armhf|armv7|aarch64|amd64|i386" \
#    maintainer="Bogdan Augustin Dobran <bad@nod.cc>"

#CMD [ "/run.sh" ]
