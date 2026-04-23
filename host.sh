#!/usr/bin/env bash
# Start the packet-spammer container using the pre-built image.
# Run ./build.sh first if the image does not exist yet.
#
# Usage:  ./host.sh           — start in foreground
#         ./host.sh -d        — start detached (background)
set -e
cd "$(dirname "$0")"

# ── Ensure Docker is running ──────────────────────────────────────────── #

if ! docker info &>/dev/null; then
    echo "[host] Starting Docker service..."
    systemctl start docker
fi

# ── Check that the image has been built ───────────────────────────────── #

if ! docker image inspect packet-spammer:latest &>/dev/null; then
    echo "[host] ERROR: Image 'packet-spammer:latest' not found."
    echo "[host]        Run ./build.sh first to build the image."
    exit 1
fi

# ── Start ─────────────────────────────────────────────────────────────── #

echo "[host] Starting packet-spammer..."
docker compose up "$@" packet-spammer
