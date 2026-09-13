# OSIRIS Geo API

GeoJSON API and PostGIS-backed Geo Data Hub for OSIRIS. OSIRIS remains a read-only client; management and source ingestion are added in later Phase 3 commits.

## API

| Endpoint | Response |
| --- | --- |
| `GET /health` | `{"status":"ok"}` |
| `GET /ready` | Database readiness |
| `GET /layers` | Available layer metadata |
| `GET /layers/test` | Static RFC 7946-style GeoJSON FeatureCollection |
| `GET /api/v1/layers` | Enabled persistent-layer summaries |
| `GET /api/v1/layers/{slug}` | Published persistent GeoJSON FeatureCollection |
| `GET /api/v1/layers/{slug}/features` | Alias for the layer GeoJSON collection |

Example response:

```json
{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Point","coordinates":[-3.7038,40.4168]},"properties":{"id":"test-1","name":"Madrid test point","source":"local","category":"test","status":"online"}}]}
```

OpenAPI documentation is available at `/docs`.

`/layers`, `/layers/test`, and their response shapes are retained for OSIRIS compatibility. The static `test` layer remains available if PostGIS is unavailable; persistent layers require `/ready` to be healthy.

## Database and migrations

PostGIS is required for persistent layers. Apply migrations explicitly, before starting a new Geo API image:

```sh
DATABASE_URL=postgresql+psycopg://osiris:<password>@localhost:5432/osiris alembic upgrade head
```

The initial migration creates `layers`, `features`, and `feature_provenance`. Feature geometry is PostGIS `GEOMETRY` in SRID 4326 with a GIST index. A feature may retain multiple provenance records. External identifiers are unique only within their layer.

## Local development

```sh
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

```sh
ruff check .
ruff format --check .
pytest
```

## Configuration

Copy `.env.example` for local reference. The application reads these environment variables directly:

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_ENV` | `production` | Deployment label |
| `APP_HOST` | `0.0.0.0` | Uvicorn bind host |
| `APP_PORT` | `8000` | Uvicorn port |
| `LOG_LEVEL` | `INFO` | Stdout logging level |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `HOST_PORT` | `8000` | Host port used by `deploy/compose.yml` |
| `DATABASE_URL` | none | PostgreSQL/PostGIS SQLAlchemy URL |
| `POSTGRES_PASSWORD` | none | Password for the Compose PostGIS service |

For LAN production, set `CORS_ORIGINS` to the OSIRIS URL, for example `http://osiris.lan:3000`, rather than `*`.

## Docker

```sh
docker build -t osiris-geo-api .
docker run --rm -p 8000:8000 -e CORS_ORIGINS="http://osiris.lan:3000" osiris-geo-api
curl http://localhost:8000/health
curl http://localhost:8000/layers/test
```

The container runs as a non-root user and has an HTTP liveness check. `/health` does not check PostGIS; use `/ready` for readiness.

## Portainer

1. In Portainer, create a Stack from the Git repository `https://github.com/osviel91/geo-osiris-api`.
2. Set the compose path to `deploy/compose.yml` and deploy it.
3. Set `CORS_ORIGINS` in the stack environment to the actual OSIRIS origin before deployment.
4. Optionally set `HOST_PORT` in the Portainer environment, for example `8080`; the API will then be available at `http://<ZIMA-IP>:8080`.
5. If GitOps updates are available, enable image re-pull/forced redeploy. Otherwise, redeploy the stack manually after an image publication.

The Compose stack starts an internal PostGIS service and joins the existing `geo-osiris_default` network. Set `POSTGRES_PASSWORD` in Portainer and run `docker compose -f deploy/compose.yml run --rm geo-api alembic upgrade head` from the new image before switching traffic. Do not expose the PostGIS service publicly.

The service is then available at `http://<ZIMA-IP>:8000/health` and `http://<ZIMA-IP>:8000/layers/test`. Public GHCR packages need no registry credential; for a private package, configure a Portainer GHCR registry credential with package-read-only access.

The publish workflow creates `latest` and immutable `sha-<shortsha>` tags on every push to `main`. If the installed Portainer edition exposes a supported webhook, store its URL in the GitHub Actions secret `PORTAINER_WEBHOOK_URL`; the workflow calls it only after the image push succeeds. Do not put that URL or a GitHub token in Compose.

## Troubleshooting

```sh
docker logs osiris-geo-api
curl -i http://<ZIMA-IP>:8000/health
docker pull ghcr.io/osviel91/geo-osiris-api:latest
```

If the pull fails, confirm the package visibility or Portainer registry credential. If the browser blocks layer requests, set `CORS_ORIGINS` to the exact OSIRIS origin and redeploy.

Future data sources belong behind new API layers/adapters here; OSIRIS should only consume this API.
