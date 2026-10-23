# Device Red Flags

A local Android diagnostic app installed as `dev.emulab.devicecheck`, with the launcher label **Device Red Flags**. It runs as an ordinary app, never requests `su`, and has no Internet permission. It checks its own app-visible environment; it cannot reproduce Bumble's proprietary logic or predict account acceptance.

Build offline with the installed SDK and Java 17:

Install build tools `36.0.0` and `platforms;android-35` first. The build prefers
API 35, falls back to the newest installed numeric API 35+ platform, and accepts
an explicit `ANDROID_JAR=/path/to/android.jar` override. The SDK is resolved
from `ANDROID_SDK_ROOT`, `ANDROID_HOME`, then `~/Library/Android/sdk`.

```sh
bash device-checker/build.sh
adb -s emulator-5554 install -r device-checker/DeviceRedFlags.apk
adb -s emulator-5554 shell am start -n dev.emulab.devicecheck/.MainActivity
```

Use **Scan again** after making changes. **Copy report** copies evidence and explanations. Each scan also saves `latest-report.json` under the app's external files directory, readable over ADB:

```sh
adb -s emulator-5554 pull /sdcard/Android/data/dev.emulab.devicecheck/files/latest-report.json
```

The signing key in `.signing/` is for this local lab only and is ignored by Git. Keep it to update the installed APK with the same signature.

## Evidence and limitations

- [Bumble's privacy policy](https://bumble.com/privacy-policy/en-us) describes collection of device model, OS, identifiers, log data and usage data. It does not publish a reproducible emulator-detection algorithm.
- [OWASP emulator detection](https://mas.owasp.org/MASTG-KNOW-0031/) documents build characteristics, emulator files, graphics and related heuristics.
- [OWASP root detection](https://mas.owasp.org/MASTG-KNOW-0027/) documents root binaries, root-manager package checks and the limits of those techniques.
- [Google Play Integrity](https://developer.android.com/google/play/integrity/overview) is a separate service. This APK has no Play/Cloud/backend integration and reports it as **not tested**.
- [PackageInfo.firstInstallTime](https://developer.android.com/reference/android/content/pm/PackageInfo#firstInstallTime) is the installation timestamp of an individual package. It is not the device's first-ever installation or setup date.

Red flags are observations, not a probability or independent proof of emulation. Weak signals have legitimate explanations on real devices. Missing data is unknown. A stable battery reading over twelve seconds is not scored; health enum `GOOD` is not a wear-percentage measurement. Storage fragmentation is not used as a device-age detector.

Magisk mount isolation is per app. The checker was added to the same enforced DenyList as Bumble for the saved comparison. In that configuration it stopped observing the tested root binaries, while other emulator indicators remained visible. This does not establish what Bumble's different process, permissions, native checks or backend can observe.
