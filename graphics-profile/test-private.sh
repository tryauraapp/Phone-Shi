#!/system/bin/sh
set -e
# Caller creates a new mount namespace. Make it private before any test mounts.
/data/adb/magisk/busybox mount --make-rprivate /
mount --bind /data/adb/s25-avd-lab/file-aliases/renderer-egl /vendor/lib64/egl
CLASSPATH=/data/local/tmp/s25-gpu-probe.dex app_process /system/bin GpuProbe
