#!/bin/bash
# Offline build using the installed Android SDK. No Gradle or downloads required.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
SDK="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/Library/Android/sdk}}"
TOOLS="$SDK/build-tools/36.0.0"
ANDROID_JAR="${ANDROID_JAR:-$SDK/platforms/android-37.0/android.jar}"
BUILD="$ROOT/build"
mkdir -p "$BUILD/classes" "$BUILD/dex" "$ROOT/.signing"
[[ -f "$ANDROID_JAR" ]] || { echo "Missing Android platform jar: $ANDROID_JAR" >&2; exit 1; }
javac --release 8 -classpath "$ANDROID_JAR" -d "$BUILD/classes" "$ROOT/src/dev/emulab/devicecheck/MainActivity.java"
jar cf "$BUILD/classes.jar" -C "$BUILD/classes" .
"$TOOLS/d8" --min-api 26 --lib "$ANDROID_JAR" --output "$BUILD/dex" "$BUILD/classes.jar"
"$TOOLS/aapt" package -f -M "$ROOT/AndroidManifest.xml" -S "$ROOT/res" -I "$ANDROID_JAR" -F "$BUILD/unsigned.apk"
cp "$BUILD/dex/classes.dex" "$BUILD/classes.dex"
(cd "$BUILD" && "$TOOLS/aapt" add unsigned.apk classes.dex)
"$TOOLS/zipalign" -f 4 "$BUILD/unsigned.apk" "$BUILD/aligned.apk"
if [[ ! -f "$ROOT/.signing/lab-checker.p12" ]]; then
  keytool -genkeypair -keystore "$ROOT/.signing/lab-checker.p12" -storetype PKCS12 -alias lab-checker \
    -storepass android-lab-only -keypass android-lab-only -keyalg RSA -keysize 2048 -validity 3650 \
    -dname 'CN=Local Device Lab, OU=Education, O=Local Lab, C=US'
fi
"$TOOLS/apksigner" sign --ks "$ROOT/.signing/lab-checker.p12" --ks-key-alias lab-checker \
  --ks-pass pass:android-lab-only --out "$ROOT/DeviceRedFlags.apk" "$BUILD/aligned.apk"
"$TOOLS/apksigner" verify "$ROOT/DeviceRedFlags.apk"
printf 'Built: %s\n' "$ROOT/DeviceRedFlags.apk"
