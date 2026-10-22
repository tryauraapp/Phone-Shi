#!/system/bin/sh
# Run once while the original vendor paths are still available. Requires root.
set -e
D=/data/adb/s25-avd-lab/file-aliases
[ ! -e "$D/prepared" ] || { echo 'File-alias fixture already prepared' >&2; exit 1; }
umask 077
mkdir -p "$D/private"
cp /vendor/etc/fstab.ranchu "$D/private/fstab.ranchu"
cp /vendor/etc/init/hw/init.ranchu.rc "$D/private/init.ranchu.rc"
magisk --clone-attr /vendor/etc/fstab.ranchu "$D/private/fstab.ranchu"
magisk --clone-attr /vendor/etc/init/hw/init.ranchu.rc "$D/private/init.ranchu.rc"
cp -a /vendor/etc "$D/vendor-etc"
# Copy SELinux attributes explicitly, including directories and non-symlink files.
find /vendor/etc -type d -o -type f | while IFS= read -r original; do
  relative=${original#/vendor/etc}
  magisk --clone-attr "$original" "$D/vendor-etc$relative"
done
rm -f "$D/vendor-etc/fstab.ranchu" "$D/vendor-etc/init/hw/init.ranchu.rc"
ln -s "$D/private/fstab.ranchu" "$D/vendor-etc/fstab.ranchu"
ln -s "$D/private/init.ranchu.rc" "$D/vendor-etc/init/hw/init.ranchu.rc"
find "$D/payload/vendor" -type f | while IFS= read -r patched; do
  original=/${patched#"$D/payload/"}
  magisk --clone-attr "$original" "$patched"
done
touch "$D/prepared"
echo 'File aliases prepared; reboot required to apply before graphics starts'
