#!/usr/bin/env bash
# Launch Playground Mods from any working directory.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
exec python3 main.py "$@"
