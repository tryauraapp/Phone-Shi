#!/bin/zsh
set -euo pipefail

key="$HOME/.ssh/phone_shi_team"
host="169.58.133.150"
if [[ ! -f "$key" ]]; then
  echo "Run 1-create-access-key.command first."
  read -k 1 "?Press any key to close."
  exit 2
fi

if lsof -nP -iTCP:8790 -sTCP:LISTEN >/dev/null 2>&1; then
  if ! curl -fsS --max-time 3 http://127.0.0.1:8790/api/bootstrap \
      | grep -q 'vmi3698254'; then
    echo "Port 8790 is already used by another application. Close it and run this launcher again."
    read -k 1 "?Press any key to close."
    exit 2
  fi
else
  ssh -fN -i "$key" -o BatchMode=yes -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -L 8790:127.0.0.1:8790 -L 6080:127.0.0.1:6080 \
    "phone-shi-team@$host"
fi
open "http://127.0.0.1:8790/"
open "http://127.0.0.1:6080/vnc.html?autoconnect=true&resize=scale"
