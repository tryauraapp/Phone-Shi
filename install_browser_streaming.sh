#!/usr/bin/env bash
# Install the display-stream dependencies on an existing Linux VPS checkout.
set -euo pipefail
repo=$(cd "$(dirname "$0")" && pwd)
apt-get install -y --no-install-recommends python3-venv curl ca-certificates
python3 -m venv --system-site-packages "$repo/.local/controller-venv"
"$repo/.local/controller-venv/bin/pip" install 'av>=19,<20'
install -d "$repo/.local/browser-stream"
curl --fail --location --retry 3 \
  https://github.com/Genymobile/scrcpy/releases/download/v5.0.1/scrcpy-server-v5.0.1 \
  -o "$repo/.local/browser-stream/scrcpy-server.download"
printf '%s  %s\n' 764eb6f79811d5211fe9df341120882ba9994c7a61b897d7bf3fb662e53bc536 \
  "$repo/.local/browser-stream/scrcpy-server.download" | sha256sum -c -
mv "$repo/.local/browser-stream/scrcpy-server.download" "$repo/.local/browser-stream/scrcpy-server"
printf '5.0.1\n' > "$repo/.local/browser-stream/scrcpy-version"
