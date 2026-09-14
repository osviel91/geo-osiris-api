import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import engine
from app.main import app
from app.models import Feature, FeatureProvenance, ImportApproval

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="requires a PostGIS test database",
)

client = TestClient(app)
STAGE = {"Authorization": "Bearer stage"}
APPROVE = {"Authorization": "Bearer approve"}
PUBLISH = {"Authorization": "Bearer publish"}
ADMIN = {"Authorization": "Bearer admin"}


@pytest.fixture(autouse=True)
def empty_database(monkeypatch):
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
            "filename": "approval.csv",
            "format": "csv",
            "content": content,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def request(import_id: str, status: str = "published") -> dict:
    response = client.post(
        f"/api/v1/admin/imports/{import_id}/approval-request",
        headers=STAGE,
        json={"status": status},
    )
    assert response.status_code == 200, response.text
    return response.json()


def approve(import_id: str, decision: str = "approve") -> dict:
    response = client.post(
        f"/api/v1/admin/imports/{import_id}/approval",
        headers=APPROVE,
        json={"decision": decision, "reason": "test" if decision == "reject" else None},
    )
    assert response.status_code == 200, response.text
    return response.json()


def commit(import_id: str, status: str = "published"):
    return client.post(
        f"/api/v1/admin/imports/{import_id}/commit",
        headers=PUBLISH,
        json={"status": status},
    )


def test_scopes_and_ready_request_contract() -> None:
    layer = create_layer("approval-scopes")
    staged = stage(layer["id"], "longitude,latitude\n-3.7,40.4\n")
    request_url = f"/api/v1/admin/imports/{staged['id']}/approval-request"
    approval_url = f"/api/v1/admin/imports/{staged['id']}/approval"
    commit_url = f"/api/v1/admin/imports/{staged['id']}/commit"

    assert (
        client.post(
            approval_url, headers=STAGE, json={"decision": "approve"}
        ).status_code
        == 403
    )
    assert (
        client.post(commit_url, headers=STAGE, json={"status": "draft"}).status_code
        == 403
    )
    assert (
        client.post("/api/v1/admin/imports", headers=APPROVE, json={}).status_code
        == 403
    )
    assert (
        client.post(commit_url, headers=APPROVE, json={"status": "draft"}).status_code
        == 403
    )
    assert (
        client.post(request_url, headers=PUBLISH, json={"status": "draft"}).status_code
        == 403
    )
    assert (
        client.post("/api/v1/admin/layers", headers=PUBLISH, json={}).status_code == 403
    )
    assert (
        client.post(commit_url, headers=ADMIN, json={"status": "draft"}).status_code
        == 403
    )
    assert commit(staged["id"], "draft").status_code == 409

    invalid = stage(layer["id"], "longitude,latitude\nnot-a-number,40.4\n")
    assert (
        client.post(
            f"/api/v1/admin/imports/{invalid['id']}/approval-request",
            headers=STAGE,
            json={"status": "draft"},
        ).status_code
        == 409
    )


def test_rejection_history_and_deterministic_snapshot() -> None:
    layer = create_layer("approval-history")
    staged = stage(layer["id"], "longitude,latitude\n-3.7,40.4\n-3.8,40.5\n")
    first = request(staged["id"])
    assert first["requester"] == "geo-stage"
    assert first["snapshot"]["content_hash"]
    assert first["snapshot"]["mapping_hash"]
    assert (
        client.post(
            f"/api/v1/admin/imports/{staged['id']}/approval-request",
            headers=STAGE,
            json={"status": "published"},
        ).status_code
        == 409
    )
    rejected = approve(staged["id"], "reject")
    assert rejected["state"] == "rejected"
    second = request(staged["id"])
    assert second["fingerprint"] == first["fingerprint"]
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ImportApproval)) == 2


def test_mutation_stales_approval_and_blocks_execution() -> None:
    layer = create_layer(
        "approval-stale", duplicate_detection={"identity_properties": ["callsign"]}
    )
    existing = client.post(
        f"/api/v1/admin/layers/{layer['id']}/features",
        headers=STAGE,
        json={
            "geometry": {"type": "Point", "coordinates": [-3.7, 40.4]},
            "properties": {"callsign": "DUP"},
        },
    ).json()
    assert existing["id"]
    staged = stage(layer["id"], "longitude,latitude,callsign\n-3.7,40.4,DUP\n")
    resolution_url = f"/api/v1/admin/imports/{staged['id']}/rows/1/resolution"
    assert (
        client.post(
            resolution_url, headers=STAGE, json={"resolution": "skip"}
        ).status_code
        == 200
    )
    request(staged["id"])
    assert (
        client.post(
            resolution_url, headers=STAGE, json={"resolution": "import_anyway"}
        ).status_code
        == 200
    )
    assert commit(staged["id"]).status_code == 409
    with Session(engine) as session:
        approval = session.scalar(select(ImportApproval))
        assert approval is not None and approval.state == "stale"
    assert request(staged["id"])["state"] == "pending"


