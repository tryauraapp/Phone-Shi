#!/system/bin/sh
# Apply only after boot. Early init / HAL discovery retain the original values.
# Disable with /data/adb/s25-avd-lab/qemu.disabled and reboot.
D=${S25_LAB_DIR:-/data/adb/s25-avd-lab}
if [ "${1:-}" != --restore ]; then
  [ ! -f "$D/disabled" ] && [ ! -f "$D/qemu.disabled" ] || exit 0
fi
i=0
until [ "$(getprop sys.boot_completed)" = 1 ]; do
  i=$((i + 1)); [ "$i" -lt 300 ] || exit 1
  sleep 1
done
MAGISK=$(command -v magisk)
[ -n "$MAGISK" ] || exit 1
mkdir -p "$D"
umask 077
if [ ! -f "$D/qemu.original" ]; then
  printf 'ro.kernel.qemu=%s\nro.boot.qemu=%s\n' "$(getprop ro.kernel.qemu)" "$(getprop ro.boot.qemu)" >"$D/qemu.original"
fi
restore() {
  while IFS='=' read -r key value; do
    case "$key" in ro.kernel.qemu|ro.boot.qemu) "$MAGISK" resetprop -n "$key" "$value" ;; esac
  done <"$D/qemu.original"
}
if [ "${1:-}" = --restore ]; then restore; exit $?; fi
if ! "$MAGISK" resetprop -n ro.kernel.qemu 0 || ! "$MAGISK" resetprop -n ro.boot.qemu 0; then
  restore
  exit 1
fi
[ "$(getprop ro.kernel.qemu)" = 0 ] && [ "$(getprop ro.boot.qemu)" = 0 ] || { restore; exit 1; }
printf '%s qemu-profile: kernel=0 boot=0\n' "$(date '+%F %T')" >>"$D/boot.log"
