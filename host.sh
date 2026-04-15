#!/usr/bin/env bash
# Build and start the packet-spammer container.
# Usage:  ./host.sh           — build + start (foreground)
#         ./host.sh -d        — build + start (detached / background)
set -e
cd "$(dirname "$0")"

# ── Ensure Docker is available ────────────────────────────────────────── #

if ! command -v docker &>/dev/null; then
    echo "[host] Docker not found — installing..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
    if [ -n "$SUDO_USER" ] && ! groups "$SUDO_USER" | grep -q docker; then
        usermod -aG docker "$SUDO_USER"
        echo "[host] NOTE: Log out and back in (or run 'newgrp docker') before using Docker without sudo."
    fi
fi

if ! docker info &>/dev/null; then
    echo "[host] Starting Docker service..."
    systemctl start docker
fi

# ── Build ─────────────────────────────────────────────────────────────── #

echo "[host] Building image..."
docker compose build --build-arg CACHEBUST="$(date +%s)" packet-spammer

# ── Start ─────────────────────────────────────────────────────────────── #

echo "[host] Starting packet-spammer..."
docker compose up "$@" packet-spammer
