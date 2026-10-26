# Duck Detector audit — 2026-10-23

Inspected the running `emulator-5554` with Duck Detector
`2026.10.23-a7afa02a6239` (1069). Exported its full report from the app UI.
Raw reports remain private in `.local/duck-audit/before.txt`,
`after-isolation.txt`, and `after.txt`; these contain device-specific data.

## Changes applied and verified

- Added `com.eltavine.duckdetector` to the setup script's optional root-isolation
  packages. It is skipped when absent, rather than downloaded automatically.
- Applied the existing isolation helper to the live app, including the running
  `:helper_probe` and `:zygisk_fd_detector` processes. Enforcement is enabled.
- Removed the file-alias payload's temporary self-bind after constructing the
  vendor binds. The vendor mounts retain their flags and file references.
- Updated the live boot helper, retaining its original copy at
  `/data/adb/s25-avd-lab/file-aliases/boot-helper-before-duck.sh`.
- Rebooted and verified that the staging mount stays absent, vendor config and
  EGL mounts remain present, shell root works, and the sensor service still
  exposes 12 Samsung-labelled hardware sensors.
- Shell syntax checks and all 17 `test_lab.py` tests passed. The full fresh-AVD
  creation workflow was not rerun.

## Results

The intermediate direct MainActivity launch reported 4 danger / 5 warning / 20
ready, but bypassed Duck's NativeActivity launcher. It is not the final result.
The final scan used the actual launcher after reboot, with fresh startup preload:
**5 danger / 4 warning / 20 ready / 0 pending**. These are Duck's own counters;
they should not be interpreted as a complete count of every exported card.

| Finding | Original scan | Final normal-launch scan |
| --- | --- | --- |
| SU | `/system_ext/bin/su` visible | No longer a danger finding |
| Mount | 19 critical signals; Magisk/module/staging mounts | 1 startup observation; main mounts and mountinfo have no direct root artifacts |
| Bootloader | Unlocked; software attestation; 6 critical signals | Unchanged |
| TEE | Hardware-backed local verification not established | Unchanged |
| Virtualization | 8 direct signals | 8 direct signals |
| SELinux | Warning; Magisk contexts and dirty policy | Danger; privileged contexts still recognized |
| ADB Runtime | Warning: debugging active | Unchanged |
| LSPosed | Warning: 2 dirty-policy signals | Unchanged; no direct LSPosed runtime evidence |
| Native Root | Warning: `/data/local/tmp` inode 196610 | Unchanged; indirect heuristic |
| System Properties | Warning: `persist.sys.usb.config=adb` | Unchanged |

The final Mount card is internally inconsistent: it labels one finding critical
and claims a direct root token, but its only listed observation is a startup peer
group gap with three unrepresented group IDs. The report itself says peer IDs
are global and need not be consecutive in the current namespace. Its Artifacts,
Runtime, and Filesystem sections are clean. Treat this as a detector scoring
issue to investigate, not proof that the removed staging mount remains present.

## Remaining evidence and limits

- Bootloader/TEE: attestation reports `Software`, `deviceLocked=false`,
  `verifiedBootState=Unverified`, and zero boot key/hash. A valid local certificate
  chain does not establish hardware-backed Samsung trust. No Play Integrity
  verdict was obtained. Property overrides do not supply a hardware root of trust.
- Virtualization: `ro.boot.hardware=ranchu`, the AVD-name boot property,
  `/dev/goldfish_pipe_dprctd` file descriptor, a mapped ranchu graphics mapper,
  and startup-preload observations. Existing display labels do not replace the
  emulator's driver implementation.
- SELinux/LSPosed: recognized `magisk`/`magisk_file` contexts,
  `system_server` execmem, and `untrusted_app -> magisk:binder call` allowed.
  Per-app filesystem isolation does not restore the global stock SELinux policy.
  The LSPosed warning does not demonstrate that LSPosed is installed.
- Native Root: an elevated tmp-directory inode alone does not establish root.
  Directory ownership/mode and other native checks were normal. Recreating or
  renumbering filesystem metadata merely to satisfy this heuristic is not a
  demonstrated repair.
- ADB and USB property warnings reflect the debugging connection used to manage
  this lab device. They were retained for continued device access.

The requested all-green state has **not** been achieved. The verified fixes are
persisted; genuine hardware attestation, stock root-free policy, and physical
Samsung drivers cannot be provided by these setup-script changes.

