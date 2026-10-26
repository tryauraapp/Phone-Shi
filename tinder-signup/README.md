# Tinder onboarding screen map

This includes a guarded runner for the recorded signup path plus individual
screen handlers. Only screens seen on the actual test device are mapped. Bumble
state is retained.

| Observed screen | Recorded behavior |
| --- | --- |
| Android notification permission | Optional decline with `--decline-notifications` |
| Tinder welcome, terms and login choices | Pause for method choice and terms confirmation |
| Google number hint | Recognized; dismiss manually to avoid using simulated SIM number |
| US +1 phone entry | `--enter-phone` privately retrieves, fills, and verifies the number; does not tap Next |
| Six-digit SMS code | `--enter-code` retrieves the code privately, checks read-back, then submits Next; stops if the screen changes |
| Invalid SMS code | Recognized rejection; stops without retrying or requesting another SMS |
| Welcome / House Rules | Pause for explicit user agreement; `--agree-house-rules` is a separate opt-in action |
| First name | `--enter-name` privately prompts for the user-supplied name, verifies it, then taps Next; never invents a name |
| Personalized profile welcome | `--start-profile` taps the observed “Let’s go”; personalized greeting is excluded from saved fixtures |
| Birth date | `--enter-birth-date` privately prompts for the actual adult DOB (YYYY-MM-DD), fills observed MM/DD/YYYY fields, verifies all eight digits, then taps Next; never invents a date |
| Gender | `--select-gender Woman --gender-visibility show` applies explicit choices, verifies visibility, and taps enabled Next; no randomization |
| Discovery preference | Runner defaults to Men for Woman, Women for Man as configured for this workflow; override with `--signup-interested-in`; selection is verified |
| Distance preference | Runner defaults to the observed maximum, 100 Mi, and verifies it before Next; `--signup-distance default` keeps 50 Mi |
| Education | Selects and verifies Prefer Not to Say, then continues |
| Relationship goals | `--relationship-goal` selects an authorized option through its accessibility label, then enabled Next |
| School | Recognized by static labels and school-title ID; optional skip without inventing a school |
| Lifestyle habits | Runner randomly selects one reviewed answer for each of drinking, smoking, exercise and pets; requires the counter to advance from 0/4 to 4/4 |
| Personality / basics | Supports recorded three/four-question variants and verifies each counter increment; education is a separate privacy choice in the new layout |
| Interests | Runner selects three distinct reviewed visible interests, verifies each counter, and preserves reviewed selected chips on resume |
| Add recent photos | `--open-photo-picker` opens first empty slot; onboarding Next remains a manual stop boundary |
| Android photo picker | `--pick-photo-index` plus repeated `--photo` paths require an exact library hash match before selecting; `--confirm-four-photos` requires exactly four selections and Add (4) |
| Edit photos | `--finish-photo-edit` taps Done only in the observed four-photo editor, never onboarding Next |
| Photo-page Next | `--continue-photos` is a separate explicit opt-in after four added photos; it is not part of photo upload automation |
| Bio and prompt | Records the optional intro choices; `--skip-optional` skips without inventing text |
| Location explanation | `--allow-location-rationale` taps exact Allow only on the reviewed Tinder explanation screen, after authorization |
| Android location permission | `--allow-foreground-location` selects While using the app only for Tinder's exact permission dialog; precision stays unchanged, no background grant |
| Google Location Accuracy / Wi-Fi scanning | `--decline-wifi-scanning` declines the separate device-wide opt-in, preserving app location authorization and existing system settings |
| Temporary account lock / video selfie | Manual hard stop: record the suspicious-activity lock and hidden-profile message; never tap Get verified, retry signup or attempt a bypass |
| Any other screen | Stop without tapping; inspect and add evidence first |

```sh
python3 play_store_install.py --app tinder --serial emulator-5554 --avd YOUR_AVD
python3 tinder_signup.py --serial emulator-5554 --avd YOUR_AVD --output .local/tinder/screens
```

To run the recorded flow, explicitly supply every consent/choice and the exact
four-photo library. The phone number, SMS code, first name, and birth date are
requested through hidden interactive prompts and are not written to fixtures:

