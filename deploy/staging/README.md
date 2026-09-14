# OSIRIS Geo Hub — staging deployment (Phase 4F)

Staging stack for Geo API + Geo Hub Admin + OSIRIS + PostGIS. **Production is not
touched by anything here.**

## Topology

```
Browser ──HTTPS──► admin-proxy :443 (127.0.0.1) ─► Authelia (forward-auth)
                                                        │ trusted headers
                                                        ▼
                                                   geo-admin (internal) ─► geo-api :8000 (internal) ─► postgis :5432 (internal)
Browser ──► osiris :3000 (published) ─────────────────────────────────────────► geo-api :8000 (internal)
```

- `geo-api` and `postgis` have **no host ports**.
- Only `admin-proxy` (TLS) and `osiris` are published. `geo-admin` is now
  Docker-internal; it has no login form and trusts identity only from the proxy.
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

| Variable | Consumed by | Notes |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | postgis, geo-api | required |
| `GEO_READ_TOKEN` | geo-api | optional read-only API credential |
| `GEO_STAGE_TOKEN` | geo-api, Geo MCP | stage credential; grants read and stage only |
| `GEO_APPROVE_TOKEN` | geo-api | human approval credential; grants read and approve only |
| `GEO_PUBLISH_TOKEN` | geo-api, geo-publisher | publication executor only; never mount in Geo MCP |
| `GEO_ADMIN_TOKEN` | geo-api, geo-admin | human administration credential; server-side only |
| `ADMIN_API_TOKEN` | geo-api | deprecated legacy full-admin compatibility; remove before production |
| `AEMET_API_KEY` | geo-api | optional; absent means sync records a failure |
| `CORS_ORIGINS` | geo-api | keep empty |
| `ADMIN_PROXY_SECRET` | admin-proxy, geo-admin | shared proof-of-proxy secret; required |
| `AUTHELIA_SESSION_SECRET` | authelia | random 32-byte hex; required |
| `AUTHELIA_STORAGE_ENCRYPTION_KEY` | authelia | random 32-byte hex; required |
| `AUTHELIA_JWT_SECRET` | authelia | random 32-byte hex; required |
| `ADMIN_HTTPS_PORT` | admin-proxy | loopback port for the TLS proxy (default 443) |

## Bring-up

```sh
cp deploy/staging/.env.staging.example deploy/staging/.env.staging   # fill secrets
docker compose -f deploy/staging/compose.yml --env-file deploy/staging/.env.staging up -d
docker exec osiris-staging-geo-api-1 alembic upgrade head            # migrations are manual
```

## Human authentication (Phase 10D — prepared, not yet deployed)

Geo Admin no longer has a shared-password login. It is Docker-internal and sits
behind `admin-proxy`, which performs Authelia forward-auth and injects trusted
`Remote-User`/`Remote-Name`/`Remote-Email` headers plus `X-Proxy-Secret`. The
admin rejects all identity unless `X-Proxy-Secret` matches `ADMIN_PROXY_SECRET`.

### Namespace and the home.arpa PSL constraint

Authelia refuses a session cookie domain that is a Public Suffix List entry.
`home.arpa` is in the PSL, so a cookie on `home.arpa` (which would be needed to
share a session between `geo-admin.home.arpa` and `auth.home.arpa`) cannot work.
The staging namespace is therefore the registrable child `osiris.home.arpa`:

- `geo-admin.osiris.home.arpa` — admin UI (forward-auth)
- `auth.osiris.home.arpa` — Authelia portal
- cookie domain: `osiris.home.arpa`

### Host setup (manual — requires approval before running)

```sh
brew install mkcert
mkcert -install
mkdir -p deploy/staging/certs
mkcert -cert-file deploy/staging/certs/osiris.home.arpa.pem \
       -key-file  deploy/staging/certs/osiris.home.arpa-key.pem \
       geo-admin.osiris.home.arpa auth.osiris.home.arpa
```

Name resolution (only if no local DNS exists):

```
127.0.0.1 geo-admin.osiris.home.arpa auth.osiris.home.arpa
```

Certificates live in `deploy/staging/certs/` (gitignored; never committed).

### Bring-up after TLS is trusted

```sh
docker run --rm authelia/authelia:4.38 authelia hash-password 'YOUR_PASSWORD'
# paste the Argon2 hash into deploy/staging/authelia/users_database.yml
docker compose -f deploy/staging/compose.yml --env-file deploy/staging/.env.staging up -d
```

Then browse `https://geo-admin.osiris.home.arpa/`.

## Publication executor

`geo-publisher` is a narrow, non-root, port-less container on the internal
staging network. It receives only `GEO_API_URL` and `GEO_PUBLISH_TOKEN` and its
only action is to call `POST /api/v1/admin/imports/{import_id}/commit` for an
import a human has already approved. Geo Hub owns approval state, fingerprint
verification, expiry, locking, and the commit itself; the publisher never
retries. The Geo MCP container never receives the publish credential.

```sh
# An operator, after a human has approved the import:
docker exec osiris-staging-geo-publisher-1 python /app/publisher.py <import_id>
```

Exit code `0` prints `{"status":"executed", ...}`; a non-zero exit prints a
bounded error (`401`/`403`/`404`/`409`/`422`/connectivity) without the token.
The import status is `draft|published` and is derived from the approved request,
so the publisher takes only the import identifier.

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
2. Pin `deploy/compose.yml` to `image@sha256:…` (not `latest`); provision
   distinct read, stage, publish, and admin credentials. Mount only the stage
   credential in Geo MCP and keep publish/admin credentials out of agent-facing
   services. Remove the temporary `ADMIN_API_TOKEN` compatibility credential.
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
