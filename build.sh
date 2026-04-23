#!/usr/bin/env bash
# Build the packet-spammer Docker image.
# Run this once (and again whenever you update the code or dependencies).
# After building, use ./host.sh to start the container instantly.
#
# Usage:  ./build.sh
set -e
cd "$(dirname "$0")"

# ── Ensure Docker is available ────────────────────────────────────────── #

if ! command -v docker &>/dev/null; then
    echo "[build] Docker not found — installing..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
    if [ -n "$SUDO_USER" ] && ! groups "$SUDO_USER" | grep -q docker; then
        usermod -aG docker "$SUDO_USER"
        echo "[build] NOTE: Log out and back in (or run 'newgrp docker') before using Docker without sudo."
    fi
fi

if ! docker info &>/dev/null; then
    echo "[build] Starting Docker service..."
    systemctl start docker
fi

# ── Build ─────────────────────────────────────────────────────────────── #

echo "[build] Building packet-spammer image..."
docker compose build --build-arg CACHEBUST="$(date +%s)" packet-spammer
echo "[build] Done. Run ./host.sh to start."
