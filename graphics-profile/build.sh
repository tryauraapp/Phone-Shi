#!/bin/bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
SDK="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/Library/Android/sdk}}"
INPUT=${1:-$ROOT/input}
OUT=${2:-$ROOT/build}
mkdir -p "$OUT"
python3 -I "$ROOT/rename_backend.py" "$INPUT/libGLESv2_emulation.so" "$OUT/libGLESv2_backend.so"
clang --target=aarch64-linux-android35 -O2 -fPIC -ffreestanding -fno-stack-protector -fvisibility=hidden \
  -c "$ROOT/renderer_labels.c" -o "$OUT/renderer_labels.o"
"$SDK/build-tools/36.0.0/lld" -flavor gnu -shared -z noexecstack -z relro -z now -z max-page-size=16384 \
  --soname=libGLESv2_emulation.so --enable-new-dtags -rpath '$ORIGIN' \
  --no-as-needed "$OUT/libGLESv2_backend.so" "$INPUT/libdl.so" "$OUT/renderer_labels.o" \
  -o "$OUT/libGLESv2_emulation.so"
printf 'Built renderer label wrapper: %s\n' "$OUT/libGLESv2_emulation.so"
