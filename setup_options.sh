#!/bin/bash
# Shared setup validation and prompts; sourcing this file has no side effects.
name_taken() {
  [[ -e "$AVD_HOME/$1.avd" || -e "$AVD_HOME/$1.ini" || -e "$HOME/galaxy_s25_avd_backups/$1" ]]
}
random_name() {
  local candidate
  while :; do
    candidate="Galaxy_S25_$(date +%Y%m%d)_$(python3 -c 'import secrets; print(secrets.token_hex(4))')" || return 1
    if ! name_taken "$candidate"; then printf '%s\n' "$candidate"; return 0; fi
  done
}
prompt_value() {
  local variable=$1 label=$2 value current
  eval 'current=${'"$variable"'}'
  printf '   %s [%s]: ' "$label" "$current"
  IFS= read -r value || return 1
  [[ -z "$value" ]] || printf -v "$variable" '%s' "$value"
}
validate_options() {
  case "$FRONT_CAMERA" in
    emulated|none) ;;
    imagefile:*|videofile:*)
      local camera_mode=${FRONT_CAMERA%%:*} camera_file=${FRONT_CAMERA#*:}
      [[ "$camera_file" != *$'\n'* && "$camera_file" != *$'\r'* && -f "$camera_file" && -r "$camera_file" && -s "$camera_file" ]] || {
        echo 'Camera media must be a readable, nonempty local file with no line breaks in its path.' >&2; return 1;
      }
      camera_file=$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).absolute())' "$camera_file") || return 1
      FRONT_CAMERA="$camera_mode:$camera_file"
      ;;
    *) [[ "$FRONT_CAMERA" =~ ^webcam[0-9]+$ ]] || {
      echo 'Front camera must be emulated, webcamN, none, imagefile:PATH or videofile:PATH.' >&2; return 1;
    } ;;
  esac
  [[ "$NAME" =~ ^[A-Za-z0-9._-]+$ && "$NAME" != . && "$NAME" != .. ]] || { echo 'Invalid AVD name.' >&2; return 1; }
  ! name_taken "$NAME" || { echo "AVD name or backup already exists: $NAME. Choose a new name." >&2; return 1; }
  [[ "$RAM_MB" =~ ^[0-9]+$ && ${#RAM_MB} -le 6 ]] && ((10#$RAM_MB >= 2048 && 10#$RAM_MB <= 65536)) || { echo 'RAM must be 2048–65536 MB.' >&2; return 1; }
  [[ "$CORES" =~ ^[0-9]+$ && ${#CORES} -le 2 ]] && ((10#$CORES >= 1 && 10#$CORES <= 32)) || { echo 'Cores must be 1–32.' >&2; return 1; }
  [[ -z "$VSYNC" ]] || { [[ "$VSYNC" =~ ^[0-9]+$ && ${#VSYNC} -le 3 ]] && ((10#$VSYNC >= 30 && 10#$VSYNC <= 240)); } || { echo 'Refresh rate must be 30–240 Hz.' >&2; return 1; }
  case "$BUMBLE_PROFILE_GENDER" in
    ''|Woman|Man|Nonbinary) ;;
    *) echo 'Profile gender must be Woman, Man or Nonbinary.' >&2; return 1 ;;
  esac
}
configure_setup() {
  [[ -n "$NAME" ]] || NAME=$(random_name) || return 1
  if (( !YES && INTERACTIVE != 0 )) && { [[ -t 0 ]] || ((INTERACTIVE == 1)); }; then
    printf '\n   Create a Galaxy S25 test phone (Enter keeps each default).\n'
    prompt_value NAME 'Android Studio device name' || return 1
    prompt_value RAM_MB 'RAM in MB' || return 1
    prompt_value CORES 'CPU cores' || return 1
    prompt_value VSYNC 'Refresh rate in Hz (empty uses emulator default)' || return 1
    if ((BUMBLE_SIGNUP)); then
      while [[ -z "$BUMBLE_PROFILE_NAME" ]]; do
        prompt_value BUMBLE_PROFILE_NAME 'Bumble profile first name' || return 1
      done
      while :; do
        prompt_value BUMBLE_PROFILE_GENDER 'Bumble gender (Woman / Man / Nonbinary)' || return 1
        case "$BUMBLE_PROFILE_GENDER" in
          Woman|woman|1) BUMBLE_PROFILE_GENDER=Woman; break ;;
          Man|man|2) BUMBLE_PROFILE_GENDER=Man; break ;;
          Nonbinary|nonbinary|3) BUMBLE_PROFILE_GENDER=Nonbinary; break ;;
          *) printf '   Choose Woman, Man or Nonbinary.\n' ;;
        esac
      done
      printf '   Four supplied photos will be selected randomly; the phone number is asked at Bumble phone entry.\n'
    fi
    printf '   Samsung identity, battery drift, modem signal, sensor labels, file aliases,\n   graphics labels, checker and root isolation are enabled unless disabled by flags.\n'
  fi
  validate_options
}
