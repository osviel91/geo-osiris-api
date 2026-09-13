# Phase 4 production cutover runbook (NOT YET EXECUTED)

Blocked on: publishing the three immutable images to GHCR and recording their
registry digests. Do not run this until the cutover gate passes.

## Image digests

| Component        | Previous (production)                     | New (accepted commit)                    | New registry digest |
| ---------------- | ----------------------------------------- | ---------------------------------------- | ------------------- |
| geo-osiris-api   | `<record with docker inspect>`            | `0ef6d4a03e88e2c398060bc7cf07f1c4df01b1b1` | `ghcr.io/osviel91/geo-osiris-api@sha256:<fill>` |
| geo-osiris-admin | (not deployed)                            | `0926b3677d93093c8b8b256088d613effbaca88b` | `ghcr.io/osviel91/geo-osiris-admin@sha256:<fill>` |
| osiris           | `<record with docker inspect>`            | `a353dcec7602a2d0188bc2f76709f7787666a152` | `ghcr.io/osviel91/osiris@sha256:<fill>` |

Production Compose must reference `image@sha256:…`, never `latest`.

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

1. **Record current running image digests** (per service):
   `docker inspect --format '{{.Config.Image}} {{index .RepoDigests 0}}' <container>`
2. **Record current Alembic revision:** `docker exec <api> alembic current`
   (expected `20260913_05`).
3. **Create production backup:**
   `docker exec <postgis> pg_dump -U osiris -d osiris -Fc -f /tmp/prod-<date>.dump`
   `docker cp <postgis>:/tmp/prod-<date>.dump ./prod-<date>.dump`
4. **Verify:** `pg_restore --list ./prod-<date>.dump`
5. **SHA256:** `sha256sum ./prod-<date>.dump` → store with the file.
6. **Migrate:** `docker exec <api> alembic upgrade head` (`20260913_05` → `20260913_09`).
   Prefer migration before exposing the Phase 4 API: the new app expects the
   Phase 4 schema.
7. **Verify:** `alembic current` → `20260913_09`; re-run the data snapshot query
   and compare to step 0's baseline.
8. **Deploy new Geo API digest** (pin `image@sha256:…`); pass `ADMIN_API_TOKEN`.
9. **Deploy Geo Admin digest** (pin `image@sha256:…`), behind the authenticated
   boundary; `ADMIN_API_TOKEN` server-side only.
10. **Deploy new OSIRIS digest** (pin `image@sha256:…`).
11. **Acceptance:** `/health`, `/ready`, `/layers`, `/layers/test`,
    `/api/v1/layers`; Admin login; Admin token absent from browser HTML/bundles;
    layer list/detail; one disposable create; one small import stage+commit;
    OSIRIS discovers the layer; LOCAL DATA refresh; native OSIRIS data functional.

## Rollback (two levels)

- **Application rollback (default):** re-pin the previous Geo API / OSIRIS
  digests and stop Geo Admin if necessary. Do **not** downgrade the database.
- **Database disaster rollback (exception only):** stop writers, restore the
  verified pre-cutover dump, restore the matching previous applications. No
  ad-hoc reverse migrations during an incident.

## Cutover gate

Proceed only when: GHCR publishing succeeded, all three registry digests are
recorded here, staging was recreated from those digests, the reduced smoke
passed, and this runbook contains exact previous/new digests.
