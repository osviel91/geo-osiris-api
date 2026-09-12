# Handoff — OSIRIS Custom Geo API + GitHub CI/CD + Portainer

## Context

OSIRIS is already running successfully on a ZimaBoard managed with ZimaOS/Docker. Runtime impact on the ZimaBoard is low enough to continue extending the platform.

The goal is **not** to fork OSIRIS heavily yet. First build an independent service that exposes our own geospatial data through a stable API, package it as a Docker image, publish it to GHCR, and deploy it through Portainer. Once this backend is stable, OSIRIS will consume it as a custom layer.

This service should become the future integration boundary for sources such as Home Assistant, homelab infrastructure, DMR/radio data, Spanish public datasets, weather, traffic, sensors, etc.

## Primary objective

Create a production-quality but deliberately small repository for a service tentatively named:

`osiris-geo-api`

Suggested GitHub repository:

`osviel91/osiris-geo-api`

The agent may choose a better name only if there is a strong reason; otherwise keep this name.

The deliverable is a repository that can be cloned, tested, built as a Docker image, published to GHCR, and deployed as a Portainer stack on the ZimaBoard.

---

# Architecture

Initial architecture:

```text
OSIRIS
   │
   │ HTTP / GeoJSON
   ▼
osiris-geo-api
   │
   ├── /health
   ├── /layers
   └── /layers/test

Future:

osiris-geo-api
   ├── adapters/home_assistant
   ├── adapters/homelab
   ├── adapters/dmr
   ├── adapters/aemet
   ├── adapters/traffic
   └── persistence/PostGIS (later, NOT now)
```

Use FastAPI + Python.

Do **not** add Postgres/PostGIS, Redis, Celery, Kafka, authentication, MCP, or any other infrastructure in this phase unless strictly required for the baseline.

Keep the service stateless.

---

# Functional requirements

Implement at minimum:

## `GET /health`

Response:

```json
{
  "status": "ok"
}
```

HTTP 200.

## `GET /layers`

Returns metadata describing currently available layers.

Example shape:

```json
{
  "layers": [
    {
      "id": "test",
      "name": "Test Layer",
      "description": "Static validation layer",
      "endpoint": "/layers/test"
    }
  ]
}
```

Do not over-engineer the schema yet, but model it cleanly enough to evolve later.

## `GET /layers/test`

Return valid RFC 7946-style GeoJSON `FeatureCollection` with several static test features.

Example:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Point",
        "coordinates": [-3.7, 40.4]
      },
      "properties": {
        "id": "test-1",
        "name": "OSVI TEST",
        "source": "local",
        "category": "test",
        "status": "online"
      }
    }
  ]
}
```

Use generic/static locations for the test dataset. Do not encode private home coordinates or secrets in the repo.

Add at least 3 distinct test points so rendering a layer is visually obvious.

---

# API design constraints

Prefer a clean separation such as:

```text
app/
  main.py
  api/
  models/
  services/
  layers/
```

But avoid architecture ceremony for a tiny service. A small, maintainable structure is better than premature DDD.

Use Pydantic models where they add contract value.

The API must expose OpenAPI normally through FastAPI.

Enable CORS deliberately. For the first LAN deployment, allow the OSIRIS origin(s) through configuration rather than hard-coding `*` if practical. A configurable comma-separated `CORS_ORIGINS` env var is sufficient. A permissive default may be used for the initial proof of concept only if clearly documented.

Add structured/simple logging to stdout so Portainer can display useful logs.

---

# Configuration

Use environment variables and sane defaults.

Recommended baseline:

```text
APP_ENV=production
APP_HOST=0.0.0.0
APP_PORT=8000
LOG_LEVEL=INFO
CORS_ORIGINS=*
```

No `.env` containing real values should be committed.

Provide `.env.example`.

---

# Quality and tests

Use `pytest`.

Minimum tests:

- `/health` returns 200 and the expected contract.
- `/layers` returns the test layer.
- `/layers/test` returns `FeatureCollection`.
- Test layer contains at least one feature.
- Every test feature has valid Point geometry and coordinate order `[longitude, latitude]`.
- API schema/models serialize correctly.

Prefer Ruff for lint/format validation.

Optional but useful: mypy/pyright only if it stays lightweight.

CI must fail on test or lint failure.

---

# Docker image

Create a production Dockerfile.

Requirements:

- Python 3.12 slim (unless there is a concrete incompatibility).
- Non-root runtime user.
- No compiler/build dependencies left in the final runtime unless required.
- Install dependencies reproducibly.
- Run Uvicorn/FastAPI on `0.0.0.0:8000`.
- Add Docker `HEALTHCHECK` if implementation is reliable and lightweight.
- Keep the image small.
- Support `linux/amd64`; this is required for the ZimaBoard.
- `linux/arm64` may also be published if buildx makes this trivial.

Do not build OSIRIS into this container. It is an independent service.

---

# Docker Compose / Portainer stack

Provide a repository file such as:

`deploy/compose.yml`

Baseline:

```yaml
services:
  geo-api:
    image: ghcr.io/osviel91/osiris-geo-api:latest
    container_name: osiris-geo-api
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      APP_ENV: production
      APP_HOST: 0.0.0.0
      APP_PORT: 8000
      LOG_LEVEL: INFO
      CORS_ORIGINS: "*"
