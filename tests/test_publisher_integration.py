"""End-to-end publisher test against the real API and a disposable PostGIS DB.

The API runs over real HTTP (uvicorn in a background thread) so the publisher's
stdlib client, the approval gate, and the commit logic are all exercised.
"""

import importlib.util
import os
import socket
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.database import engine
from app.main import app
from app.models import Feature, FeatureProvenance, ImportApproval

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="requires a PostGIS test database",
)

_SPEC = importlib.util.spec_from_file_location(
    "publisher", Path(__file__).resolve().parents[1] / "publisher" / "publisher.py"
)
publisher = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(publisher)

client = TestClient(app)
STAGE = {"Authorization": "Bearer stage"}
APPROVE = {"Authorization": "Bearer approve"}


@pytest.fixture(autouse=True)
def scoped_tokens_and_empty_database(monkeypatch):
    for name, value in {
        "GEO_STAGE_TOKEN": "stage",
        "GEO_APPROVE_TOKEN": "approve",
        "GEO_PUBLISH_TOKEN": "publish",
        "GEO_ADMIN_TOKEN": "admin",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE import_approvals, import_rows, imports, external_sources, "
                "feature_provenance, features, layers CASCADE"
            )
        )


@pytest.fixture(scope="module")
def api_base_url():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started, "uvicorn did not start"
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True


def create_layer(slug: str, **metadata) -> dict:
    response = client.post(
        "/api/v1/admin/layers",
        headers=STAGE,
        json={
            "slug": slug,
            "name": slug,
            "category": "TEST",
            "mode": "managed",
            "geometry_types": ["Point"],
            "metadata_": metadata,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def stage(layer_id: str, content: str) -> dict:
    response = client.post(
        "/api/v1/admin/imports",
        headers=STAGE,
        json={
            "layer_id": layer_id,
            "filename": "publisher.csv",
            "format": "csv",
            "content": content,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def request_approval(import_id: str, status: str = "published") -> None:
    response = client.post(
        f"/api/v1/admin/imports/{import_id}/approval-request",
        headers=STAGE,
        json={"status": status},
    )
    assert response.status_code == 200, response.text


def approve(import_id: str) -> None:
    response = client.post(
        f"/api/v1/admin/imports/{import_id}/approval",
        headers=APPROVE,
        json={"decision": "approve"},
    )
    assert response.status_code == 200, response.text


def test_publisher_executes_approved_import(api_base_url):
    layer = create_layer("publisher-success")
    staged = stage(layer["id"], "longitude,latitude\n-3.7,40.4\n-3.8,40.5\n")
    request_approval(staged["id"])
    approve(staged["id"])

    result = publisher.execute(
        staged["id"], api_url=api_base_url, token="publish", timeout=10
    )
    assert result["status"] == "executed"
    assert result["import_id"] == staged["id"]
    assert result["committed_at"]

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Feature)) == 2
        assert session.scalar(select(func.count()).select_from(FeatureProvenance)) == 2
        approval = session.scalar(select(ImportApproval))
        assert approval is not None and approval.state == "executed"
        assert approval.executor == "geo-publish"

    with pytest.raises(publisher.PublisherError) as error:
        publisher.execute(
            staged["id"], api_url=api_base_url, token="publish", timeout=10
        )
    assert error.value.http_status == 409
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Feature)) == 2


def test_publisher_denied_without_approval(api_base_url):
    layer = create_layer("publisher-unapproved")
    staged = stage(layer["id"], "longitude,latitude\n-3.7,40.4\n")

    with pytest.raises(publisher.PublisherError) as error:
        publisher.execute(
            staged["id"], api_url=api_base_url, token="publish", timeout=10
        )
    assert error.value.http_status == 409
    assert error.value.detail == "No active approval request"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Feature)) == 0


def test_publisher_denied_when_approval_expired(api_base_url):
    layer = create_layer("publisher-expired")
    staged = stage(layer["id"], "longitude,latitude\n-3.7,40.4\n")
    request_approval(staged["id"])
    approve(staged["id"])
    with Session(engine) as session:
        approval = session.scalar(select(ImportApproval))
        assert approval is not None
        approval.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    with pytest.raises(publisher.PublisherError) as error:
        publisher.execute(
            staged["id"], api_url=api_base_url, token="publish", timeout=10
        )
    assert error.value.http_status == 409
    assert error.value.detail == "Approval has expired"
    with Session(engine) as session:
        approval = session.scalar(select(ImportApproval))
        assert approval is not None and approval.state == "expired"
        assert session.scalar(select(func.count()).select_from(Feature)) == 0


def test_publisher_denied_when_approval_is_stale(api_base_url):
    layer = create_layer(
        "publisher-stale", duplicate_detection={"identity_properties": ["callsign"]}
    )
    existing = client.post(
        f"/api/v1/admin/layers/{layer['id']}/features",
        headers=STAGE,
        json={
            "geometry": {"type": "Point", "coordinates": [-3.7, 40.4]},
            "properties": {"callsign": "DUP"},
        },
    )
    assert existing.status_code == 200, existing.text
    staged = stage(layer["id"], "longitude,latitude,callsign\n-3.7,40.4,DUP\n")
    resolution_url = f"/api/v1/admin/imports/{staged['id']}/rows/1/resolution"
    assert (
        client.post(
            resolution_url, headers=STAGE, json={"resolution": "skip"}
        ).status_code
        == 200
    )
    request_approval(staged["id"])
    assert (
        client.post(
            resolution_url, headers=STAGE, json={"resolution": "import_anyway"}
        ).status_code
        == 200
    )

    with pytest.raises(publisher.PublisherError) as error:
        publisher.execute(
            staged["id"], api_url=api_base_url, token="publish", timeout=10
        )
    assert error.value.http_status == 409
    assert error.value.detail == "No active approval request"
    with Session(engine) as session:
        approval = session.scalar(select(ImportApproval))
        assert approval is not None and approval.state == "stale"
        assert session.scalar(select(func.count()).select_from(Feature)) == 1
