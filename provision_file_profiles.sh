#!/bin/bash
# Sourced by setup after rooting and before the first identity reboot.
if ((FILE_ALIASES)); then
  step "Preparing per-device file aliases and vendor config overlay"
  mkdir -p "$WORK/file-aliases/input"
  while IFS= read -r path; do
    # Several HAL libraries are not readable by the adb shell UID. Stage a
    # root-owned copy, as with the sensor HAL, rather than changing vendor modes.
    dsu "set -e
cp /$path /data/local/tmp/s25-alias-original
chmod 644 /data/local/tmp/s25-alias-original" >>"$LOG" 2>&1 || die "Cannot stage $path."
    adb -s "$SERIAL" pull /data/local/tmp/s25-alias-original "$WORK/file-aliases/input/${path##*/}" >>"$LOG" 2>&1 || die "Cannot retrieve $path."
  done < <(python3 - "$SCRIPT_DIR" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from build_file_aliases import BINARY_PATHS
print('\n'.join(BINARY_PATHS))
PY
  )
  python3 -I "$SCRIPT_DIR/build_file_aliases.py" --input-dir "$WORK/file-aliases/input" --output-dir "$WORK/file-aliases" >>"$LOG" 2>&1 || die "Unrecognized vendor binaries; file fixture was not installed."
  # Keep the previously tested Android-35 metadata policy separate from the
  # config overlay. Only non-app domains regain qemu_device getattr access.
  python3 - "$SCRIPT_DIR" "$WORK/file-aliases/metadata.zip" <<'PY'
from pathlib import Path
import sys, zipfile
with zipfile.ZipFile(sys.argv[2], 'x', zipfile.ZIP_DEFLATED) as archive:
    archive.writestr('module.prop', 'id=s25_qemu_metadata\nname=S25 lab QEMU metadata fixture\nversion=1\nversionCode=1\nauthor=EMU Lab\ndescription=Android-35 app metadata visibility fixture\n')
    archive.write(Path(sys.argv[1])/'fixtures/qemu-metadata.rules', 'sepolicy.rule')
PY
  [[ $? == 0 ]] || die "Could not package metadata policy."
  adb -s "$SERIAL" push "$WORK/file-aliases/metadata.zip" /data/local/tmp/s25-metadata.zip >>"$LOG" 2>&1 || die "Cannot copy metadata policy."
  dsu 'magisk --install-module /data/local/tmp/s25-metadata.zip' >>"$LOG" 2>&1 || die "Metadata policy installation failed."
  adb -s "$SERIAL" push "$WORK/file-aliases/payload" /data/local/tmp/s25-alias-payload >>"$LOG" 2>&1 || die "Cannot copy file-alias payload."
  adb -s "$SERIAL" push "$SCRIPT_DIR/device_prepare_file_aliases.sh" /data/local/tmp/s25-prepare-aliases.sh >>"$LOG" 2>&1 || die "Cannot copy preparation helper."
  adb -s "$SERIAL" push "$SCRIPT_DIR/device_file_aliases.sh" /data/local/tmp/s25-file-aliases.sh >>"$LOG" 2>&1 || die "Cannot copy boot helper."
  dsu 'set -e
D=/data/adb/s25-avd-lab/file-aliases
mkdir -p "$D" /data/adb/post-fs-data.d
cp -a /data/local/tmp/s25-alias-payload "$D/payload"
sh /data/local/tmp/s25-prepare-aliases.sh
cp /data/local/tmp/s25-file-aliases.sh /data/adb/post-fs-data.d/98-s25-file-aliases.sh
chmod 755 /data/adb/post-fs-data.d/98-s25-file-aliases.sh
rm -rf /data/local/tmp/s25-alias-payload
rm -f /data/local/tmp/s25-prepare-aliases.sh /data/local/tmp/s25-file-aliases.sh /data/local/tmp/s25-metadata.zip /data/local/tmp/s25-alias-original' >>"$LOG" 2>&1 || die "File-alias installation failed."
  ok "Seven vendor binaries and private config overlay prepared for the next boot"
fi

if ((GRAPHICS_LABELS)); then
  step "Building per-device graphics label fixture"
  mkdir -p "$WORK/graphics/input"
  adb -s "$SERIAL" pull /vendor/lib64/egl/libGLESv2_emulation.so "$WORK/graphics/input/libGLESv2_emulation.so" >>"$LOG" 2>&1 || die "Cannot retrieve GLES backend."
  adb -s "$SERIAL" pull /apex/com.android.runtime/lib64/bionic/libdl.so "$WORK/graphics/input/libdl.so" >>"$LOG" 2>&1 || die "Cannot retrieve libdl."
  bash "$SCRIPT_DIR/graphics-profile/build.sh" "$WORK/graphics/input" "$WORK/graphics/build" >>"$LOG" 2>&1 || die "Graphics fixture build failed."
  for library in libGLESv2_backend.so libGLESv2_emulation.so; do
    adb -s "$SERIAL" push "$WORK/graphics/build/$library" "/data/local/tmp/$library" >>"$LOG" 2>&1 || die "Cannot copy $library."
  done
  dsu 'set -e
D=/data/adb/s25-avd-lab/file-aliases
cp -a /vendor/lib64/egl "$D/renderer-egl"
# Android cp -a does not preserve SELinux labels on these copies. The bind
# exposes the directory and every library to vendor/system processes, so clone
# their attributes explicitly before enabling it.
magisk --clone-attr /vendor/lib64/egl "$D/renderer-egl"
for original in /vendor/lib64/egl/*; do
  [ ! -f "$original" ] || magisk --clone-attr "$original" "$D/renderer-egl/${original##*/}"
done
for library in libGLESv2_backend.so libGLESv2_emulation.so; do
  cp "/data/local/tmp/$library" "$D/renderer-egl/$library"
  magisk --clone-attr /vendor/lib64/egl/libGLESv2_emulation.so "$D/renderer-egl/$library"
  rm -f "/data/local/tmp/$library"
done
touch "$D/renderer.enabled"' >>"$LOG" 2>&1 || die "Graphics fixture installation failed."
  ok "Qualcomm / Adreno 830 labels prepared; rendering uses the existing backend"
fi
