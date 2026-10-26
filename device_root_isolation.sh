#!/system/bin/sh
# Magisk mount isolation for one installed lab app; requires root.
# Does not hide every root signal or change a remote integrity verdict.
set -e
package=${1:-}
case "$package" in ''|*[!a-zA-Z0-9._]*) echo 'Invalid package name' >&2; exit 2 ;; esac
[ "$(id -u)" = 0 ] || { echo 'Root required' >&2; exit 1; }
pm path "$package" | grep -q '^package:' || { echo "Not installed: $package" >&2; exit 1; }
# DenyList entries alone left su/debug_ramdisk visible on this Android-35
# image. Built-in Zygisk activates the per-process unmount path at app start.
# The host must reboot once after configuring all packages.
magisk --sqlite "INSERT OR REPLACE INTO settings (key,value) VALUES ('zygisk',1)" >/dev/null
magisk --sqlite "SELECT value FROM settings WHERE key='zygisk'" | grep -qx 'value=1'
add_process() {
  if ! magisk --denylist ls | grep -qxF "$package|$1"; then
    magisk --denylist add "$package" "$1"
  fi
}
add_process "$package"
# Register known secondary processes before their first launch. Discovering only
# running processes misses these on a freshly provisioned AVD.
case "$package" in
  com.bumble.app) add_process "$package:light" ;;
  com.eltavine.duckdetector)
    add_process "$package:helper_probe"
    add_process "$package:zygisk_fd_detector"
    ;;
esac
ps -A -o NAME | while IFS= read -r process; do
  case "$process" in "$package":*) add_process "$process" ;; esac
done
magisk --denylist enable
magisk --denylist status
am force-stop "$package"
magisk --denylist ls | grep -F "$package|"
echo 'Zygisk enabled; reboot required before verifying app-visible mounts'
