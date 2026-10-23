#!/system/bin/sh
# Reversible app-visible /proc/cpuinfo fixture, installed before zygote starts.
set -e
D=${S25_LAB_DIR:-/data/adb/s25-avd-lab}/cpu
CPUINFO=${S25_CPUINFO:-/proc/cpuinfo}
MOUNTINFO=${S25_MOUNTINFO:-/proc/self/mountinfo}
trap 'rc=$?; if [ "$rc" -ne 0 ] && [ -d "$D" ]; then printf "%s cpu-profile: unavailable (exit %s); see cpu/last-error.log\n" "$(date "+%F %T")" "$rc" >>"${D%/cpu}/boot.log"; fi' EXIT
if [ "${1:-}" = --restore ]; then
  if grep -q " $CPUINFO " "$MOUNTINFO"; then
    [ -f "$D/cpuinfo" ] && [ "$(stat -c '%d:%i' "$CPUINFO")" = "$(stat -c '%d:%i' "$D/cpuinfo")" ] || exit 1
    umount "$CPUINFO"
  fi
  exit 0
fi
[ ! -f "${D%/cpu}/disabled" ] && [ ! -f "$D/disabled" ] || exit 0
# Do not stack mounts or replace a different tool's fixture.
if grep -q " $CPUINFO " "$MOUNTINFO"; then
  [ -f "$D/cpuinfo" ] && [ "$(stat -c '%d:%i' "$CPUINFO")" = "$(stat -c '%d:%i' "$D/cpuinfo")" ]
  exit $?
fi
mkdir -p "$D"
chmod 700 "$D"
[ -f "$D/original" ] || cp "$CPUINFO" "$D/original"
# Keep all other CPU fields intact; translate only Apple's implementer value.
awk '
  /^[[:space:]]*CPU implementer[[:space:]]*:/ { sub(/0[xX]61/, "0x41") }
  { print }
' "$CPUINFO" >"$D/cpuinfo.tmp"
grep -qi '^[[:space:]]*CPU implementer[[:space:]]*:[[:space:]]*0x41[[:space:]]*$' "$D/cpuinfo.tmp"
! grep -qi '^[[:space:]]*CPU implementer[[:space:]]*:[[:space:]]*0x61[[:space:]]*$' "$D/cpuinfo.tmp"
mv "$D/cpuinfo.tmp" "$D/cpuinfo"
magisk --clone-attr "$CPUINFO" "$D/cpuinfo" 2>"$D/last-error.log"
mount --bind "$D/cpuinfo" "$CPUINFO" 2>>"$D/last-error.log"
if ! cmp -s "$D/cpuinfo" "$CPUINFO"; then
  umount "$CPUINFO"
  exit 1
fi
printf '%s cpu-profile: Apple implementer 0x61 -> ARM 0x41\n' "$(date '+%F %T')" >>"${D%/cpu}/boot.log"
