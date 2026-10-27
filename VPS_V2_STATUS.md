# VPS V2 port status

## Ready in this folder

- self-contained control panel and image-variant helper
- Linux Android SDK discovery (`$ANDROID_SDK_ROOT`, then `~/Android/Sdk`)
- KVM/nested-virtualization preflight
- Ubuntu dependency and Android 15 x86-64 SDK installer
- persistent systemd services
- private Xvfb/noVNC viewer reachable through an SSH tunnel
- external state and secrets under `/var/lib/phone-shi` and `/etc/phone-shi`

## Validated on the purchased VPS

- Linux x86-64 host, nested KVM access and Android SDK availability
- Android 15 Google Play x86-64 system image
- CRM provisioning queue and persistent job-state API

## Still validated per newly created phone

- first boot of the freshly created x86-64 AVD
- NodeMaven city/carrier exit and proxy-derived runtime state
- the renderer workaround and live Camera2 texture motion
- selected Google Play package installation
- realistic RAM/CPU concurrency under the selected machine type

The worker stops at the Google Play checkpoint and certifies only after its
per-phone checks pass. The Mac ARM64 Samsung/root transformations are not
relabelled as Linux support; VPS certificates describe the actual Google
x86-64 emulator identity. This is intentional fail-closed behavior, not a
silent partial migration.
