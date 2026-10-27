#!/bin/sh
set -eu
bridge_ip="${1:-}"
if [ -z "$bridge_ip" ]; then echo "usage: $0 <LAN-IP>" >&2; exit 2; fi
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
mkdir -p "$script_dir/.certs"
mkcert -install
mkcert -cert-file "$script_dir/.certs/$bridge_ip.pem" -key-file "$script_dir/.certs/$bridge_ip-key.pem" "$bridge_ip" localhost 127.0.0.1
mkcert -CAROOT
