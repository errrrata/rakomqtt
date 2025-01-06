# Use Python 3.12 slim image as base
FROM python:3.12-slim

# Set working directory
WORKDIR /deploy

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    curl \  # Add this
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
COPY start.sh .
RUN pip install --no-cache-dir -r requirements.txt && \
    chmod +x /deploy/start.sh

# Copy application code
COPY ./rakomqtt ./rakomqtt/

# Set environment variables
ENV RAKO_BRIDGE_HOST=""
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/deploy

# Set healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:9761 || exit 1

# Run the application
CMD ["./start.sh"]
