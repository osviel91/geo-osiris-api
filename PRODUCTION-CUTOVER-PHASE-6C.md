# Production Cutover Plan — Phase 6C

**Status: PLANNING ONLY — REVISION 3. Nothing in production has been changed.**
**Read-only production access is restored (Portainer API). The live baseline in §1.0 is
verified. Deployment is still STOPPED pending human review of this revision.**

This document is the plan to move the Phase 6C approval-gated publication architecture
(proven in staging) to production. It does **not** authorize execution. Every command in
§8 onward is for the operator to run after review.

Revision 2 incorporated operator corrections:
1. The recorded production baseline is **stale and untrusted**; a fresh live read-only
   baseline is mandatory before any mutation (§1).
2. Production MCP deployment/connectivity is **removed from the Phase 6C critical path**
   and split into **Phase 6D — Production MCP Deployment** (§10).
3. The TLS/DNS target is **decided**: VPN/private network + private DNS + internally
   trusted CA/certificate, with no public exposure (§5).
4. Cutover preparation is stopped at the **operational access blocker** (§0a).

Revision 3 adds:
5. A **live, verified production baseline** (§1.0) collected read-only through the
   Portainer API (environment `3`) — the stale §1.1/§1.2 tables are now historical only.
6. The **verified diff** between production and the Phase 6C target (§2).
7. The discovered **existing TLS terminator** (Nginx Proxy Manager) recorded in §5.

---

## 0. Blocker — RESOLVED for read-only discovery

Production is the remote Zima host (`192.168.31.39`). Direct SSH/LAN access from the
authoring machine is **still unavailable** (ping loss, ARP incomplete, SSH timeout, VPN
inactive). However, **read-only discovery was performed through the Portainer API**
(`https://portainer.osviel.duckdns.org`, environment `3`, temporary read-only API key).

§1.0 below was collected with **read-only** requests only: list/inspect containers,
Docker exec for `alembic current`, and `SELECT`-only count queries. No production object
was created, changed, or deleted.

This is not a reason to weaken any network isolation. It is a reason to verify first.

---

## 0a. Management access — planning (restored) vs execution (still required)

Read-only discovery is restored via the Portainer API and was sufficient for §1.0.

**Executing** the cutover still requires a trusted **write** path to the Zima host, because
it needs `docker exec`, image pull, stack update, and a database dump. The operator must
restore **one** of:

1. **VPN (preferred).** Activate WireGuard/OpenVPN with the existing production peer;
   confirm `ping`/SSH to `192.168.31.39` and Docker access over the tunnel.
2. **LAN restore.** Confirm the host is powered/connected; re-check ARP/ping from the
   authoring machine.
3. **Portainer write access** for environment `3` (an API key permitted to update stack 22
   and run exec). A read-only key cannot execute the cutover.

No brute force, no public DNS change, no new exposed services/ports, no replacement
resources. Do **not** begin deployment until this revision is reviewed.

---

## 1. Current production baseline

### 1.0 VERIFIED live baseline (2026-09-14, read-only via Portainer environment `3`)

Stack: Portainer stack **22** (`geo-osiris`), Docker 28.3.2 on the Zima host.

Containers (relevant to this cutover):

| Container | State | Image (digest) | Commit / built | Published ports | Networks |
|---|---|---|---|---|---|
| `osiris-geo-api` | running (healthy) | `ghcr.io/osviel91/geo-osiris-api@sha256:42dd61dcbc45ede99b59bce05364766f710d2cd3ec1bd2e1ed77b785d23725bf` | `9c2d5369b84624b303a6a8c9792344b151725eb4`, 2026-09-13T21:58:58Z | **none** (8000 internal) | `geo-osiris-internal`, `geo-osiris_default` |
| `osiris-geo-admin` | running | `ghcr.io/osviel91/geo-osiris-admin@sha256:4eae4cb3bf181a8de7ae34c95ffc205f872ccc05a3225d1aba19ac91e467f26a` | `9889d26241327f9a2beca70f20caa8a50ace58f7`, 2026-09-13T19:53:24Z | **`0.0.0.0:8081->3000` (EXPOSED)** | `geo-osiris-internal`, `geo-osiris_default` |
| `osiris-geo-postgis` | running (healthy) | `postgis/postgis@sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5` | — | none | `geo-osiris-internal` |
| `osiris` | running | `ghcr.io/osviel91/osiris@sha256:20ab071ef17529a589435bd8b2d73ff9093c2247b8ee8379787ca340d9ee39f5` | — | `3005->3000` | `geo-osiris_default`, `unruffled_belen_default` |
| `nginxproxymanager` | running | `jc21/nginx-proxy-manager:latest` | — | `80`, `443`, `81` | `bridge` |

