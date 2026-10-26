#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
#  Galaxy S25 AVD — one-shot setup, entirely from the CLI.
#
#   1. Creates a new "Medium Phone" AVD on the Android 15 Google Play arm64 image
#   2. Gives it a private copy of the stock ramdisk (the shared SDK image is never touched)
#   3. Roots that copy with Magisk via rootAVD
#   4. Grants Magisk su to the adb shell and completes Magisk's "additional setup"
#   5. Runs galaxy_s25_avd_lab.sh: baseline inventory → Galaxy S25 profile → reboot
#      verification → post-change inventory
#   6. Starts battery, signal and proxy-derived GPS before app installation
#   7. Installs the selected dating app without opening it, isolates its Magisk
#      mounts, reboots, verifies the full phone, then launches only for signup
#
#  Usage: ./setup_galaxy_s25_avd.sh [--name NAME] [--app FILE]... [--no-apps]
#                                   [--vsync 120] [--ram MB] [--cores N] [--yes]
#                                   [--fingerprint VALUE] [--hide-root-package PKG]...
#                                   [--no-root-isolation] [--no-battery-sim] [--no-signal-sim]
#                                   [--keep-magisk-app]
#                                   [--keep-qemu-flags] [--keep-sensor-labels]
#    --name     optional explicit AVD name; default is a fresh random name each run
#    --interactive / --non-interactive  enable/disable the setup prompts
#    --dry-run  show the resolved setup without creating or changing a device
#    --proxy VALUE / --proxy-file PATH  host-side HTTP proxy (host:port:user:password or URL)
#    --nodemaven-key-file PATH  provision a unique verified US/T-Mobile mobile proxy
#    --no-proxy  disable the default .local/emulator-proxy for this run
#    --keep-file-paths / --keep-graphics-labels  skip the corresponding fixtures
#    --no-checker  skip installing and running Device Red Flags
#    --app      optional extra .xapk or .apk to install (repeatable)
#    --no-apps  skip extra apps and the Google Play dating-app installation
#    --no-play-store  skip Google Play installation only
#    --no-bumble-signup  skip the final interactive Bumble signup step
#    --bumble-signup  enable the final signup step (default)
#    --pof-signup  install POF and enable its guarded capture/resume step
#    --tinder-signup  install Tinder, isolate it, certify the phone, then open its guarded flow
#    --tinder-allow-notifications / --tinder-decline-notifications
#    --tinder-accept-terms --tinder-accept-sms-terms --tinder-accept-house-rules
#    --tinder-gender Woman|Man --tinder-gender-visibility show|hide
#    --tinder-relationship-goal VALUE --tinder-allow-location
#    --no-pof-signup  skip the POF capture/resume step
#    --profile-name NAME  Bumble first name (separate from the AVD name)
#    --profile-gender Woman|Man|Nonbinary  Bumble profile gender
#    --camera-video PATH  per-phone front-camera video (prepared before first boot)
#    --front-camera SOURCE  emulated|webcamN|none|imagefile:PATH|videofile:PATH
#    --vsync    launch with a 120 Hz guest display mode
#    --yes      don't ask for confirmation
#    --fingerprint  optional Samsung/API-35 fingerprint; related build fields follow it
#    --hide-root-package  isolate another installed app (Bumble is included by default)
#    --no-root-isolation  skip Magisk DenyList configuration
#    --no-battery-sim  keep the emulator's normal battery values
#    --no-signal-sim  skip the host-side modem signal controller
#    --keep-magisk-app  keep the manager UI; default removes it after configuration
#    --keep-qemu-flags  skip the two late-boot QEMU property overrides
#    --keep-sensor-labels  skip the sensor-label HAL overlay
#
# Root stays installed to maintain the identity and battery boot services. DenyList
# limits app-visible Magisk mounts; it does not guarantee root invisibility. This
# script does not relock an emulator bootloader or replace emulator infrastructure.
# The two QEMU properties are overridden only after boot. Sensor display names are
# changed through a reversible Magisk overlay; simulated sensor behavior is retained.
#
#  Needs: Android SDK with emulator + platform-tools, the system image
#  system-images;android-35;google_apis_playstore;arm64-v8a, git (if rootAVD isn't
#  local yet) and lz4 (optional, used to verify the ramdisk is stock).
#  Compatible with macOS /bin/bash 3.2.
# ─────────────────────────────────────────────────────────────────────────────
set -u -o pipefail
SETUP_STARTED=$SECONDS

NAME=
VSYNC=
RAM_MB=4096
CORES=4
YES=0
APPS=()
NO_APPS=0
PLAY_STORE_BUMBLE=1
PLAY_STORE_POF=0
PLAY_STORE_TINDER=0
PLAY_STORE_DISABLED=0
FINGERPRINT=
BATTERY_SIM=1
SIGNAL_SIM=1
ROOT_ISOLATION=1
KEEP_MAGISK_APP=0
QEMU_PROFILE=1
SENSOR_LABELS=1
FILE_ALIASES=1
GRAPHICS_LABELS=1
CHECKER=1
INTERACTIVE=-1
DRY_RUN=0
BUMBLE_SIGNUP=1
POF_SIGNUP=0
TINDER_SIGNUP=0
TINDER_ALLOW_NOTIFICATIONS=0
TINDER_DECLINE_NOTIFICATIONS=0
TINDER_ACCEPT_TERMS=0
TINDER_ACCEPT_SMS_TERMS=0
TINDER_ACCEPT_HOUSE_RULES=0
TINDER_ALLOW_LOCATION=0
TINDER_GENDER=
TINDER_GENDER_VISIBILITY=
TINDER_RELATIONSHIP_GOAL=
BUMBLE_PROFILE_NAME=
BUMBLE_PROFILE_GENDER=
FRONT_CAMERA=emulated
PROXY_OPTIONS=()
NODEMAVEN_KEY_FILE=
NODEMAVEN_KEY_EXPLICIT=0
NODEMAVEN_AUTO=0
# Direct-network fallback only; proxy runs resolve these before creating the AVD.
# Emulator console geo fix takes longitude before latitude.
LOCATION_LATITUDE=40.7357
LOCATION_LONGITUDE=-74.1724
LOCATION_TIMEZONE=America/New_York
LOCATION_LABEL='Newark, New Jersey'
ROOT_PACKAGES=(com.bumble.app dev.emulab.devicecheck)
NETWORK_PROFILE_INSTALLED=0

SDK="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/Library/Android/sdk}}"
export PATH="$SDK/platform-tools:$SDK/emulator:$PATH"
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
# Use the supplied recording in the normal setup flow; --front-camera overrides it.
if [[ -s "$SCRIPT_DIR/bumble-signup/camera/phone-video.mp4" ]]; then
  FRONT_CAMERA="videofile:$SCRIPT_DIR/bumble-signup/camera/phone-video.mp4"
fi
LAB="$SCRIPT_DIR/galaxy_s25_avd_lab.sh"
AVD_HOME="${ANDROID_AVD_HOME:-$HOME/.android/avd}"
SYSIMG_REL=system-images/android-35/google_apis_playstore/arm64-v8a
SYSIMG="$SDK/$SYSIMG_REL"
ROOTAVD_SRC="${ROOTAVD_DIR:-$HOME/Downloads/rootAVD}"
ROOTAVD_REPO="${ROOTAVD_REPO:-https://github.com/galihlasahido/rootAVD.git}"
MAGISK_PKG=com.topjohnwu.magisk

while (($#)); do
  case "$1" in
    --name) NAME=${2:?}; shift ;;
    --vsync) VSYNC=${2:?}; shift ;;
    --app) APPS+=("${2:?}"); shift ;;
    --no-apps) NO_APPS=1 ;;
    --no-play-store) PLAY_STORE_DISABLED=1; PLAY_STORE_BUMBLE=0; PLAY_STORE_POF=0; PLAY_STORE_TINDER=0 ;;
    --no-bumble-signup) BUMBLE_SIGNUP=0 ;;
    --bumble-signup)
      BUMBLE_SIGNUP=1; POF_SIGNUP=0; TINDER_SIGNUP=0
      if ((!PLAY_STORE_DISABLED)); then PLAY_STORE_BUMBLE=1; PLAY_STORE_POF=0; PLAY_STORE_TINDER=0; fi
      ;;
    --pof-signup)
      POF_SIGNUP=1; BUMBLE_SIGNUP=0; TINDER_SIGNUP=0; ROOT_PACKAGES+=(com.pof.android)
      if ((!PLAY_STORE_DISABLED)); then PLAY_STORE_POF=1; PLAY_STORE_BUMBLE=0; PLAY_STORE_TINDER=0; fi
      ;;
    --no-pof-signup) POF_SIGNUP=0 ;;
    --tinder-signup)
      TINDER_SIGNUP=1; BUMBLE_SIGNUP=0; POF_SIGNUP=0; ROOT_PACKAGES+=(com.tinder)
      if ((!PLAY_STORE_DISABLED)); then PLAY_STORE_TINDER=1; PLAY_STORE_BUMBLE=0; PLAY_STORE_POF=0; fi
      ;;
    --no-tinder-signup) TINDER_SIGNUP=0 ;;
    --tinder-allow-notifications) TINDER_ALLOW_NOTIFICATIONS=1; TINDER_DECLINE_NOTIFICATIONS=0 ;;
    --tinder-decline-notifications) TINDER_DECLINE_NOTIFICATIONS=1; TINDER_ALLOW_NOTIFICATIONS=0 ;;
    --tinder-accept-terms) TINDER_ACCEPT_TERMS=1 ;;
    --tinder-accept-sms-terms) TINDER_ACCEPT_SMS_TERMS=1 ;;
    --tinder-accept-house-rules) TINDER_ACCEPT_HOUSE_RULES=1 ;;
    --tinder-allow-location) TINDER_ALLOW_LOCATION=1 ;;
    --tinder-gender) TINDER_GENDER=${2:?}; shift ;;
    --tinder-gender-visibility) TINDER_GENDER_VISIBILITY=${2:?}; shift ;;
    --tinder-relationship-goal) TINDER_RELATIONSHIP_GOAL=${2:?}; shift ;;
    --profile-name) BUMBLE_PROFILE_NAME=${2:?}; shift ;;
    --profile-gender) BUMBLE_PROFILE_GENDER=${2:?}; shift ;;
    --camera-video) FRONT_CAMERA="videofile:${2:?}"; shift ;;
    --front-camera) FRONT_CAMERA=${2:?}; shift ;;
    --proxy) PROXY_OPTIONS+=(--proxy "${2:?}"); shift ;;
    --proxy-file) PROXY_OPTIONS+=(--proxy-file "${2:?}"); shift ;;
    --nodemaven-key-file) NODEMAVEN_KEY_FILE=${2:?}; NODEMAVEN_KEY_EXPLICIT=1; shift ;;
    --no-proxy) PROXY_OPTIONS+=(--no-proxy) ;;
    --ram) RAM_MB=${2:?}; shift ;;
    --cores) CORES=${2:?}; shift ;;
    --fingerprint) FINGERPRINT=${2:?}; shift ;;
    --hide-root-package) ROOT_PACKAGES+=("${2:?}"); shift ;;
    --no-root-isolation) ROOT_ISOLATION=0 ;;
    --no-battery-sim) BATTERY_SIM=0 ;;
    --no-signal-sim) SIGNAL_SIM=0 ;;
    --keep-magisk-app) KEEP_MAGISK_APP=1 ;;
    --keep-qemu-flags) QEMU_PROFILE=0 ;;
    --keep-sensor-labels) SENSOR_LABELS=0 ;;
    --keep-file-paths) FILE_ALIASES=0; GRAPHICS_LABELS=0 ;;
    --keep-graphics-labels) GRAPHICS_LABELS=0 ;;
    --no-checker) CHECKER=0 ;;
    --interactive) INTERACTIVE=1 ;;
    --non-interactive) INTERACTIVE=0; YES=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --yes | -y) YES=1 ;;
    -h | --help) sed -n '2,/Compatible with/p' "$0"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

