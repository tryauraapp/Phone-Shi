#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  Galaxy S25 AVD Lab — Samsung Galaxy S25 (SM-S931B / pa1q) identity and
#  display profile for a Magisk-rooted, Google Play Android Studio emulator.
#
#  Local identity spoofing only: it changes what system properties and
#  android.os.Build report. It does not create Samsung firmware, hardware-backed
#  keys or attestation, and it does not make Play Integrity pass.
#
#  Usage: galaxy_s25_avd_lab.sh [--avd NAME] [--action ACTION] [--yes] [--vsync HZ]
#    ACTION  apply | status | inventory | reboot | rollback | watch
#    --yes   answer "yes" to confirmations (non-interactive use)
#    --vsync guest refresh rate to request when this script launches the AVD
#    --fingerprint VALUE  supplied Samsung/Android-15 fingerprint (apply only)
#
#  Compatible with macOS /bin/bash 3.2.
# ─────────────────────────────────────────────────────────────────────────────
set -u -o pipefail

VERSION=2.0
# Space-separated: the only AVDs this script will modify. S25_LAB_ALLOW adds more
# (setup_galaxy_s25_avd.sh uses it for the AVD it just created).
ALLOWED_AVDS="Galaxy_s25_-_3 ${S25_LAB_ALLOW:-}"
SDK="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/Library/Android/sdk}}"
export PATH="$SDK/platform-tools:$SDK/emulator:$PATH"
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROBE_DEX="$SCRIPT_DIR/probe/BuildProbe.dex"
LAB_ROOT="$HOME/galaxy_s25_avd_backups"

# On-device layout (inside Magisk's root-only /data/adb)
DEV_DIR=/data/adb/s25-avd-lab
PFD_SCRIPT=/data/adb/post-fs-data.d/99-s25-avd-lab.sh
SVC_SCRIPT=/data/adb/service.d/99-s25-avd-lab.sh
TMP=/data/local/tmp

# ── Galaxy S25 profile ──────────────────────────────────────────────────────
S25_MODEL=SM-S931B
S25_BRAND=samsung
S25_MANUFACTURER=samsung
S25_DEVICE=pa1q
S25_NAME=pa1qxxx
S25_BOARD=sun            # board codename reported by SM-S931B Geekbench entries
S25_SOC_MANUFACTURER=QTI
S25_SOC_MODEL=SM8750     # Snapdragon 8 Elite (for Galaxy)
S25_HARDWARE=sun
SYN_ID=AP3A.240905.015.A2
SYN_INCREMENTAL=S931BXXS4AYF1
# Constructed Samsung-shaped lab profile, not an extracted/attested firmware image.
# Samsung lists this incremental for SM-S931B / Android 15. See REPORT.md.
FINGERPRINT_OVERRIDE=
FINGERPRINT_SOURCE='synthetic fixture'
WM_SIZE=1080x2340
WM_DENSITY=416
PARTITIONS=". .product. .system. .system_ext. .vendor. .odm. .bootimage. .system_dlkm. .vendor_dlkm."

# Prints the profile as key=value lines. $1 = Android release (kept as-is).
profile_props() {
  local rel=$1 p fp="$S25_BRAND/$S25_NAME/$S25_DEVICE:$1/$SYN_ID/$SYN_INCREMENTAL:user/release-keys"
  for p in $PARTITIONS; do
    echo "ro.product${p}model=$S25_MODEL"
    echo "ro.product${p}brand=$S25_BRAND"
    echo "ro.product${p}manufacturer=$S25_MANUFACTURER"
    echo "ro.product${p}device=$S25_DEVICE"
    echo "ro.product${p}name=$S25_NAME"
  done
  for p in $PARTITIONS; do echo "ro${p}build.fingerprint=$fp"; done
  echo "ro.build.description=$S25_NAME-user $rel $SYN_ID $SYN_INCREMENTAL release-keys"
  echo "ro.build.display.id=$SYN_ID"
  # Keep Build.ID / VERSION.INCREMENTAL consistent with the fingerprint.
  echo "ro.build.id=$SYN_ID"
  echo "ro.build.version.incremental=$SYN_INCREMENTAL"
  echo "ro.build.flavor=$S25_NAME-user"
  echo "ro.build.product=$S25_DEVICE"
  echo "ro.build.characteristics=phone"
  # Conditionally testable: only Build.BOARD / Build.SOC_* read these; emulator HALs
  # select modules through ro.hardware.* instead.
  echo "ro.product.board=$S25_BOARD"
  echo "ro.soc.manufacturer=$S25_SOC_MANUFACTURER"
  echo "ro.soc.model=$S25_SOC_MODEL"
  # Set before zygote caches Build.HARDWARE. Keep boot hardware and explicit
  # graphics/power HAL selectors unchanged so emulator drivers still load.
  echo "ro.hardware=$S25_HARDWARE"
}

# Not changed by the identity profile. The optional separate QEMU service changes
# only ro.kernel.qemu / ro.boot.qemu after boot; early init uses their original values.
KEYS_UNTOUCHED="ro.boot.hardware ro.hardware.egl ro.hardware.gralloc ro.hardware.power
ro.hardware.vulkan ro.boot.hardware.vulkan ro.board.platform ro.kernel.qemu ro.boot.qemu
ro.boot.qemu.avd_name ro.boot.serialno ro.serialno ro.product.cpu.abi ro.product.cpu.abilist
ro.product.cpu.abilist32 ro.product.cpu.abilist64
ro.build.version.release ro.build.version.sdk ro.build.tags ro.build.type ro.build.host
ro.build.user ro.bootloader ro.boot.verifiedbootstate qemu.sf.lcd_density"

# ── UI ──────────────────────────────────────────────────────────────────────
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  B=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'
  BLU=$'\033[34m'; MAG=$'\033[35m'; CYN=$'\033[36m'; X=$'\033[0m'
else
  B= DIM= RED= GRN= YEL= BLU= MAG= CYN= X=
fi
LOG=/dev/null
STEP=0
STEPS=0
YES=0