- **No** `geo-osiris-mcp` container and **no** publisher container exist in production.
- `osiris-geo-api` env variable **names**: `ADMIN_API_TOKEN`, `AEMET_API_KEY`, `APP_ENV`,
  `APP_HOST`, `APP_PORT`, `CORS_ORIGINS`, `DATABASE_URL`. **No scoped tokens exist yet.**
- `osiris-geo-admin` env variable **names**: `ADMIN_API_TOKEN`, `ADMIN_UI_PASSWORD`,
  `GEO_API_URL`, `NODE_ENV`, `PORT`. (Legacy shared password + legacy full token.)
- PostGIS volume: external `geo-osiris-phase3_postgis-data`.
- Production stack compose (stack 22) defines `geo-api`, `geo-admin`, `postgis`; networks
  `geo-internal` (= `geo-osiris-internal`, `internal: true`) and external
  `geo-osiris_default`; stack secrets are `ADMIN_API_TOKEN`, `ADMIN_UI_PASSWORD`,
  `POSTGRES_PASSWORD`, `AEMET_API_KEY`.

Database (`alembic current` = **`20260913_09 (head)`**; migration `20260914_10` NOT applied):

| Metric | Value |
|---|---|
| Layers | 3 |
| — `aemet-observation-stations` | 926 |
| — `amateur-radio-repeaters-es` | 270 |
| — `phase4-smoke` | 2 |
| Features total | 1198 |
| — published | 1196 |
| — archived | 2 |
| — draft | 0 |
| Provenance | 1207 |
| External sources | 1 (`aemet-observation-stations`, adapter `aemet_stations`, enabled, status success) |

This matches the operator's later-state context in §1.2. §1.1's figures are confirmed
obsolete.

> §1.1 and §1.2 below are retained only as **historical context** for drift detection. The
> authoritative baseline is §1.0.

### 1.1 Older recorded baseline (2026-09-13, Portainer environment `3`) — HISTORICAL

| Item | Recorded value (untrusted) |
|---|---|
| Containers | `osiris-geo-api` (healthy), `osiris-geo-postgis` (healthy), `osiris` |
| Geo Admin | **not deployed** |
| Alembic revision | `20260913_05` |
| Layers | 2 (`aemet-observation-stations`=926, `amateur-radio-repeaters-es`=2) |
| Features | 928 total / 928 published / 0 archived |
| Provenance | 928 |
| External sources | 1 (`aemet`, enabled, status success) |
| API host port | **none** (internal only) |
| API networks | `geo-osiris_default`, `geo-osiris-phase3_default` |
| PostGIS host port | none |
| OSIRIS | published `3005:3000` |
| API image | `ghcr.io/osviel91/geo-osiris-api@sha256:f0beb308…` (commit `0ef6d4a`) |
| Admin image | `ghcr.io/osviel91/geo-osiris-admin@sha256:4f8fdcbf…` (commit `0926b36`, not deployed) |
| OSIRIS image | `ghcr.io/osviel91/osiris@sha256:20ab071e…` (commit `a353dce`) |
| PostGIS image | `postgis/postgis@sha256:44126d87…` |
| API secrets (names only) | `ADMIN_API_TOKEN`, `AEMET_API_KEY` |

### 1.2 Known later production state (historical context only) — also UNTRUSTED

Later production work is believed to have advanced beyond §1.1. These values are
operator-supplied context, **not** verified facts, and must be confirmed or corrected by
§1.3:

| Item | Believed later value (unverified) |
|---|---|
| Alembic revision | `20260913_09` |
| Geo Admin | **deployed** |
| Import features | typed CSV v2, duplicate detection v2, hardened PATCH |
| AEMET features | 926 |
| Amateur-radio features | 270 |
| Global feature count | ~1198 |
| Provenance count | ~1207 |

Implication: §1.1's "no Geo Admin", `20260913_05`, and 928-feature figures are almost
certainly obsolete. Treat every number and digest below as unknown until §1.3.

### 1.3 Live baseline checklist (collected 2026-09-14 → see §1.0)

The live read-only baseline was collected on 2026-09-14 via the Portainer Docker API
(environment `3`) and is recorded in **§1.0**. The checklist below is retained as the
**pre-execution re-verification** list: run it again immediately before any mutation and
abort if anything differs from §1.0.

Required facts:
- container names / status
- image refs / digests
- Geo API version / digest
- Geo Admin version / digest
- OSIRIS digest
- PostGIS digest
- `alembic current`
- feature counts (total)
- published / archived counts
- provenance count
- AEMET count
- amateur-radio count
- layer count
- source count
- current env variable **names** (never values)
- published ports
- Docker networks

### 1.4 Read-only re-verification commands (run on the Zima host / via Portainer exec)