```

Use the actual image/repository name if it differs.

For the initial deployment no bind mount or persistent volume should be required.

Do not set arbitrary CPU/RAM limits initially. We want to observe real usage first.

The stack should be suitable for deployment from Portainer using **Git repository** mode, with the compose path pointing to `deploy/compose.yml`.

---

# GitHub repository

If GitHub CLI is authenticated, create the repository:

```text
osviel91/osiris-geo-api
```

Default visibility: **public**, unless the current environment/user configuration strongly indicates otherwise. If repo creation would have an irreversible or ambiguous consequence, stop and ask before creation rather than guessing.

Initialize with:

- README.md
- LICENSE (MIT is acceptable unless user/repo policy suggests something else)
- `.gitignore`
- `.dockerignore`
- `.env.example`
- `pyproject.toml`
- Dockerfile
- tests
- deploy/compose.yml
- GitHub Actions workflows

Use conventional, understandable commits. Do not force-push.

---

# CI/CD design

Use GitHub Actions.

GitHub officially supports publishing Docker images to GHCR using `GITHUB_TOKEN`, `docker/login-action`, `docker/metadata-action`, and `docker/build-push-action`.

## Workflow 1 — CI

`.github/workflows/ci.yml`

Triggers:

- pull requests
- push to `main`

Run:

1. checkout
2. setup Python 3.12
3. install dependencies
4. Ruff lint/format check
5. pytest
6. optionally build Docker image without pushing, to catch Dockerfile failures

Use dependency caching where reasonable.

## Workflow 2 — image publish / CD

`.github/workflows/publish.yml`

Trigger:

- push to `main` after CI-compatible code changes, OR
- GitHub release/tag if the implementation chooses a release-driven production model.

For this small homelab service, `main -> latest` is acceptable initially.

Publish to:

```text
ghcr.io/osviel91/osiris-geo-api
```

Tags should include at least:

- `latest` for `main`
- immutable commit SHA tag, e.g. `sha-<shortsha>` or equivalent

Optionally add semantic version tags when Git tags/releases are introduced.

Use:

```yaml
permissions:
  contents: read
  packages: write
