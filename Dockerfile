FROM python:3.13-slim

# System tools required for WiFi interface management and raw packet injection.
#   iw         — monitor mode + channel configuration
#   iproute2   — ip link up/down
#   net-tools  — optional but handy (ifconfig)
RUN apt-get update && apt-get install -y --no-install-recommends \
        iw \
        iproute2 \
        net-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (cached layer unless pyproject.toml changes).
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy source (bust cache on every build via build arg).
ARG CACHEBUST
COPY . .

ENTRYPOINT ["python3", "run.py"]
