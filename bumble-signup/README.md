# Interactive Bumble onboarding

`../bumble_signup.py` resumes the currently visible screen on an existing AVD;
it never clears app data. Creation invokes it after installation and diagnostics
when Bumble is installed and an interactive terminal is available. Read the
[root README](../README.md) for prerequisites and [SETUP.md](../SETUP.md) for the
full setup flow and options.

## Inputs and behavior

- Creation installs Bumble from Google Play by default. Supply at least four
  photos in `photos/`. No personal photos or camera video is published.
- Review `profile-defaults.json`. The checked-in birthday and profile choices
  are examples; name/gender are separate arguments or prompts.
- Phone number and SMS code are requested only at their respective screens,
  using hidden terminal input. Phone entry keeps the existing +1 country code
  and fills only the national number, without opening the country selector.
  They are held in memory. At the SMS prompt,
  `/mac` reads a six-digit code from the Mac clipboard; empty input tries the
  device clipboard. The helper never requests a replacement SMS automatically.
- Five interests and two distinct prompt questions/answers are selected. The
  catalog has 52 mapped questions and three answers per question. Optional
  height, habits, family plans, beliefs, marketing and passkey steps are skipped.
- Four selected photos are staged and uploaded. Existing uploaded photos are
  retained; an ambiguous library requires manual selection.
- Precise location and notification permissions are checked before completion.
- The default endpoint follows Profile → Complete Profile → Verification →
  Get photo verified and stops at **Open camera**. Capture/submission and any
  identity verification remain manual. Set `verification` to `false` to stop
  before **Start connecting** instead. No swipes or messages are automated.

## Resume

To install Bumble through Google Play instead of a local
APK/XAPK, run this from the repository root:

```sh
python3 play_store_install.py --serial emulator-5554 --avd YOUR_AVD_NAME --sign-in
```

The helper opens Bumble's exact listing, taps **Install**, dismisses the optional
Play Pass offer with **Not now**, and waits for both Android's installed-package
record and the enabled **Open** control. It verifies Google Play as the installer,
taps **Open**, and checks that Bumble reaches the foreground. Unknown prompts
stop for manual handling. `--sign-in` handles the observed Google login screens
with private terminal prompts; omit it when already signed in. Phone creation
runs this helper after the rooted profile is active and keeps the existing
Bumble signup steps afterward.

The optional **Sign in with ease** carrier-discovery screen is dismissed with
**SKIP**. The observed Google account setup used **Sign in** → email → **Next** → password
→ **Next** → **I will be using this device** → **Next** → **I agree**. Optional
recovery information was skipped with **Cancel**, home address with **Skip**,
and Google services completed with basic device backup off, **MORE** → **ACCEPT**.
Account-specific security checks may add screens to this flow.

```sh
python3 bumble_signup.py --serial emulator-5554 --avd YOUR_AVD_NAME \
  --output .local/signup-status --profile-name Alex --profile-gender Woman
```

Run from the repository root. Confirm both serial and AVD name first. The
helper requires Android-validated internet and can reconnect only the emulator's
open `AndroidWifi` access point. Use `emulator_proxy.py` to launch with the
configured host proxy; this signup helper does not change proxy routing.

Unknown screens and errors pause for manual handling. Enter retries inspection;
`/quit` or Ctrl-C stops while retaining the phone. Unsupported non-ASCII text
can be entered manually. Status output contains elapsed time; error screenshots
may include visible personal data and should remain in an ignored directory.

## UI evidence and maintenance

Sanitized recorded screen hierarchies live in
`tests/fixtures/bumble-signup/`, including the later native profile and interest
picker layouts under `live-20261022/`. They preserve UI structure and labels
while replacing account identifiers with examples. Historical live captures,
raw XML dumps, logs and personal screenshots remain local and ignored by Git.

The recordings cover the observed Android app UI around version 5.488.0. They
are regression evidence, not a promise that a future version or region has the
same screens. Update screen recognition and fixtures together when the app
changes. The tests do not create an account, submit an SMS or verify a selfie.

For prompt mapping, see [prompt-picker/README.md](prompt-picker/README.md).
