#!/system/bin/sh
# Synthetic framework battery telemetry for the AVD lab, not hardware wear.
# The counter override affects BatteryService, not direct Health HAL properties.
# Magisk runs this service at boot. Disable with battery.disabled, then wait
# up to 5 seconds; dumpsys battery reset restores the emulator's own values.
D=${S25_BATTERY_DIR:-/data/adb/s25-avd-lab}
[ -f "$D/battery.conf" ] && [ ! -f "$D/battery.disabled" ] || exit 0
. "$D/battery.conf"
TARGET_TEMP=$TEMP
[ ! -f "$D/battery.state" ] || . "$D/battery.state"

valid_int() { case "$1" in ''|*[!0-9]*) return 1 ;; esac; }
for value in "$LEVEL" "$TEMP" "$FULL_CHARGE_UAH" "$DRAIN_TICKS" "${TICKS:-0}"; do
  valid_int "$value" || exit 1
done
[ "$LEVEL" -ge 5 ] && [ "$LEVEL" -le 100 ] || exit 1
[ "$TEMP" -ge 250 ] && [ "$TEMP" -le 350 ] || exit 1
[ "$FULL_CHARGE_UAH" -ge 3000000 ] && [ "$FULL_CHARGE_UAH" -le 4000000 ] || exit 1
[ "$DRAIN_TICKS" -ge 8 ] && [ "$DRAIN_TICKS" -le 12 ] || exit 1
TICKS=${TICKS:-0}
until [ "$(getprop sys.boot_completed)" = 1 ]; do sleep 2; done
umask 077

apply_battery() {
  # BatteryService freezes hardware updates while these overrides are set.
  # Health, voltage, cycle count and design capacity are not overridden.
  dumpsys battery set ac 0 >/dev/null || return 1
  dumpsys battery set usb 0 >/dev/null || return 1
  dumpsys battery set wireless 0 >/dev/null || return 1
  dumpsys battery set dock 0 >/dev/null || return 1
  dumpsys battery set present 1 >/dev/null || return 1
  dumpsys battery set status 3 >/dev/null || return 1
  dumpsys battery set counter "$((FULL_CHARGE_UAH * LEVEL / 100))" >/dev/null || return 1
  dumpsys battery set temp "$TEMP" >/dev/null || return 1
  dumpsys battery set -f level "$LEVEL" >/dev/null || return 1
  {
    printf 'LEVEL=%s\nTEMP=%s\nTICKS=%s\n' "$LEVEL" "$TEMP" "$TICKS"
  } >"$D/battery.state.tmp" && mv "$D/battery.state.tmp" "$D/battery.state"
}

trap 'dumpsys battery reset >/dev/null; exit 0' INT TERM
while [ -f "$D/battery.conf" ] && [ ! -f "$D/battery.disabled" ]; do
  if ! apply_battery; then
    dumpsys battery reset >/dev/null
    echo "Battery simulation failed" >&2
    exit 1
  fi
  [ "${1:-}" != --once ] || exit 0
  sleep 5
  TICKS=$((TICKS + 1))
  if [ "$TICKS" -ge "$((DRAIN_TICKS * 12))" ]; then
    # Stop at 5% so a long unattended lab session doesn't shut down the AVD.
    [ "$LEVEL" -le 5 ] || LEVEL=$((LEVEL - 1))
    TICKS=0
  fi
  # A small mean-reverting random walk; at most 0.1 °C per five seconds.
  delta=$((RANDOM % 3 - 1))
  if [ "$TEMP" -gt "$((TARGET_TEMP + 5))" ] && [ "$((RANDOM % 4))" = 0 ]; then delta=-1; fi
  if [ "$TEMP" -lt "$((TARGET_TEMP - 5))" ] && [ "$((RANDOM % 4))" = 0 ]; then delta=1; fi
  TEMP=$((TEMP + delta))
  [ "$TEMP" -ge 250 ] || TEMP=250
  [ "$TEMP" -le 350 ] || TEMP=350
done
dumpsys battery reset >/dev/null
