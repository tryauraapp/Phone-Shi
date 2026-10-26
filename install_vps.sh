#!/usr/bin/env bash
# Install Phone Shi V2 on an Ubuntu 22.04/24.04 x86-64 VPS with nested KVM.
set -euo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Run this installer with sudo." >&2
  exit 2
fi
if [[ $(uname -s) != Linux || $(uname -m) != x86_64 ]]; then
  echo "VPS V2 requires Linux x86-64." >&2
  exit 2
fi
if [[ ! -e /dev/kvm ]]; then
  echo "Missing /dev/kvm. Enable nested virtualization before installing." >&2
  exit 2
fi

SOURCE_DIR=$(cd "$(dirname "$0")" && pwd)
INSTALL_DIR=${PHONE_SHI_INSTALL_DIR:-/opt/phone-shi}
SDK=${ANDROID_SDK_ROOT:-/opt/android-sdk}
SERVICE_USER=${PHONE_SHI_USER:-phone-shi}

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  ca-certificates curl unzip git ffmpeg openjdk-17-jdk-headless python3 python3-pil \
  qemu-kvm cpu-checker libgl1 libpulse0 libx11-6 libxcomposite1 libxcursor1 \
  libxi6 libxrandr2 libxrender1 libxtst6 xvfb x11vnc novnc websockify fluxbox

id "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/phone-shi --shell /usr/sbin/nologin "$SERVICE_USER"
usermod -aG kvm "$SERVICE_USER"
install -d -m 0755 "$INSTALL_DIR" "$SDK" /etc/phone-shi
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0700 \
  /var/lib/phone-shi/.android/avd /var/lib/phone-shi/backups /var/lib/phone-shi/control-panel

# rsync deliberately excludes Git metadata and local/private Mac runtime state.
apt-get install -y --no-install-recommends rsync
rsync -a --delete --exclude .git --exclude .local --exclude control-panel/data \
  "$SOURCE_DIR/" "$INSTALL_DIR/"

if [[ ! -x "$SDK/cmdline-tools/latest/bin/sdkmanager" ]]; then
  if [[ -z ${ANDROID_CMDLINE_TOOLS_URL:-} ]]; then
    echo "Android command-line tools are not installed." >&2
    echo "Set ANDROID_CMDLINE_TOOLS_URL to Google's current Linux command-line-tools ZIP URL and rerun." >&2
    exit 3
  fi
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  curl --fail --location "$ANDROID_CMDLINE_TOOLS_URL" -o "$tmp/tools.zip"
  unzip -q "$tmp/tools.zip" -d "$tmp/unpacked"
  install -d "$SDK/cmdline-tools/latest"
  cp -a "$tmp/unpacked/cmdline-tools/." "$SDK/cmdline-tools/latest/"
fi

export ANDROID_SDK_ROOT="$SDK" ANDROID_HOME="$SDK"
yes | "$SDK/cmdline-tools/latest/bin/sdkmanager" --licenses >/dev/null || true
"$SDK/cmdline-tools/latest/bin/sdkmanager" \
  "platform-tools" "emulator" "platforms;android-35" \
  "system-images;android-35;google_apis_playstore;x86_64"
chown -R "$SERVICE_USER:$SERVICE_USER" "$SDK" "$INSTALL_DIR"

if [[ ! -f /etc/phone-shi/phone-shi.env ]]; then
  token=$(openssl rand -hex 32)
  sed "s/replace-with-a-long-random-token/$token/" "$INSTALL_DIR/.env.vps.example" \
    > /etc/phone-shi/phone-shi.env
  chmod 600 /etc/phone-shi/phone-shi.env
fi

install -m 0644 "$INSTALL_DIR/deploy/systemd/phone-shi-display.service" /etc/systemd/system/
install -m 0644 "$INSTALL_DIR/deploy/systemd/phone-shi-novnc.service" /etc/systemd/system/
install -m 0644 "$INSTALL_DIR/deploy/systemd/phone-shi-control.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now phone-shi-display phone-shi-novnc phone-shi-control

echo "Installed. Use SSH tunnels:"
echo "  ssh -L 8790:127.0.0.1:8790 -L 6080:127.0.0.1:6080 YOUR_VPS"
echo "Then open http://127.0.0.1:8790 and http://127.0.0.1:6080/vnc.html"
