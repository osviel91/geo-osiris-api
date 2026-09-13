# Phase 4 production cutover runbook (PRE-CUTOVER VERIFIED, NOT YET EXECUTED)

Pre-cutover verification is complete (production confirmed unchanged). The
migration/deploy steps below are **not yet executed**. Do not run them until the
cutover gate passes.

## Image digests

| Component        | Previous (production, recorded)   | New (accepted commit)                      | New registry digest |
| ---------------- | --------------------------------- | ------------------------------------------ | ------------------- |
| geo-osiris-api   | `ghcr.io/osviel91/geo-osiris-api@sha256:aa6c0b719cf607880b9d04d6bbe1fa68e359922488089ede4a9c63b9c76b6b13` | `0ef6d4a03e88e2c398060bc7cf07f1c4df01b1b1` | `ghcr.io/osviel91/geo-osiris-api@sha256:f0beb308d20f63474ab2d5cd1821425d83f1b8ff04dd78c6bdcc1bb100da00e4` |
| geo-osiris-admin | (not deployed)                    | `0926b3677d93093c8b8b256088d613effbaca88b` | `ghcr.io/osviel91/geo-osiris-admin@sha256:4f8fdcbfcaf7c99d5f5174557701323746ed828deaa6be67851ca433c68f4210` |
| osiris           | `ghcr.io/osviel91/osiris@sha256:f39bccd0fe72b750bf8ca2b1a6ea4e6f947d1890b3e1673b967270e9f7a0d7c3` (tag `sha-5ca60d6`) | `a353dcec7602a2d0188bc2f76709f7787666a152` | `ghcr.io/osviel91/osiris@sha256:20ab071ef17529a589435bd8b2d73ff9093c2247b8ee8379787ca340d9ee39f5` |
| geo-osiris-postgis | `postgis/postgis@sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5` | (unchanged) | (unchanged) |

- The admin image was published from `4691dbe` (= accepted `0926b36` plus only
  `.github/workflows/publish.yml`); app content is identical.
- OSIRIS is a multi-arch index; the linux/amd64 manifest is
  `sha256:16d5dfa45e34438722a1dbbbca938ec7cd669ae6e24841d52f091169ad0e885c`.
- All three registry images are **linux/amd64**. Run them with
  `platform: linux/amd64` (as in `deploy/staging/compose.yml`).

Production Compose must reference `image@sha256:…`, never `latest`.

## Staging revalidation from registry (this checkpoint)

Staging was recreated with `--force-recreate` using only the three registry
digests above; each container's `.Config.Image` and `docker image inspect`
`RepoDigests` resolve to the intended immutable artifact. Reduced release smoke
passed: `/health` 200, `/ready` 200, Alembic `20260913_09`, Admin login gate
(no/bad cookie → login, good cookie → layer list), Admin token absent from all
browser HTML, layer list/detail, disposable layer+feature create, CSV import
stage+commit, OSIRIS discovery, LOCAL DATA proxy refresh, compatibility
`/layers` and `/layers/test` 200, native OSIRIS root and `/api/flights` 200.

## Production baseline recorded (pre-cutover, 2026-09-13)

Recorded via Portainer (environment `3`, host `portainer.osviel.duckdns.org`),
read-only:

- Running containers: `osiris-geo-api` (healthy), `osiris-geo-postgis`
  (healthy), `osiris`. No `geo-admin` yet.
- Alembic revision: **`20260913_05`**.
- Counts: layers=2, features=928, published=928, archived=0, provenance=928,
  external_sources=1.
- Per layer: `aemet-observation-stations=926`, `amateur-radio-repeaters-es=2`.
- External source: `aemet-observation-stations | aemet_stations | enabled=true |
  status=success | last_success_at=2026-09-13 10:33:08Z`.
- Secrets present as env on the API container (names only, values not read):
  `ADMIN_API_TOKEN`, `AEMET_API_KEY`.
- Network: `osiris-geo-api` no host port (`8000/tcp` internal), networks
  `geo-osiris_default` + `geo-osiris-phase3_default`; `osiris-geo-postgis` no
  host port, network `geo-osiris-phase3_default`; `osiris` published
  `3005:3000`, networks `geo-osiris_default` + `unruffled_belen_default`.

No unexpected count changes are acceptable from the schema migration; the only
allowed difference is the `duplicate_detection` metadata backfill on the radio
layer. The expected freshness backfill (`revision`, `data_updated_at`) is allowed.

## Network target

- PostGIS: no host port.
- Geo API: no host port (unless explicitly required for diagnostics).
- Geo Admin: user-facing port / reverse proxy only.
- OSIRIS: existing user-facing port.
- OSIRIS and Geo Admin reach Geo API over the internal Docker network by DNS.

