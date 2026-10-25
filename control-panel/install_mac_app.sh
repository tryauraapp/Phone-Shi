#!/bin/zsh
set -eu

SOURCE="/Users/lucapritchard/claude-code/Phone-Shi/control-panel/Creator Control.applescript"
DESTINATION="/Users/lucapritchard/Applications/Creator Control.app"

if [[ ! -f "$SOURCE" ]]; then
  print -u2 "Creator Control AppleScript source was not found."
  exit 1
fi

if [[ -e "$DESTINATION" ]]; then
  print -u2 "Creator Control is already installed at $DESTINATION"
  exit 2
fi

/bin/mkdir -p /Users/lucapritchard/Applications
/usr/bin/osacompile -o "$DESTINATION" "$SOURCE"
/usr/bin/touch "$DESTINATION"
print "Installed Creator Control in /Users/lucapritchard/Applications"
