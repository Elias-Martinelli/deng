#!/usr/bin/env bash
# Make sure a Docker daemon is reachable before any Docker target runs.
#
# Why this exists: on Windows + WSL 2, `docker` inside WSL is only a link to
# Docker Desktop. When Docker Desktop is not running, the command vanishes
# ("The command 'docker' could not be found in this WSL 2 distro") and
# `make up` fails although nothing is wrong with the project.
#
# What it does:
#   1. Docker answers            -> nothing to do.
#   2. WSL with Docker Desktop   -> start Docker Desktop on Windows, wait.
#   3. macOS                     -> `open -a Docker`, wait.
#   4. anything else (Linux)     -> no sudo from a Makefile: print the command.
# It gives up after DENG_DOCKER_WAIT seconds (default 180) with instructions.
#
# Overrides: DOCKER (command to probe, for tests), DENG_DOCKER_WAIT,
# DOCKER_DESKTOP_EXE (Windows path if Docker Desktop is installed elsewhere).

set -euo pipefail

DOCKER="${DOCKER:-docker}"
WAIT="${DENG_DOCKER_WAIT:-180}"
DESKTOP_EXE="${DOCKER_DESKTOP_EXE:-C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe}"

# `docker info` talks to the daemon; `docker --version` would succeed even
# when only the client is installed.
docker_ready() { "$DOCKER" info >/dev/null 2>&1; }

if docker_ready; then
    exit 0
fi

is_wsl() { grep -qi microsoft /proc/version 2>/dev/null; }

started=""
if is_wsl && command -v powershell.exe >/dev/null 2>&1; then
    echo "Docker is not reachable - starting Docker Desktop on Windows ..."
    # Start-Process detaches, so Docker Desktop keeps running after make ends.
    # cd /mnt/c: Windows programs cannot use a WSL path as working directory.
    (cd /mnt/c && powershell.exe -NoProfile -Command \
        "Start-Process -FilePath '$DESKTOP_EXE'") >/dev/null 2>&1 && started="Docker Desktop"
elif [ "$(uname -s)" = "Darwin" ] && command -v open >/dev/null 2>&1; then
    echo "Docker is not reachable - starting Docker Desktop ..."
    open -a Docker && started="Docker Desktop"
fi

if [ -z "$started" ]; then
    echo "ERROR: Docker is not running."
    echo "  Linux: sudo systemctl start docker   (then run the command again)"
    exit 1
fi

# Docker Desktop needs 20-60 s until the engine accepts connections; in WSL the
# `docker` link itself only reappears once the WSL integration is up.
printf "waiting for %s to accept connections" "$started"
for _ in $(seq 1 "$WAIT"); do
    if docker_ready; then
        echo " - ready."
        exit 0
    fi
    printf "."
    sleep 1
done

echo
echo "ERROR: $started was started but Docker did not answer within ${WAIT}s."
if is_wsl; then
    echo "  In Docker Desktop: Settings -> Resources -> WSL integration ->"
    echo "  enable the integration for this distro, then run the command again."
fi
exit 1
