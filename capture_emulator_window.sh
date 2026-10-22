#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec /usr/bin/swift -module-cache-path "${TMPDIR:-/tmp}/emu-window-module-cache" \
  "$SCRIPT_DIR/capture_emulator_window.swift" "$@"
