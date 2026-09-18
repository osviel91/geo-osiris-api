# IMPORT-REVIEW — amateur-radio-repeaters-es (full Spain, Phase 5C)

Read-only research output for review. Retrieval date **2026-09-13**. Nothing here has been staged, imported, committed or published.

## Overall counts

| Metric | Count |
|---|---|
| Raw URE records | 290 |
| Raw RadioID records | 167 |
| Normalized canonical rows | 416 |
| URE-derived rows (exact geometry) | 290 |
| RadioID-only rows (null geometry) | 126 |
| URE↔RadioID exact callsign+frequency matches | 34 |
| RadioID DMR enrichments applied to URE rows | 18 |
| URE internal duplicates | 0 |
| RadioID internal duplicate groups | 6 |
| Conflicts (all categories) | 27 |
| IMPORT_READY | 268 |
| NEEDS_REVIEW | 21 |
| NOT_IMPORTABLE | 127 |

## Comparison with current Geo Hub production layer

Read-only snapshot of the 25 published features; no production data was modified.

| vs_production | Canonical rows |
|---|---|
| NEW | 393 |
| ALREADY_PRESENT | 23 |
| CONFLICT_WITH_EXISTING | 0 |

### Existing 25 published features

| Classification | Count |
|---|---|
| UNCHANGED | 14 |
| SOURCE_UPDATED | 9 |
| CONFLICT | 0 |
| MISSING_FROM_CURRENT_SOURCE | 2 |

Field differences on SOURCE_UPDATED published features (fresh vs published; non-material — no value was silently chosen):

| Callsign | rx MHz | Differences |
|---|---|---|
| ED1YAB | 145.725 | autonomous_region: published='Autonomous Community of the Basque Country' fresh='Basque Country' |
| ED5ZAC | 145.6875 | province: published='Alacant / Alicante' fresh='Alicante' |
| ED6ZAC | 145.625 | province: published='Balearic Islands' fresh='Illes Balears' |
| ED2ZAB | 145.775 | autonomous_region: published='Autonomous Community of the Basque Country' fresh='Basque Country' |
| ED9YAB | 438.675 | dmr_color_code: published=None fresh=1; dmr_network: published=None fresh='DMR-plus' |
| ED5ZAC | 1298.5 | province: published='Alacant / Alicante' fresh='Alicante' |
| EC2E | 439.35 | province: published=None fresh='Navarra' |
| ED8YAB | 439.0 | ctcss_hz: published=None fresh=79.7 |
| EA6VHF | 144.426 | province: published='Balearic Islands' fresh='Illes Balears' |

## Records requiring human attention

### NEEDS_REVIEW (unresolved material conflict)

| Callsign | rx MHz | Field(s) | Sources | Recommended action |
|---|---|---|---|---|
| ED1YBM | 439.3 | modes | URE vs RadioID.net DMR repeater API | Manual review; do not import until resolved |
| ED1YBW | 145.725 | modes, offset_mhz | URE vs RadioID.net DMR repeater API | Manual review; do not import until resolved |
| ED1ZAK | 438.65 | modes, offset_mhz | URE vs RadioID.net DMR repeater API | Manual review; do not import until resolved |
| ED2YAP | 145.65 | modes | URE vs RadioID.net DMR repeater API | Manual review; do not import until resolved |
| ED2YAQ | 145.775 | modes | URE vs RadioID.net DMR repeater API | Manual review; do not import until resolved |
| ED3YAC | 438.8 | modes | URE vs RadioID.net DMR repeater API | Manual review; do not import until resolved |
| ED3YAD | 438.975 | modes | URE vs RadioID.net DMR repeater API | Manual review; do not import until resolved |
| ED3YAI | 439.375 | modes | URE vs RadioID.net DMR repeater API | Manual review; do not import until resolved |
| ED3YAV | 438.75 | modes, offset_mhz | URE vs RadioID.net DMR repeater API | Manual review; do not import until resolved |
| ED3YBB | 145.75 | modes | URE vs RadioID.net DMR repeater API | Manual review; do not import until resolved |
| ED3YBC | 438.7 | modes | URE vs RadioID.net DMR repeater API | Manual review; do not import until resolved |
| ED4ZAG | 438.3 | offset_mhz | URE vs RadioID.net DMR repeater API, URE 70 cm band convention | Manual review; do not import until resolved |
| ED4ZAH | 438.325 | offset_mhz | URE vs RadioID.net DMR repeater API, URE 70 cm band convention | Manual review; do not import until resolved |
| ED4ZAH | 438.35 | offset_mhz | URE vs URE 70 cm band convention | Manual review; do not import until resolved |
| ED4ZAH | 438.375 | offset_mhz | URE vs URE 70 cm band convention | Manual review; do not import until resolved |
| ED4ZAL | 438.475 | offset_mhz | URE vs URE 70 cm band convention | Manual review; do not import until resolved |
| ED5YAT | 145.625 | modes, offset_mhz | URE vs RadioID.net DMR repeater API | Manual review; do not import until resolved |
| ED6ZAB | 438.45 | modes | URE vs RadioID.net DMR repeater API | Manual review; do not import until resolved |
| ED7YAU | 439.35 | modes | URE vs RadioID.net DMR repeater API | Manual review; do not import until resolved |
| ED7ZAE | 438.3 | modes | URE vs RadioID.net DMR repeater API | Manual review; do not import until resolved |
| ED7ZAM | 438.5 | modes | URE vs RadioID.net DMR repeater API | Manual review; do not import until resolved |

### Previously excluded records re-evaluated

- **ED4ZAG 438.3 MHz** — fresh retrieval: NEEDS_REVIEW. Conflicts: offset_mhz URE=-0.0076 vs RadioID.net DMR repeater API=-7.6; offset_mhz URE=-0.0076 vs URE 70 cm band convention=-7.6. Remains excluded pending human resolution.
- **ED7ZAM 438.5 MHz** — fresh retrieval: NEEDS_REVIEW. Conflicts: modes URE='C4FM' vs RadioID.net DMR repeater API='DMR'. Remains excluded pending human resolution.
- **RadioID-only null-geometry records** — 126 records (e.g. EA7JYO 439.65 MHz) still have no authoritative exact site coordinate; all are NOT_IMPORTABLE.

### NOT_IMPORTABLE summary

| Reason | Count |
|---|---|
| RadioID-only, no exact geometry | 126 |
| Missing required identity (no rx frequency) | 1 |
