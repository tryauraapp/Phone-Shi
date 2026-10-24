# Plenty of Fish signup capture

This directory documents the POF 5.70.1.1516767 onboarding observed on a fresh
Android 15 Galaxy S25 test AVD. The private raw screenshots and UI dumps stay in
the per-device backup directory and are not source-controlled.

The recorded path contains 74 captures: notification permission, welcome,
first name, gender and visibility, ethnicity, location explanation and Android
permission, location details, birthday, credentials and terms, Google Password
Manager, account-created confirmation, seeking gender, dating preferences,
about-you details, lifestyle, family, headline, bio, conversation topic,
interests, phone verification, SMS code, the full required photo-guidelines
page, its Add photo/Take photo source chooser, Android picker, crop/upload
states for five supplied images, optional selfie verification, the success
interstitial, the full community Pledge, Prestige offer, filters tip, and main
feed landing state.

Five images explicitly supplied for this profile were hash-verified, selected,
cropped, and uploaded. Optional selfie verification was skipped. After explicit
authorization, the community Pledge was accepted, the Prestige purchase was
declined with **Continue as free**, and the flow reached the main feed. No
CAPTCHA, face/video check, or identity-verification step was automated. Do not
use generated, stock, or third-party portraits; only use media the account
owner supplied and is authorized to use.

Inspect the current screen and save a sanitized snapshot:

```sh
python3 pof_signup.py --serial emulator-5554 --avd YOUR_AVD \
  --output .local/pof/screens
```

The guarded runner can apply only explicitly authorized notification and
foreground-location permissions:

```sh
python3 pof_signup.py --serial emulator-5554 --avd YOUR_AVD \
  --output .local/pof/screens --run-signup \
  --allow-notifications --allow-location \
  --accept-pledge --continue-as-free --dismiss-filters-tip
```

It pauses at every unmapped profile choice and at credentials, terms, phone,
SMS, photo, CAPTCHA, or identity-verification screens. Pledge acceptance is
available only through the explicit `--accept-pledge` flag. The free-account
path never starts a purchase. The helper does not launch or stop the app, retry
rejected codes, or automate a human-verification challenge. Snapshot XML keeps
reviewed labels and structural data only; edit-field values and unknown text
are removed.

