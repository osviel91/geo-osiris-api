# CONFLICTS — amateur-radio-repeaters-es (full Spain, Phase 5C)

No conflict is silently resolved. Every entry is traceable to its sources. Allowed resolutions: `prefer_ure`, `prefer_radioid`, `manual_review`.

## 1. URE ↔ RadioID conflicts (22)

| Callsign | rx MHz | Field | source_a | value_a | source_b | value_b | Resolution | Conf. | Rationale |
|---|---|---|---|---|---|---|---|---|---|
| ED1YBW | 145.725 | offset_mhz | URE repeater and beacon listings | -0.6 | RadioID.net DMR repeater API | -7.6 | manual_review | high | URE publishes a kHz unit while RadioID publishes an MHz offset; retain the literal normalized URE value until the site operator confirms the unit. |
| ED1YBW | 145.725 | modes | URE repeater and beacon listings | FM | RadioID.net DMR repeater API | DMR | manual_review | medium | URE and RadioID assert different operating modes for the same callsign and published frequency; neither source has a clearly superior claim for current mode. |
| ED2YAP | 145.65 | modes | URE repeater and beacon listings | FM | RadioID.net DMR repeater API | DMR | manual_review | medium | URE and RadioID assert different operating modes for the same callsign and published frequency; neither source has a clearly superior claim for current mode. |
| ED2YAQ | 145.775 | modes | URE repeater and beacon listings | FM | RadioID.net DMR repeater API | DMR | manual_review | medium | URE and RadioID assert different operating modes for the same callsign and published frequency; neither source has a clearly superior claim for current mode. |
| ED3YBB | 145.75 | modes | URE repeater and beacon listings | FM | RadioID.net DMR repeater API | DMR | manual_review | medium | URE and RadioID assert different operating modes for the same callsign and published frequency; neither source has a clearly superior claim for current mode. |
| ED5YAT | 145.625 | offset_mhz | URE repeater and beacon listings | -0.6 | RadioID.net DMR repeater API | 0.6 | manual_review | high | URE publishes a kHz unit while RadioID publishes an MHz offset; retain the literal normalized URE value until the site operator confirms the unit. |
| ED5YAT | 145.625 | modes | URE repeater and beacon listings | FM | RadioID.net DMR repeater API | DMR | manual_review | medium | URE and RadioID assert different operating modes for the same callsign and published frequency; neither source has a clearly superior claim for current mode. |
| ED1YBM | 439.3 | modes | URE repeater and beacon listings | FM | RadioID.net DMR repeater API | DMR | manual_review | medium | URE and RadioID assert different operating modes for the same callsign and published frequency; neither source has a clearly superior claim for current mode. |
| ED1ZAK | 438.65 | offset_mhz | URE repeater and beacon listings | -7.6 | RadioID.net DMR repeater API | 7.6 | manual_review | high | URE publishes a kHz unit while RadioID publishes an MHz offset; retain the literal normalized URE value until the site operator confirms the unit. |
| ED1ZAK | 438.65 | modes | URE repeater and beacon listings | FM | RadioID.net DMR repeater API | DMR | manual_review | medium | URE and RadioID assert different operating modes for the same callsign and published frequency; neither source has a clearly superior claim for current mode. |
| ED3YAC | 438.8 | modes | URE repeater and beacon listings | FM | RadioID.net DMR repeater API | DMR | manual_review | medium | URE and RadioID assert different operating modes for the same callsign and published frequency; neither source has a clearly superior claim for current mode. |
| ED3YAD | 438.975 | modes | URE repeater and beacon listings | FM | RadioID.net DMR repeater API | DMR | manual_review | medium | URE and RadioID assert different operating modes for the same callsign and published frequency; neither source has a clearly superior claim for current mode. |
| ED3YAI | 439.375 | modes | URE repeater and beacon listings | FM | RadioID.net DMR repeater API | DMR | manual_review | medium | URE and RadioID assert different operating modes for the same callsign and published frequency; neither source has a clearly superior claim for current mode. |
| ED3YAV | 438.75 | offset_mhz | URE repeater and beacon listings | -7.6 | RadioID.net DMR repeater API | 0.0 | manual_review | high | URE publishes a kHz unit while RadioID publishes an MHz offset; retain the literal normalized URE value until the site operator confirms the unit. |
| ED3YAV | 438.75 | modes | URE repeater and beacon listings | FM | RadioID.net DMR repeater API | DMR | manual_review | medium | URE and RadioID assert different operating modes for the same callsign and published frequency; neither source has a clearly superior claim for current mode. |
| ED3YBC | 438.7 | modes | URE repeater and beacon listings | FM | RadioID.net DMR repeater API | DMR | manual_review | medium | URE and RadioID assert different operating modes for the same callsign and published frequency; neither source has a clearly superior claim for current mode. |
| ED4ZAG | 438.3 | offset_mhz | URE repeater and beacon listings | -0.0076 | RadioID.net DMR repeater API | -7.6 | manual_review | high | URE publishes a kHz unit while RadioID publishes an MHz offset; retain the literal normalized URE value until the site operator confirms the unit. |
| ED4ZAH | 438.325 | offset_mhz | URE repeater and beacon listings | -0.0076 | RadioID.net DMR repeater API | -7.6 | manual_review | high | URE publishes a kHz unit while RadioID publishes an MHz offset; retain the literal normalized URE value until the site operator confirms the unit. |
| ED6ZAB | 438.45 | modes | URE repeater and beacon listings | D-Star,FM | RadioID.net DMR repeater API | DMR | manual_review | medium | URE and RadioID assert different operating modes for the same callsign and published frequency; neither source has a clearly superior claim for current mode. |
| ED7YAU | 439.35 | modes | URE repeater and beacon listings | FM | RadioID.net DMR repeater API | DMR | manual_review | medium | URE and RadioID assert different operating modes for the same callsign and published frequency; neither source has a clearly superior claim for current mode. |
| ED7ZAE | 438.3 | modes | URE repeater and beacon listings | D-Star | RadioID.net DMR repeater API | DMR | manual_review | medium | URE and RadioID assert different operating modes for the same callsign and published frequency; neither source has a clearly superior claim for current mode. |
| ED7ZAM | 438.5 | modes | URE repeater and beacon listings | C4FM | RadioID.net DMR repeater API | DMR | manual_review | medium | URE and RadioID assert different operating modes for the same callsign and published frequency; neither source has a clearly superior claim for current mode. |

