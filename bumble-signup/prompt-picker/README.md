# Prompt picker catalog

Mapped from the running Bumble Android prompt picker on 2026-10-22.
Every category was opened and its question list scrolled until the visible
questions stopped changing. Horizontal category navigation was inspected
separately from vertical question navigation.

| Category | Questions | Answer options |
| --- | ---: | ---: |
| Date night | 9 | 27 |
| Looking for | 8 | 24 |
| About me | 9 | 27 |
| Real talk | 10 | 30 |
| Bit of fun | 12 | 36 |
| Self-care | 4 | 12 |
| Total | 52 | 156 |

`catalog.json` contains exact question text and category names. Sanitized numbered XML
files in `../../tests/fixtures/bumble-signup/prompt-picker/` preserve the
observed picker pages used by regression tests. `../prompt-pool.json` has three
distinct answers per question; runtime validation requires complete coverage
and answers of at most 160 ASCII characters for the existing ADB text input.
Questions retain their original Unicode punctuation for exact UI matching.

`../prompt-pool-legacy.json` is used only to recognize answers saved by earlier
script versions. New choices always come from the current catalog.
The catalog describes this observed app version and locale, not every possible
regional or future Bumble prompt set. Remap it if Bumble changes its picker.