log()  { printf '%s %s\n' "$(date '+%H:%M:%S')" "$*" >>"$LOG"; }
step() { STEP=$((STEP+1)); printf '\n %s[%d/%d]%s %s%s%s\n' "$CYN" "$STEP" "$STEPS" "$X" "$B" "$*" "$X"; log "== $*"; }
info() { printf '   %s›%s %s\n' "$CYN" "$X" "$*"; log "info: $*"; }
ok()   { printf '   %s✓%s %s\n' "$GRN" "$X" "$*"; log "ok: $*"; }
warn() { printf '   %s!%s %s\n' "$YEL" "$X" "$*"; log "warn: $*"; }
fail() { printf '   %s✗%s %s\n' "$RED" "$X" "$*"; log "fail: $*"; }
die()  { fail "$*"; printf '\n   %sLog:%s %s\n\n' "$DIM" "$X" "$LOG"; exit 1; }
rule() { printf ' %s%s%s\n' "$DIM" "────────────────────────────────────────────────────────────────────────────────" "$X"; }

restore_tty() { tput cnorm 2>/dev/null; printf '%s' "$X"; }
trap restore_tty EXIT
trap 'echo; exit 130' INT

banner() {
  printf '%s%s' "$B" "$BLU"
  cat <<'EOF'

    ██████╗  █████╗ ██╗      █████╗ ██╗  ██╗██╗   ██╗    ███████╗██████╗ ███████╗
   ██╔════╝ ██╔══██╗██║     ██╔══██╗╚██╗██╔╝╚██╗ ██╔╝    ██╔════╝╚════██╗██╔════╝
   ██║  ███╗███████║██║     ███████║ ╚███╔╝  ╚████╔╝     ███████╗ █████╔╝███████╗
   ██║   ██║██╔══██║██║     ██╔══██║ ██╔██╗   ╚██╔╝      ╚════██║██╔═══╝ ╚════██║
   ╚██████╔╝██║  ██║███████╗██║  ██║██╔╝ ██╗   ██║       ███████║███████╗███████║
    ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝       ╚══════╝╚══════╝╚══════╝
EOF
  printf '%s' "$X"
  printf '   %sAVD LAB v%s%s  ·  SM-S931B · pa1q · 1080×2340 @ 416 dpi · Magisk · Google Play\n' "$MAG$B" "$VERSION" "$X"
  printf '   %sLocal identity spoofing for emulator-detection coursework — not real Samsung hardware.%s\n' "$DIM" "$X"
}

confirm() {
  ((YES)) && { log "auto-confirmed: $1"; return 0; }
  local a; printf '   %s?%s %s %s[y/N]%s ' "$MAG" "$X" "$1" "$DIM" "$X"
  IFS= read -r a </dev/tty || return 1
  [[ "$a" == [yY]* ]]
}

# menu VAR "Title" item... → stores the chosen index in VAR; returns 1 on Esc/q.
menu() {
  local __var=$1 title=$2; shift 2
  local n=$# __i=0 key rest i items=("$@")
  printf '\n   %s%s%s  %s↑/↓ move · Enter select · Esc cancel%s\n' "$B" "$title" "$X" "$DIM" "$X"
  tput civis 2>/dev/null
  while :; do
    for ((i = 0; i < n; i++)); do
      if ((i == __i)); then printf '\r\033[K   %s❯ %s%s\n' "$GRN$B" "${items[i]}" "$X"
      else printf '\r\033[K     %s\n' "${items[i]}"; fi
    done
    IFS= read -rsn1 key </dev/tty
    case "$key" in
      $'\033')
        rest=
        IFS= read -rsn2 -t 1 rest </dev/tty
        case "$rest" in
          '[A' | 'OA') __i=$(((__i - 1 + n) % n)) ;;
          '[B' | 'OB') __i=$(((__i + 1) % n)) ;;
          '') tput cnorm 2>/dev/null; return 1 ;;
        esac ;;
      '') break ;;
      k) __i=$(((__i - 1 + n) % n)) ;;
      j) __i=$(((__i + 1) % n)) ;;
      q) tput cnorm 2>/dev/null; return 1 ;;
    esac
    printf '\033[%dA' "$n"
  done
  tput cnorm 2>/dev/null
  printf -v "$__var" '%s' "$__i"
}

spin_wait() { # spin_wait "message" timeout_s check_fn [args] → 0 once check_fn succeeds
  local msg=$1 t=$2 i=0 f='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'; shift 2
  while ! "$@" >/dev/null 2>&1; do
    ((i >= t * 2)) && { printf '\r\033[K'; return 1; }
    [[ -t 1 ]] && printf '\r   %s%s%s %s %s(%ds)%s' "$CYN" "${f:i%10:1}" "$X" "$msg" "$DIM" $((i / 2)) "$X"
    sleep 0.5; i=$((i + 1))
  done
  [[ -t 1 ]] && printf '\r\033[K'
  return 0
}

