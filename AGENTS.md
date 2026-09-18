# AGENTS.md

FastAPI + PostGIS GeoJSON API for OSIRIS (`app/`), plus a separate stdlib-only
publication executor (`publisher/`). OSIRIS is a read-only client of this API.

## Commands

```sh
. .venv/bin/activate
ruff check . && ruff format --check .   # CI enforces both
pytest
```

Tests need a live PostGIS database; most suites `skipif("TEST_DATABASE_URL" not in
os.environ)`. Apply migrations first:

```sh
DATABASE_URL=postgresql+psycopg://osiris:osiris@localhost:5432/osiris alembic upgrade head
TEST_DATABASE_URL=postgresql+psycopg://osiris:osiris@localhost:5432/osiris pytest
```

`pytest` also collects `publisher/` (see `[tool.pytest.ini_options] testpaths`).

## Dependencies

Pinned in `pyproject.toml` **and** in uv-generated `requirements.txt` (hashes; the
Dockerfile builds with `--require-hashes`). After changing `pyproject.toml`:

```sh
uv lock
uv export --no-dev --no-emit-project --no-annotate --output-file requirements.txt
```

## Architecture notes

- Adapters self-register via import side effects into `app.sources.ADAPTERS`.
  `app/main.py` imports `app.aemet` and `app.geojson_source` with `# noqa: F401`;
  a new adapter must be imported there too or `sync_source` cannot find it.
- Auth is env-configured Bearer tokens with scopes (`app/security.py`): `GEO_READ_TOKEN`,
  `GEO_STAGE_TOKEN`, `GEO_APPROVE_TOKEN`, `GEO_PUBLISH_TOKEN`, `GEO_ADMIN_TOKEN`.
  No database-backed auth. Admin token carries READ+STAGE, not APPROVE/PUBLISH.
- Configuration is read directly via `os.getenv`; there is no dotenv loader.
- Migrations live in `migrations/versions/`, named `YYYYMMDD_NN_description.py`.
  `migrations/env.py` honours `DATABASE_URL`.
- `/layers`, `/layers/test`, `/layers/{slug}` and their response shapes are frozen for
  OSIRIS compatibility; don't change them without intent.
- `publisher/publisher.py` is a one-shot stdlib tool that only calls
  `POST /api/v1/admin/imports/{id}/commit`; it owns no approval/commit logic. Built as a
  separate image (`publisher/Dockerfile`, no dependencies).

## Deployment

Two GHCR images (`geo-osiris-api`, `geo-osiris-publisher`) built on push to `main`,
deployed via Portainer using `deploy/compose.yml` (internal PostGIS, external
`geo-osiris_default` network). Set `POSTGRES_PASSWORD` and `CORS_ORIGINS`; run
`alembic upgrade head` before switching traffic. Never expose PostGIS publicly.

## Docs

`README.md` (API/config/deploy), `THREAT-MODEL.md` (security model),
`PRODUCTION-CUTOVER-PHASE-6C.md` (production cutover runbook).