```bash
# Container inventory + images + ports + networks
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
docker inspect -f '{{.Name}} {{.Config.Image}} {{.Image}}' \
  osiris-geo-api osiris-geo-postgis osiris osiris-geo-admin 2>/dev/null
docker network ls
docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' osiris-geo-api

# Image digests actually running
for c in osiris-geo-api osiris-geo-postgis osiris osiris-geo-admin; do
  docker inspect -f '{{.Name}} {{index .Config.Image}}' "$c" 2>/dev/null
  docker inspect --format '{{.RepoDigests}}' "$(docker inspect -f '{{.Image}}' "$c")" 2>/dev/null
done

# Alembic revision
docker exec osiris-geo-api alembic current

# Counts (re-run identically before and after cutover)
docker exec osiris-geo-postgis psql -U osiris -d osiris -c \
  "SELECT count(*) features FROM features;"
docker exec osiris-geo-postgis psql -U osiris -d osiris -c \
  "SELECT status, count(*) FROM features GROUP BY status ORDER BY status;"
docker exec osiris-geo-postgis psql -U osiris -d osiris -c \
  "SELECT count(*) provenance FROM feature_provenance;"
docker exec osiris-geo-postgis psql -U osiris -d osiris -c \
  "SELECT l.slug, count(f.id) FROM layers l LEFT JOIN features f ON f.layer_id=l.id GROUP BY l.slug ORDER BY l.slug;"
docker exec osiris-geo-postgis psql -U osiris -d osiris -c \
  "SELECT count(*) layers FROM layers;"
docker exec osiris-geo-postgis psql -U osiris -d osiris -c \
  "SELECT count(*) sources FROM external_sources;"

# Env variable NAMES only (never print values)
docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' osiris-geo-api | cut -d= -f1
```

### 1.5 Repo production compose vs the live stack

The **live** production stack is Portainer stack **22** (`geo-osiris`), whose compose is
recorded in §1.0. The repo file `deploy/compose.yml` (geo-api repo) is **out of date** and
does **not** match production: it defines only `geo-api` and `postgis`, has **no auth
tokens**, and **publishes `${HOST_PORT:-8000}:8000`** (production publishes no API port).
Do not apply `deploy/compose.yml` as-is. The production stack must be revised in place
(§5) to the target topology; keep the live stack's `geo-osiris-internal` + `geo-osiris_default`
network layout and the `geo-osiris-phase3_postgis-data` volume.

---

## 2. Differences from staging

