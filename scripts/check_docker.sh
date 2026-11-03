#!/usr/bin/env bash
# Fail fast, with the fix, when no Docker daemon is reachable.
#
# Why this exists: on Windows + WSL 2, `docker` inside WSL is only a link to
# Docker Desktop. When Docker Desktop is not running, the command vanishes
# ("The command 'docker' could not be found in this WSL 2 distro") and
# `make up` fails with a message that says nothing about the cause.
#
# Why it only checks: starting a heavy GUI service as a side effect of `make`
# is surprising, and Docker Desktop stays off unless someone wants it (#131).
# So this script never starts anything; it says what to start, per platform.
#
# Override: DOCKER (command to probe, for tests).

set -euo pipefail

DOCKER="${DOCKER:-docker}"

# `docker info` talks to the daemon; `docker --version` would succeed even
# when only the client is installed.
if "$DOCKER" info >/dev/null 2>&1; then
    exit 0
fi

echo "ERROR: Docker is not running - start it, then run the command again."
if grep -qi microsoft /proc/version 2>/dev/null; then
    echo "  WSL:   start Docker Desktop on Windows. If it runs but WSL still cannot"
    echo "         see it: Settings -> Resources -> WSL integration -> enable this distro."
elif [ "$(uname -s)" = "Darwin" ]; then
    echo "  macOS: open -a Docker   (the engine needs 20-60 s until it answers)"
else
    echo "  Linux: sudo systemctl start docker"
fi
exit 1