trunc() { local s=$1 w=$2; ((${#s} > w)) && s="${s:0:w-1}…"; printf '%s' "$s"; }

# ── Device access ───────────────────────────────────────────────────────────
# Scripts go to the device over stdin, never through adb's argv: `adb shell` re-joins
# argv and the guest sh re-parses it, so in `adb shell su -c 'a; b'` only `a` runs as
# root and `b` runs as uid 2000. That was the cause of the original
# "/data/adb: Permission denied" — root and SELinux were fine.
dsh() {
  local out rc
  out=$(printf '%s\n' "$1" | adb -s "$SERIAL" shell sh 2>&1 | tr -d '\r'); rc=$?
  { echo "--- sh (rc=$rc):"; echo "$1" | head -5; echo "$out" | head -50; } >>"$LOG"
  [[ -n "$out" ]] && printf '%s\n' "$out"
  return $rc
}
dsu() {
  local out rc
  out=$(printf '%s\n' "$1" | adb -s "$SERIAL" shell su 2>&1 | tr -d '\r'); rc=$?
  { echo "--- su (rc=$rc):"; echo "$1"; echo "$out" | head -50; } >>"$LOG"
  [[ -n "$out" ]] && printf '%s\n' "$out"
  return $rc
}
push() { adb -s "$SERIAL" push "$1" "$2" >>"$LOG" 2>&1; }

avd_of() { adb -s "$1" emu avd name 2>/dev/null | head -n1 | tr -d '\r'; }
find_serials() {
  local s
  for s in $(adb devices 2>/dev/null | awk 'NR > 1 && $1 ~ /^emulator-/ {print $1}'); do
    [[ "$(avd_of "$s")" == "$1" ]] && echo "$s"
  done
}
is_allowed() { local a; for a in $ALLOWED_AVDS; do [[ "$a" == "$1" ]] && return 0; done; return 1; }

# Two independent sources must agree: the emulator console and the guest's boot property.
assert_identity() {
  local con guest
  con=$(avd_of "$SERIAL")
  guest=$(adb -s "$SERIAL" shell getprop ro.boot.qemu.avd_name 2>/dev/null | tr -d '\r')
  [[ "$con" == "$AVD" && "$guest" == "$AVD" ]] ||
    die "Identity check failed: $SERIAL reports console='$con' guest='$guest', expected '$AVD'."
}
assert_target() {
  is_allowed "$AVD" || die "Refusing to modify '$AVD': not in ALLOWED_AVDS ($ALLOWED_AVDS)."
  assert_identity
}

booted() { [[ "$(adb -s "$SERIAL" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == 1 ]]; }
boot_id() { adb -s "$SERIAL" shell cat /proc/sys/kernel/random/boot_id 2>/dev/null | tr -d '\r'; }
new_boot() { local b; b=$(boot_id); [[ -n "$b" && "$b" != "$OLD_BOOT" ]] && booted; }
guest_up() { [[ -n "$(adb -s "$SERIAL" shell getprop ro.boot.qemu.avd_name 2>/dev/null | tr -d '\r')" ]]; }
serial_up() { SERIAL=$(find_serials "$AVD" | head -n1); [[ -n "$SERIAL" ]]; }

connect() {
  local matches n
  matches=$(find_serials "$AVD")
  n=$(printf '%s' "$matches" | grep -c . || true)
  if ((n > 1)); then die "More than one running emulator reports '$AVD': $(echo $matches). Close the extras."; fi
  if ((n == 0)); then
    is_allowed "$AVD" || die "'$AVD' is not running, and this script only launches allowlisted AVDs."
    info "Launching $AVD (cold boot so Magisk boot scripts run)…"
    local args=(-avd "$AVD" -no-snapshot-load -no-snapshot-save)
    [[ -n "$VSYNC" ]] && args+=(-vsync-rate "$VSYNC")
    nohup emulator "${args[@]}" >"$DIR/emulator-$(date +%Y%m%d-%H%M%S).log" 2>&1 &
    spin_wait "Waiting for $AVD to attach to adb" 240 serial_up || die "Emulator did not attach to adb."
  else
    SERIAL=$matches
  fi
  spin_wait "Waiting for the guest to answer over adb" 240 guest_up || die "Guest did not come up on $SERIAL."
  assert_identity
  ok "Target ${B}$AVD${X} is ${B}$SERIAL${X} (console + ro.boot.qemu.avd_name agree)"
  spin_wait "Waiting for Android to finish booting" 300 booted || die "Boot timed out."
  ok "Android boot completed"
}

# ── Property helpers ────────────────────────────────────────────────────────
# getprops KEY... → "key<TAB>value" lines (keys are plain [a-z0-9._] strings)
getprops() {
  dsh "for k in $*; do printf '%s\t%s\n' \"\$k\" \"\$(getprop \"\$k\")\"; done"
}
tsv_get() { awk -F'\t' -v k="$2" '$1 == k { print substr($0, length(k) + 2); exit }' "$1"; }
profile_keys() { profile_props 15 | cut -d= -f1; }
all_keys() { { profile_keys; echo $KEYS_UNTOUCHED | tr ' ' '\n'; } | awk 'NF && !seen[$0]++'; }

# Extracts KEY<TAB>VALUE for all_keys from a saved `getprop` dump.
getprop_dump_to_tsv() {
  local k
  for k in $(all_keys); do
    printf '%s\t%s\n' "$k" "$(grep -F "[$k]: [" "$1" | head -n1 | sed 's/^[^]]*\]: \[//; s/\]$//')"
  done
}

play_check() { # prints status lines; returns 1 if a Play component is missing
  local p rc=0 path
  for p in com.android.vending com.google.android.gms com.google.android.gsf; do
    path=$(adb -s "$SERIAL" shell pm path "$p" 2>/dev/null | tr -d '\r' | head -n1)
    if [[ "$path" == package:* ]]; then ok "$p installed"; else fail "$p MISSING"; rc=1; fi
  done
  return $rc
}

root_check() {
  local id
  id=$(dsu 'id -u')
  [[ "$id" == 0 ]] || die "Magisk su did not return uid 0 (got: '$id'). In the Magisk app → Superuser, allow 'Shell'."
  ok "Magisk root works via su (uid 0, $(dsu 'cat /proc/self/attr/current' | tr -d '\0'))"
  dsu "magisk resetprop ro.build.type >/dev/null" >/dev/null || die "magisk resetprop is unavailable."
  ok "Magisk $(dsh 'magisk -v') · resetprop available · SELinux $(dsh getenforce)"
}

persistence_state() { # → "installed" | "absent" | "partial"
  local s
  s=$(dsu "[ -x $PFD_SCRIPT ] && echo p; [ -x $SVC_SCRIPT ] && echo s; [ -f $DEV_DIR/profile.props ] && echo f" | tr -d '\n')
  case "$s" in psf) echo installed ;; '') echo absent ;; *) echo partial ;; esac
}

# 0 if the profile was applied before zygote started in the current boot → apps see it.
applied_this_boot() {
  local m
  m=$(dsu "cat $DEV_DIR/applied_boot 2>/dev/null" | awk '{print $1}')
  [[ -n "$m" && "$m" == "$(boot_id)" ]]
}

# ── Backups ─────────────────────────────────────────────────────────────────
backup() {
  local ts snap model old
  ts=$(date +%Y%m%d-%H%M%S)
  mkdir -p "$DIR/snapshots"
  snap="$DIR/snapshots/getprop-$ts.txt"
  adb -s "$SERIAL" shell getprop | tr -d '\r' >"$snap" || die "Could not snapshot properties."
  ok "Full property snapshot → ${DIM}$snap${X}"

  if [[ ! -s "$DIR/original-props.tsv" ]]; then
    model=$(grep -F '[ro.product.model]: [' "$snap" | sed 's/.*: \[//; s/\]$//')
    if [[ "$model" == "$S25_MODEL" ]]; then
      # Device already spoofed and no original saved: fall back to the oldest unmodified dump.
      old=$(grep -lF '[ro.product.model]: [sdk_' "$DIR"/getprop-before-*.txt "$DIR"/snapshots/getprop-*.txt 2>/dev/null | head -n1)
      [[ -n "$old" ]] || die "Device already reports $S25_MODEL and no pristine snapshot exists. Reboot without the profile first."
      snap=$old
      warn "Device already spoofed; originals taken from earlier snapshot $(basename "$old")"
    fi
    getprop_dump_to_tsv "$snap" >"$DIR/original-props.tsv"
    adb -s "$SERIAL" shell 'wm size; wm density' | tr -d '\r' >"$DIR/original-display.txt"
    ok "Original values saved (first run only) → ${DIM}$DIR/original-props.tsv${X}"
  else
    ok "Original values already on file (kept unchanged) → ${DIM}$DIR/original-props.tsv${X}"
    # Older versions did not track ID/incremental. Capture newly tracked keys
    # before this version changes them, without replacing existing originals.
    local k
    for k in $(profile_keys); do
      if ! awk -F'\t' -v k="$k" '$1 == k { found=1 } END { exit !found }' "$DIR/original-props.tsv"; then
        printf '%s\t%s\n' "$k" "$(grep -F "[$k]: [" "$snap" | head -n1 | sed 's/^[^]]*\]: \[//; s/\]$//')" >>"$DIR/original-props.tsv"
      fi
    done
  fi
}

# ── Device-side scripts ─────────────────────────────────────────────────────
write_device_files() { # $1 = work dir
  local rel
  rel=$(adb -s "$SERIAL" shell getprop ro.build.version.release | tr -d '\r')
  profile_props "$rel" >"$1/profile.props"
  printf 'SIZE=%s\nDENSITY=%s\n' "$WM_SIZE" "$WM_DENSITY" >"$1/display.conf"

  cat >"$1/pfd.sh" <<'EOF'
#!/system/bin/sh
# Galaxy S25 AVD Lab — Magisk post-fs-data script. Runs before zygote, so
# android.os.Build in every app process sees the profile. Never creates new
# properties; only overrides ones the image defines. Values are in-memory only:
# delete this file (or touch /data/adb/s25-avd-lab/disabled) and reboot to undo.
D=/data/adb/s25-avd-lab
[ -f "$D/profile.props" ] && [ ! -f "$D/disabled" ] || exit 0
MAGISK=$(command -v magisk 2>/dev/null)
[ -n "$MAGISK" ] || MAGISK=/debug_ramdisk/magisk
n=0; skipped=0
while IFS='=' read -r k v || [ -n "$k" ]; do
  case "$k" in '' | \#*) continue ;; esac
  if [ -z "$(getprop "$k")" ]; then skipped=$((skipped + 1)); continue; fi
  "$MAGISK" resetprop -n "$k" "$v" && n=$((n + 1))
done <"$D/profile.props"
[ "${1:-}" = runtime ] || echo "$(cat /proc/sys/kernel/random/boot_id) post-fs-data" >"$D/applied_boot"
echo "$(date '+%F %T') ${1:-boot}: set=$n skipped=$skipped" >>"$D/boot.log"
EOF

  cat >"$1/svc.sh" <<'EOF'
#!/system/bin/sh
# Galaxy S25 AVD Lab — Magisk late_start service. Android already persists wm
# overrides; this re-asserts them in case something reset them.
D=/data/adb/s25-avd-lab
[ -f "$D/display.conf" ] && [ ! -f "$D/disabled" ] || exit 0
. "$D/display.conf"
i=0
until [ "$(getprop sys.boot_completed)" = 1 ]; do
  i=$((i + 1)); [ $i -gt 180 ] && exit 0; sleep 1
done
wm size "$SIZE" && wm density "$DENSITY" &&
  echo "$(date '+%F %T') display: $SIZE @ $DENSITY dpi" >>"$D/boot.log"
EOF
}

# Copies the profile into DEV_DIR; with $2=1 also installs the boot scripts.
install_files() { # $1 = work dir, $2 = install boot scripts (1/0)
  local f
  for f in profile.props display.conf pfd.sh svc.sh; do
    push "$1/$f" "$TMP/s25lab-$f" || return 1
  done
  dsu "set -e
mkdir -p $DEV_DIR; chmod 700 $DEV_DIR
cp $TMP/s25lab-profile.props $DEV_DIR/profile.props
cp $TMP/s25lab-display.conf $DEV_DIR/display.conf
cp $TMP/s25lab-pfd.sh $DEV_DIR/apply.sh
chmod 600 $DEV_DIR/profile.props $DEV_DIR/display.conf; chmod 700 $DEV_DIR/apply.sh
if [ $2 = 1 ]; then
  mkdir -p ${PFD_SCRIPT%/*} ${SVC_SCRIPT%/*}
  cp $TMP/s25lab-pfd.sh $PFD_SCRIPT; cp $TMP/s25lab-svc.sh $SVC_SCRIPT
  chmod 755 $PFD_SCRIPT $SVC_SCRIPT
fi
rm -f $TMP/s25lab-*" >/dev/null
}

apply_display() {
  dsh "wm size $WM_SIZE && wm density $WM_DENSITY" >/dev/null &&
    ok "Display override: $WM_SIZE @ $WM_DENSITY dpi" || fail "Display override failed"
  # 120 Hz only exists if the AVD was launched with -vsync-rate 120 (--vsync 120). It is a
  # single fixed-rate mode, not the S25's adaptive 1–120 Hz panel; we only lift the peak cap.
  local hz; hz=$(dsh 'getprop ro.boot.qemu.vsync')
  if [[ "$hz" =~ ^[0-9]+$ ]] && ((hz >= 120)); then
    dsh 'settings put system peak_refresh_rate 120.0' >/dev/null && ok "Peak refresh rate: 120 Hz (guest vsync $hz Hz)"
  else
    info "Refresh rate stays ${hz:-60} Hz (launch with --vsync 120 for a 120 Hz guest mode)"
  fi
}

soft_restart() { # restart zygote so newly started app processes read the new Build values
  OLD_PID=$(dsh 'pidof system_server')
  dsu 'setprop ctl.restart zygote' >/dev/null
  spin_wait "Restarting Android framework" 180 framework_back || return 1
}
framework_back() {
  local p; p=$(dsh 'pidof system_server')
  [[ -n "$p" && "$p" != "$OLD_PID" ]] && dsh 'pm path android' | grep -q package:
}

# ── Verification dashboard ──────────────────────────────────────────────────
probe_build() {
  [[ -f "$PROBE_DEX" ]] || { warn "Build probe not found at $PROBE_DEX"; return 1; }
  push "$PROBE_DEX" "$TMP/BuildProbe.dex" && dsh "CLASSPATH=$TMP/BuildProbe.dex app_process /system/bin BuildProbe"
}

dashboard() {
  local cur prof k want o n st col c_chg=0 c_same=0 c_uns=0 c_fail=0 stale=0 rel
  cur=$(mktemp); prof=$(mktemp)
  getprops $(all_keys) >"$cur"
  rel=$(tsv_get "$cur" ro.build.version.release)
  profile_props "$rel" >"$prof"
  applied_this_boot || stale=1

  printf '\n %s%s  GALAXY S25 PROFILE · %s · %s%s\n' "$B" "$MAG" "$AVD" "$SERIAL" "$X"
  rule
  printf ' %s%-36s %-24s %-24s %s%s\n' "$DIM" PROPERTY ORIGINAL NOW STATUS "$X"
  while IFS='=' read -r k want; do
    o=$(tsv_get "$DIR/original-props.tsv" "$k" 2>/dev/null); n=$(tsv_get "$cur" "$k")
    if [[ -z "$o" && -z "$n" ]]; then st=UNSUPPORTED col=$DIM; c_uns=$((c_uns + 1))
    elif [[ "$n" == "$want" && "$o" == "$want" ]]; then st=UNCHANGED col=$BLU; c_same=$((c_same + 1))
    elif [[ "$n" == "$want" ]]; then
      c_chg=$((c_chg + 1))
      if ((stale)); then st="CHANGED·REBOOT" col=$YEL; else st=CHANGED col=$GRN; fi
    else st=FAILED col=$RED; c_fail=$((c_fail + 1))
    fi
    printf ' %-36s %-24s %-24s %s%s%s\n' "$(trunc "$k" 36)" "$(trunc "${o:-—}" 24)" "$(trunc "${n:-—}" 24)" "$col" "$st" "$X"
    log "prop $k | orig=$o | now=$n | want=$want | $st"
  done <"$prof"
  rule
  printf ' %sLeft unchanged on purpose%s (emulator infrastructure / OS version / ABI)\n' "$DIM" "$X"
  for k in ro.boot.hardware ro.kernel.qemu ro.boot.qemu ro.product.cpu.abi ro.build.version.release ro.boot.serialno; do
    printf ' %-36s %-24s %s\n' "$k" "$(trunc "$(tsv_get "$cur" "$k")" 24)" "${DIM}KEPT${X}"
  done
  rule

  local size dens
  size=$(dsh 'wm size' | tr '\n' ' '); dens=$(dsh 'wm density' | tr '\n' ' ')
  printf ' %-36s %s\n' "wm size" "$size"
  printf ' %-36s %s\n' "wm density" "$dens"
  printf ' %-36s %s\n' "refresh rate" "$(dsh "dumpsys display 2>/dev/null | grep -m1 -oE 'renderFrameRate [0-9.]+'")"
  printf ' %-36s %s\n' "boot persistence" "$(persistence_state)"
  if ((stale)); then
    printf ' %-36s %s\n' "android.os.Build in apps" "${YEL}stale until reboot (props changed after zygote start)${X}"
  else
    printf ' %-36s %s\n' "android.os.Build in apps" "${GRN}profile applied before zygote this boot${X}"
  fi
  rule
  printf ' %s%d changed%s · %s%d already matching%s · %s%d unsupported (not defined by image)%s · %s%d failed%s\n' \
    "$GRN" $c_chg "$X" "$BLU" $c_same "$X" "$DIM" $c_uns "$X" "$RED" $c_fail "$X"
  rm -f "$cur" "$prof"
  DASH_FAILED=$c_fail
}

# ── Actions ─────────────────────────────────────────────────────────────────
do_apply() {
  local work persist=1
  STEPS=7; STEP=0
  step "Pre-flight checks"
  assert_target
  root_check
  play_check || die "Google Play components missing before changes — aborting."
  info "Android $(dsh 'getprop ro.build.version.release') (API $(dsh 'getprop ro.build.version.sdk')) · $(dsh 'getprop ro.product.cpu.abi') · $(dsh 'uname -m')"

  step "Backups"
  backup

  step "Preparing Galaxy S25 profile"
  work=$(mktemp -d)
  write_device_files "$work"
  ok "$(grep -c . "$work/profile.props") property overrides generated ($FINGERPRINT_SOURCE, build $SYN_ID)"
  info "Absent properties are skipped on the device, never created."

  step "Installing boot persistence (Magisk post-fs-data.d + service.d)"
  assert_target
  if install_files "$work" 1 && [[ "$(persistence_state)" == installed ]]; then
    ok "post-fs-data.d → $PFD_SCRIPT ${DIM}(props, before zygote)${X}"
    ok "service.d     → $SVC_SCRIPT ${DIM}(display, after boot)${X}"
  else
    persist=0
    warn "Could not install Magisk boot scripts — falling back to session-only mode."
    install_files "$work" 0 || die "Could not write $DEV_DIR either."
    warn "Use '--action watch' to re-apply from the Mac each time the AVD boots."
  fi
  rm -rf "$work"
  if [[ -n "$FINGERPRINT_OVERRIDE" ]]; then
    printf '%s\n' "$FINGERPRINT_OVERRIDE" >"$DIR/identity.fingerprint"
  fi

  step "Applying identity now (runtime)"
  assert_target
  dsu "sh $DEV_DIR/apply.sh runtime" >/dev/null || die "Applying properties failed."
  ok "resetprop applied: $(dsu "tail -n1 $DEV_DIR/boot.log" | sed 's/^.*: //')"

  step "Display"
  assert_target
  apply_display

  step "Verification"
  play_check || die "Google Play component missing after changes!"
  root_check
  dashboard

  if ! applied_this_boot; then
    printf '\n'
    warn "Running apps cached the old android.os.Build values at zygote start."
    if ((persist)); then
      confirm "Reboot $AVD now and verify the profile is applied at boot?" && do_reboot
    else
      confirm "Restart the Android framework (soft restart) so apps see the new values?" &&
        soft_restart && dsu "echo \"\$(cat /proc/sys/kernel/random/boot_id) soft-restart\" > $DEV_DIR/applied_boot" &&
        ok "Framework restarted — SESSION ONLY, lost on next boot."
    fi
  fi
}

do_reboot() {
  STEPS=3; STEP=0
  step "Rebooting $AVD"
  assert_target
  OLD_BOOT=$(boot_id)
  adb -s "$SERIAL" reboot >>"$LOG" 2>&1
  spin_wait "Waiting for reboot" 360 new_boot || die "Device did not come back."
  assert_identity
  ok "Rebooted and booted (new boot id)"
  spin_wait "Waiting for service.d display step" 60 display_ok || warn "Display override not confirmed yet."

  step "Health"
  root_check
  play_check || die "Google Play component missing after reboot!"
  dashboard

  step "android.os.Build as read by a fresh ART runtime"
  probe_build | sed 's/^/   /'
  if applied_this_boot; then ok "Profile applied in post-fs-data before zygote — apps see these values."
  else warn "Profile not applied at this boot (session-only mode or persistence missing)."; fi
}
display_ok() { dsh 'wm size; wm density' | grep -q "Override size: $WM_SIZE" && dsh 'wm density' | grep -q "Override density: $WM_DENSITY"; }

do_status() {
  STEPS=2; STEP=0
  step "Health"
  assert_identity
  root_check
  play_check
  [[ -s "$DIR/original-props.tsv" ]] || { warn "No original backup yet (run 'apply')."; touch "$DIR/original-props.tsv"; }
  dashboard
  step "android.os.Build as read by a fresh ART runtime"
  probe_build | sed 's/^/   /'
}

do_rollback() {
  local work k v orig_size
  STEPS=4; STEP=0
  step "Pre-flight"
  assert_target
  root_check
  [[ -s "$DIR/original-props.tsv" ]] || die "No original backup at $DIR/original-props.tsv."
  confirm "Remove the S25 profile from $AVD and restore original values?" || { info "Cancelled."; return; }

  step "Removing boot persistence"
  mkdir -p "$DIR/device-logs"
  dsu "cat $DEV_DIR/boot.log 2>/dev/null" >"$DIR/device-logs/boot-$(date +%Y%m%d-%H%M%S).log"
  dsu "touch $DEV_DIR/battery.disabled
if [ -f /data/adb/service.d/97-s25-qemu.sh ]; then sh /data/adb/service.d/97-s25-qemu.sh --restore; fi
if [ -f /data/adb/post-fs-data.d/97-s25-cpu.sh ]; then sh /data/adb/post-fs-data.d/97-s25-cpu.sh --restore; fi
if [ -d /data/adb/modules/s25_sensor_labels ]; then touch /data/adb/modules/s25_sensor_labels/disable; fi
if [ -d /data/adb/modules_update/s25_sensor_labels ]; then touch /data/adb/modules_update/s25_sensor_labels/disable; fi
if [ -d /data/adb/modules/s25_radio_imei ]; then touch /data/adb/modules/s25_radio_imei/disable; fi
if [ -d /data/adb/modules_update/s25_radio_imei ]; then touch /data/adb/modules_update/s25_radio_imei/disable; fi
if [ -d /data/adb/modules/s25_qemu_metadata ]; then touch /data/adb/modules/s25_qemu_metadata/disable; fi
if [ -d /data/adb/modules_update/s25_qemu_metadata ]; then touch /data/adb/modules_update/s25_qemu_metadata/disable; fi
rm -f $PFD_SCRIPT $SVC_SCRIPT /data/adb/post-fs-data.d/97-s25-cpu.sh /data/adb/post-fs-data.d/98-s25-file-aliases.sh /data/adb/service.d/96-s25-network.sh /data/adb/service.d/97-s25-qemu.sh /data/adb/service.d/98-s25-battery.sh
dumpsys battery reset >/dev/null
rm -rf $DEV_DIR" >/dev/null
  [[ "$(persistence_state)" == absent ]] && ok "Boot scripts and $DEV_DIR removed" || fail "Some lab files remain"

  step "Restoring original properties and display"
  work=$(mktemp -d)
  while IFS=$'\t' read -r k v; do
    [[ -n "$v" ]] && profile_keys | grep -qxF "$k" && printf '%s=%s\n' "$k" "$v"
  done <"$DIR/original-props.tsv" >"$work/restore.props"
  push "$work/restore.props" "$TMP/s25lab-restore.props"
  dsu "while IFS='=' read -r k v || [ -n \"\$k\" ]; do [ -n \"\$k\" ] && magisk resetprop -n \"\$k\" \"\$v\"; done < $TMP/s25lab-restore.props; rm -f $TMP/s25lab-restore.props" >/dev/null
  ok "$(grep -c . "$work/restore.props") properties restored in memory"
  rm -rf "$work"
  orig_size=$(sed -n 's/^Override size: //p' "$DIR/original-display.txt" 2>/dev/null)
  if [[ -n "$orig_size" ]]; then dsh "wm size $orig_size" >/dev/null; else dsh 'wm size reset' >/dev/null; fi
  orig_size=$(sed -n 's/^Override density: //p' "$DIR/original-display.txt" 2>/dev/null)
  if [[ -n "$orig_size" ]]; then dsh "wm density $orig_size" >/dev/null; else dsh 'wm density reset' >/dev/null; fi
  dsh 'settings delete system peak_refresh_rate' >/dev/null
  ok "Display: $(dsh 'wm size' | tail -n1) · $(dsh 'wm density' | tail -n1)"

  step "Verify"
  play_check
  local cur bad=0
  cur=$(mktemp); getprops $(profile_keys) >"$cur"
  while IFS=$'\t' read -r k v; do
    profile_keys | grep -qxF "$k" || continue
    [[ "$(tsv_get "$cur" "$k")" == "$v" ]] || { fail "$k is '$(tsv_get "$cur" "$k")', original '$v'"; bad=1; }
  done <"$DIR/original-props.tsv"
  rm -f "$cur"
  ((bad)) || ok "All profile properties match the original backup"
  warn "Running apps keep the Samsung Build values until the next reboot."
  confirm "Reboot $AVD now?" && { assert_target; OLD_BOOT=$(boot_id); adb -s "$SERIAL" reboot >>"$LOG" 2>&1
    spin_wait "Waiting for reboot" 360 new_boot && ok "Rebooted — original identity: $(dsh 'getprop ro.product.model')"; }
}

do_inventory() {
  local ts out base
  STEPS=2; STEP=0
  step "Collecting emulator-signal inventory"
  assert_identity
  ts=$(date +%Y%m%d-%H%M%S)
  mkdir -p "$DIR/inventory"
  out="$DIR/inventory/inventory-$ts.txt"
  base="$DIR/inventory/inventory-baseline.txt"
  {
    echo "# Galaxy S25 AVD Lab inventory · $AVD · $SERIAL · $(date)"
    echo "# section|key|value   (collected as the adb shell user)"
    dsh "$(inventory_script)"
    probe_build | sed 's/^/build-api|/; s/=/|/'
  } >"$out"
  ok "$(grep -vc '^#' "$out") signals → ${DIM}$out${X}"
  if [[ ! -f "$base" ]]; then
    if [[ "$(grep -F 'prop|ro.product.model|' "$out")" == *"$S25_MODEL"* ]]; then
      warn "Profile already active; not saving this as the pre-change baseline."
    else
      cp "$out" "$base"; ok "Saved as pre-change baseline"
    fi
  fi

  step "Comparison with pre-change baseline"
  [[ -f "$base" ]] || { info "No baseline yet."; return; }
  awk -F'|' 'NR == FNR { if ($0 !~ /^#/) b[$1 "|" $2] = $3; next }
    !/^#/ { k = $1 "|" $2; s = (k in b) ? (b[k] == $3 ? "same" : "CHANGED") : "new"
            printf "%-8s %-11s %-38s %s\n", s, $1, substr($2, 1, 38), substr($3, 1, 70) }' "$base" "$out" >"$out.cmp"
  printf ' %s%-8s %-11s %-38s %s%s\n' "$DIM" STATE SECTION SIGNAL "VALUE NOW" "$X"
  grep -E '^CHANGED' "$out.cmp" | sed "s/^CHANGED/${GRN}CHANGED${X}/; s/^/ /"
  printf '\n %s%d signals unchanged — still detectable (full list: %s.cmp)%s\n' "$YEL" "$(grep -c '^same' "$out.cmp")" "$out" "$X"
  grep -E '^same +(emu-prop|service|file|cpu|kernel|sensor|gpu|net|telephony|battery|root|build-api)' "$out.cmp" |
    grep -vE ' (absent|0)$' | head -n 40 | sed 's/^/ /'
}

inventory_script() {
  cat <<'EOF'
p() { printf '%s|%s|%s\n' "$1" "$2" "$3"; }
for k in ro.product.model ro.product.brand ro.product.manufacturer ro.product.device ro.product.name \
  ro.product.board ro.build.fingerprint ro.build.description ro.build.display.id ro.build.flavor \
  ro.build.characteristics ro.build.tags ro.build.type ro.build.host ro.build.user ro.soc.model ro.soc.manufacturer \
  ro.hardware ro.boot.hardware ro.board.platform ro.product.cpu.abi ro.kernel.qemu ro.boot.qemu \
  ro.boot.qemu.avd_name ro.boot.serialno ro.serialno ro.debuggable ro.secure ro.boot.verifiedbootstate \
  ro.boot.vbmeta.device_state ro.boot.flash.locked; do p prop "$k" "$(getprop "$k")"; done
getprop | grep -iE 'qemu|goldfish|ranchu|emu64|sdk_gphone|emulator|android-build' |
  grep -vE 'adb\.pubkey|^\[init\.svc' | sed 's/^\[\([^]]*\)\]: \[\(.*\)\]$/emu-prop|\1|\2/'
getprop | grep -E '^\[init\.svc\.[^]]*(qemu|goldfish|ranchu|emulator)' | sed 's/^\[\([^]]*\)\]: \[\(.*\)\]$/service|\1|\2/'
for f in /dev/qemu_pipe /dev/goldfish_pipe /dev/socket/qemud /dev/goldfish_address_space /dev/goldfish_sync \
  /sys/qemu_trace /system/bin/qemu-props /vendor/bin/qemu-props /system/lib64/libc_malloc_debug_qemu.so \
  /vendor/etc/init/hw/init.ranchu.rc /vendor/etc/fstab.ranchu /vendor/ueventd.rc /system_ext/bin/su /debug_ramdisk; do
  [ -e "$f" ] && p file "$f" present || p file "$f" absent
done
for f in /vendor/lib64/hw/*; do case "$f" in *ranchu* | *goldfish* | *emulation*) p file "$f" present ;; esac; done
p kernel uname "$(uname -r)"
p kernel tty_goldfish "$(grep -c goldfish /proc/tty/drivers 2>/dev/null)"
p cpu hardware "$(grep -m1 -i '^Hardware' /proc/cpuinfo | cut -d: -f2- | sed 's/^ *//')"
p cpu implementer "$(grep -m1 'CPU implementer' /proc/cpuinfo | cut -d: -f2- | sed 's/^ *//')"
p cpu part "$(grep -m1 'CPU part' /proc/cpuinfo | cut -d: -f2- | sed 's/^ *//')"
p cpu cores "$(grep -c '^processor' /proc/cpuinfo)"
p sensor goldfish_named "$(dumpsys sensorservice 2>/dev/null | grep -ci goldfish)"
p sensor vendor "$(dumpsys sensorservice 2>/dev/null | grep -oiE '(The Android Open Source Project|AOSP|Google)' | sort -u | tr '\n' ' ')"
p gpu gles "$(dumpsys SurfaceFlinger 2>/dev/null | grep -m1 '^GLES' | cut -c1-120)"
p net wifi_ssid "$(dumpsys wifi 2>/dev/null | grep -m1 -oE 'SSID: "[^"]*"')"
p net wlan0_ipv4 "$(ip -4 addr show wlan0 2>/dev/null | grep -oE 'inet [0-9./]+')"
p net eth0 "$(ip link show eth0 >/dev/null 2>&1 && echo present || echo absent)"
p telephony ril_impl "$(getprop gsm.version.ril-impl)"
p telephony baseband "$(getprop gsm.version.baseband)"
p telephony operator "$(getprop gsm.operator.alpha) $(getprop gsm.operator.numeric)"
p battery state "$(dumpsys battery 2>/dev/null | grep -E 'AC powered|USB powered|status:|health:|level:|temperature:|Charge counter:|voltage:|technology:' | tr -s ' \n' ' ')"
p display physical "$(wm size | head -n1)"
p display refresh "$(dumpsys display 2>/dev/null | grep -m1 -oE 'renderFrameRate [0-9.]+')"
p display panel "$(dumpsys display 2>/dev/null | grep -m1 -oE 'deviceProductInfo DeviceProductInfo\{name=[^,]*, manufacturerPnpId=[^,]*')"
p root su_binaries "$(ls /system/bin/su /system/xbin/su /system_ext/bin/su /sbin/su 2>/dev/null | tr '\n' ' ')"
p root magisk_app "$(pm list packages 2>/dev/null | grep -ciE 'magisk')"
EOF
}

do_watch() {
  STEPS=1; STEP=0
  step "Host-side re-apply watcher (fallback when Magisk boot scripts are unavailable)"
  is_allowed "$AVD" || die "Refusing: '$AVD' is not allowlisted."
  warn "SESSION-ONLY mode: values are re-applied from this Mac after each boot; nothing persists on its own."
  info "Press Ctrl-C to stop."
  local last=
  while :; do
    if serial_up && booted && assert_identity 2>/dev/null; then
      local b; b=$(boot_id)
      if [[ "$b" != "$last" ]]; then
        if [[ "$(persistence_state)" == installed ]] && applied_this_boot; then
          ok "$(date '+%T') boot $b: Magisk persistence already applied the profile — nothing to do."
        elif [[ "$(dsu "[ -f $DEV_DIR/profile.props ] && echo y")" == y ]]; then
          dsu "sh $DEV_DIR/apply.sh runtime" >/dev/null && apply_display &&
            soft_restart && dsu "echo \"\$(cat /proc/sys/kernel/random/boot_id) watcher\" > $DEV_DIR/applied_boot" >/dev/null &&
            ok "$(date '+%T') boot $b: profile re-applied + framework restarted (session-only)"
        else
          warn "No profile on device — run 'apply' first."
        fi
        last=$b
      fi
    fi
    sleep 10
  done
}

# ── Main ────────────────────────────────────────────────────────────────────
AVD= ACTION= VSYNC=
while (($#)); do
  case "$1" in
    --avd) AVD=${2:-}; shift ;;
    --action) ACTION=${2:-}; shift ;;
    --vsync) VSYNC=${2:-}; shift ;;
    --fingerprint) FINGERPRINT_OVERRIDE=${2:?}; shift ;;
    --yes | -y) YES=1 ;;
    -h | --help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

banner
command -v adb >/dev/null || die "adb not found (expected in $SDK/platform-tools)."
command -v emulator >/dev/null || die "emulator not found (expected in $SDK/emulator)."

AVDS=()
while IFS= read -r a; do [[ -n "$a" && "$a" != INFO* ]] && AVDS+=("$a"); done < <(emulator -list-avds 2>/dev/null)
((${#AVDS[@]})) || die "No AVDs found."

if [[ -z "$AVD" ]]; then
  [[ -t 0 ]] || die "Non-interactive: pass --avd NAME."
  labels=()
  for a in "${AVDS[@]}"; do
    if is_allowed "$a"; then labels+=("$a  ${GRN}● modifiable${X}"); else labels+=("$a  ${DIM}○ read-only (not allowlisted)${X}"); fi
  done
  menu idx "Select an AVD" "${labels[@]}" || { echo; info "Cancelled."; exit 0; }
  AVD=${AVDS[idx]}
fi
found=0; for a in "${AVDS[@]}"; do [[ "$a" == "$AVD" ]] && found=1; done
((found)) || die "Unknown AVD: $AVD"

DIR="$LAB_ROOT/$AVD"
if [[ -z "$FINGERPRINT_OVERRIDE" && -f "$DIR/identity.fingerprint" ]]; then
  IFS= read -r FINGERPRINT_OVERRIDE <"$DIR/identity.fingerprint"
fi
if [[ -n "$FINGERPRINT_OVERRIDE" ]]; then
  [[ "$FINGERPRINT_OVERRIDE" =~ ^samsung/pa1qxxx/pa1q:15/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+):user/release-keys$ ]] ||
    die "Fingerprint must match samsung/pa1qxxx/pa1q:15/BUILD_ID/INCREMENTAL:user/release-keys."
  SYN_ID=${BASH_REMATCH[1]}
  SYN_INCREMENTAL=${BASH_REMATCH[2]}
  FINGERPRINT_SOURCE='supplied fingerprint (not attestation)'
fi
mkdir -p "$DIR/logs"
LOG="$DIR/logs/run-$(date +%Y%m%d-%H%M%S).log"
log "Galaxy S25 AVD Lab v$VERSION · AVD=$AVD"
printf '\n   %sSelected AVD:%s %s%s%s %s\n' "$DIM" "$X" "$B" "$AVD" "$X" \
  "$(is_allowed "$AVD" && echo "${GRN}(modifiable)${X}" || echo "${YEL}(read-only)${X}")"
printf '   %sLogs & backups:%s %s\n' "$DIM" "$X" "$DIR"
connect

if [[ -z "$ACTION" ]]; then
  [[ -t 0 ]] || die "Non-interactive: pass --action."
  acts=(apply status inventory reboot rollback watch quit)
  menu idx "What would you like to do?" \
    "Apply Galaxy S25 profile        ${DIM}backup → identity → display → persistence${X}" \
    "Status dashboard                ${DIM}verify properties, display, root, Play${X}" \
    "Emulator-signal inventory       ${DIM}collect + compare with pre-change baseline${X}" \
    "Reboot & verify                 ${DIM}prove the profile survives a reboot${X}" \
    "Roll back                       ${DIM}remove profile, restore originals${X}" \
    "Host-side re-apply watcher      ${DIM}fallback if Magisk boot scripts are unusable${X}" \
    "Quit" || { echo; exit 0; }
  ACTION=${acts[idx]}
fi

case "$ACTION" in
  apply) do_apply ;;
  status) do_status ;;
  inventory) do_inventory ;;
  reboot) do_reboot ;;
  rollback) do_rollback ;;
  watch) do_watch ;;
  quit) exit 0 ;;
  *) die "Unknown action: $ACTION" ;;
esac
printf '\n   %sLog:%s %s\n\n' "$DIM" "$X" "$LOG"
