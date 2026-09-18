# Import Review

Target layer: `amateur-radio-repeaters-es`. Classification is independent of Geo Hub validation: a valid geometry is not sufficient when a source conflict remains unresolved.

| pilot row | callsign | rx_frequency_mhz | classification | reason |
| ---: | --- | ---: | --- | --- |
| 1 | EA6VHF | 144.426 | IMPORT_READY | Exact URE Point geometry; callsign, receive frequency and row provenance are present; no unresolved conflict. |
| 2 | EA7JYO | 439.65 | NOT_IMPORTABLE | RadioID-only record has intentionally null geometry. |
| 3 | EA7JYO | 439.65 | NOT_IMPORTABLE | RadioID-only record has intentionally null geometry. |
| 4 | EC2E | 439.35 | IMPORT_READY | Exact URE Point geometry; required identity and provenance are present; no unresolved conflict. |
| 5 | ED1YAB | 145.725 | IMPORT_READY | Exact URE Point geometry; required identity and provenance are present; no unresolved conflict. |
| 6 | ED1YAZ | 145.675 | IMPORT_READY | Exact URE Point geometry; required identity and provenance are present; no unresolved conflict. |
| 7 | ED1YBQ | 29.68 | IMPORT_READY | Exact URE Point geometry; required identity and provenance are present; no unresolved conflict. |
| 8 | ED1ZBG | 145.7125 | IMPORT_READY | Exact URE Point geometry; required identity and provenance are present; no unresolved conflict. |
| 9 | ED1ZBG_C | 145.6375 | IMPORT_READY | Exact URE Point geometry; required identity and provenance are present; no unresolved conflict. |
| 10 | ED1ZBJ | 438.225 | IMPORT_READY | Exact URE Point geometry; required identity and URE provenance are present. RadioID color-code/network enrichment is explicitly retained in `notes`. |
| 11 | ED2ZAB | 145.775 | IMPORT_READY | Exact URE Point geometry; required identity and provenance are present; no unresolved conflict. |
| 12 | ED3YAI | 51.9 | IMPORT_READY | Exact URE Point geometry; required identity and provenance are present; no unresolved conflict. |
| 13 | ED3YAK | 145.65 | IMPORT_READY | Exact URE Point geometry; required identity and provenance are present; no unresolved conflict. |
| 14 | ED3ZAN | 145.5875 | IMPORT_READY | Exact URE Point geometry; required identity and URE provenance are present. RadioID color-code/network enrichment is explicitly retained in `notes`. |
| 15 | ED4YAE | 1298.5 | IMPORT_READY | Exact URE Point geometry; required identity and provenance are present; no unresolved conflict. |
| 16 | ED4YAG | 144.8 | IMPORT_READY | Exact URE Point geometry; required identity and provenance are present; no unresolved conflict. |
| 17 | ED4YAW | 51.95 | IMPORT_READY | Exact URE Point geometry; required identity and provenance are present; no unresolved conflict. |
| 18 | ED4ZAG | 438.3 | NEEDS_REVIEW | Exact Point geometry, but `offset_mhz` conflicts between URE and RadioID; manual decision required. |
| 19 | ED5ZAC | 145.6875 | IMPORT_READY | Exact URE Point geometry; required identity and provenance are present; no unresolved conflict. |
| 20 | ED5ZAC | 1298.5 | IMPORT_READY | Exact URE Point geometry; separate same-callsign service with its own receive frequency and provenance; no unresolved conflict. |
| 21 | ED6ZAC | 145.625 | IMPORT_READY | Exact URE Point geometry; required identity and provenance are present; no unresolved conflict. |
| 22 | ED7YAM | 51.81 | IMPORT_READY | Exact URE Point geometry; required identity and provenance are present; no unresolved conflict. |
| 23 | ED7YAU | 144.8 | IMPORT_READY | Exact URE Point geometry; required identity and provenance are present; no unresolved conflict. |
| 24 | ED7ZAL | 438.425 | IMPORT_READY | Exact URE Point geometry; required identity and URE provenance are present. RadioID color-code/network enrichment is explicitly retained in `notes`. |
| 25 | ED7ZAM | 438.5 | NEEDS_REVIEW | Exact Point geometry, but URE reports C4FM and RadioID reports DMR; manual decision required. |
| 26 | ED8YAB | 439 | IMPORT_READY | Exact URE Point geometry; required identity and provenance are present; no unresolved conflict. |
| 27 | ED9YAB | 438.675 | IMPORT_READY | Exact URE Point geometry; required identity and provenance are present; no unresolved conflict. |

