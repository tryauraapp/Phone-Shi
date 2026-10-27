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
  printf '%s=%s\n' \
    ro.kernel.qemu "$(getprop ro.kernel.qemu)" \
    ro.boot.qemu "$(getprop ro.boot.qemu)" \
    ro.hardware "$(getprop ro.hardware)" \
    ro.hardware.egl "$(getprop ro.hardware.egl)" \
    ro.hardware.gralloc "$(getprop ro.hardware.gralloc)" \
    ro.boot.hardware "$(getprop ro.boot.hardware)" \
    >"$D/qemu.original"
fi
restore() {
  while IFS='=' read -r key value; do
    case "$key" in
      ro.kernel.qemu|ro.boot.qemu|ro.hardware|ro.hardware.egl|ro.hardware.gralloc|ro.boot.hardware)
        "$MAGISK" resetprop -n "$key" "$value"
        ;;
    esac
  done <"$D/qemu.original"
}
if [ "${1:-}" = --restore ]; then restore; exit $?; fi
if ! "$MAGISK" resetprop -n ro.kernel.qemu 0 || ! "$MAGISK" resetprop -n ro.boot.qemu 0; then
  restore; exit 1
fi
[ "$(getprop ro.kernel.qemu)" = 0 ] && [ "$(getprop ro.boot.qemu)" = 0 ] || { restore; exit 1; }
# Only override ro.hardware if it still exposes a ranchu/goldfish value.
if [ "$(getprop ro.hardware)" = ranchu ] || [ "$(getprop ro.hardware)" = goldfish ]; then
  "$MAGISK" resetprop -n ro.hardware pa1q || { restore; exit 1; }
fi
# The EGL loader checks persist.graphics.egl before ro.hardware.egl when picking
# the library to dlopen. Set it to the real emulation backend first so new
# Zygote forks still find libEGL_emulation.so after we change the visible prop.
setprop persist.graphics.egl emulation
if ! "$MAGISK" resetprop -n ro.hardware.egl adreno \
  || ! "$MAGISK" resetprop -n ro.hardware.gralloc default \
  || ! "$MAGISK" resetprop -n ro.boot.hardware pa1q; then
  restore; exit 1
fi
[ "$(getprop ro.hardware.egl)" = adreno ] \
  && [ "$(getprop ro.hardware.gralloc)" = default ] \
  && [ "$(getprop ro.boot.hardware)" = pa1q ] || { restore; exit 1; }
# NOTE: /dev/goldfish_pipe_dprctd is NOT an unused artifact — the guest GPU
# emulation encoder (libOpenglSystemCommon/libGLESv2_enc) opens it to reach the
# host renderer ("both vsock and goldfish_pipe paths failed"). Masking or
# bind-mounting over it breaks GL for every process that opens it after boot
# (black screen). Leave the node intact; it is not safely hidable from userspace.
printf '%s qemu-profile: kernel=0 boot=0 hw=pa1q egl=adreno gralloc=default\n' \
  "$(date '+%F %T')" >>"$D/boot.log"
