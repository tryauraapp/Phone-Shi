#!/bin/bash
# Create a new emulator using the supplied host-side video as its front camera.
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
exec /bin/bash "$SCRIPT_DIR/setup_galaxy_s25_avd.sh" \
  --front-camera "videofile:$SCRIPT_DIR/bumble-signup/camera/phone-video.mp4" "$@"