source "$SCRIPT_DIR/setup_options.sh" || exit 1
configure_setup || exit 2
case "$TINDER_GENDER" in ''|Woman|Man) ;; *) echo 'Tinder gender must be Woman or Man.' >&2; exit 2 ;; esac
case "$TINDER_GENDER_VISIBILITY" in ''|show|hide) ;; *) echo 'Tinder gender visibility must be show or hide.' >&2; exit 2 ;; esac
case "$TINDER_RELATIONSHIP_GOAL" in
  ''|'Long-term partner'|'Long-term, open to short'|'Short-term, open to long'|'Short-term fun'|'New friends'|'Still figuring it out') ;;
  *) echo 'Unsupported Tinder relationship goal.' >&2; exit 2 ;;
esac
if ((NO_APPS)); then PLAY_STORE_BUMBLE=0; PLAY_STORE_POF=0; PLAY_STORE_TINDER=0; fi
WORK="$HOME/galaxy_s25_avd_backups/$NAME/setup"
if [[ -z "$NODEMAVEN_KEY_FILE" ]]; then
  NODEMAVEN_KEY_FILE="$SCRIPT_DIR/.local/nodemaven-api-key"
fi
if ((NODEMAVEN_KEY_EXPLICIT)) && [[ ! -s "$NODEMAVEN_KEY_FILE" ]]; then
  printf 'NodeMaven API key file is missing or empty: %s\n' "$NODEMAVEN_KEY_FILE" >&2
  exit 2