References: [Android key attestation](https://source.android.com/docs/security/features/keystore/attestation),
[Magisk CLI](https://github.com/topjohnwu/Magisk/blob/master/docs/tools.md).

## Live revalidation and fresh-provisioning fix

A subsequent normal NativeActivity launch produced **4 danger / 5 warning /
20 ready / 0 pending**. The complete export is saved privately as
`.local/duck-audit/revalidated.txt` (113,632 bytes). SELinux moved to warning;
its recognized Magisk contexts remain present. This score change is not evidence
that the underlying policy was repaired. Both normal-launch results are retained.

The isolation helper now registers Duck's `:helper_probe` and
`:zygisk_fd_detector` processes before their first launch. Previously those
entries depended on the processes already running when provisioning executed.
Bumble's existing `:light` registration remains. Applied the updated helper to
both installed apps and confirmed enforced entries for all five processes.
Zygisk was already active in this boot; this update did not require another
activation reboot. Future setup runs use this same helper.

### Complete flagged-card disposition

| Card | Latest severity | Evidence and disposition |
| --- | --- | --- |
| Bootloader | Danger | Six boot-integrity findings; software attestation says unlocked/unverified with zero boot hash/key. Property labels do not repair attested trust. |
| Mount | Danger | Startup peer-group gap remains. The card's direct-root-token headline is not substantiated by its detailed findings, as explained above. Separately, live Bumble mounts do expose overlay backing paths; see below. |
| TEE | Danger | Software tier, no hardware-backed local verification, StrongBox not advertised. Many deeper probes are skipped or unavailable. Requires a suitable hardware trust environment for genuine hardware attestation. |
| Virtualization | Danger | Eight signals: ranchu boot hardware, QEMU AVD-name metadata, goldfish pipe FD, ranchu mapper mapping, and early-launch observations. The current scripts deliberately preserve boot hardware/HAL selectors and use the AVD-name property for target verification. Changing those requires redesign and driver compatibility checks, and would not provide physical Samsung hardware. |
| ADB Runtime | Warning | ADB is enabled. Retained to manage the running lab device. A session with debugging disabled would require a separate access/recovery workflow. |
| LSPosed | Warning | Dirty-policy access results; package/bridge/runtime checks are clean. Does not demonstrate LSPosed installation. |
| Native Root | Warning | `/data/local/tmp` inode 196610 exceeds an app heuristic; other ownership/mode checks are normal. Not a demonstrated defect to repair by rewriting filesystem metadata. |
| SELinux | Warning | Enforcing; Magisk contexts recognized and modified access-policy signals remain. Removing active Magisk types/permissions arbitrarily could break root or services. No policy rewrite applied. |
| System Properties | Warning | `persist.sys.usb.config=adb`, consistent with the debugging connection. Retained with ADB. |

### Coverage beyond the nine flagged cards

- Custom ROM: reduced coverage; missing build observations are unknown.
- Dangerous Apps: no package matches, but behavioral checks are incomplete.
- Kernel Check: Duck reports an unpatched CVE-2024-43093 path-filter behavior.
  This is a separate security observation, not an emulator-identification result.
  Remediation would require a verified patched image/framework; the current
  binary fixtures target this fixed Android-35 image and were not migrated.
- Location Risk: no mismatch observed, but optional cached location and several
  synthetic contract probes were not observed. This is limited coverage.
- Network Risk: collected network/proxy context, without a clean-device guarantee.
- SU: no tested root indicators observed.
- Zygote heap residue: no target trace observed; coverage marked unknown.
- Memory, Play Integrity Fix residue, Root Managers, and Zygisk: clear for their
  tested checks. The Play Integrity Fix card does not obtain a Play Integrity
  verdict, and a clear Zygisk card does not mean Zygisk is disabled.

### Bumble verification and remaining mount evidence

Launched Bumble normally and inspected its main process mount table through
root. The saved `.local/duck-audit/bumble-verification.json` and corresponding
mountinfo capture show nine vendor overlay mounts with backing roots under
`/adb/s25-avd-lab/file-aliases/`. This is real remaining evidence of the lab
modifications, despite Duck's clean ordinary mount sections. The temporary
payload self-bind is absent; the required vendor binds remain. These are
different observations and should not be conflated.

Verified that the installed boot helper exactly matches `device_file_aliases.sh`.
The vendor overlay cleanup therefore applies system-wide, including Bumble;
the per-process isolation configuration also includes Bumble. No claim is made
that Bumble's native checks, remote integrity checks, or backend accept this
device. No account interactions were performed during this revalidation.

Validation: shell syntax checks passed for the setup, alias, and isolation
helpers; all 17 `test_lab.py` tests passed after the helper update. The complete
fresh-AVD creation flow was not rerun. The requested all-green state remains
unachieved; this audit records the residual findings rather than treating
isolation or altered labels as proof of a physical, stock device.
