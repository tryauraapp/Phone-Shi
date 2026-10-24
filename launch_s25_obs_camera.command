#!/bin/zsh
# Launch the Galaxy S25 emulator with its normal identity/proxy settings.
# Run this from your own Terminal (or double-click it in Finder) so that macOS
# asks *that* app for camera permission; the front camera is the OBS Virtual Camera.
cd "$(dirname "$0")" || exit 1
echo "Launching Galaxy S25 emulator (front camera = OBS Virtual Camera)."
echo "If macOS asks for camera access, click Allow."
exec python3 -I emulator_proxy.py --avd Galaxy_S25_20261024_10f841ca -verbose 2>&1 | tee "$HOME/s25-terminal-launch.log"
