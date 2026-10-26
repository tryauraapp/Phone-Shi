#!/bin/zsh
set -e
APP_DIR="${0:A:h}/.local/Deep-Live-Cam"
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export MPLCONFIGDIR="$APP_DIR/.cache/matplotlib"
export KERAS_BACKEND=torch
export NO_ALBUMENTATIONS_UPDATE=1
cd "$APP_DIR"
exec "$APP_DIR/.venv/bin/python" run.py --execution-provider coreml