```

Prefer pinning third-party GitHub Actions to commit SHAs if convenient; GitHub recommends SHA pinning for stronger supply-chain guarantees.

---

# Portainer CD strategy

Do not assume a Portainer edition feature without checking the deployed Portainer capabilities.

There are two supported paths:

## Preferred path A — Git stack + GitOps update

Configure the stack in Portainer from the GitHub repository and `deploy/compose.yml`.

If this Portainer installation supports **GitOps updates**, enable them.

Possible mechanisms in current Portainer versions:

- polling the Git repository, or
- webhook-triggered update.

Enable `Re-pull image`/equivalent so a redeploy obtains the newest GHCR image.

Important: a normal Portainer **stack webhook is a Business Edition feature** according to current Portainer documentation. Git-deployed stacks may expose GitOps update mechanisms depending on edition/version. Detect what is actually available rather than assuming.

## Preferred path B — GitHub Action calls Portainer webhook

If Portainer exposes a usable GitOps/stack webhook, store it in GitHub as:

```text
PORTAINER_WEBHOOK_URL
```

After the GHCR push succeeds:

```bash
curl --fail --silent --show-error -X POST "$PORTAINER_WEBHOOK_URL"
```

Never commit the webhook URL.

The deployment job must only run after image publication succeeds.

## Fallback — Portainer GitOps polling

If webhook deployment is unavailable, configure Portainer to poll the repository and document the required setting.

Be careful: if the Compose file always references `:latest` and only the image changes, a pure Git-change detector may not notice anything. In that case choose one of these explicit strategies:

1. enable Portainer's re-pull/forced redeploy option if available, or
2. use immutable image tags and update a tracked deployment tag/compose value in Git, or
3. keep automatic image publication while using a manual Portainer redeploy until a supported secure automation path is configured.

Do not implement insecure SSH tricks or expose the Docker socket remotely just to force CD.

---

# GHCR authentication from Portainer

If the GHCR package is public, Portainer should be able to pull without registry credentials.

If the image/package is private, configure a GHCR registry credential in Portainer using a GitHub token with only the minimum package read permissions needed.

Never put a GitHub PAT directly into `compose.yml`.

---

# README requirements

Document:

- project purpose
- local development
- test commands
- Docker build/run
- API endpoints
- sample GeoJSON response
- environment variables
- deployment via Portainer
- GHCR image name
- CI/CD behavior
- how to configure Portainer Git stack
- how to configure optional webhook secret
- basic troubleshooting

Include commands that can be copied directly.

---

# Security baseline

- Do not commit credentials or home coordinates.
- Run container as non-root.
- Avoid privileged mode.
- Do not mount `/var/run/docker.sock`.
- Do not expose Portainer APIs/tokens inside the application.
- Dependency versions should be reasonably pinned/locked.
- GitHub Actions should use least privilege.
- CD webhook/token must live in GitHub Secrets.

---

# Acceptance criteria / Definition of Done

The phase is complete only when all of the following are true:

1. GitHub repository exists and has clean history.
2. `pytest` passes locally.
3. Ruff checks pass.
4. Docker image builds locally.
5. `/health` works from the container.
6. `/layers` works.
7. `/layers/test` returns valid GeoJSON.
8. GitHub CI passes.
9. GitHub Actions publishes an image to GHCR.
10. Portainer stack is configured from `deploy/compose.yml` or clear exact deployment instructions are provided if direct access to Portainer is unavailable.
11. ZimaBoard pulls and runs the GHCR image successfully.
12. `http://<ZIMA-IP>:8000/health` returns `{"status":"ok"}`.
13. `http://<ZIMA-IP>:8000/layers/test` returns the expected FeatureCollection.
14. No secrets/private coordinates exist in Git history.
15. README explains deployment and future extension points.

Do not start modifying OSIRIS itself until this backend phase is complete.

---

# Follow-up phase (NOT part of this implementation unless explicitly requested)

Once this service is live, the next handoff will modify/integrate OSIRIS minimally so that it can consume `/layers/test` and render those features as a custom layer.

Desired direction:

```text
OSIRIS UI
   ↓
GET /layers
   ↓
discover available local layers
   ↓
GET /layers/{id}
   ↓
render GeoJSON
```

Long term, adding a new data source should normally require a new adapter in `osiris-geo-api`, **not a new OSIRIS fork change**.

Potential future sources:

- Home Assistant
- homelab nodes/services
- DMR repeaters/radio data
- AEMET
- Madrid/Spanish traffic and transport
- air quality
- public emergency/incidents feeds
- user-imported GeoJSON/CSV
- historical storage in PostGIS
- Hermes/MCP analysis layer

None of those should be implemented in this phase.

---

# Agent operating instructions

Work incrementally and verify after every meaningful step.

Before modifying an existing environment, inspect it first.

Do not destroy/recreate unrelated containers or stacks.

Do not alter the current working OSIRIS deployment.

If Portainer access is unavailable from the coding environment, finish the repository/CI/CD work and produce the exact final manual Portainer steps instead of inventing access.

If GitHub authentication is unavailable, stop only at the point that requires it and report the exact command/action the user must perform; everything else should still be prepared and committed locally.

At the end, report:

- repository URL
- latest commit SHA
- CI status
- GHCR image/tag
- Portainer deployment status
- health-check output
- test summary
- any manual action still required