fi
if ((${#PROXY_OPTIONS[@]} == 0)) && [[ -s "$NODEMAVEN_KEY_FILE" ]]; then
  NODEMAVEN_AUTO=1
  if ((DRY_RUN)); then
    HOST_PROXY=nodemaven-dry-run
  else
    python3 -I "$SCRIPT_DIR/nodemaven_proxy.py" --avd "$NAME" \
      --key-file "$NODEMAVEN_KEY_FILE" --output "$WORK/nodemaven-proxy" || exit 2
    PROXY_OPTIONS=(--proxy-file "$WORK/nodemaven-proxy")
    HOST_PROXY=$(python3 -I "$SCRIPT_DIR/emulator_proxy.py" --resolve "${PROXY_OPTIONS[@]}") || exit 2
  fi
else
  HOST_PROXY=$(python3 -I "$SCRIPT_DIR/emulator_proxy.py" --resolve ${PROXY_OPTIONS[@]+"${PROXY_OPTIONS[@]}"}) || exit 2
fi
if ((DRY_RUN)); then
  printf 'AVD name: %s\nAndroid Studio display name: %s\nRAM: %s MB\nCores: %s\nRefresh rate: %s\n' "$NAME" "${NAME//_/ }" "$RAM_MB" "$CORES" "${VSYNC:-emulator default}"
  printf 'Front camera: %s\n' "$FRONT_CAMERA"
  if [[ -n "$HOST_PROXY" ]]; then
    printf 'Location and time zone: resolved from the proxy exit IP at startup (lookup skipped in dry-run)\n'
  else
    printf 'Location: %s (%s, %s)\nTime zone: %s\n' "$LOCATION_LABEL" "$LOCATION_LATITUDE" "$LOCATION_LONGITUDE" "$LOCATION_TIMEZONE"
  fi
  printf 'GPS movement: 20–30 feet every 3–5 seconds; within 1000 feet of the startup center\n'
  printf 'Identifiers: unique persistent synthetic IMEI, serial and Android ID per new AVD\n'
  printf 'CPU architecture: ARM64; original CPU implementer retained\n'
  printf 'Network: simulated LTE cellular data; Wi-Fi off; unique private subnet and MAC addresses\n'
  printf 'User-Agent: unique S25 / Android 15 test profile exported; Bumble override not applied\n'
  if [[ -n "$HOST_PROXY" ]]; then
    printf 'Host proxy: enabled (TCP only; Android proxy settings untouched)\n'
    if ((NODEMAVEN_AUTO)); then
      printf 'NodeMaven: unique fixed US mobile/T-Mobile session; API verification runs before creation\n'
    fi
  else
    printf 'Host proxy: disabled\n'
  fi
  printf 'Identity: Samsung Galaxy S25\nBattery: %s\nSignal: %s\nQEMU profile: %s\nSensor labels: %s\nFile aliases: %s\nGraphics labels: %s\nRoot isolation: %s\nChecker: %s\n' "$BATTERY_SIM" "$SIGNAL_SIM" "$QEMU_PROFILE" "$SENSOR_LABELS" "$FILE_ALIASES" "$GRAPHICS_LABELS" "$ROOT_ISOLATION" "$CHECKER"
  if ((PLAY_STORE_BUMBLE)); then
    printf 'Bumble flow: finish phone → Google Play Install (held closed) → isolate → reboot → verify → first launch\n'
  else
    printf 'Bumble installation: Google Play skipped\n'
  fi
  if ((PLAY_STORE_POF)); then
    printf 'POF flow: finish phone → Google Play Install (held closed) → isolate → reboot → verify → first launch\n'
  else
    printf 'POF installation: Google Play skipped\n'
  fi
  if ((PLAY_STORE_TINDER)); then
    printf 'Tinder flow: finish phone → Google Play Install (held closed) → isolate → reboot → verify → guarded first launch\n'
  else
    printf 'Tinder installation: Google Play skipped\n'
  fi
  printf 'Local app bundles: explicit --app files only; no automatic APK/XAPK installation\n'
  printf 'Bumble signup: %s (requires installed Bumble and a terminal; prompts after device setup)\n' "$BUMBLE_SIGNUP"
  if ((BUMBLE_SIGNUP)); then
    printf 'Bumble profile name: %s\nBumble profile gender: %s\nBumble photos: 4 random images from the supplied photo pool (video excluded)\nPhone number: requested only at Bumble phone entry\n' "${BUMBLE_PROFILE_NAME:-ask at signup}" "${BUMBLE_PROFILE_GENDER:-ask at signup}"
  fi
  printf 'POF guarded signup capture: %s (permissions only; profile, terms, SMS and photos pause)\n' "$POF_SIGNUP"
  printf 'Tinder guarded signup: %s (terms, SMS, identity details and human verification remain explicit/manual)\n' "$TINDER_SIGNUP"
  if ((TINDER_SIGNUP)); then
    printf 'Tinder choices: notifications=%s gender=%s visibility=%s goal=%s location=%s\n' \
      "$([[ $TINDER_ALLOW_NOTIFICATIONS == 1 ]] && echo allow || { [[ $TINDER_DECLINE_NOTIFICATIONS == 1 ]] && echo decline || echo ask; })" \
      "${TINDER_GENDER:-ask}" "${TINDER_GENDER_VISIBILITY:-ask}" \
      "${TINDER_RELATIONSHIP_GOAL:-ask}" "$TINDER_ALLOW_LOCATION"
  fi
  if ((BUMBLE_SIGNUP || POF_SIGNUP || TINDER_SIGNUP)); then
    printf 'Signup safeguard: required setup artifacts, checker result and live phone state must certify first\n'
  fi
  exit 0
fi

AVD_DIR="$AVD_HOME/$NAME.avd"
LOG="$WORK/setup-$(date +%Y%m%d-%H%M%S).log"

# Local apps are opt-in. Bumble comes from Google Play by default.
if ((NO_APPS)); then
  APPS=()
fi

# ── UI ──────────────────────────────────────────────────────────────────────
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  B=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'
  BLU=$'\033[34m'; MAG=$'\033[35m'; CYN=$'\033[36m'; X=$'\033[0m'
else
  B= DIM= RED= GRN= YEL= BLU= MAG= CYN= X=
fi
STEP=0
STEPS=$((17 + (${#APPS[@]} > 0) + PLAY_STORE_BUMBLE + PLAY_STORE_POF + PLAY_STORE_TINDER + BATTERY_SIM + 2*SIGNAL_SIM + ROOT_ISOLATION + QEMU_PROFILE + SENSOR_LABELS + FILE_ALIASES + GRAPHICS_LABELS + 2*CHECKER + (ROOT_ISOLATION && !KEEP_MAGISK_APP) + (BUMBLE_SIGNUP || POF_SIGNUP || TINDER_SIGNUP) + BUMBLE_SIGNUP + POF_SIGNUP + TINDER_SIGNUP + ROOT_ISOLATION*(2 + SIGNAL_SIM)))
log()  { printf '%s %s\n' "$(date '+%H:%M:%S')" "$*" >>"$LOG"; }
step() { STEP=$((STEP+1)); printf '\n %s[%d/%d]%s %s%s%s\n' "$CYN" "$STEP" "$STEPS" "$X" "$B" "$*" "$X"; log "== $*"; }
info() { printf '   %s›%s %s\n' "$CYN" "$X" "$*"; log "info: $*"; }
ok()   { printf '   %s✓%s %s\n' "$GRN" "$X" "$*"; log "ok: $*"; }
warn() { printf '   %s!%s %s\n' "$YEL" "$X" "$*"; log "warn: $*"; }
die()  { printf '   %s✗%s %s\n' "$RED" "$X" "$*"; log "fail: $*"; printf '\n   %sLog:%s %s\n\n' "$DIM" "$X" "$LOG"; exit 1; }
confirm() {
  ((YES)) && return 0
  local a; printf '   %s?%s %s %s[y/N]%s ' "$MAG" "$X" "$1" "$DIM" "$X"
  IFS= read -r a </dev/tty || return 1
  [[ "$a" == [yY]* ]]
}
spin_wait() { # spin_wait "message" timeout_s check_fn [args]
  local msg=$1 t=$2 i=0 started=$SECONDS f='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'; shift 2
  while ! "$@" >/dev/null 2>&1; do
    ((SECONDS - started >= t)) && { printf '\r\033[K'; return 1; }
    [[ -t 1 ]] && printf '\r   %s%s%s %s %s(%ds)%s' "$CYN" "${f:i%10:1}" "$X" "$msg" "$DIM" $((SECONDS - started)) "$X"
    sleep 0.5; i=$((i + 1))
  done
  [[ -t 1 ]] && printf '\r\033[K'
  return 0
}
finish_timing() {
  local rc=$? elapsed=$((SECONDS - SETUP_STARTED))
  printf '%s\n   Total elapsed: %02dh %02dm %02ds (includes prompts and SMS wait; exit %d)\n' "$X" "$((elapsed / 3600))" "$((elapsed / 60 % 60))" "$((elapsed % 60))" "$rc"
}
trap finish_timing EXIT
trap 'echo; exit 130' INT

# ── Emulator helpers ────────────────────────────────────────────────────────
SERIAL=
avd_of() { adb -s "$1" emu avd name 2>/dev/null | head -n1 | tr -d '\r'; }
find_serial() {
  local s
  for s in $(adb devices 2>/dev/null | awk 'NR > 1 && $1 ~ /^emulator-/ {print $1}'); do
    [[ "$(avd_of "$s")" == "$NAME" ]] && { echo "$s"; return 0; }
  done
  return 1
}
serial_up() { SERIAL=$(find_serial); [[ -n "$SERIAL" ]]; }
guest_name() { adb -s "$SERIAL" shell getprop ro.boot.qemu.avd_name 2>/dev/null | tr -d '\r'; }
guest_up() { [[ "$(guest_name)" == "$NAME" ]]; }
booted() { [[ "$(adb -s "$SERIAL" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == 1 ]]; }
gone() { ! find_serial >/dev/null && ! pgrep -f -- "-avd $NAME( |$)" >/dev/null; }
# Root scripts go over stdin: `adb shell su -c 'a; b'` would run b as the shell user.
dsu() { printf '%s\n' "$1" | adb -s "$SERIAL" shell su 2>&1 | tr -d '\r'; }

set_location() {
  local result
  adb -s "$SERIAL" shell cmd location set-location-enabled true >>"$LOG" 2>&1 || die "Could not enable device location."
  result=$(adb -s "$SERIAL" emu geo fix "$LOCATION_LONGITUDE" "$LOCATION_LATITUDE" 0 8 2>&1 | tr -d '\r')
  [[ $? == 0 && "$result" == *OK* && "$result" != *KO:* ]] || die "Could not set GPS location: $result"
  ok "GPS set to $LOCATION_LABEL ($LOCATION_LATITUDE, $LOCATION_LONGITUDE)"
}

verify_identifiers() {
  python3 -I "$SCRIPT_DIR/device_identifiers.py" --avd-dir "$AVD_DIR" --verify-serial "$SERIAL" --adb "$SDK/platform-tools/adb" >"$WORK/identifiers-verified.json" 2>>"$LOG" ||
    die "Device identifiers did not match their reserved values; see $LOG."
  ok "Modem IMEI, serial and Android ID match this device's unique persistent identifiers"
}

verify_cpu_architecture() {
  local abi machine
  abi=$(adb -s "$SERIAL" shell getprop ro.product.cpu.abi | tr -d '\r') || die "Could not read CPU ABI."
  machine=$(adb -s "$SERIAL" shell uname -m | tr -d '\r') || die "Could not read kernel architecture."
  [[ "$abi" == arm64-v8a && "$machine" == aarch64 ]] ||
    die "Expected ARM64 Android and kernel; got ABI=$abi, kernel=$machine."
  ok "ARM64 CPU verified: Android ABI=$abi, kernel=$machine"
  return 0
}

try_cellular_network() {
  python3 "$SCRIPT_DIR/setup_network.py" --serial "$SERIAL" >>"$LOG" 2>&1 || return 1
  if ((NETWORK_PROFILE_INSTALLED)); then
    dsu 'sh /data/adb/service.d/96-s25-network.sh' >>"$LOG" 2>&1 || return 1
  fi
}

ensure_cellular_network() {
  try_cellular_network || die "LTE cellular data is not validated; see $LOG."
}

launch() { # launch [extra emulator args...]
  local args=(-avd "$NAME" -no-snapshot-load -no-snapshot-save -camera-front "$FRONT_CAMERA" -timezone "$LOCATION_TIMEZONE")
  [[ -n "$VSYNC" ]] && args+=(-vsync-rate "$VSYNC")
  log "launch: emulator ${args[*]} $*"
  # Only the host emulator process receives the proxy, including every setup restart.
  nohup python3 -I "$SCRIPT_DIR/emulator_proxy.py" ${PROXY_OPTIONS[@]+"${PROXY_OPTIONS[@]}"} --avd "$NAME" "${args[@]:2}" "$@" >>"$WORK/emulator.log" 2>&1 &
  spin_wait "Starting emulator" 240 serial_up || die "Emulator did not attach to adb (see $WORK/emulator.log)."
  spin_wait "Waiting for guest adbd" 240 guest_up || die "Guest on $SERIAL never identified as $NAME."
  spin_wait "Booting Android" 600 booted || die "Android did not finish booting."
  verify_cpu_architecture
  if ! try_cellular_network; then
    warn "Initial Android boot did not validate LTE; retrying once after a guest reboot"
    adb -s "$SERIAL" reboot >>"$LOG" 2>&1 || die "LTE recovery reboot failed."
    sleep 3
    spin_wait "Reconnecting after LTE recovery" 240 guest_up || die "Guest did not return after LTE recovery reboot."
    spin_wait "Booting after LTE recovery" 600 booted || die "Android did not finish the LTE recovery reboot."
    verify_cpu_architecture
    try_cellular_network || die "LTE cellular data is still not validated after one recovery reboot; see $LOG."
    ok "Validated LTE after the bounded first-boot recovery"
  fi
  set_location
  ok "$NAME is up as $SERIAL"
}

shutdown_avd() {
  [[ -n "$SERIAL" ]] && [[ "$(avd_of "$SERIAL")" == "$NAME" ]] && adb -s "$SERIAL" emu kill >>"$LOG" 2>&1
  spin_wait "Shutting down $NAME" 120 gone || die "Emulator for $NAME did not exit."
  SERIAL=
}

stock_check() { # 0 = no Magisk files inside the ramdisk ($1); 2 = cannot check
  command -v lz4 >/dev/null || return 2
  local n
  n=$( { lz4 -dc "$1" 2>/dev/null || gunzip -c "$1" 2>/dev/null; } | cpio -t 2>/dev/null | grep -ciE 'magisk|overlay\.d')
  [[ "$n" == 0 ]]
}

# ── 0. Pre-flight ───────────────────────────────────────────────────────────
mkdir -p "$WORK"
printf '%s%s\n' "$B$BLU" "
   ╔═╗┌─┐┬  ┌─┐─┐ ┬┬ ┬  ╔═╗┌─┐┌─┐   ┌─┐┌─┐┌┬┐┬ ┬┌─┐
   ║ ╦├─┤│  ├─┤┌┴┬┘└┬┘  ╚═╗┌─┘└─┐───└─┐├┤  │ │ │├─┘
   ╚═╝┴ ┴┴─┘┴ ┴┴ └─ ┴   ╚═╝└─┘└─┘   └─┘└─┘ ┴ └─┘┴  $X"
printf '   %sNew Medium Phone AVD → Magisk root → Galaxy S25 profile%s\n' "$DIM" "$X"

step "Pre-flight"
if [[ -n "$HOST_PROXY" ]]; then
  info "Resolving GPS center and time zone through the configured proxy"
  python3 -I "$SCRIPT_DIR/emulator_proxy.py" --location ${PROXY_OPTIONS[@]+"${PROXY_OPTIONS[@]}"} >"$WORK/proxy-location.json" ||
    die "Proxy geolocation failed; no new AVD was created."
  LOCATION_VALUES=$(python3 -I - "$WORK/proxy-location.json" <<'PY'
import json, sys
p = json.load(open(sys.argv[1]))
for key in ('latitude', 'longitude', 'timezone', 'label'):
    print(p[key])
PY
  ) || die "Could not read proxy geolocation."
  LOCATION_LATITUDE=$(printf '%s\n' "$LOCATION_VALUES" | sed -n '1p')
  LOCATION_LONGITUDE=$(printf '%s\n' "$LOCATION_VALUES" | sed -n '2p')
  LOCATION_TIMEZONE=$(printf '%s\n' "$LOCATION_VALUES" | sed -n '3p')
  LOCATION_LABEL=$(printf '%s\n' "$LOCATION_VALUES" | sed -n '4p')
  ok "Proxy location: $LOCATION_LABEL ($LOCATION_LATITUDE, $LOCATION_LONGITUDE); $LOCATION_TIMEZONE"
fi
command -v adb >/dev/null || die "adb not found in $SDK/platform-tools."
command -v emulator >/dev/null || die "emulator not found in $SDK/emulator."
case "$FRONT_CAMERA" in
  imagefile:*|videofile:*)
    camera_help=$(emulator -help-camera-front 2>>"$LOG") || die "Could not inspect emulator camera support."
    [[ "$camera_help" == *"${FRONT_CAMERA%%:*}:"* ]] || die "Installed emulator does not support ${FRONT_CAMERA%%:*} camera input."
    ;;
esac
if [[ "$FRONT_CAMERA" == videofile:* ]]; then
  command -v ffmpeg >/dev/null || die "ffmpeg is required to prepare native camera playback."
  [[ -f "$SCRIPT_DIR/configure_video_camera.py" ]] || die "Missing configure_video_camera.py helper."
fi
if [[ "$FRONT_CAMERA" == webcam* ]]; then
  camera_sources=$(emulator -webcam-list 2>>"$LOG") || die "Could not list host cameras."
  [[ "$camera_sources" == *"'$FRONT_CAMERA'"* ]] || die "$FRONT_CAMERA is unavailable. Run emulator -webcam-list to choose a live camera."
fi
command -v python3 >/dev/null || die "python3 is required for app bundles and per-device profiles."
[[ -x "$LAB" ]] || die "galaxy_s25_avd_lab.sh must sit next to this script ($SCRIPT_DIR)."
for f in setup_su.py setup_magisk.py setup_ui.py phone_setup_guard.py generate_lab_profile.py device_battery_service.sh device_root_isolation.sh emulator_signal_sim.py device_qemu_profile.sh patch_sensor_labels.py build_file_aliases.py device_prepare_file_aliases.sh device_file_aliases.sh provision_file_profiles.sh; do
  [[ -f "$SCRIPT_DIR/$f" ]] || die "Missing helper $SCRIPT_DIR/$f"
done
(( !BUMBLE_SIGNUP )) || [[ -f "$SCRIPT_DIR/bumble_signup.py" ]] || die 'Missing bumble_signup.py helper.'
(( !POF_SIGNUP )) || [[ -f "$SCRIPT_DIR/pof_signup.py" ]] || die 'Missing pof_signup.py helper.'
(( !TINDER_SIGNUP )) || [[ -f "$SCRIPT_DIR/tinder_signup.py" ]] || die 'Missing tinder_signup.py helper.'
if ((PLAY_STORE_BUMBLE || PLAY_STORE_POF || PLAY_STORE_TINDER)); then
  for f in play_store_install.py google_play_signin.py; do
    [[ -f "$SCRIPT_DIR/$f" ]] || die "Missing $f helper."
  done
fi
(( !BUMBLE_SIGNUP )) || [[ -f "$SCRIPT_DIR/setup_network.py" ]] || die 'Missing setup_network.py helper.'
(( !BUMBLE_SIGNUP )) || [[ -f "$SCRIPT_DIR/bumble-signup/prompt-pool.json" ]] || die 'Missing Bumble prompt pool.'
[[ -f "$SCRIPT_DIR/prepare_modem_config.py" ]] || die 'Missing prepare_modem_config.py helper.'
if ((GRAPHICS_LABELS)); then
  command -v clang >/dev/null || die "clang is required to build the graphics fixture."
  [[ -x "$SDK/build-tools/36.0.0/lld" ]] || die "Install Android SDK build-tools 36.0.0 for the graphics fixture."
  for f in build.sh rename_backend.py renderer_labels.c; do
    [[ -f "$SCRIPT_DIR/graphics-profile/$f" ]] || die "Missing graphics helper: $f"
  done
fi
((!FILE_ALIASES)) || [[ -f "$SCRIPT_DIR/fixtures/qemu-metadata.rules" ]] || die "Missing QEMU metadata policy fixture."
if ((CHECKER)); then
  [[ -f "$SCRIPT_DIR/device-checker/DeviceRedFlags.apk" ]] || die "Build the checker first: bash '$SCRIPT_DIR/device-checker/build.sh'"
fi
if [[ -n "$FINGERPRINT" ]]; then
  [[ "$FINGERPRINT" =~ ^samsung/pa1qxxx/pa1q:15/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+:user/release-keys$ ]] ||
    die "Fingerprint must match samsung/pa1qxxx/pa1q:15/BUILD_ID/INCREMENTAL:user/release-keys."
fi
for p in "${ROOT_PACKAGES[@]}"; do
  [[ "$p" =~ ^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$ ]] || die "Invalid package name: $p"
done
[[ -f "$SYSIMG/system.img" ]] || die "Missing system image. Install it with:
       sdkmanager 'system-images;android-35;google_apis_playstore;arm64-v8a'"
[[ "$NAME" =~ ^[A-Za-z0-9._-]+$ ]] || die "AVD name may only contain letters, digits, . _ -"
if [[ -e "$AVD_DIR" || -e "$AVD_HOME/$NAME.ini" ]]; then
  die "AVD '$NAME' already exists. Pick another --name (this script never overwrites an AVD)."
fi
mkdir -p "$AVD_HOME" || die "Cannot create AVD home."
free_gb=$(df -g "$AVD_HOME" | awk 'NR == 2 {print $4}')
((free_gb >= 8)) || die "Only ${free_gb} GB free; the new AVD needs about 8 GB."
ok "SDK $SDK · image $SYSIMG_REL · ${free_gb} GB free"

for f in ${APPS[@]+"${APPS[@]}"}; do
  [[ -f "$f" ]] || die "App file not found: $f"
  case "$f" in
    *.xapk) [[ "$(unzip -Z1 "$f" 2>/dev/null)" == *.apk* ]] || die "$(basename "$f") contains no APKs." ;;
    *.apk) ;;
    *) die "Unsupported app file (use .xapk or .apk): $f" ;;
  esac
  ok "Will install $(basename "$f") ($(du -h "$f" | cut -f1 | tr -d ' '))"
done

# Stock ramdisk source: rootAVD keeps the original as ramdisk.img.backup when it
# patched the shared image in the past.
STOCK=
for f in "$SYSIMG/ramdisk.img.backup" "$SYSIMG/ramdisk.img"; do
  [[ -f "$f" ]] || continue
  stock_check "$f"; rc=$?
  if ((rc == 0)); then STOCK=$f; break; fi
  if ((rc == 2)); then STOCK=$f; warn "lz4 not installed — can't pre-check the ramdisk; the first boot will verify it."; break; fi
  info "$(basename "$f") already contains Magisk — skipping it as a source"
done
[[ -n "$STOCK" ]] || die "No stock ramdisk found in $SYSIMG."
ok "Stock ramdisk: $(basename "$STOCK")"

if [[ ! -x "$ROOTAVD_SRC/rootAVD.sh" ]]; then
  info "rootAVD not found at $ROOTAVD_SRC"
  confirm "Clone $ROOTAVD_REPO into $ROOTAVD_SRC?" || die "rootAVD is required."
  git clone --depth 1 "$ROOTAVD_REPO" "$ROOTAVD_SRC" >>"$LOG" 2>&1 || die "git clone failed."
fi
ok "rootAVD: $ROOTAVD_SRC ($(git -C "$ROOTAVD_SRC" log -1 --format=%h 2>/dev/null || echo local))"

printf '\n   Will create %s%s%s: Medium Phone · Android 15 · Google Play · %s MB RAM · %s cores%s\n' \
  "$B" "$NAME" "$X" "$RAM_MB" "$CORES" "${VSYNC:+ · ${VSYNC} Hz}"
printf '   %sOther AVDs and the shared SDK system image are not modified.%s\n' "$DIM" "$X"
confirm "Continue?" || { info "Cancelled."; exit 0; }

# ── 1. Create AVD ───────────────────────────────────────────────────────────
step "Creating AVD $NAME (Medium Phone profile)"
mkdir "$AVD_DIR" || die "Could not reserve $NAME; another setup may have created it."
(set -C; cat >"$AVD_HOME/$NAME.ini" <<EOF
avd.ini.encoding=UTF-8
path=$AVD_DIR
path.rel=avd/$NAME.avd
target=android-35
EOF
) || die "Could not create AVD registration without overwriting it."
cat >"$AVD_DIR/config.ini" <<EOF
AvdId=$NAME
PlayStore.enabled=true
abi.type=arm64-v8a
avd.ini.displayname=$(echo "$NAME" | tr '_' ' ')
avd.ini.encoding=UTF-8
disk.dataPartition.size=8G
fastboot.chosenSnapshotFile=
fastboot.forceChosenSnapshotBoot=no
fastboot.forceColdBoot=yes
fastboot.forceFastBoot=no
hw.accelerometer=yes
hw.arc=false
hw.audioInput=yes
hw.battery=yes
hw.camera.back=virtualscene
hw.camera.front=$FRONT_CAMERA
hw.cpu.arch=arm64
hw.cpu.ncore=$CORES
hw.dPad=no
hw.device.manufacturer=Generic
hw.device.name=medium_phone
hw.gps=yes
hw.gpu.enabled=yes
hw.gpu.mode=auto
hw.gyroscope=yes
hw.initialOrientation=portrait
hw.keyboard=yes
hw.lcd.density=420
hw.lcd.height=2400
hw.lcd.width=1080
hw.mainKeys=no
hw.ramSize=$RAM_MB
hw.sdCard=yes
hw.sensors.light=yes
hw.sensors.magnetic_field=yes
hw.sensors.orientation=yes
hw.sensors.pressure=yes
hw.sensors.proximity=yes
hw.trackBall=no
image.sysdir.1=$SYSIMG_REL/
runtime.network.latency=none
runtime.network.speed=full
sdcard.size=512M
showDeviceFrame=yes
skin.dynamic=yes
tag.display=Google Play
tag.displaynames=Google Play
tag.id=google_apis_playstore
tag.ids=google_apis_playstore
target=android-35
vm.heapSize=228
EOF
if [[ "$FRONT_CAMERA" == videofile:* ]]; then
  python3 -I "$SCRIPT_DIR/configure_video_camera.py" --avd "$NAME" \
    --video "${FRONT_CAMERA#videofile:}" --preview-size 1080x1440 >>"$LOG" 2>&1 || \
    die "Could not prepare the native video camera profile (see $LOG)."
  FRONT_CAMERA=environment
fi
"$SDK/emulator/mksdcard" 512M "$AVD_DIR/sdcard.img" >>"$LOG" 2>&1 || warn "mksdcard failed (AVD will run without an SD card)."
python3 -I "$SCRIPT_DIR/device_identifiers.py" --avd-dir "$AVD_DIR" --name "$NAME" --sdk "$SDK" \
  --registry "$SCRIPT_DIR/.local/device-identifiers.sqlite3" >>"$LOG" 2>&1 || die "Could not prepare unique device identifiers and private emulator engines."
# Private ramdisk: the emulator prefers ramdisk.img in the AVD folder over the system image's.
cp "$STOCK" "$AVD_DIR/ramdisk.img"
cp "$STOCK" "$AVD_DIR/ramdisk.img.stock"
# Emulator resolves modem source configs relative to the selected ramdisk.
# A private ramdisk needs its matching SDK data/misc/modem_simulator directory.
python3 -I "$SCRIPT_DIR/prepare_modem_config.py" --system-image "$SYSIMG" --avd-dir "$AVD_DIR" --lte-only >>"$LOG" 2>&1 ||
  die "Could not stage modem configs beside the private ramdisk (see $LOG)."
if ((BATTERY_SIM || SIGNAL_SIM)); then
  python3 -I "$SCRIPT_DIR/generate_lab_profile.py" --name "$NAME" --output-dir "$WORK/profile" >>"$LOG" 2>&1 ||
    die "Could not create the per-device battery fixture (see $LOG)."
fi
grep -qxF "$NAME" <<<"$(emulator -list-avds 2>/dev/null)" || die "Emulator does not list the new AVD."
ok "AVD created at $AVD_DIR (fast boot off: every launch is a cold boot so Magisk scripts run)"

# ── 2. First boot (stock) ───────────────────────────────────────────────────
step "First boot with the private stock ramdisk"
launch
python3 -I "$SCRIPT_DIR/device_identifiers.py" --avd-dir "$AVD_DIR" --initialize-serial "$SERIAL" --adb "$SDK/platform-tools/adb" >>"$LOG" 2>&1 || die "Could not initialize Android ID and per-device settings."
rd=$(sed -n 's/^disk\.ramdisk\.path *= *//p' "$AVD_DIR/hardware-qemu.ini" 2>/dev/null)
canon() { (cd "$(dirname "$1")" 2>/dev/null && echo "$(pwd -P)/$(basename "$1")"); }
[[ -n "$rd" && "$(canon "$rd")" == "$(canon "$AVD_DIR/s25-system/ramdisk.img")" ]] || die "Emulator used '$rd' instead of the AVD's private launch ramdisk — stopping before rooting."
ok "Emulator boots this AVD's own ramdisk: ${DIM}$rd${X}"
if [[ "$(adb -s "$SERIAL" shell 'command -v magisk' 2>/dev/null)" == *magisk* ]]; then
  die "Magisk is already present on a supposedly stock boot — refusing to continue."
fi
ok "Stock boot confirmed (no Magisk) · Android $(adb -s "$SERIAL" shell getprop ro.build.version.release | tr -d '\r') · $(adb -s "$SERIAL" shell getprop ro.product.cpu.abi | tr -d '\r')"
for p in com.android.vending com.google.android.gms com.google.android.gsf; do
  [[ "$(adb -s "$SERIAL" shell pm path "$p" 2>/dev/null)" == package:* ]] || die "$p missing on a Play Store image?"
done
ok "Google Play components present"

if ((CHECKER)); then
  step "Installing Device Red Flags"
  adb -s "$SERIAL" install -r "$SCRIPT_DIR/device-checker/DeviceRedFlags.apk" >>"$LOG" 2>&1 || die "Checker installation failed."
  adb -s "$SERIAL" shell pm grant dev.emulab.devicecheck android.permission.READ_PHONE_STATE >>"$LOG" 2>&1 || die "Could not grant checker permission to verify LTE."
fi

# ── 3. Root with rootAVD ────────────────────────────────────────────────────
step "Rooting the private ramdisk with Magisk (rootAVD)"
# rootAVD patches "$ANDROID_HOME/<arg>". We give it a stand-in SDK whose ramdisk is
# this AVD's copy, so the real SDK image cannot be touched. Everything else is symlinked.
FAKE="$WORK/fake-sdk"
rm -rf "$FAKE" "$WORK/rootAVD"
mkdir -p "$FAKE/$SYSIMG_REL"
ln -s "$SDK/platform-tools" "$FAKE/platform-tools"
ln -s "$SDK/emulator" "$FAKE/emulator"
for f in "$SYSIMG"/*; do
  case "${f##*/}" in ramdisk.img*) ;; *) ln -s "$f" "$FAKE/$SYSIMG_REL/${f##*/}" ;; esac
done
cp "$AVD_DIR/ramdisk.img" "$FAKE/$SYSIMG_REL/ramdisk.img"
rsync -a --exclude .git "$ROOTAVD_SRC/" "$WORK/rootAVD/"
rm -f "$WORK/rootAVD/Apps/"*.apk   # only install the Magisk app this run produces
info "Running rootAVD (about a minute; it picks the bundled Magisk automatically)…"
(
  cd "$WORK/rootAVD" &&
    ANDROID_HOME="$FAKE" ANDROID_SERIAL="$SERIAL" ./rootAVD.sh "$SYSIMG_REL/ramdisk.img" </dev/null
) >>"$WORK/rootAVD.log" 2>&1
grep -E '^\[[-*!]\]' "$WORK/rootAVD.log" | grep -iE 'magisk (v|version|stable)|choose|patch|error|fail|success' | tail -n 6 | sed 's/^/     /'
PATCHED="$FAKE/$SYSIMG_REL/ramdisk.img"
cmp -s "$PATCHED" "$AVD_DIR/ramdisk.img.stock" && die "rootAVD did not produce a patched ramdisk (see $WORK/rootAVD.log)."
if stock_check "$PATCHED"; then die "Patched ramdisk contains no Magisk files (see $WORK/rootAVD.log)."; fi
MAGISK_APK="$WORK/rootAVD/Apps/Magisk.apk"
[[ -f "$MAGISK_APK" ]] || die "rootAVD did not produce Apps/Magisk.apk."
cp "$PATCHED" "$AVD_DIR/ramdisk.img"
ok "Patched ramdisk installed into $AVD_DIR/ramdisk.img (stock kept as ramdisk.img.stock)"
spin_wait "Waiting for rootAVD's shutdown" 60 gone || shutdown_avd
SERIAL=

# ── 4. Rooted boot + Magisk's one-time setup ────────────────────────────────
step "Booting rooted and completing Magisk setup"
launch
magisk_up() { [[ "$(adb -s "$SERIAL" shell logcat -d -s Magisk 2>/dev/null)" == *"daemon started"* ]]; }
spin_wait "Waiting for the Magisk daemon" 90 magisk_up || die "Magisk daemon did not start — the patched ramdisk did not take effect."
ok "Magisk daemon running from the patched ramdisk"
[[ "$(adb -s "$SERIAL" shell pm path "$MAGISK_PKG" 2>/dev/null)" == package:* ]] ||
  { adb -s "$SERIAL" install -r "$MAGISK_APK" >>"$LOG" 2>&1 || die "Magisk app install failed."; }
adb -s "$SERIAL" shell pm grant "$MAGISK_PKG" android.permission.POST_NOTIFICATIONS >/dev/null 2>&1
ok "Magisk app installed"

boot_id() { adb -s "$SERIAL" shell cat /proc/sys/kernel/random/boot_id 2>/dev/null | tr -d '\r'; }
new_boot() { local b; b=$(boot_id); [[ -n "$b" && "$b" != "$OLD_BOOT" ]] && booted; }
env_ready() { [[ "$(adb -s "$SERIAL" shell 'for f in /system_ext/bin/su /system/bin/su /system/xbin/su; do [ -e $f ] && echo yes; done' 2>/dev/null)" == *yes* ]]; }

if env_ready; then
  ok "Magisk installed (su executable present; shell authorization pending)"
else
  info "Accepting Magisk's one-time \"Requires additional setup\" in the app (it reboots by itself)…"
  python3 -I "$SCRIPT_DIR/setup_magisk.py" --serial "$SERIAL" --avd "$NAME" --timeout 240 2>>"$LOG" ||
    die "Magisk additional setup did not complete. See $LOG for confirmation and reboot errors."
  ok "Magisk installed after reboot (shell authorization pending)"
fi

# ── 5. su for the adb shell ─────────────────────────────────────────────────
step "Granting Magisk superuser to the adb shell"
su_works() { python3 -I "$SCRIPT_DIR/setup_su.py" --serial "$SERIAL" --avd "$NAME" --verify-only --timeout 42 >>"$LOG" 2>&1; }
python3 -I "$SCRIPT_DIR/setup_su.py" --serial "$SERIAL" --avd "$NAME" \
  --output "$WORK/shell-diagnostics" --timeout 180 2>>"$LOG" ||
  die "Shell authorization failed; review $WORK/shell-diagnostics and $LOG. Phone retained."
adb -s "$SERIAL" shell input keyevent KEYCODE_HOME >/dev/null 2>&1
ok "adb shell → su → uid 0 ($(dsu 'cat /proc/self/attr/current' | tr -d '\0'))"
[[ "$(dsu '[ -x /data/adb/magisk/busybox ] && echo y')" == y ]] || die "/data/adb/magisk is incomplete."
ok "Magisk $(adb -s "$SERIAL" shell magisk -v | tr -d '\r') fully installed (/data/adb/magisk present)"

# ── 6–8. Galaxy S25 profile via the lab script ──────────────────────────────
export S25_LAB_ALLOW="$NAME"
step "Baseline emulator-signal inventory (before spoofing)"
"$LAB" --avd "$NAME" --action inventory | sed -n '/\[1\/2\]/,/\[2\/2\]/p' | grep -E '✓|!|✗' || die "Inventory failed."

step "Installing the per-device Android radio IMEI overlay"
mkdir -p "$WORK/radio"
dsu 'set -e
cp /vendor/lib64/libril-modem-lib.so /data/local/tmp/s25-original-radio.so
chmod 644 /data/local/tmp/s25-original-radio.so' >>"$LOG" 2>&1 || die "Could not stage the original radio library."
adb -s "$SERIAL" pull /data/local/tmp/s25-original-radio.so "$WORK/radio/original.so" >>"$LOG" 2>&1 || die "Could not retrieve the radio library."
python3 -I "$SCRIPT_DIR/patch_radio_imei.py" --input "$WORK/radio/original.so" --identity "$AVD_DIR/s25-identifiers.json" --output-dir "$WORK/radio" >>"$LOG" 2>&1 || die "Unsupported radio IMEI layout; no overlay installed."
adb -s "$SERIAL" push "$WORK/radio/s25_radio_imei.zip" /data/local/tmp/s25_radio_imei.zip >>"$LOG" 2>&1 || die "Could not copy radio IMEI overlay."
dsu 'magisk --install-module /data/local/tmp/s25_radio_imei.zip' >>"$LOG" 2>&1 || die "Radio IMEI overlay install failed."
ok "Android radio API will use this phone's reserved IMEI after the profile reboot"

step "Installing the cellular-only LTE network profile"
adb -s "$SERIAL" push "$AVD_DIR/s25-network.conf" /data/local/tmp/s25-network.conf >>"$LOG" 2>&1 || die "Could not copy network configuration."
adb -s "$SERIAL" push "$SCRIPT_DIR/device_network_profile.sh" /data/local/tmp/s25-network-profile.sh >>"$LOG" 2>&1 || die "Could not copy network service."
dsu 'set -e
mkdir -p /data/adb/service.d /data/adb/s25-avd-lab
cp /data/local/tmp/s25-network.conf /data/adb/s25-avd-lab/network.conf
chmod 600 /data/adb/s25-avd-lab/network.conf
cp /data/local/tmp/s25-network-profile.sh /data/adb/service.d/96-s25-network.sh
chmod 755 /data/adb/service.d/96-s25-network.sh
rm -f /data/local/tmp/s25-network.conf /data/local/tmp/s25-network-profile.sh' >>"$LOG" 2>&1 || die "Could not install cellular network profile."
NETWORK_PROFILE_INSTALLED=1

if ((QEMU_PROFILE)); then
  step "Installing the late-boot QEMU property profile"
  adb -s "$SERIAL" push "$SCRIPT_DIR/device_qemu_profile.sh" /data/local/tmp/s25-qemu-profile.sh >>"$LOG" 2>&1 || die "Could not copy QEMU profile."
  dsu 'set -e
mkdir -p /data/adb/service.d
cp /data/local/tmp/s25-qemu-profile.sh /data/adb/service.d/97-s25-qemu.sh
chmod 755 /data/adb/service.d/97-s25-qemu.sh' >>"$LOG" 2>&1 || die "Could not install QEMU profile."
  ok "ro.kernel.qemu / ro.boot.qemu will be overridden after boot completes"
fi

if ((SENSOR_LABELS)); then
  step "Preparing and installing the sensor-label overlay"
  mkdir -p "$WORK/sensors"
  dsu 'set -e
cp /vendor/lib64/hw/android.hardware.sensors@2.1-impl.ranchu.so /data/local/tmp/s25-original-sensors.so
chmod 644 /data/local/tmp/s25-original-sensors.so' >>"$LOG" 2>&1 || die "Could not back up sensor HAL."
  adb -s "$SERIAL" pull /data/local/tmp/s25-original-sensors.so "$WORK/sensors/original.so" >>"$LOG" 2>&1 || die "Could not retrieve sensor HAL."
  python3 -I "$SCRIPT_DIR/patch_sensor_labels.py" --input "$WORK/sensors/original.so" --output-dir "$WORK/sensors" >>"$LOG" 2>&1 || die "Sensor HAL layout was not recognized; no patch installed."
  adb -s "$SERIAL" push "$WORK/sensors/s25_sensor_labels.zip" /data/local/tmp/s25_sensor_labels.zip >>"$LOG" 2>&1 || die "Could not copy sensor overlay."
  dsu 'magisk --install-module /data/local/tmp/s25_sensor_labels.zip' >>"$LOG" 2>&1 || die "Sensor overlay install failed."
  ok "Sensor labels patched in a Magisk overlay; original binary and hashes saved"
fi

source "$SCRIPT_DIR/provision_file_profiles.sh"

step "Applying the Galaxy S25 profile (backup → identity → display → persistence → reboot)"
info "The first boot with a new fingerprint is slow: Android treats it like a system update."
profile_args=()
[[ -z "$FINGERPRINT" ]] || profile_args+=(--fingerprint "$FINGERPRINT")
"$LAB" --avd "$NAME" --action apply --yes ${profile_args[@]+"${profile_args[@]}"} || die "Profile apply failed."
verify_cpu_architecture
ensure_cellular_network
set_location
verify_identifiers

if ((QEMU_PROFILE)); then
  qemu_profile_ok() {
    [[ "$(adb -s "$SERIAL" shell getprop ro.kernel.qemu | tr -d '\r')" == 0 ]] &&
      [[ "$(adb -s "$SERIAL" shell getprop ro.boot.qemu | tr -d '\r')" == 0 ]]
  }
  if ! spin_wait "Verifying late-boot QEMU profile" 30 qemu_profile_ok; then
    # A very slow first boot can outlast the boot service's wait. Retry only
    # after Android is up, then require the same property read-back.
    booted || die "Android is not booted; refusing runtime QEMU recovery."
    info "Retrying the QEMU service after the slow first boot"
    dsu 'sh /data/adb/service.d/97-s25-qemu.sh' >>"$LOG" 2>&1 || die "QEMU service retry failed."
    qemu_profile_ok || die "QEMU property read-back failed after retry."
  fi
fi
if ((SENSOR_LABELS)); then
  adb -s "$SERIAL" shell dumpsys sensorservice >"$WORK/sensors/after-reboot.txt" || die "Could not query sensor service after reboot."
  grep -q 'Samsung  3-axis Accelerometer' "$WORK/sensors/after-reboot.txt" || die "Sensor label overlay did not take effect."
  grep -q 'Goldfish ' "$WORK/sensors/after-reboot.txt" && die "Unpatched Goldfish labels remain in the sensor service."
fi
if ((FILE_ALIASES)); then
  [[ "$(dsu '[ -c /dev/s25_address_space ] && [ -c /dev/s25_gpu_sync ] && echo ready')" == ready ]] || die "File-alias boot fixture failed. See device boot.log."
fi

step "Post-change inventory"
"$LAB" --avd "$NAME" --action inventory | sed -n '/\[2\/2\]/,$p'

# The phone's runtime profile is active before any dating app is installed.
# Battery is a persistent Magisk boot service. Signal and GPS are host-side
# controllers and are restarted after the later isolation reboot.
battery_runtime_ok() {
  ((BATTERY_SIM)) || return 0
  local state level temp actual_level actual_temp
  state=$(dsu 'cat /data/adb/s25-avd-lab/battery.state 2>/dev/null') || return 1
  level=$(sed -n 's/^LEVEL=//p' <<<"$state")
  temp=$(sed -n 's/^TEMP=//p' <<<"$state")
  [[ "$level" =~ ^[0-9]+$ && "$temp" =~ ^[0-9]+$ ]] || return 1
  actual_level=$(adb -s "$SERIAL" shell dumpsys battery get level | tr -d '\r')
  actual_temp=$(adb -s "$SERIAL" shell dumpsys battery get temp | tr -d '\r')
  [[ "$actual_level" == "$level" && "$actual_temp" == "$temp" ]]
}

signal_runtime_ok() {
  ((SIGNAL_SIM)) || return 0
  python3 -I - "$WORK/profile/radio-state.json" "$NAME" <<'PY' >/dev/null 2>&1
import json, sys
p = json.load(open(sys.argv[1]))
assert p.get('avd') == sys.argv[2] and p.get('tick', 0) >= 1
PY
}

location_runtime_ok() {
  python3 -I - "$WORK/location/location-state.json" "$NAME" "$LOCATION_LATITUDE" "$LOCATION_LONGITUDE" <<'PY' >/dev/null 2>&1
import json, math, sys
p = json.load(open(sys.argv[1]))
assert p.get('avd') == sys.argv[2] and p.get('tick', 0) >= 1
assert math.isclose(float(p['center_latitude']), float(sys.argv[3]), abs_tol=1e-7)
assert math.isclose(float(p['center_longitude']), float(sys.argv[4]), abs_tol=1e-7)
PY
}

start_signal_runtime() {
  ((SIGNAL_SIM)) || return 0
  step "Starting per-device modem signal simulation"
  python3 -I "$SCRIPT_DIR/emulator_signal_sim.py" --avd "$NAME" --profile "$WORK/profile/device-profile.json" --once >>"$LOG" 2>&1 || die "Signal-console verification failed."
  python3 -I "$SCRIPT_DIR/emulator_signal_sim.py" --avd "$NAME" --profile "$WORK/profile/device-profile.json" --background >>"$LOG" 2>&1 || die "Signal controller exited; see $WORK/profile/signal.log."
  ok "Signal controller started; small changes every 15 seconds"
}

start_location_runtime() {
  step "Starting bounded GPS movement around the proxy-derived location"
  python3 -I "$SCRIPT_DIR/emulator_location_sim.py" --avd "$NAME" --output "$WORK/location" \
    --latitude "$LOCATION_LATITUDE" --longitude "$LOCATION_LONGITUDE" --background >>"$LOG" 2>&1 || die "GPS controller exited; see $WORK/location/location.log."
  ok "GPS moves 20–30 feet every 3–5 seconds within 1000 feet of the proxy-derived center"
}

verify_runtime_services() {
  step "Verifying battery, signal and proxy-derived GPS"
  spin_wait "Verifying battery service" 30 battery_runtime_ok || die "Battery service did not match its saved state."
  signal_runtime_ok || die "Signal controller did not produce a valid state for this phone."
  location_runtime_ok || die "GPS controller did not use this phone's proxy-derived center."
  ok "Runtime services match this phone: battery, signal and proxy-derived GPS"
}

wait_host_controller_exit() {
  local pid=${1:-} label=${2:-controller} i
  [[ "$pid" =~ ^[0-9]+$ ]] || return 0
  for i in {1..30}; do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 1
  done
  die "$label did not stop across the isolation reboot."
}

if ((BATTERY_SIM)); then
  step "Installing per-device battery simulation"
  adb -s "$SERIAL" push "$WORK/profile/battery.conf" /data/local/tmp/s25-battery.conf >>"$LOG" 2>&1 || die "Could not copy battery fixture."
  adb -s "$SERIAL" push "$SCRIPT_DIR/device_battery_service.sh" /data/local/tmp/s25-battery-service.sh >>"$LOG" 2>&1 || die "Could not copy battery service."
  dsu 'set -e
mkdir -p /data/adb/s25-avd-lab /data/adb/service.d
cp /data/local/tmp/s25-battery.conf /data/adb/s25-avd-lab/battery.conf
chmod 600 /data/adb/s25-avd-lab/battery.conf
cp /data/local/tmp/s25-battery-service.sh /data/adb/service.d/98-s25-battery.sh
chmod 755 /data/adb/service.d/98-s25-battery.sh
rm -f /data/local/tmp/s25-battery.conf /data/local/tmp/s25-battery-service.sh
sh /data/adb/service.d/98-s25-battery.sh --once' >>"$LOG" 2>&1 || die "Battery service installation failed."
  expected_level=$(sed -n 's/^LEVEL=//p' "$WORK/profile/battery.conf")
  expected_temp=$(sed -n 's/^TEMP=//p' "$WORK/profile/battery.conf")
  actual_level=$(adb -s "$SERIAL" shell dumpsys battery get level | tr -d '\r')
  actual_temp=$(adb -s "$SERIAL" shell dumpsys battery get temp | tr -d '\r')
  [[ "$actual_level" == "$expected_level" && "$actual_temp" == "$expected_temp" ]] || die "Battery simulation read-back did not match the fixture."
  dsu 'sh /data/adb/service.d/98-s25-battery.sh </dev/null >/data/adb/s25-avd-lab/battery.log 2>&1 &' >>"$LOG" 2>&1 || die "Could not start the battery loop."
  ok "Battery fixture active: ${actual_level}% · $((actual_temp / 10)).$((actual_temp % 10)) °C; temperature updates every five seconds"
  info "Unique fixture: $WORK/profile/device-profile.json"
  info "Framework charge counter is simulated; direct BatteryManager/HAL readings may differ."
  info "Health/wear, voltage and cycle count are not overridden."
fi

if ((SIGNAL_SIM)); then
  step "Priming the per-device modem signal profile"
  python3 -I "$SCRIPT_DIR/emulator_signal_sim.py" --avd "$NAME" --profile "$WORK/profile/device-profile.json" --once >>"$LOG" 2>&1 || die "Signal-console verification failed."
  ok "Initial modem signal profile applied before the base verification reboot"
fi

step "Confirming proxy-derived GPS before the base verification reboot"
set_location
battery_runtime_ok || die "Battery simulation was not active before the base verification reboot."
ok "Battery and proxy-derived GPS are active before the base verification reboot"

step "Rebooting and verifying the optimized base phone"
OLD_BOOT=$(boot_id)
adb -s "$SERIAL" reboot >>"$LOG" 2>&1 || die "Base verification reboot failed."
spin_wait "Rebooting optimized base phone" 360 new_boot || die "Android did not finish the base verification reboot."
verify_cpu_architecture
ensure_cellular_network
set_location
verify_identifiers
su_works || die "Shell root was not retained after the base verification reboot."
if ((QEMU_PROFILE)); then
  spin_wait "Verifying QEMU settings after base reboot" 30 qemu_profile_ok || {
    dsu 'sh /data/adb/service.d/97-s25-qemu.sh' >>"$LOG" 2>&1 && qemu_profile_ok
  } || die "QEMU settings were not retained after the base verification reboot."
fi

start_signal_runtime
start_location_runtime
verify_runtime_services

# ── 10. Apps ────────────────────────────────────────────────────────────────
# .xapk = zip of a base APK + split APKs (+ optional OBB data) described by manifest.json.
# Splits for CPU ABIs the device doesn't support are skipped; everything else goes into
# one `adb install-multiple` session.
install_app() {
  local f=$1 dir meta pkg ver kind file path abis a apks=() obbs=()
  if [[ "$f" == *.apk ]]; then
    adb -s "$SERIAL" install -r -d "$f" >>"$LOG" 2>&1 || return 1
    ok "$(basename "$f") installed"
    return 0
  fi
  dir=$(mktemp -d "$WORK/xapk.XXXXXX")
  unzip -q -o "$f" -d "$dir" || { rm -rf "$dir"; return 1; }
  meta=$(python3 -I - "$dir/manifest.json" <<'PY' 2>/dev/null
import json, sys
m = json.load(open(sys.argv[1], encoding="utf-8"))
print(m.get("package_name", ""))
print(m.get("version_name", ""))
for s in m.get("split_apks", []):
    print("APK\t" + s["file"])
for e in m.get("expansions", []):
    print("OBB\t" + e["file"] + "\t" + e["install_path"])
PY
)
  pkg=$(sed -n 1p <<<"$meta"); ver=$(sed -n 2p <<<"$meta")
  abis=",$(adb -s "$SERIAL" shell getprop ro.product.cpu.abilist | tr -d '\r'),"
  while IFS=$'\t' read -r kind file path; do
    case "$kind" in
      APK) apks+=("$file") ;;
      OBB) obbs+=("$file"$'\t'"$path") ;;
    esac
  done <<<"$(sed -n '3,$p' <<<"$meta")"
  ((${#apks[@]})) || while IFS= read -r file; do apks+=("$file"); done <<<"$(cd "$dir" && ls *.apk)"
  local keep=()
  for file in "${apks[@]}"; do
    a=$(sed -nE 's/^(split_)?config\.(arm64_v8a|armeabi_v7a|armeabi|x86_64|x86|mips64|mips)\.apk$/\2/p' <<<"$file" | tr '_' '-')
    if [[ -n "$a" && "$abis" != *",$a,"* ]]; then info "skipping $file (device has no $a)"; continue; fi
    keep+=("$dir/$file")
  done
  info "Installing ${pkg:-$(basename "$f")} ${ver} (${#keep[@]} APKs)…"
  adb -s "$SERIAL" install-multiple -r -d "${keep[@]}" >>"$LOG" 2>&1 || { rm -rf "$dir"; return 1; }
  for file in ${obbs[@]+"${obbs[@]}"}; do
    adb -s "$SERIAL" push "$dir/${file%%$'\t'*}" "/sdcard/${file#*$'\t'}" >>"$LOG" 2>&1 || warn "OBB push failed: ${file%%$'\t'*}"
  done
  rm -rf "$dir"
  if [[ -n "$pkg" ]]; then
    local got; got=$(adb -s "$SERIAL" shell dumpsys package "$pkg" 2>/dev/null | tr -d '\r' | sed -n 's/^ *versionName=//p' | head -n1)
    [[ -n "$got" ]] || return 1
    ok "$pkg $got installed"
  fi
}
if ((${#APPS[@]})); then
  step "Installing apps"
  for f in "${APPS[@]}"; do install_app "$f" || die "Installing $(basename "$f") failed (see $LOG)."; done
fi

if ((PLAY_STORE_BUMBLE)); then
  step "Installing Bumble from Google Play without opening it"
  if ((INTERACTIVE == 0)) || [[ ! -t 0 ]]; then
    warn "Google Play sign-in awaits an interactive terminal; local Bumble bundles will not be installed."
    printf '   Resume Google Play: python3 %q --serial %q --avd %q --sign-in --install-only\n' "$SCRIPT_DIR/play_store_install.py" "$SERIAL" "$NAME"
  else
    # Google credentials and manual verification input must never enter the setup log.
    python3 "$SCRIPT_DIR/play_store_install.py" --serial "$SERIAL" --avd "$NAME" --sign-in --install-only ||
      die "Google Play installation paused or failed; the phone is retained. Resume with play_store_install.py --sign-in --install-only."
    ok "Bumble installed by Google Play and held closed until final verification"
  fi
fi

if ((PLAY_STORE_POF)); then
  step "Installing Plenty of Fish from Google Play without opening it"
  if ((INTERACTIVE == 0)) || [[ ! -t 0 ]]; then
    warn "Google Play sign-in awaits an interactive terminal; no local POF bundle will be installed."
    printf '   Resume Google Play: python3 %q --serial %q --avd %q --app pof --sign-in --install-only\n' "$SCRIPT_DIR/play_store_install.py" "$SERIAL" "$NAME"
  else
    # Google credentials and manual verification input must never enter the setup log.
    python3 "$SCRIPT_DIR/play_store_install.py" --serial "$SERIAL" --avd "$NAME" --app pof --sign-in --install-only ||
      die "Google Play POF installation paused or failed; the phone is retained. Resume with play_store_install.py --app pof --sign-in --install-only."
    ok "Plenty of Fish installed by Google Play and held closed until final verification"
  fi
fi

if ((PLAY_STORE_TINDER)); then
  step "Installing Tinder from Google Play without opening it"
  if ((INTERACTIVE == 0)) || [[ ! -t 0 ]]; then
    warn "Google Play sign-in awaits an interactive terminal; no local Tinder bundle will be installed."
    printf '   Resume Google Play: python3 %q --serial %q --avd %q --app tinder --sign-in --install-only\n' "$SCRIPT_DIR/play_store_install.py" "$SERIAL" "$NAME"
  else
    python3 "$SCRIPT_DIR/play_store_install.py" --serial "$SERIAL" --avd "$NAME" --app tinder --sign-in --install-only ||
      die "Google Play Tinder installation paused or failed; the phone is retained. Resume with play_store_install.py --app tinder --sign-in --install-only."
    ok "Tinder installed by Google Play and held closed until final verification"
  fi
fi

if ((ROOT_ISOLATION)); then
  step "Configuring Magisk mount isolation for installed test apps"
  isolated_packages=0
  adb -s "$SERIAL" push "$SCRIPT_DIR/device_root_isolation.sh" /data/local/tmp/s25-root-isolation.sh >>"$LOG" 2>&1 || die "Could not copy the isolation helper."
  for p in "${ROOT_PACKAGES[@]}"; do
    if [[ "$(adb -s "$SERIAL" shell pm path "$p" 2>/dev/null)" != package:* ]]; then
      info "$p is not installed; no DenyList entry added."
      continue
    fi
    dsu "sh /data/local/tmp/s25-root-isolation.sh $p" >>"$LOG" 2>&1 || die "DenyList configuration failed for $p."
    isolated_packages=$((isolated_packages + 1))
    ok "$p: DenyList entries installed and enforcement enabled"
  done
  adb -s "$SERIAL" shell rm -f /data/local/tmp/s25-root-isolation.sh >>"$LOG" 2>&1
  if ((isolated_packages)); then
    info "Rebooting to activate Zygisk and app mount isolation"
    old_signal_pid=$(python3 -I - "$WORK/profile/radio-state.json" <<'PY' 2>/dev/null || true
import json, sys
print(json.load(open(sys.argv[1])).get('pid', ''))
PY
)
    old_location_pid=$(python3 -I - "$WORK/location/location-state.json" <<'PY' 2>/dev/null || true
import json, sys
print(json.load(open(sys.argv[1])).get('pid', ''))
PY
)
    OLD_BOOT=$(boot_id)
    adb -s "$SERIAL" reboot >>"$LOG" 2>&1 || die "Isolation activation reboot failed."
    spin_wait "Activating root isolation" 360 new_boot || die "Android did not finish the isolation activation reboot."
    wait_host_controller_exit "$old_signal_pid" "Signal controller"
    wait_host_controller_exit "$old_location_pid" "GPS controller"
    verify_cpu_architecture
    ensure_cellular_network
    set_location
    verify_identifiers
    su_works || die "Shell root was not retained after activating isolation."
    if ((QEMU_PROFILE)); then
      spin_wait "Verifying QEMU settings after isolation reboot" 30 qemu_profile_ok || {
        dsu 'sh /data/adb/service.d/97-s25-qemu.sh' >>"$LOG" 2>&1 && qemu_profile_ok
      } || die "QEMU settings were not retained after isolation reboot."
    fi
    start_signal_runtime
    start_location_runtime
    verify_runtime_services
    ok "Isolation activated; shell root retained"
  fi
  warn "Root remains installed. DenyList does not hide all root or emulator signals."
fi

if ((ROOT_ISOLATION && !KEEP_MAGISK_APP)); then
  step "Removing the Magisk manager package while retaining the boot daemon"
  manager_result=$(adb -s "$SERIAL" shell cmd package uninstall -k "$MAGISK_PKG" 2>&1 | tr -d '\r')
  [[ "$manager_result" == Success ]] || die "Manager removal failed: $manager_result"
  su_works || die "Root daemon access failed after manager removal. Reinstall $MAGISK_APK to recover management."
  ok "Manager package removed; boot services and shell root remain available"
  info "Restore manager UI: adb -s $SERIAL install -r '$MAGISK_APK'"
fi

if ((CHECKER)); then
  step "Checking app-visible signals on the new phone"
  # A fresh process and report prevent an earlier scan from satisfying read-back.
  adb -s "$SERIAL" shell am force-stop dev.emulab.devicecheck >>"$LOG" 2>&1
  adb -s "$SERIAL" shell rm -f /sdcard/Android/data/dev.emulab.devicecheck/files/latest-report.json >>"$LOG" 2>&1
  adb -s "$SERIAL" shell am start -W -n dev.emulab.devicecheck/.MainActivity >>"$LOG" 2>&1 || die "Could not launch checker."
  checker_report_ready() {
    adb -s "$SERIAL" pull /sdcard/Android/data/dev.emulab.devicecheck/files/latest-report.json "$WORK/checker-report.json" >>"$LOG" 2>&1 &&
      python3 -c 'import json,sys; p=json.load(open(sys.argv[1])); assert "redFlags" in p and "findings" in p' "$WORK/checker-report.json" >>"$LOG" 2>&1
  }
  spin_wait "Waiting for checker report" 90 checker_report_ready || die "Checker did not produce a report."
  python3 - "$WORK/checker-report.json" <<'PY'
import json, sys
p = json.load(open(sys.argv[1]))
print(f"   Checker: {p['redFlags']} red flags / {p['weakSignals']} weak signals")
for finding in p['findings']:
    if finding['severity'] in ('RED FLAG', 'WEAK SIGNAL'):
        print(f"   {finding['severity']}: {finding['name']}")
PY
  info "Saved report: $WORK/checker-report.json"
  python3 - "$WORK/checker-report.json" <<'PY'
import json, re, sys
p = json.load(open(sys.argv[1]))
network = [f for f in p['findings'] if f['name'] == 'Network topology']
if len(network) != 1 or 'Transport=CELLULAR' not in network[0]['evidence'] or 'Data network=LTE' not in network[0]['evidence']:
    raise SystemExit('Checker app does not see LTE cellular data as its active network')
if re.search(r'\b10\.0\.2\.\d+\b', network[0]['evidence']):
    raise SystemExit('Default emulator subnet remains visible inside the checker app')
PY
  [[ $? == 0 ]] || die "App-visible network verification failed."
  if ((ROOT_ISOLATION)); then
    python3 - "$WORK/checker-report.json" <<'PY'
import json, sys
p = json.load(open(sys.argv[1]))
root = [f for f in p['findings'] if f['name'] == 'Root binaries']
if len(root) != 1 or root[0]['severity'] != 'NOT OBSERVED':
    raise SystemExit('Root binaries are still visible or the check is missing')
PY
    [[ $? == 0 ]] || die "App-visible root isolation failed. Review $WORK/checker-report.json."
    su_works || die "Checker passed but shell root is unavailable."
    ok "Checker cannot see the tested root paths; shell root remains available"
  fi
fi

if ((BUMBLE_SIGNUP || POF_SIGNUP || TINDER_SIGNUP)); then
  step "Certifying the full phone setup before app signup"
  GUARD_ARGS=(--record --serial "$SERIAL" --avd "$NAME" --work "$WORK")
  if ((BUMBLE_SIGNUP)); then
    GUARD_ARGS+=(--package com.bumble.app)
    adb -s "$SERIAL" shell am force-stop com.bumble.app >>"$LOG" 2>&1
  fi
  if ((POF_SIGNUP)); then
    GUARD_ARGS+=(--package com.pof.android)
    adb -s "$SERIAL" shell am force-stop com.pof.android >>"$LOG" 2>&1
  fi
  if ((TINDER_SIGNUP)); then
    GUARD_ARGS+=(--package com.tinder)
    adb -s "$SERIAL" shell am force-stop com.tinder >>"$LOG" 2>&1
  fi
  python3 "$SCRIPT_DIR/phone_setup_guard.py" "${GUARD_ARGS[@]}" >>"$LOG" 2>&1 ||
    die "Full phone setup verification failed; app signup is blocked. Review $LOG."
  ok "Full setup certificate created; the signup helper will re-check app-specific state"
  info "Certificate: $WORK/setup-complete.json"
fi

if ((BUMBLE_SIGNUP)); then
  step "Bumble signup"
  BUMBLE_ARGS=(--serial "$SERIAL" --avd "$NAME" --output "$WORK/bumble-signup")
  [[ -z "$BUMBLE_PROFILE_NAME" ]] || BUMBLE_ARGS+=(--profile-name "$BUMBLE_PROFILE_NAME")
  [[ -z "$BUMBLE_PROFILE_GENDER" ]] || BUMBLE_ARGS+=(--profile-gender "$BUMBLE_PROFILE_GENDER")
  if ! adb -s "$SERIAL" shell pm path com.bumble.app 2>/dev/null | grep -q '^package:'; then
    warn "Bumble is not installed; signup skipped. Install Bumble and run the helper below."
  elif ((INTERACTIVE == 0)) || [[ ! -t 0 ]]; then
    warn "Bumble signup awaits a terminal for your details and SMS code; device setup is complete."
  else
    # Keep credentials and OTPs out of the setup log and shell arguments.
    python3 "$SCRIPT_DIR/bumble_signup.py" "${BUMBLE_ARGS[@]}"
    bumble_rc=$?
    if ((bumble_rc == 2)); then
      warn "Bumble signup paused; resume with the helper below."
    elif ((bumble_rc != 0)); then
      die "Bumble signup failed; phone setup is retained. Resume with bumble_signup.py."
    else
      ok "Bumble onboarding finished at your selected endpoint (selfie verification is manual)."
    fi
  fi
  printf '   Resume Bumble: python3 %q ' "$SCRIPT_DIR/bumble_signup.py"
  printf '%q ' "${BUMBLE_ARGS[@]}"
  printf '\n'
fi

if ((POF_SIGNUP)); then
  step "Plenty of Fish signup capture"
  POF_ARGS=(--serial "$SERIAL" --avd "$NAME" --output "$WORK/pof-signup")
  if ! adb -s "$SERIAL" shell pm path com.pof.android 2>/dev/null | grep -q '^package:'; then
    warn "POF is not installed; capture skipped. Install it and run the helper below."
  elif ((INTERACTIVE == 0)) || [[ ! -t 0 ]]; then
    warn "POF profile choices and sensitive steps require direct review; device setup is complete."
  else
    python3 "$SCRIPT_DIR/pof_signup.py" "${POF_ARGS[@]}" --run-signup --allow-notifications --allow-location
    pof_rc=$?
    if ((pof_rc == 2)); then
      warn "POF capture paused at a profile or sensitive/manual boundary, as designed."
    elif ((pof_rc != 0)); then
      die "POF capture failed; phone setup is retained. Resume with pof_signup.py."
    else
      ok "POF capture completed at its guarded endpoint."
    fi
  fi
  printf '   Resume POF: python3 %q ' "$SCRIPT_DIR/pof_signup.py"
  printf '%q ' "${POF_ARGS[@]}"
  printf '\n'
fi

if ((TINDER_SIGNUP)); then
  step "Tinder guarded signup"
  TINDER_ARGS=(--serial "$SERIAL" --avd "$NAME" --output "$WORK/tinder-signup")
  if ! adb -s "$SERIAL" shell pm path com.tinder 2>/dev/null | grep -q '^package:'; then
    warn "Tinder is not installed; signup is blocked until Google Play installation and isolation complete."
  else
    adb -s "$SERIAL" shell monkey -p com.tinder -c android.intent.category.LAUNCHER 1 >>"$LOG" 2>&1 ||
      die "Tinder did not launch after final phone verification."
    sleep 2
    if ((TINDER_ACCEPT_TERMS && TINDER_ACCEPT_SMS_TERMS && TINDER_ACCEPT_HOUSE_RULES)) &&
       [[ -n "$TINDER_GENDER" && -n "$TINDER_GENDER_VISIBILITY" && -n "$TINDER_RELATIONSHIP_GOAL" ]] &&
       ((TINDER_ALLOW_NOTIFICATIONS || TINDER_DECLINE_NOTIFICATIONS)); then
      TINDER_ARGS+=(--run-signup --accept-terms --accept-sms-terms --accept-house-rules
        --signup-gender "$TINDER_GENDER" --signup-gender-visibility "$TINDER_GENDER_VISIBILITY"
        --signup-relationship-goal "$TINDER_RELATIONSHIP_GOAL" --pause-at-private-input)
      ((TINDER_ALLOW_NOTIFICATIONS)) && TINDER_ARGS+=(--allow-notifications)
      ((TINDER_DECLINE_NOTIFICATIONS)) && TINDER_ARGS+=(--decline-notifications)
      ((TINDER_ALLOW_LOCATION)) && TINDER_ARGS+=(--allow-location)
    fi
    python3 "$SCRIPT_DIR/tinder_signup.py" "${TINDER_ARGS[@]}" || tinder_rc=$?
    tinder_rc=${tinder_rc:-0}
    if ((tinder_rc == 2)); then
      warn "Tinder paused at its first explicit choice or manual boundary, as designed."
    elif ((tinder_rc != 0)); then
      die "Tinder inspection failed; phone setup is retained. Resume with tinder_signup.py."
    fi
  fi
  printf '   Resume Tinder: python3 %q ' "$SCRIPT_DIR/tinder_signup.py"
  printf '%q ' "${TINDER_ARGS[@]}"
  printf '\n'
fi

printf '\n %s%s  DONE%s  %s is a rooted Galaxy S25 test device (%s)\n' "$B" "$GRN" "$X" "$NAME" "$SERIAL"
printf '   Status any time:  %s"%s" --avd %s --action status%s\n' "$CYN" "$LAB" "$NAME" "$X"
printf '   Launch later:     python3 %q --avd %q\n' "$SCRIPT_DIR/emulator_proxy.py" "$NAME"
[[ -z "$HOST_PROXY" ]] || info 'Host TCP proxy active. This phone’s saved proxy is selected automatically when relaunching; UDP is not proxied.'
printf '   Backups & logs:   %s\n\n' "$HOME/galaxy_s25_avd_backups/$NAME"
warn "No Play Integrity pass, physical-device identity or locked bootloader is claimed."
