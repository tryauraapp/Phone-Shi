# VPS V2 port status

## Ready in this folder

- self-contained control panel and image-variant helper
- Linux Android SDK discovery (`$ANDROID_SDK_ROOT`, then `~/Android/Sdk`)
- KVM/nested-virtualization preflight
- Ubuntu dependency and Android 15 x86-64 SDK installer
- persistent systemd services
- private Xvfb/noVNC viewer reachable through an SSH tunnel
- external state and secrets under `/var/lib/phone-shi` and `/etc/phone-shi`

## Must be validated on the purchased VPS

- creation and boot of a fresh x86-64 AVD
- rootAVD compatibility with the exact Android 15 x86-64 image
- any host-emulator binary transformation (the Mac implementation is ARM64
  Mach-O specific and cannot be reused)
- the renderer workaround and live camera texture motion
- realistic RAM/CPU concurrency under the selected machine type

Until those checks pass, the VPS control panel is deployable, but the full Mac
phone setup is not certified on Linux. This is intentional fail-closed
behavior, not a silent partial migration.
