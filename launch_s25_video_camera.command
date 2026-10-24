#!/bin/zsh
# Launch the Galaxy S25 emulator with the selected video as its live camera feed.
cd "$(dirname "$0")" || exit 1
echo "=================================================================="
echo " Launching Galaxy S25 Emulator"
echo " Native Front Camera: saved per-phone video and framing"
echo " Startup includes a real front-camera motion check."
echo "=================================================================="
mkdir -p .local
setopt PIPE_FAIL
python3 -I emulator_proxy.py --avd Galaxy_S25_20261024_10f841ca --check-video-camera --camera-viewer "$@" 2>&1 | tee -a ".local/s25-terminal-launch.log"