Add `--use-google-email` to use **Sign in with Google** on the observed
**Your email?** screen after SMS. The runner selects the single signed-in Google
account on the Tinder-specific chooser. Multiple accounts require a manual
choice. Account identifiers are omitted from fixtures. Google security checks
and unfamiliar consent screens remain manual. The observed single-account path
advances directly to House Rules without a separate consent screen.
Both recorded gender layouts are supported, including the newer parent-gender
rows. The optional sexual-orientation page is skipped; no orientation is chosen
or displayed by the runner.

The signup runner defaults to the maximum observed distance of **100 Mi**.
`--signup-distance default` retains 50 Mi instead. This workflow defaults to
Men when gender is Woman and Women when gender is Man; an explicit
`--signup-interested-in` overrides it. Education uses **Prefer Not to Say**.
Recorded Compose trait buttons, three/four-question personality layouts,
interests whose subtitle changes to selected chips, and empty photo-picker
selection markers are supported. Three interests are selected to enable Next.

`--allow-location-accuracy` separately authorizes Google's **Turn on** action,
including Wi-Fi scanning inside the emulator. Without it the runner declines;
if Tinder then refuses location access, it stops and explains the required flag.
The observed location error permits one retry when location is authorized.
The observed **This is awkward** connection error permits one retry only when
Android reports validated cellular Internet, then stops if the error persists.

```sh
python3 tinder_signup.py \
  --serial emulator-5554 \
  --avd YOUR_AVD \
  --output .local/tinder/screens \
  --run-signup \
  --accept-terms \
  --accept-sms-terms \
  --accept-house-rules \
  --decline-notifications \
  --signup-gender Woman \
  --signup-gender-visibility show \
  --signup-relationship-goal 'Still figuring it out' \
  --allow-location \
  --photo /absolute/path/one.jpg \
  --photo /absolute/path/two.jpg \
  --photo /absolute/path/three.jpg \
  --photo /absolute/path/four.jpg
```

The runner is resumable: invoke the same command again after an ordinary manual
pause. It stops without interacting whenever it sees a CAPTCHA, robot/human
check, face/photo/video verification, an invalid SMS code, an unknown screen,
or the recorded locked-account video-selfie screen. It never taps **Get
verified**, never attempts to solve or bypass a challenge, and never retries a
rejected verification code. A manual-stop exit uses status 2.

Lifestyle and personality questions are single-choice: the runner chooses one
answer from each reviewed option group. Interests are multi-choice: it chooses
three distinct visible options. Every selection must increment Tinder's
displayed counter exactly; a partial, preselected, or changed layout is a hard
stop. The same bounded behavior is available for the current screen with
`--randomize-profile-traits`.

The observer and runner never launch/stop apps, restart the emulator, or solve
CAPTCHA challenges. Standalone `--enter-phone` does not submit; the runner submits
phone Next only with `--accept-sms-terms`, while `--enter-code` submits the supplied
SMS code. XML artifacts retain reviewed
static labels and layout only; edit values and unknown text are omitted. Live
progress is implemented only for the mapped actions above. `--skip-optional` is
restricted to reviewed school, lifestyle, personality, interests and bio/prompt
screens. Unknown screens always stop.

During this screen-mapping session, the authorized path selected “Still figuring
it out” and skipped the optional school, habits, basics and interests questions.
After additional upload authorization, all four earlier supplied photos were
hash-verified against the existing emulator library, selected in Android's
picker, and accepted using the photo editor's Done control. The main onboarding
screen displayed four added photos; its enabled Next was deliberately not tapped.
No final account/publication control was
tapped; this does not guarantee Tinder has not already saved intermediate data.

Following subsequent authorization to continue, photo-page Next was tapped,
bio/prompt was skipped, and location was granted while using Tinder. Precision
was left unchanged, and the separate device-wide Wi-Fi scanning opt-in was
declined. Tinder then displayed a temporary suspicious-activity lock, stated
that the profile is hidden, and required a video selfie. The session stopped
without tapping Get verified. This confirms there is account state on Tinder;
it is not a local-only mock. The UI does not identify the cause of the lock.

`CredentialsProvider` separates number/code retrieval from UI automation.
`ManualCredentials` uses hidden prompts. A future API implementation can supply
the same methods; no API endpoint or provider credentials are configured yet.
Phone entry sends its value to ADB through stdin and excludes it from fixtures.
On the US +1 screen, enter the ten national digits; optional `1` or `+1`
prefixes, spaces, parentheses and hyphens are also accepted. The script keeps
the displayed country code and fills only the national number.