## Data snapshot to record before and after migration

```sql
SELECT 'features_total', count(*) FROM features
UNION ALL SELECT 'features_published', count(*) FROM features WHERE status='published'
UNION ALL SELECT 'features_archived',  count(*) FROM features WHERE status='archived'
UNION ALL SELECT 'provenance',         count(*) FROM feature_provenance;

SELECT l.slug, count(f.id) FROM layers l
LEFT JOIN features f ON f.layer_id = l.id GROUP BY l.slug ORDER BY l.slug;

SELECT slug, adapter, enabled, status, last_success_at FROM external_sources ORDER BY slug;
```

Also record the AEMET feature count and the amateur-radio feature count
individually. No unexpected count changes are acceptable from the schema
migration; the `duplicate_detection` metadata backfill on the radio layer is the
only allowed difference.

## Runbook

1. **Record current running image digests** — done in the baseline above.
   Re-check with `docker inspect --format '{{.Config.Image}}' osiris-geo-api osiris osiris-geo-postgis`.
2. **Record current Alembic revision** — done: `20260913_05`.
   Re-check with `docker exec osiris-geo-api alembic current`.
3. **Create production backup:**
   `docker exec osiris-geo-postgis pg_dump -U osiris -d osiris -Fc -f /tmp/prod-20260913.dump`
   `docker cp osiris-geo-postgis:/tmp/prod-20260913.dump ./prod-20260913.dump`
4. **Verify:** `pg_restore --list ./prod-20260913.dump` (must list a readable TOC).
5. **SHA256:** `sha256sum ./prod-20260913.dump` → store with the file.
6. **Migrate:** `docker exec osiris-geo-api alembic upgrade head`
   (`20260913_05` → `20260913_09`).
   Prefer migration before exposing the Phase 4 API: the new app expects the
   Phase 4 schema.
7. **Verify:** `docker exec osiris-geo-api alembic current` → `20260913_09`;
   re-run the data snapshot query and compare to the recorded baseline above.
   Expected: counts unchanged (AEMET 926, amateur-radio 2, provenance 928,
   sources 1); only the radio layer gains `duplicate_detection` metadata.
8. **Deploy new Geo API digest** (pin `image@sha256:…`); keep
   `ADMIN_API_TOKEN`/`AEMET_API_KEY`; no host port.
   `ghcr.io/osviel91/geo-osiris-api@sha256:f0beb308d20f63474ab2d5cd1821425d83f1b8ff04dd78c6bdcc1bb100da00e4`
9. **Deploy Geo Admin digest** (pin `image@sha256:…`), behind the authenticated
   boundary; `ADMIN_API_TOKEN` server-side only, `ADMIN_UI_PASSWORD` set.
   `ghcr.io/osviel91/geo-osiris-admin@sha256:4f8fdcbfcaf7c99d5f5174557701323746ed828deaa6be67851ca433c68f4210`
10. **Deploy new OSIRIS digest** (pin `image@sha256:…`), existing user-facing port.
    `ghcr.io/osviel91/osiris@sha256:20ab071ef17529a589435bd8b2d73ff9093c2247b8ee8379787ca340d9ee39f5`
    (amd64 manifest `sha256:16d5dfa45e34438722a1dbbbca938ec7cd669ae6e24841d52f091169ad0e885c`)
11. **Acceptance:** `/health`, `/ready`, `/layers`, `/layers/test`,
    `/api/v1/layers`; Admin login; Admin token absent from browser HTML/bundles;
    layer list/detail; one disposable create; one small import stage+commit;
    OSIRIS discovers the layer; LOCAL DATA refresh; native OSIRIS data functional.
    Re-run the data snapshot query and confirm no unexpected count changes.

Update the production stack through Portainer to pin these digests, then
redeploy the stack. Do not use `latest`.

## Rollback (two levels)

- **Application rollback (default):** re-pin the previous Geo API / OSIRIS
  digests (`ghcr.io/osviel91/geo-osiris-api@sha256:aa6c0b71…`,
  `ghcr.io/osviel91/osiris@sha256:f39bccd0…`) and stop Geo Admin if necessary.
  Do **not** downgrade the database.
- **Database disaster rollback (exception only):** stop writers, restore the
  verified pre-cutover dump, restore the matching previous applications. No
  ad-hoc reverse migrations during an incident.

## Cutover gate

Proceed only when: GHCR publishing succeeded, all three registry digests are
recorded here, staging was recreated from those digests, the reduced smoke
passed, and this runbook contains exact previous/new digests.
