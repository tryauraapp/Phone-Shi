#!/bin/bash
# Build the per-app emulator-hide Zygisk module (arm64-v8a) with Apple clang +
# SDK lld, linking against device libc/liblog stubs — the same no-NDK toolchain
# as graphics-profile/build.sh.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
SDK="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/Library/Android/sdk}}"
BT="$SDK/build-tools/36.0.0"
OUT="$ROOT/build"
IN="$ROOT/input"
mkdir -p "$OUT" "$ROOT/module/zygisk"

# Device stubs are required to resolve libc/liblog imports at link time.
for lib in libc.so liblog.so; do
  if [[ ! -f "$IN/$lib" ]]; then
    SERIAL=${SERIAL:-$(adb devices | awk 'NR>1 && $1 ~ /^emulator-/ {print $1; exit}')}
    [[ -n "$SERIAL" ]] || { echo "Need $IN/$lib (no device to pull from)"; exit 1; }
    adb -s "$SERIAL" pull "/system/lib64/$lib" "$IN/$lib" >/dev/null
  fi
done

clang --target=aarch64-linux-android35 -std=c++17 -O2 -fPIC \
  -fvisibility=hidden -fno-exceptions -fno-rtti -fno-threadsafe-statics \
  -fno-stack-protector -ffunction-sections -fdata-sections \
  -I "$ROOT/jni" -c "$ROOT/jni/hide.cpp" -o "$OUT/hide.o"

"$BT/lld" -flavor gnu -shared -z noexecstack -z relro -z now \
  -z max-page-size=16384 --gc-sections --hash-style=both \
  --soname=libemuhide.so -o "$ROOT/module/zygisk/arm64-v8a.so" \
  "$OUT/hide.o" "$IN/libc.so" "$IN/liblog.so"

printf 'Built Zygisk module: %s (%s bytes)\n' \
  "$ROOT/module/zygisk/arm64-v8a.so" \
  "$(wc -c < "$ROOT/module/zygisk/arm64-v8a.so" | tr -d ' ')"
