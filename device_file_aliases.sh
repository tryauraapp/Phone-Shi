#!/system/bin/sh
# Boot-time aliases for the fixed Android-35 AVD image. No vendor image writes.
# Payload and config overlay live outside Magisk's module directory so the
# app-visible graphics libraries stay consistent with the renamed device nodes.
D=/data/adb/s25-avd-lab/file-aliases
[ ! -f /data/adb/s25-avd-lab/disabled ] && [ ! -f "$D/disabled" ] || exit 0
[ -f "$D/prepared" ] || exit 1
PATHS='vendor/lib64/egl/libEGL_emulation.so
vendor/lib64/hw/android.hardware.graphics.mapper@3.0-impl-ranchu.so
vendor/lib64/hw/vulkan.ranchu.so
vendor/lib64/libOpenglSystemCommon.so
vendor/lib64/libcodec2_goldfish_common.so
vendor/bin/hw/android.hardware.graphics.allocator@3.0-service.ranchu
vendor/bin/hw/android.hardware.graphics.composer3-service.ranchu'
mounted=
config_mounted=0
renderer_mounted=0
payload_mounted=0
complete=0
rollback() {
  set +e
  [ "$renderer_mounted" = 0 ] || umount /vendor/lib64/egl
  [ "$config_mounted" = 0 ] || umount /vendor/etc
  [ ! -e /dev/s25_address_space ] || [ -e /dev/goldfish_address_space ] || mv /dev/s25_address_space /dev/goldfish_address_space
  [ ! -e /dev/s25_gpu_sync ] || [ -e /dev/goldfish_sync ] || mv /dev/s25_gpu_sync /dev/goldfish_sync
  for target in $mounted; do umount "$target"; done
  [ "$payload_mounted" = 0 ] || umount "$D/payload"
}
trap '[ "$complete" = 1 ] || rollback' EXIT
set -e
for relative in $PATHS; do
  [ -f "$D/payload/$relative" ] && [ -f "/$relative" ]
done
for pair in goldfish_address_space:s25_address_space goldfish_sync:s25_gpu_sync; do
  old=${pair%:*}; new=${pair#*:}
  [ -c "/dev/$old" ] && [ ! -e "/dev/$new" ]
done
# Match the normal vendor executable semantics. Clear nosuid on this private
# payload bind before creating the shared vendor binds, so init's existing
# SELinux domain transitions remain available. No policy permissions are added.
mount --bind "$D/payload" "$D/payload"
payload_mounted=1
mount -o remount,bind,suid "$D/payload"
for relative in $PATHS; do
  mount --bind "$D/payload/$relative" "/$relative"
  mounted="/$relative $mounted"
done
mv /dev/goldfish_address_space /dev/s25_address_space
mv /dev/goldfish_sync /dev/s25_gpu_sync
mount --bind "$D/vendor-etc" /vendor/etc
config_mounted=1
if [ -f "$D/renderer.enabled" ]; then
  [ -f "$D/renderer-egl/libGLESv2_backend.so" ]
  [ -f "$D/renderer-egl/libGLESv2_emulation.so" ]
  mount --bind "$D/renderer-egl" /vendor/lib64/egl
  renderer_mounted=1
fi
# Each vendor bind retains its own mount flags and reference to the payload.
# The temporary self-bind is only needed while preparing those binds; leaving
# it mounted exposes an unnecessary /data/adb mount in every app namespace.
umount "$D/payload"
payload_mounted=0
complete=1
printf '%s file-aliases applied\n' "$(date '+%F %T')" >>/data/adb/s25-avd-lab/boot.log
