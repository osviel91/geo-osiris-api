# Source Notes

## Principal sources

- **URE repeater and beacon listings**: `https://www.ure.es/repetidores/`. Individual records are parsed from the linked `repe*_N.php` and `balizas*_N.php` Leaflet marker payloads. URE supplies the published callsign, frequency, offset, mode, CTCSS where listed, Maidenhead locator, operator text and exact site coordinates.
- **RadioID.net DMR repeater API**: `https://radioid.net/api/dmr/repeater/?country=Spain`. It supplies DMR color code/network enrichment and two intentionally coordinate-less sample rows. `identity_id` is retained as `source_record_id`.
- RepeaterBook was not used: its Spain export requires authorization.

## Retrieval and normalization

- Retrieval date: `2026-09-13`.
- URE requests use `Referer: https://www.ure.es/repetidores/` and `X-Requested-With: XMLHttpRequest`; numeric commas are normalized to decimal points.
- `rx_frequency_mhz` is the frequency published in the source listing. URE does not explicitly label a receive/transmit direction, so `tx_frequency_mhz` remains null rather than inferred from offset.
- Logical research identity is `callsign + rx_frequency_mhz`; records sharing either component are retained separately.
- URE is the principal source for URE rows. RadioID enrichment is named in each applicable row's `notes`; it is not represented as URE-provided data.

## Derived administrative areas

For each URE coordinate, municipality, province and autonomous region were derived with OpenStreetMap Nominatim, not supplied by URE. Each applicable row says: `Administrative areas derived from exact URE site coordinates using OpenStreetMap Nominatim.`

- Endpoint: `https://nominatim.openstreetmap.org/reverse`
- Retrieval date: `2026-09-13`
- User-Agent: `OSIRIS-Geo-API-Phase5A/1.0 (+https://github.com/osviel91/geo-osiris-api)`
- Request policy: one request per second for uncached coordinates.
- Cache: JSON responses are cached in the transient local build directory `/var/folders/1y/v3_ww26x61l3nh_qxsx1wnc40000gn/T/opencode/phase5a-cache` by coordinate, so a rerun does not repeat successful reverse-geocoding calls.
- Directionality: exact URE site coordinate -> Nominatim -> administrative fields only. RadioID city names were never geocoded into repeater points.

## Geometry and import readiness

The two unmatched RadioID records intentionally have `latitude`, `longitude` and GeoJSON `geometry` set to null. They remain in this research dataset with an explicit note but are not import-ready for the current managed Point import path.