## 2. URE internal unit anomaly (5)

| Callsign | rx MHz | Field | value_a | source_b | value_b | Resolution | Rationale |
|---|---|---|---|---|---|---|---|
| ED4ZAG | 438.3 | offset_mhz | -0.0076 | URE 70 cm band convention | -7.6 | manual_review | URE publishes the offset in kHz on this row (literal normalized value -0.0076), which is inconsistent with the Spanish 70 cm standard -7.6 MHz offset used on every other 432 MHz entry; treated as a source unit anomaly pending confirmation. |
| ED4ZAH | 438.35 | offset_mhz | -0.0076 | URE 70 cm band convention | -7.6 | manual_review | URE publishes the offset in kHz on this row (literal normalized value -0.0076), which is inconsistent with the Spanish 70 cm standard -7.6 MHz offset used on every other 432 MHz entry; treated as a source unit anomaly pending confirmation. |
| ED4ZAH | 438.325 | offset_mhz | -0.0076 | URE 70 cm band convention | -7.6 | manual_review | URE publishes the offset in kHz on this row (literal normalized value -0.0076), which is inconsistent with the Spanish 70 cm standard -7.6 MHz offset used on every other 432 MHz entry; treated as a source unit anomaly pending confirmation. |
| ED4ZAH | 438.375 | offset_mhz | -0.0076 | URE 70 cm band convention | -7.6 | manual_review | URE publishes the offset in kHz on this row (literal normalized value -0.0076), which is inconsistent with the Spanish 70 cm standard -7.6 MHz offset used on every other 432 MHz entry; treated as a source unit anomaly pending confirmation. |
| ED4ZAL | 438.475 | offset_mhz | -0.0076 | URE 70 cm band convention | -7.6 | manual_review | URE publishes the offset in kHz on this row (literal normalized value -0.0076), which is inconsistent with the Spanish 70 cm standard -7.6 MHz offset used on every other 432 MHz entry; treated as a source unit anomaly pending confirmation. |

## 3. Internal source duplicates

### URE

None. Every URE callsign+frequency pair is unique in the retrieved endpoints.

### RadioID

Exact duplicates were collapsed to one canonical record while retaining all `identity_id` values; ambiguous groups remain flagged.

| Callsign | rx MHz | Class | identity_ids |
|---|---|---|---|
| EA7JYO | 439.65 | EXACT_SOURCE_DUPLICATE | 650, 651, 653 |
| ED3YBK | 145.575 | EXACT_SOURCE_DUPLICATE | 668, 669 |
| ED7ZAI | 439.0 | LIKELY_SAME_SERVICE | 17559, 795 |
| ED1ZAW | 438.4 | LIKELY_SAME_SERVICE | 17582, 676 |
| ED1ZBH | 438.575 | EXACT_SOURCE_DUPLICATE | 682, 688 |
| ED3ZAS | 438.5 | EXACT_SOURCE_DUPLICATE | 741, 748 |

## 4. Production-vs-new-source conflicts

None. No canonical row materially disagrees with a currently published feature; non-material completeness differences are listed in IMPORT-REVIEW.md.


## 5. Pilot-vs-current-source (published features)

- **ED1YAB 145.725** — SOURCE_UPDATED: Fresh source has more or different field values.
- **ED5ZAC 145.6875** — SOURCE_UPDATED: Fresh source has more or different field values.
- **ED6ZAC 145.625** — SOURCE_UPDATED: Fresh source has more or different field values.
- **ED2ZAB 145.775** — SOURCE_UPDATED: Fresh source has more or different field values.
- **ED9YAB 438.675** — SOURCE_UPDATED: Fresh source has more or different field values.
- **ED5ZAC 1298.5** — SOURCE_UPDATED: Fresh source has more or different field values.
- **EC2E 439.35** — SOURCE_UPDATED: Fresh source has more or different field values.
- **DEMO-EA4 None** — MISSING_FROM_CURRENT_SOURCE: Placeholder demo feature, not a source record.
- **DEMO-EA3 None** — MISSING_FROM_CURRENT_SOURCE: Placeholder demo feature, not a source record.
- **ED8YAB 439.0** — SOURCE_UPDATED: Fresh source has more or different field values.
- **EA6VHF 144.426** — SOURCE_UPDATED: Fresh source has more or different field values.

