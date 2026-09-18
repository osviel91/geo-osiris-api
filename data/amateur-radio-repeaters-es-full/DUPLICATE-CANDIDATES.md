# DUPLICATE-CANDIDATES — amateur-radio-repeaters-es (Phase 5D)

Import `26276681-448a-4d6a-95f1-b9fb83962c47` (staged, uncommitted). Layer duplicate configuration under review: `identity_properties = ["callsign"]`, `coordinate_radius_m = 300`.

Identity model for this dataset is **callsign + rx_frequency_mhz**. A candidate raised on callsign alone (property_exact) and/or on proximity within 300 m is not a duplicate unless the receive frequency also matches.

## Summary

- Candidate rows: **11**
- Candidate feature matches: **16**
- TRUE_DUPLICATE: **0** · FALSE_POSITIVE: **16** · UNCLEAR: **0**
- No candidate shares the incoming receive frequency, so none is a true duplicate.
- Resolution intentionally deferred; no candidate resolved or committed.

## Candidate-by-candidate

| # | Incoming callsign | Incoming rx MHz | Existing feature | Existing rx MHz | Matching reasons | Distance (m) | Assessment |
|---|---|---|---|---|---|---|---|
| 1 | ED4YAE | 10368.862 | ED4YAE (49400e2d) | 1298.5 | property_exact, spatial_proximity | 0.0 | FALSE_POSITIVE |
| 2 | ED4YAE | 10368.862 | ED4YAW (95618558) | 51.95 | spatial_proximity | 0.0 | FALSE_POSITIVE |
| 3 | EA4URE-R | 145.2875 | ED4YAG (a4cfa492) | 144.8 | spatial_proximity | 3.0 | FALSE_POSITIVE |
| 4 | ED4YAE | 145.675 | ED4YAE (49400e2d) | 1298.5 | property_exact | 3623.4 | FALSE_POSITIVE |
| 5 | ED5YAC | 145.75 | ED5ZAC (49272859) | 145.6875 | spatial_proximity | 32.1 | FALSE_POSITIVE |
| 6 | ED5YAC | 145.75 | ED5ZAC (b40f2eba) | 1298.5 | spatial_proximity | 32.1 | FALSE_POSITIVE |
| 7 | ED1YAZ | 439.225 | ED1YAZ (902a1429) | 145.675 | property_exact, spatial_proximity | 51.4 | FALSE_POSITIVE |
| 8 | ED1YBL-R | 438.75 | ED1ZBG (126f2248) | 145.7125 | spatial_proximity | 38.5 | FALSE_POSITIVE |
| 9 | ED1YBL-R | 438.75 | ED1ZBG_C (590e1dec) | 145.6375 | spatial_proximity | 92.3 | FALSE_POSITIVE |
| 10 | ED1ZBG | 438.55 | ED1ZBG (126f2248) | 145.7125 | property_exact, spatial_proximity | 65.8 | FALSE_POSITIVE |
| 11 | ED1ZBG | 438.55 | ED1ZBG_C (590e1dec) | 145.6375 | spatial_proximity | 95.4 | FALSE_POSITIVE |
| 12 | ED3YAN | 439.125 | ED3YAK (baf6d467) | 145.65 | spatial_proximity | 36.8 | FALSE_POSITIVE |
| 13 | ED4YAW | 438.9 | ED4YAW (95618558) | 51.95 | property_exact | 3622.7 | FALSE_POSITIVE |
| 14 | ED5ZAC | 438.3 | ED5ZAC (49272859) | 145.6875 | property_exact, spatial_proximity | 0.0 | FALSE_POSITIVE |
| 15 | ED5ZAC | 438.3 | ED5ZAC (b40f2eba) | 1298.5 | property_exact, spatial_proximity | 0.0 | FALSE_POSITIVE |
| 16 | ED7YAM | 438.925 | ED7YAM (a1830c5b) | 51.81 | property_exact | 1105.7 | FALSE_POSITIVE |

## Why the callsign-only identity over-flags here

- Multi-band / multi-service callsigns: ED4YAE (10 GHz beacon vs 1.2 GHz repeater vs 2 m), ED1YAZ (2 m vs 70 cm), ED4YAW (6 m vs 70 cm), ED5ZAC (2 m vs 23 cm vs 70 cm), ED1ZBG (2 m C4FM vs 2 m D-Star vs 70 cm DMR), ED7YAM (6 m vs 70 cm) are distinct services sharing one callsign.
- Co-located distinct callsigns: EA4URE-R vs ED4YAG (3 m), ED5YAC vs ED5ZAC (32 m), ED1YBL-R vs ED1ZBG (38–95 m), ED3YAN vs ED3YAK (37 m) share a site but are separate stations.
- Seven flags use only spatial_proximity (distance ≤ 300 m); the remaining nine also use callsign property_exact. None uses a frequency match.
- The engine flagged these for human review only; it did not auto-merge. All should be resolved as `import_anyway` in Phase 5E.
