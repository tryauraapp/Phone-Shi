#!/bin/bash
set -euo pipefail

repo="/Users/lucapritchard/claude-code/Phone-Shi-VPS-V2"
sdk="/Users/lucapritchard/Library/Android/sdk"
token_file="$repo/.local/mac-phone-control-token"

if [[ ! -s "$token_file" ]]; then
  echo "Missing private controller token: $token_file" >&2
  exit 2
fi

lan_ip=$(/usr/sbin/ipconfig getifaddr en0 2>/dev/null || true)
if [[ -z "$lan_ip" ]]; then
  lan_ip=$(/usr/sbin/ipconfig getifaddr en1 2>/dev/null || true)
fi
if [[ -z "$lan_ip" ]]; then
  echo "The Mac has no active LAN address." >&2
  exit 3
fi

python=/opt/homebrew/bin/python3
[[ -x "$python" ]] || python=/usr/bin/python3

export CONTROL_PANEL_TOKEN
CONTROL_PANEL_TOKEN=$(<"$token_file")
export PHONE_SHI_SHARE_BASE_URL="http://$lan_ip:8791"
export ANDROID_SDK_ROOT="$sdk"
export ANDROID_HOME="$sdk"
export ANDROID_AVD_HOME="/Users/lucapritchard/.android/avd"
export PATH="$sdk/platform-tools:$sdk/emulator:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

exec "$python" "$repo/control-panel/server.py" --host 0.0.0.0 --port 8791
