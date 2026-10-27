#!/usr/bin/env bash
# Runs a scanner image against the workspace as the current user, so reports stay writable by the runner.
# The runner UID does not exist inside the images, so HOME must point to a writable directory.
set -euo pipefail

readonly IMAGE="${1:?usage: docker_scan.sh <image> <scanner-args...>}"
readonly CONTAINER_HOME="/tmp"
shift

exec docker run --rm --user "$(id -u):$(id -g)" --env "HOME=${CONTAINER_HOME}" \
  --volume "${PWD}:/src" --workdir /src "$IMAGE" "$@"
