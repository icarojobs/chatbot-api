#!/usr/bin/env bash
# Runs a scanner image against the workspace as the current user, so reports stay writable by the runner.
set -euo pipefail

readonly IMAGE="${1:?usage: docker_scan.sh <image> <scanner-args...>}"
shift

exec docker run --rm --user "$(id -u):$(id -g)" --volume "${PWD}:/src" --workdir /src "$IMAGE" "$@"
