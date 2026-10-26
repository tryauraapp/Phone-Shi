#!/usr/bin/env bash
# Auto-dismiss "System UI isn't responding" (ANR) dialogs by clicking "Wait".
# Runs in a loop watching a specific emulator serial.
#   ./dismiss_anr.sh emulator-5554

set -euo pipefail
SERIAL="${1:?usage: dismiss_anr.sh <serial>}"

while true; do
    # Dump the current UI; look for the ANR dialog's Wait button
    xml=$(adb -s "$SERIAL" shell uiautomator dump /dev/stdout 2>/dev/null || true)
    if echo "$xml" | grep -q 'text="Wait"'; then
        # Extract bounds of the Wait button: bounds="[x1,y1][x2,y2]"
        bounds=$(echo "$xml" | grep -oP 'text="Wait"[^/]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"' | grep -oP '\d+' | head -4)
        if [ -n "$bounds" ]; then
            read -r x1 y1 x2 y2 <<< "$(echo $bounds | tr '\n' ' ')"
            cx=$(( (x1 + x2) / 2 ))
            cy=$(( (y1 + y2) / 2 ))
            adb -s "$SERIAL" shell input tap "$cx" "$cy" 2>/dev/null
            echo "$(date '+%H:%M:%S') dismissed ANR dialog at ($cx,$cy)"
        fi
    fi
    sleep 3
done