def test_expiry_failure_audit_and_single_use_execution() -> None:
    layer = create_layer("approval-execution")
    staged = stage(layer["id"], "longitude,latitude\n-3.7,40.4\n-3.8,40.5\n")
    request(staged["id"])
    approve(staged["id"])
    response = commit(staged["id"])
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "committed"
    assert commit(staged["id"]).status_code == 409
    with Session(engine) as session:
        approval = session.scalar(select(ImportApproval))
        assert approval is not None and approval.state == "executed"
        assert approval.executor == "geo-publish"
        assert session.scalar(select(func.count()).select_from(Feature)) == 2
        assert session.scalar(select(func.count()).select_from(FeatureProvenance)) == 2

    expiring = stage(layer["id"], "longitude,latitude\n-3.9,40.6\n")
    request(expiring["id"])
    with Session(engine) as session:
        approval = session.scalar(
            select(ImportApproval).where(ImportApproval.import_id == expiring["id"])
        )
        assert approval is not None
        approval.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        expiring_approval_id = approval.id
        session.commit()
    detail = client.get(
        f"/api/v1/admin/approvals/{expiring_approval_id}", headers=ADMIN
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["state"] == "expired"
    assert (
        client.post(
            f"/api/v1/admin/imports/{expiring['id']}/approval",
            headers=APPROVE,
            json={"decision": "approve"},
        ).status_code
        == 409
    )
    with Session(engine) as session:
        approval = session.scalar(
            select(ImportApproval).where(ImportApproval.import_id == expiring["id"])
        )
        assert approval is not None and approval.state == "expired"


def test_concurrent_execution_commits_once() -> None:
    layer = create_layer("approval-concurrent")
    staged = stage(layer["id"], "longitude,latitude\n-3.7,40.4\n-3.8,40.5\n")
    request(staged["id"])
    approve(staged["id"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: commit(staged["id"]).status_code, range(2)))
    assert sorted(responses) == [200, 409]
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Feature)) == 2
        approval = session.scalar(select(ImportApproval))
        assert approval is not None and approval.state == "executed"


def test_failed_execution_records_terminal_audit(monkeypatch) -> None:
    layer = create_layer("approval-failure")
    staged = stage(layer["id"], "longitude,latitude\n-3.8,40.5\n")
    request(staged["id"])
    approve(staged["id"])
    monkeypatch.setattr(
        "app.imports._commit_job",
        lambda *args: (_ for _ in ()).throw(SQLAlchemyError("test failure")),
    )
    assert commit(staged["id"]).status_code == 409
    with Session(engine) as session:
        approval = session.scalar(select(ImportApproval))
        assert approval is not None and approval.state == "failed"
        assert approval.failure_reason == "Authoritative import commit failed"


def test_approver_identity_comes_from_trusted_header() -> None:
    layer = create_layer("approval-identity")
    staged = stage(layer["id"], "longitude,latitude\n-3.7,40.4\n")
    request(staged["id"])
    response = client.post(
        f"/api/v1/admin/imports/{staged['id']}/approval",
        headers={**APPROVE, "X-Approver-Identity": "admin"},
        json={"decision": "approve"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["approver"] == "admin"

    other = stage(layer["id"], "longitude,latitude\n-3.8,40.5\n")
    request(other["id"])
    rejected = client.post(
        f"/api/v1/admin/imports/{other['id']}/approval",
        headers={**APPROVE, "X-Approver-Identity": "bad identity!"},
        json={"decision": "approve"},
    )
    assert rejected.status_code == 400

    fallback = client.post(
        f"/api/v1/admin/imports/{other['id']}/approval",
        headers=APPROVE,
        json={"decision": "approve"},
    )
    assert fallback.status_code == 200, fallback.text
    assert fallback.json()["approver"] == "geo-approve"


def test_list_and_get_approvals() -> None:
    layer = create_layer("approval-read")
    staged = stage(layer["id"], "longitude,latitude\n-3.7,40.4\n-3.8,40.5\n")
    created = request(staged["id"])

    listing = client.get(
        "/api/v1/admin/approvals",
        headers=STAGE,
        params={"state": "active", "import_id": staged["id"]},
    )
    assert listing.status_code == 200, listing.text
    item = listing.json()["items"][0]
    assert item["id"] == created["id"]
    assert item["layer_name"] == "approval-read"
    assert item["layer_slug"] == "approval-read"
    assert item["row_count"] == 2
    assert item["valid_count"] == 2
    assert item["requested_status"] == "published"
    assert item["state"] == "pending"

    detail = client.get(f"/api/v1/admin/approvals/{created['id']}", headers=STAGE)
    assert detail.status_code == 200
    assert detail.json()["fingerprint"] == created["fingerprint"]

    assert (
        client.get(
            "/api/v1/admin/approvals", headers=STAGE, params={"state": "bogus"}
        ).status_code
        == 422
    )
    assert client.get("/api/v1/admin/approvals").status_code == 401
    assert (
        client.get(
            "/api/v1/admin/approvals/00000000-0000-0000-0000-000000000000"
        ).status_code
        == 401
    )
