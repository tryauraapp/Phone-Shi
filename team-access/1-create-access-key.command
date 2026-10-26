#!/bin/zsh
set -euo pipefail

key="$HOME/.ssh/phone_shi_team"
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
if [[ ! -f "$key" ]]; then
  ssh-keygen -t ed25519 -a 64 -f "$key" -N '' -C "phone-shi-team-$(id -un)"
fi
chmod 600 "$key"
chmod 644 "$key.pub"
pbcopy < "$key.pub"
echo "Your public key was copied to the clipboard. Send only that public key to the Phone Shi administrator."
echo "Never send the private file: $key"
read -k 1 "?Press any key to close."
