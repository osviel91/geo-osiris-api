# OSIRIS Geo API

Small, stateless GeoJSON API intended to supply custom layers to OSIRIS. It ships one public static validation layer and has no database, credentials, or private coordinates.

## API

| Endpoint | Response |
| --- | --- |
| `GET /health` | `{"status":"ok"}` |
| `GET /layers` | Available layer metadata |
| `GET /layers/test` | Static RFC 7946-style GeoJSON FeatureCollection |

Example response:

```json
{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Point","coordinates":[-3.7038,40.4168]},"properties":{"id":"test-1","name":"Madrid test point","source":"local","category":"test","status":"online"}}]}
```

OpenAPI documentation is available at `/docs`.

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

For LAN production, set `CORS_ORIGINS` to the OSIRIS URL, for example `http://osiris.lan:3000`, rather than `*`.

## Docker

```sh
docker build -t osiris-geo-api .
docker run --rm -p 8000:8000 -e CORS_ORIGINS="http://osiris.lan:3000" osiris-geo-api
curl http://localhost:8000/health
curl http://localhost:8000/layers/test
```

The published image is `ghcr.io/osviel91/geo-osiris-api:latest`. The container runs as a non-root user and has an HTTP health check.

## Portainer

1. In Portainer, create a Stack from the Git repository `https://github.com/osviel91/geo-osiris-api`.
2. Set the compose path to `deploy/compose.yml` and deploy it.
3. Set `CORS_ORIGINS` in the stack environment to the actual OSIRIS origin before deployment.
4. If GitOps updates are available, enable image re-pull/forced redeploy. Otherwise, redeploy the stack manually after an image publication.

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
