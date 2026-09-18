# SOURCE-NOTES — amateur-radio-repeaters-es (full Spain, Phase 5C)

Retrieval date: **2026-09-13**. Acquisition/normalization script: `work/build.py` sha256 `418b1f40f32c2d2d77bc55b950cd84480c7cff91cbcc432108a1d6c79403cf5e`.

## Primary source — URE (Union de Radioaficionados Espanoles)

Authority for callsign, exact site coordinates, published frequency, offset, mode, CTCSS, Maidenhead locator, operator/site text, and repeater/beacon classification.

- Landing page: https://www.ure.es/repetidores/
- Access: each band tab requests an XHR fragment via `onclick="javascript:p('/appure/repetidores/<file>.php')"`.
- Required headers: `User-Agent: Mozilla/5.0`, `Referer: https://www.ure.es/repetidores/`, `X-Requested-With: XMLHttpRequest` (without them the endpoint returns 7 bytes).

| Endpoint | Bytes |
|---|---|
| repe28_N.php | 4994 |
| repe50_N.php | 6368 |
| repe144_N.php | 286607 |
| repe432_N.php | 109698 |
| repe1200_N.php | 6338 |
| repeATV_N.php | 5168 |
| balizas28_N.php | 6236 |
| balizas50_N.php | 8168 |
| balizas144_N.php | 7550 |
| balizas432_N.php | 6173 |
| balizas1200_N.php | 5508 |
| balizas10000_N.php | 6222 |

- Extraction: regex over Leaflet marker declarations `L.marker([lat,lon],{icon:icono<X>,title:'<callsign>'}).bindPopup('<html>').addTo`; the popup `<span class=tipo2>` block is HTML-decoded and whitespace-collapsed.
- Number normalization: `145.712,5` → `145.7125`; `10368,862` → `10368.862`; `71,9` → `71.9`; GHz values ×1000 to MHz; offsets in kHz ×0.001 to MHz.
- Known limitations: source uses decimal commas; 5 rows publish a literal `-7.600 kHz` 70 cm offset (unit anomaly); the ATV row lists multiple input/output frequencies with no single receive frequency; 21 rows state no operating mode; direction (receive/transmit) is not labelled, so `tx_frequency_mhz` is always null rather than inferred.

## Secondary source — RadioID.net (DMR enrichment only)

- Endpoint: https://radioid.net/api/dmr/repeater/?country=Spain (public, no auth).
- Records retrieved: 167. Fields: callsign, city, color_code, ipsc_network, status, frequency, offset, state, identity_id. **No coordinates.**
- Authority: DMR color code and network/IPSC metadata only. RadioID is never used for site coordinates, and its city/state are used only as DMR-only research rows with null geometry.
- Network normalization: BM/BrandMeister/Brandmeister → BrandMeister; DMR-plus/'DMR +' → DMR-plus; tgif → TGIF.
- Enrichment is recorded in each row's `notes` with the RadioID identity_id; URE remains the principal source and is never made to look like the origin of DMR metadata.

- Not used: RepeaterBook (export API requires authorization) and BrandMeister API (no working public endpoint). Phase 5C does not depend on either.

## Derived fields — reverse geocoding

Municipality, province and autonomous region are **derived** from the exact URE site coordinate using OpenStreetMap Nominatim; URE does not supply them.
- Endpoint: `https://nominatim.openstreetmap.org/reverse?format=jsonv2&addressdetails=1&zoom=18`.
- Custom User-Agent: `OSIRIS-Geo-API-Phase5C/1.0 (+https://github.com/osviel91/geo-osiris-api)`.
- Rate limit: ≥1.05 s between uncached requests; responses cached under `work/nominatim/nominatim-<lat>-<lon>.json` (seeded from the Phase 5A cache).
- Municipality = first of municipality/city/town/village/hamlet/suburb. Province from the `ISO3166-2-lvl6` code; autonomous region from `ISO3166-2-lvl4`, falling back to the Nominatim `province`/`state` fields.
- Every geocoded row carries: "Administrative areas derived from exact URE site coordinates using OpenStreetMap Nominatim."

## Reproducibility

Raw responses are cached under `work/raw/`; re-running `work/build.py` reuses them and does not re-fetch unchanged endpoints. Final deliverables are written to the parent directory and are regenerated deterministically from the cache.