| Area | Staging (proven) | Production live (2026-09-14, §1.0) → target |
|---|---|---|
| Alembic | `20260914_10` | **`20260913_09`** → `20260914_10` |
| API auth | scoped tokens | **`ADMIN_API_TOKEN` only** (no scoped tokens) → scoped tokens |
| Geo Admin | deployed, internal, Authelia | **deployed, exposed `8081`, shared password, legacy token** → authenticated, internal-only |
| Admin auth | Authelia + proxy | **shared password (`ADMIN_UI_PASSWORD`) + layout-only gate** → Authelia + proxy |
| MCP | `geo-osiris-mcp` (staging mode) | **not deployed** — Phase 6D, out of scope here |
| Publisher | `osiris-staging-geo-publisher-1` | **not deployed** → isolated publisher |
| TLS | mkcert local CA (do not reuse) | Nginx Proxy Manager terminates public TLS (Let's Encrypt) → **decided: VPN + private DNS + internal CA (§5)** |
| Hostname | `geo-admin.osiris.home.arpa` | none (LAN `:8081`) → private name in a domain the operator controls (§5) |
| Networks | `osiris-staging` | **`geo-osiris-internal` (internal) + `geo-osiris_default`** |
| API host port | none | **none** (8000 internal) — already correct |
| Admin host port | none | **`0.0.0.0:8081->3000`** → remove (internal only) |
| PostGIS host port | none | none — already correct |
| Data | disposable test data | **1198 features / 1207 provenance / 3 layers / 1 source** (§1.0) |

---

## 3. Required images

Production must run **immutable, digest-pinned** images (never `latest`). Build/publish
from a tagged commit; deploy by digest.

| Component | Source | Registry target | Platform |
|---|---|---|---|
| Geo API | `geo-api-osiris` repo-root `Dockerfile` | `ghcr.io/osviel91/geo-osiris-api` | linux/amd64 |
| Geo Admin | `geo-osiris-admin` `Dockerfile` | `ghcr.io/osviel91/geo-osiris-admin` | linux/amd64 |
| Publisher | `geo-api-osiris/publisher/Dockerfile` | `ghcr.io/osviel91/geo-osiris-publisher` (new) | linux/amd64 |
| Authelia | upstream | `authelia/authelia:4.38` (pin by digest) | linux/amd64 |
| Proxy | upstream | `nginx:1.27-alpine` (pin by digest) | linux/amd64 |
| PostGIS | upstream | unchanged `postgis/postgis:16-3.4` | linux/amd64 |
| OSIRIS | unchanged | unchanged | linux/amd64 |
| **MCP** | `geo-osiris-mcp` `Dockerfile` | `ghcr.io/osviel91/geo-osiris-mcp` (new) | linux/amd64 — **Phase 6D, not 6C.6** |

Record for each: **commit SHA + tag + digest + platform**. See §17 for CI work needed
(the publisher currently publishes nothing; MCP publication is deferred to Phase 6D).

**Current live production digests (2026-09-14, §1.0) — for rollback pinning:**

| Component | Live digest | Live commit |
|---|---|---|
| Geo API | `ghcr.io/osviel91/geo-osiris-api@sha256:42dd61dcbc45ede99b59bce05364766f710d2cd3ec1bd2e1ed77b785d23725bf` | `9c2d5369b84624b303a6a8c9792344b151725eb4` |
| Geo Admin | `ghcr.io/osviel91/geo-osiris-admin@sha256:4eae4cb3bf181a8de7ae34c95ffc205f872ccc05a3225d1aba19ac91e467f26a` | `9889d26241327f9a2beca70f20caa8a50ace58f7` |
| OSIRIS | `ghcr.io/osviel91/osiris@sha256:20ab071ef17529a589435bd8b2d73ff9093c2247b8ee8379787ca340d9ee39f5` | (unchanged; out of scope) |
| PostGIS | `postgis/postgis@sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5` | (unchanged) |

The cutover builds **new** API/Admin/Publisher images from the Phase 6C code and pins them
by digest; the OSIRIS and PostGIS digests above must not change.

---

## 4. Required production secrets

Fresh, independent values. **Do not reuse any staging token.** Generate with
`openssl rand -hex 32`. Never print values; store per §18.

| Secret | Consumers | Notes |
|---|---|---|
| `GEO_READ_TOKEN` | geo-api | optional read-only credential |
| `GEO_STAGE_TOKEN` | geo-api, geo-osiris-mcp | stage only; MCP holds **only** this |
| `GEO_APPROVE_TOKEN` | geo-api, geo-admin | human approval path only; never publish/stage/admin |
| `GEO_PUBLISH_TOKEN` | geo-api, geo-publisher | executor only; never in admin/browser |
| `GEO_ADMIN_TOKEN` | geo-api, geo-admin | read+stage+admin; **no** approve, **no** publish |
| `ADMIN_PROXY_SECRET` | geo-admin, admin-proxy | shared trust gate for identity headers |
| `AUTHELIA_SESSION_SECRET` | authelia | |
| `AUTHELIA_STORAGE_ENCRYPTION_KEY` | authelia | |
| `AUTHELIA_JWT_SECRET` | authelia | |
| `POSTGRES_PASSWORD` | geo-api, postgis | existing; do not rotate in this cutover unless required |
| `AEMET_API_KEY` | geo-api | existing |

Container → secret mapping (least privilege):

```
geo-osiris-mcp   → GEO_API_URL, GEO_STAGE_TOKEN          (Phase 6D only)
geo-admin        → GEO_API_URL, GEO_ADMIN_TOKEN, GEO_APPROVE_TOKEN, ADMIN_PROXY_SECRET, AUTHELIA_PORTAL_URL
geo-publisher    → GEO_API_URL, GEO_PUBLISH_TOKEN
geo-api          → all token values it validates + DATABASE_URL + AEMET_API_KEY
authelia         → the three AUTHELIA_* secrets
admin-proxy      → ADMIN_PROXY_SECRET
postgis          → POSTGRES_PASSWORD
```

No component receives a credential it does not use. In Phase 6C.6 the MCP row is not
deployed; `GEO_STAGE_TOKEN` is held only by `geo-api` (and, for the acceptance test, the
operator's trusted stage-scoped path).

---

## 5. TLS / DNS architecture

**Decided by the operator. Do not re-open during execution.**

Target architecture:

```
VPN / private network
  + private DNS
  + internally trusted CA / certificate
```

Rules:

- **Do not reuse the staging mkcert certificates or the staging `home.arpa` hostname.**
  mkcert is a local-CA convenience, not a production trust model; and `home.arpa` is a PSL
  entry that Authelia rejects as a cookie domain.
- **Do not expose Geo Admin publicly simply to obtain TLS.** Public exposure is not an
  acceptable shortcut for certificate issuance.
- Geo Admin is reached only over the VPN/private network, by a private DNS name in a
  domain the operator controls, with a certificate from an internal CA (e.g. `step-ca`) or
  an equivalent internally trusted certificate.
- Authelia cookie domain must be a **registrable domain** (never `localhost`, `.local`,
  `.test`, or a PSL entry such as `home.arpa`).
- **Do not implement the TLS/DNS change yet.** It waits until production connectivity is
  restored (§0a) and the actual network topology has been re-inspected against §1.3.

Invariant (unchanged): **only the TLS proxy is published**; Geo Admin, Geo API and PostGIS
stay internal. Geo Admin must **not** keep any LAN/public port.

**Confirmed live (2026-09-14, §1.0):** production already runs **Nginx Proxy Manager**
(`jc21/nginx-proxy-manager`, ports `80`/`443`/`81`, volumes under
`/DATA/AppData/nginxproxymanager/`) as the public TLS terminator, fronting
`portainer.osviel.duckdns.org` and others with Let's Encrypt. It is operator-controlled, so
the DNS/TLS stack is not a greenfield problem. However NPM currently sits on the default
`bridge` network, so to front an internal-only Geo Admin it must either join
`geo-osiris-internal`/`geo-osiris_default` or reach the admin over a host port — and adding
a host port would violate the "Geo Admin must not be published" invariant. Any NPM change is
part of the execution phase, not this planning checkpoint.

Facts that still need to be confirmed live before implementation: the private DNS zone/VPN
subnet actually in use, the exact private hostname to issue the certificate for, and whether
the chosen internal CA or an NPM-managed cert will be used for that private name.

---

## 6. Database migration

Migration `20260914_10` (`migrations/versions/20260914_10_import_approvals.py`), revision
`20260914_10`, down-revision `20260913_09`.

**Schema impact — additive only:**

```sql
CREATE TABLE import_approvals (
  id UUID PRIMARY KEY,
  import_id UUID NOT NULL REFERENCES imports(id),
  snapshot JSONB NOT NULL,
  fingerprint VARCHAR(64) NOT NULL,
  requested_status VARCHAR(20) NOT NULL,
  requester VARCHAR(100) NOT NULL,
  requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  state VARCHAR(20) NOT NULL DEFAULT 'pending',
  approver VARCHAR(100),
  approved_at TIMESTAMPTZ,
  rejection_reason TEXT,
  expires_at TIMESTAMPTZ NOT NULL,
  executor VARCHAR(100),
  executed_at TIMESTAMPTZ,
  failure_reason TEXT,
  CONSTRAINT import_approvals_requested_status_check
    CHECK (requested_status IN ('draft','published')),
  CONSTRAINT import_approvals_state_check
    CHECK (state IN ('pending','approved','rejected','expired','stale','executed','failed'))
);
CREATE INDEX import_approvals_import_id ON import_approvals (import_id);
CREATE UNIQUE INDEX import_approvals_one_active_per_import
  ON import_approvals (import_id) WHERE state IN ('pending','approved');
```

- No existing table is altered. No column added to `imports`, `features`,
  `feature_provenance`, `layers`, or `external_sources`.
- No data backfill. Existing features / provenance / layers / sources (live counts from
  §1.3) are untouched by the migration.
- The partial unique index is the DB-level guarantee of "one active approval per import".
- Safe to apply against a live DB; takes a brief lock only on the new table's creation.

Migration also requires `APPROVAL_TTL_MINUTES` (default `60`) and the scoped token
variables to be present in the API container.

---

## 7. Backup plan

Before any production mutation:

1. Dump PostGIS:
   ```bash
   docker exec osiris-geo-postgis pg_dump -U osiris -d osiris -Fc \
     > /secure/backups/osiris-pre-6c-$(date -u +%Y%m%dT%H%M%SZ).dump
   ```
2. Record alongside the dump:
   - filename + UTC timestamp
   - `sha256sum` of the dump
   - an off-host copy (VPN copy to the authoring machine or another host)
   - the §1.2 counts (features/published/archived/provenance/per-layer/sources)
   - `alembic current`
   - all running image digests
3. Verify the dump is restorable into a **throwaway** container before relying on it.

Do **not** perform this during planning. It is the first execution step.

---

## 8. Exact deployment order

Adapted to the real dependency graph. The goal is to avoid any window where Admin uses an
old token against a new API, where the publisher has credentials before the approval
backend exists, or where the legacy token remains silently valid.

```
0.  Freeze: announce window; confirm no curator/staging activity targets production.
1.  Backup (§7) + record LIVE counts + digests from §1.3. ABORT if counts differ from the
    live baseline without explanation.
2.  Publish immutable images (§3) and record commit/tag/digest.
3.  Stage production secrets in the durable store (§18). Do not remove ADMIN_API_TOKEN yet.
4.  Deploy NEW geo-api WITH scoped tokens AND legacy ADMIN_API_TOKEN still accepted.
    (Compatibility window: new code, old token still works, so nothing breaks yet.)
5.  Run alembic upgrade head (live revision → 20260914_10). Verify revision + counts.
6.  Verify read-only API: health/readiness + GET /api/v1/admin/layers with GEO_ADMIN_TOKEN.
7.  Deploy Authelia + admin-proxy (internal geo-admin reachable only via proxy; §5).
8.  Deploy updated Geo Admin (GEO_ADMIN_TOKEN + GEO_APPROVE_TOKEN + ADMIN_PROXY_SECRET).
9.  Verify human auth end-to-end (login → read → save → refresh → logout) on the chosen
    hostname.
10. Deploy geo-publisher with GEO_PUBLISH_TOKEN only (§11).
11. Run the negative/security checks (§13) while the legacy token still exists, confirming
    scopes hold.
12. Remove ADMIN_API_TOKEN from geo-api env; recreate geo-api; confirm old token now 401.
13. Production acceptance test without MCP (§12), then end-to-end smoke.
14. Record final counts + digests; close window.
```

**Explicitly excluded from this order:** production MCP and Hermes production connectivity
(Phase 6D, §10), auto-publisher, OSIRIS changes, and any AEMET/radio mutations.

Order rationale: the API compatibility window (step 4) lets scoped and legacy credentials
coexist only until Admin/publisher are on scoped credentials. `ADMIN_API_TOKEN` is removed
(step 12) only after nothing depends on it, eliminating the "silently still valid" window.

---

## 9. Rollback plan

Distinguish clearly: **container rollback ≠ database rollback ≠ credential rollback.**

| Component | Rollback |
|---|---|
| Geo API | Re-pin previous digest (`…f0beb308…` or the recorded prior) and recreate. Does **not** undo the schema migration. |
| Geo Admin | Not deployed before cutover; rollback = stop/remove the stack. |
| Authelia / proxy | Stop/remove the new stack; no prior state existed. |
| MCP | Phase 6D — not part of this cutover. |
| Publisher | Not deployed before cutover; rollback = stop/remove. |
| DB migration | **Forward-only in normal operation.** Do not `alembic downgrade` a live DB. If the new table must be removed, it is an additive, unused table; dropping it loses only approval history. Disaster rollback = restore the §7 dump into a fresh volume. |
| Credentials | Re-adding `ADMIN_API_TOKEN` to geo-api env is a fast, reversible escape hatch during the window. Rotating scoped tokens is independent of the schema. |

Key rule: **rolling back the application image does not roll back the schema.** If the new
API code is rolled back while the `import_approvals` table exists, that is harmless (old
code ignores it). If the schema is rolled back, approval history is lost — treat the dump
as the only true DB rollback.

---

## 10. Production MCP connectivity — moved to Phase 6D

**Production MCP deployment and Hermes→production connectivity are OUT OF SCOPE for Phase
6C.6.** The secure remote path does not exist today, and it must **not** be solved by
exposing Geo API.

Phase 6C's production target is therefore:

```
scoped Geo API + approval DB migration + Authelia + Admin proxy
+ updated Geo Admin + isolated publisher
```

**Phase 6D — Production MCP Deployment** will cover, later, the secure path (MCP container
on the Zima host in `geo-osiris_default`, reached by a trusted Hermes node over the VPN).
It remains blocked until the VPN/private path is restored and verified.

Explicitly **not** done in Phase 6C.6:
- no production MCP container
- no Hermes production connectivity
- no Geo API exposure to make MCP work
- no agent-driven production approval-request creation

When Phase 6D proceeds, MCP will receive **only** `GEO_API_URL` + `GEO_STAGE_TOKEN`, with no
approve/publish credential and no publication-execution tool.

---

## 11. Publisher runbook

Publisher stays a **manual, isolated, one-shot** executor. No auto-publish in this cutover.

Trusted operator procedure for an approved import:

```bash
# 1. Confirm the request is approved (read-only)
#    GET /api/v1/admin/approvals/{id}  -> state == "approved"

# 2. Execute inside the isolated publisher container (holds only GEO_PUBLISH_TOKEN)
docker exec osiris-geo-publisher python /app/publisher.py <import_id>

# 3. Expected on success:
#    exit 0  {"status":"executed","approval_state":"executed","committed_at":...}
#    On replay / not-approved: exit 1, HTTP 409, nothing published.
```

The publisher container has no host ports, no database credentials, no Docker socket, and
no stage/approve/admin token.

---

## 12. Production acceptance test (without MCP)

One disposable, clearly named acceptance artifact. Do not touch AEMET/radio data.
Because production MCP is deferred to Phase 6D, the approval request is created through an
**operator-controlled, stage-scoped API path from inside the trusted production
environment** (e.g. `docker exec` into a trusted container on `geo-osiris_default` using
`GEO_STAGE_TOKEN`). This is for cutover validation only.

1. Create managed layer `acceptance-6c` (name `Phase 6C Acceptance`, category `test`).
2. Stage 1–2 harmless rows (e.g. two points) via the stage-scoped API path
   (`GEO_STAGE_TOKEN`).
3. Request publication (`POST /api/v1/admin/imports/{id}/approval-request`, status
   `published`).
4. Human opens production Geo Admin `/approvals`, reviews the snapshot, approves.
   - Verify `approved_by` = the authenticated Authelia user, state `approved`, import
     still `validated`, feature_count unchanged, publisher not invoked.
5. Manually invoke the publisher (§11).
   - Verify state `executed`, import `committed`, feature_count increases by exactly the
     staged rows, provenance correct, executor `geo-publish`, approver unchanged.
6. Document the acceptance layer id/name; it is the only intended new data.

Do **not** weaken networking to make this test convenient. Agent-driven production
request creation is validated later in Phase 6D.

---

## 13. Negative / security tests (production)

Run against production after the new API is live:

| Check | Expected |
|---|---|
| `GEO_STAGE_TOKEN` → `POST …/commit` | 403 |
| `GEO_ADMIN_TOKEN` → `POST …/commit` | 403 |
| `GEO_APPROVE_TOKEN` → `POST …/imports` (stage) | 403 |
| `GEO_PUBLISH_TOKEN` → `POST …/imports` (stage) | 403 |
| Unauthenticated Admin BFF mutation | 401 (and **zero** Geo API calls) |
| Forged identity headers (no/wrong `X-Proxy-Secret`) | 401 |
| Cross-origin Admin mutation | 403 |
| Stale approval → publisher | 409 |
| Replay of executed import → publisher | 409 |
| `GEO_STAGE_TOKEN` → `POST …/approval` | 403 |

---

## 14. Expected data invariants

Capture before cutover and immediately after; they must be equal except for the explicit
acceptance artifacts (§12). Values come from the live §1.3 baseline, not §1.1/§1.2.

- `features` total
- `features` by status (`published`, `archived`, `draft`)
- `feature_provenance` count
- per-layer feature counts (all layers, including `aemet-observation-stations` and
  `amateur-radio-repeaters-es`)
- `layers` count
- `external_sources` count + `aemet` enabled/status
- Alembic revision (must advance to `20260914_10`)
- `import_approvals` count (0 before; only acceptance/approval rows after)

AEMET and amateur-radio data must be byte-for-byte unchanged.

---

## 15. Abort conditions

Stop the cutover immediately if **any** of these is true:

0. **Trusted *execution* access is not available, or the live §1.0 baseline no longer
   matches a fresh §1.3 re-read.** Read-only discovery access is restored (Portainer API),
   but the cutover still requires the ability to change the production stack (Portainer
   write / VPN / LAN management). If only read-only access is available, the cutover stays
   stopped. This is the current state.
1. Migration fails or leaves the revision not at `20260914_10`.
2. Data counts differ unexpectedly from the live baseline (before or after migration).
3. `ADMIN_API_TOKEN` still works **after** step 12 (removal).
4. Geo Admin cannot identify the human (no `Remote-User` / `approved_by` not the user).
5. Geo API becomes reachable on a LAN/public port.
6. Any scoped token exceeds its scope in §13.
7. TLS cannot be trusted on the chosen private hostname.
8. Publisher isolation is broken (extra credentials, a port, or a DB socket).

Aborting at steps 4–6 is cheap: re-pin the previous API digest and restore the legacy
token. Aborting after migration is safe (additive table); restoring the §7 dump is the only
way to remove the schema.

---

## 16. Post-cutover checks

- API `/health` and readiness OK; `alembic current` = `20260914_10`.
- Admin login works on the production hostname; save/refresh/logout behave.
- Authelia healthy; no config warnings; session cookie on the correct registrable domain.
- Publisher runs and reports expected JSON; approval state transitions recorded.
- DB counts match §14 invariants.
- `docker inspect` env **names** confirm least-privilege mapping (§4) — no extra tokens.
- Old `ADMIN_API_TOKEN` removed and now rejected.

---

## 17. CI/CD and image publication

Current state:

- `geo-api-osiris` `.github/workflows/publish.yml` publishes
  `ghcr.io/osviel91/geo-osiris-api` (`latest` + `sha-<short>`, linux/amd64) and
  optionally fires a **Portainer webhook** (dead pattern — do not revive).
- `geo-osiris-admin` `.github/workflows/publish.yml` publishes
  `ghcr.io/osviel91/geo-osiris-admin` similarly.
- `geo-osiris-mcp`: **no workflow**; image is built locally.
- publisher: **no workflow**; image is built locally.

Minimum change required:

1. Add a publish workflow for the **publisher** image (or one workflow that builds it from
   the geo-api repo) producing `ghcr.io/osviel91/geo-osiris-publisher`, linux/amd64, tagged
   by commit SHA, recorded by digest. **Required for Phase 6C.6.**
2. Add a publish workflow for `geo-osiris-mcp` producing
   `ghcr.io/osviel91/geo-osiris-mcp`. **Deferred to Phase 6D.**
3. Keep **image publish** separate from **deploy production**. No automatic deploy.
4. Do not reintroduce the Portainer webhook.

---

## 18. Secrets persistence

Eliminate temporary `/tmp/*.env` dependencies (staging currently keeps tokens only in
container env / a gitignored `.env.staging`).

Recommendation: store production secrets in the deployment platform's secret mechanism —
either Docker Compose `secrets:` (files on the host, `0600`, outside the repo) or Portainer
stack secrets/environment, injected at deploy time. Requirements:

- Never in Git.
- Not in a world-readable file.
- Not in shell history; generated with `openssl rand -hex 32`.
- Documented as *names* only in runbooks.

---

## 19. Authelia production identity

File-backed users (`users_database.yml`, Argon2id) remain acceptable at homelab scale.
Keep the hash file out of Git and `0600`. TOTP may be enabled but **must not be mandatory**
for this cutover unless explicitly chosen. Authelia session secrets belong in §18 storage.

---

## 20. Human identity forwarding

Current approach: the admin BFF, holding `GEO_APPROVE_TOKEN`, sends a trusted
`X-Approver-Identity` header; the API accepts it only from a caller presenting the approve
credential. The proxy strips any client-supplied identity headers and injects trusted ones;
geo-admin fails closed without `ADMIN_PROXY_SECRET`.

**Decision: retain the trusted server-to-server header for 6C.6.** Signing it (HMAC) would
add key distribution and rotation for little gain given the token + network isolation.

Residual risk: anyone who obtains `GEO_APPROVE_TOKEN` *and* can reach the API could assert
an arbitrary approver identity. Mitigations already in place: the token lives only in
geo-admin, geo-admin is internal-only, and the API requires the approve scope. Harden with
signing only if the threat model changes (e.g. the approve token is ever shared).

---

## 21. Monitoring during cutover

- **API**: `/health`, readiness, error rate; watch for 401/403 spikes (scope misconfig).
- **Migration**: `alembic current` before/after; log the exact revision.
- **Admin auth**: successful login, `Remote-User` present, 401/403 counts on BFF routes.
- **Authelia**: container health, config validation, no cookie-domain warnings.
- **Publisher**: exit codes and JSON output; any 409 should be expected (replay/stale).
- **DB**: row counts (§14) and `import_approvals` state transitions.
- **Approval transitions**: pending → approved → executed (and rejected/stale/expired).

(MCP connectivity monitoring is Phase 6D.)

---

## 22. Cleanup actions (after successful cutover)

1. Remove `ADMIN_API_TOKEN` from every production container/config; confirm rejected.
2. Remove the production API host port if the current compose publishes one.
3. Delete the acceptance layer artifacts only if lifecycle support allows; otherwise
   document them as intentional.
4. Remove temporary `.env`/`/tmp` secret files; confirm secrets live only in §18 storage.
5. Remove/retire the Portainer webhook secret from CI.
6. Tag the exact commits deployed and record digests in this document.
7. Keep the §7 backup for the agreed retention period before pruning.

---

## Revised Phase 6C.6 scope

**In scope (after access + live baseline + review):**

- fresh PostGIS backup
- fresh, independent scoped production secrets
- scoped-auth Geo API release
- Alembic → `20260914_10` (approval backend)
- Authelia + admin reverse proxy (VPN/private DNS/internal CA)
- authenticated Geo Admin
- isolated geo-publisher
- legacy `ADMIN_API_TOKEN` removal
- approval + publisher smoke test (operator-driven, no MCP)

**Explicitly out of scope:**

- production MCP and Hermes production connectivity (Phase 6D)
- auto-publisher
- OSIRIS changes
- radio/AEMET mutations

## Open decisions required before execution

1. **Management access** (§0a): restore the VPN (preferred), LAN, or provide a read-only
   Portainer token. Gating item.
2. **Live baseline** (§1.3): collect and reconcile before any mutation.
3. **TOTP** (§19): optional, not required for cutover.
4. **Private DNS name / internal CA** (§5): choose the exact private hostname and CA once
   the live topology is re-inspected.
