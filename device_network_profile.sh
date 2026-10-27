#!/system/bin/sh
# Persist cellular-only LTE settings and the reserved Wi-Fi MAC on each boot.
set -e
D=${S25_LAB_DIR:-/data/adb/s25-avd-lab}
[ ! -f "$D/disabled" ] && [ ! -f "$D/network.disabled" ] || exit 0
[ -f "$D/network.conf" ] || exit 1
. "$D/network.conf"
case "$WIFI_MAC" in 02:??:??:??:??:??) ;; *) exit 1 ;; esac
i=0
until [ "$(getprop sys.boot_completed)" = 1 ]; do
  i=$((i + 1)); [ "$i" -lt 300 ] || exit 1
  sleep 1
done
settings put global wifi_scan_always_enabled 0
settings put global wifi_on 0
svc wifi disable
svc data enable
# The Wi-Fi HAL can create wlan0 shortly after sys.boot_completed, even with
# Wi-Fi disabled. Wait briefly so its factory MAC does not appear after setup.
i=0
until ip link show wlan0 >/dev/null 2>&1; do
  i=$((i + 1)); [ "$i" -lt 20 ] || break
  sleep 0.5
done
# Apply to an existing, disabled interface. Never enable Wi-Fi to configure it.
if ip link show wlan0 >/dev/null 2>&1; then
  ip link set wlan0 down
  ip link set wlan0 address "$WIFI_MAC"
  [ "$(cat /sys/class/net/wlan0/address)" = "$WIFI_MAC" ] || exit 1
fi
i=0
while :; do
  result=$(cmd phone set-allowed-network-types-for-users -s 0 1000000000000 2>&1) || result=
  case "$result" in *completed*) break ;; esac
  i=$((i + 1)); [ "$i" -lt 30 ] || exit 1
  sleep 2
done
# Block UDP 443/80 (QUIC) so browsers and apps never bypass the TCP proxy via UDP.
iptables -C OUTPUT -p udp --dport 443 -j DROP 2>/dev/null || iptables -I OUTPUT -p udp --dport 443 -j DROP
iptables -C OUTPUT -p udp --dport 80 -j DROP 2>/dev/null || iptables -I OUTPUT -p udp --dport 80 -j DROP
printf '%s network-profile: LTE-only; Wi-Fi disabled; QUIC blocked\n' "$(date '+%F %T')" >>"$D/boot.log"
