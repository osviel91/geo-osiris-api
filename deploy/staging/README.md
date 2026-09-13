# OSIRIS Geo Hub — staging deployment (Phase 4F)

Staging stack for Geo API + Geo Hub Admin + OSIRIS + PostGIS. **Production is not
touched by anything here.**

## Topology

```
Browser ──► geo-admin :3000 (published) ─┐
                                         ├─► geo-api :8000 (internal only) ─► postgis :5432 (internal only)
Browser ──► osiris    :3000 (published) ─┘
```

- `geo-api` and `postgis` have **no host ports**.
- Only `geo-admin` and `osiris` are published.
- Admin and OSIRIS both call the API server-side (Next.js BFF / proxy), so the
  API needs no browser CORS. `CORS_ORIGINS` stays empty; `*` must not be used.

## Images (this checkpoint)

Built locally; commit SHA tags. Production must pin by `image@sha256:…`, never
`latest`.

| Component      | Commit SHA                                 | Tag                              | Local image digest                                                        |
| -------------- | ------------------------------------------ | -------------------------------- | ------------------------------------------------------------------------- |
| geo-osiris-api | `0ef6d4a03e88e2c398060bc7cf07f1c4df01b1b1` | `geo-osiris-api:sha-0ef6d4a`     | `sha256:f5cac752c0aea52e34a5655e63378b7a47def677ddcc812dc5a6f2074e7a3795` |
| geo-osiris-admin | `0926b3677d93093c8b8b256088d613effbaca88b` | `geo-osiris-admin:sha-0926b36` | `sha256:dc92b7afff024d7bce3ae665e1de263e606a20ea0bccd9eb52617486a960628f` |
| osiris         | `a353dcec7602a2d0188bc2f76709f7787666a152` | `osiris:sha-a353dce`             | `sha256:8465b603c7014b2a112b6bbc246a4da53eca4223d0cb0ac64b233d3b83f3489f` |

Registry digests are recorded at publish time (`docker buildx imagetools
inspect`). The publish workflow currently emits `latest` + `sha-<short>`; add
digest pinning before production cutover.

## Required environment

See `.env.staging.example`. All values are injected at runtime; none are baked
into images, and no infrastructure secret uses `NEXT_PUBLIC_*`.

| Variable            | Consumed by        | Notes                                              |
| ------------------- | ------------------ | -------------------------------------------------- |
| `POSTGRES_PASSWORD` | postgis, geo-api   | required                                           |
| `ADMIN_API_TOKEN`   | geo-api, geo-admin | required; server-side only, never browser JS       |
| `ADMIN_UI_PASSWORD` | geo-admin         | required for the staging auth gate                 |
| `AEMET_API_KEY`     | geo-api            | optional; absent ⇒ sync records a failure          |
| `CORS_ORIGINS`      | geo-api            | keep empty                                         |

## Bring-up

```sh
cp deploy/staging/.env.staging.example deploy/staging/.env.staging   # fill secrets
docker compose -f deploy/staging/compose.yml --env-file deploy/staging/.env.staging up -d
docker exec osiris-staging-geo-api-1 alembic upgrade head            # migrations are manual
```

## Alembic

- Production baseline: `20260913_05`
- Phase 4 head: `20260913_09` (06 freshness → 07 import mapping → 08 candidate
  resolution → 09 import provenance)
- Chain validated 05→09 on a representative database: row counts
  (layers/features/provenance/sources) and all feature geometry, provenance and
  AEMET source state were byte-identical before/after. The only intentional
  backfill is `duplicate_detection` metadata added to the radio demo layer.

## Backup / restore procedure

```sh
docker exec <postgis> pg_dump -U osiris -d osiris -Fc -f /tmp/osiris.dump
docker cp <postgis>:/tmp/osiris.dump ./osiris.dump
sha256sum ./osiris.dump
pg_restore --list ./osiris.dump            # verify readable TOC
docker exec <postgis> pg_restore -U osiris -d <new_db> /tmp/osiris.dump
```

Proven during this checkpoint on staging data:

- dump SHA256: `44e7720e8e5d4d2d11e441ded9bdf5c5d9ef0509418cb54c8192c8ba3f7fa6e7`
- `pg_restore --list`: 56 TOC entries, readable
- restore into a fresh DB: layers 2 / features 2 / provenance 2 / sources 1,
  alembic `20260913_09`, demo features intact

## Rollback

- **Application rollback (default):** redeploy the previous immutable
  `image@sha256:…` for Geo API / Admin / OSIRIS. Leave the database as-is.
- **Database rollback (exception only):** Phase 4 migrations are additive; keep
  the upgraded DB unless a schema/data problem specifically requires restoring
  the backup. If it does, restore the verified dump before rolling app images
  back to the pre-Phase-4 versions.

## Production cutover checklist (not executed)

1. Commit all Phase 4 work; publish images to the registry; record digests.
2. Pin `deploy/compose.yml` to `image@sha256:…` (not `latest`); pass
   `ADMIN_API_TOKEN` to the Geo API service.
3. Take a production logical backup; verify with `pg_restore --list`; record SHA256.
4. Run `alembic upgrade head` (05→09) against production; confirm seeded
   AEMET/radio rows and source state survive.
5. Deploy API + Admin + OSIRIS; confirm regression endpoints (`/health`,
   `/ready`, `/layers`, `/layers/test`, `/api/v1/layers`) and native OSIRIS layers.
6. Verify Admin is behind its authenticated boundary; verify the API is not
   publicly exposed.

## Staging acceptance (this checkpoint)

All checks passed against the running stack:

- **Layers**: create managed Point layer with config; **Manual feature**: add,
  edit (provenance appended, `action=edit`), archive.
- **CSV**: stage with mapping v1, inspect row candidate reasons
  (`property_exact`), commit blocked while unresolved (409), resolve `skip`,
  commit published; committed provenance carries the import source name/URL.
- **GeoJSON**: stage, review, commit published.
- **External source**: AEMET source listed/detailed; sync with no key returns
  `status=failed` and preserves last-known-good state.
- **OSIRIS**: discovers newly created managed layers; proxy reflects mutations
  (3→4 features after an admin add); client-side Refresh replaces cached data on
  success and preserves it on failure (unit-tested).
- **Failure behavior**: Geo API stopped ⇒ OSIRIS root 200, LOCAL DATA proxy 502,
  Admin still serves; API restarted ⇒ proxy 200.
- **Regression**: `/health`, `/ready`, `/layers`, `/layers/test`,
  `/api/v1/layers` all 200.
- **CORS**: no `Access-Control-Allow-Origin` returned for a cross-origin request.