## Totals

| classification | rows |
| --- | ---: |
| IMPORT_READY | 23 |
| NEEDS_REVIEW | 2 |
| NOT_IMPORTABLE | 2 |

## Unresolved conflicts

| callsign | rx_frequency_mhz | conflicting field | URE value | RadioID value | source authority | recommended_resolution | confidence | status |
| --- | ---: | --- | --- | --- | --- | --- | --- | --- |
| ED4ZAG | 438.3 | offset_mhz | -0.0076 (literal normalization of published `-7.600 kHz`) | -7.6 MHz | URE owns published operating parameters; RadioID owns DMR color code/network, not an unambiguous offset correction | manual_review | high | NEEDS_REVIEW |
| ED7ZAM | 438.5 | modes | C4FM | DMR | Neither source has a clearly superior current-mode claim | manual_review | medium | NEEDS_REVIEW |

No authority rule is applied to select either disputed value. These two records are excluded from the candidate CSV pending a human decision.

## Candidate provenance

`amateur-radio-repeaters-es-import-ready.csv` retains per-row `source_name`, `source_url`, and `source_record_id` as import properties. URE remains the primary provenance for its rows. For ED1ZBJ, ED3ZAN, and ED7ZAL, `notes` identifies `dmr_color_code` and `dmr_network` as RadioID-derived secondary enrichment; this does not attribute those fields to URE.

## Geo Hub staging

Staged through `POST /api/v1/admin/imports` with the CSV mapping below. Import ID: `e90502f1-cc56-4bb6-ae7e-88acb94e7cba`. It remains `validated`; no row resolution or commit was called.

| metric | count |
| --- | ---: |
| candidate CSV rows | 23 |
| staged rows | 23 |
| valid rows | 23 |
| invalid rows | 0 |
| duplicate candidates | 0 |
| resolved candidates | 0 |
| unresolved candidates | 0 |

The mapping uses `longitude`, `latitude`, and `source_record_id` as the CSV coordinate and external-ID columns. Every remaining column, including `callsign`, `rx_frequency_mhz`, `source_name`, `source_url`, and `source_record_id`, is retained as a property.

### Duplicate evaluation

No Geo Hub duplicate candidate was generated, so there are no `TRUE_DUPLICATE`, `FALSE_POSITIVE`, or `UNCLEAR` assessments to make.

The only existing features are the two published demos:

| feature ID | callsign | assessment |
| --- | --- | --- |
| c5b19e6c-0e47-4c57-90e1-bb00f1e10001 | DEMO-EA4 | No candidate match: no exact callsign and the nearest Madrid candidate (ED4YAG) is about 4 km away, exceeding 300 m. |
| c5b19e6c-0e47-4c57-90e1-bb00f1e10002 | DEMO-EA3 | No candidate match: no exact callsign and the nearest Barcelona candidate (ED3YAK) is about 4.7 km away, exceeding 300 m. |

For this sample, the configured exact-callsign or 300 m proximity rule behaves as expected against the demo data.

### Schema friction

The current CSV importer stores CSV properties as strings: numeric optional properties, `modes` (serialized JSON text), and missing optional values arrive as strings or empty strings rather than typed JSON numbers, arrays, or `null`. Geometry coordinates are correctly numeric. This staging is valid, but a typed-property import would require a GeoJSON flow or importer enhancement; neither was changed here.
