from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.security import ADMIN, APPROVE, PUBLISH, READ, STAGE, require_scope


def clear_tokens(monkeypatch) -> None:
    for name in (
        "GEO_READ_TOKEN",
        "GEO_STAGE_TOKEN",
        "GEO_APPROVE_TOKEN",
        "GEO_PUBLISH_TOKEN",
        "GEO_ADMIN_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


def app_with_scopes() -> FastAPI:
    app = FastAPI()
    for path, scope in {
        "/read": READ,
        "/stage": STAGE,
        "/approve": APPROVE,
        "/commit": PUBLISH,
        "/admin": ADMIN,
    }.items():
        app.add_api_route(
            path,
            lambda: {"ok": True},
            methods=["POST"] if path != "/read" else ["GET"],
            dependencies=[Depends(require_scope(scope))],
        )
    return app


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_missing_and_unknown_tokens_are_unauthorized(monkeypatch) -> None:
    clear_tokens(monkeypatch)
    monkeypatch.setenv("GEO_READ_TOKEN", "read")
    client = TestClient(app_with_scopes())
    assert client.get("/read").status_code == 401
    assert client.get("/read", headers=headers("unknown")).status_code == 401


def test_read_token_cannot_mutate(monkeypatch) -> None:
    clear_tokens(monkeypatch)
    monkeypatch.setenv("GEO_READ_TOKEN", "read")
    client = TestClient(app_with_scopes())
    assert client.get("/read", headers=headers("read")).status_code == 200
    assert client.post("/stage", headers=headers("read")).status_code == 403
    assert client.post("/commit", headers=headers("read")).status_code == 403


def test_stage_token_cannot_publish_or_administer(monkeypatch) -> None:
    clear_tokens(monkeypatch)
    monkeypatch.setenv("GEO_STAGE_TOKEN", "stage")
    client = TestClient(app_with_scopes())
    assert client.get("/read", headers=headers("stage")).status_code == 200
    assert client.post("/stage", headers=headers("stage")).status_code == 200
    assert client.post("/commit", headers=headers("stage")).status_code == 403
    assert client.post("/admin", headers=headers("stage")).status_code == 403


def test_approve_publish_and_admin_tokens_are_limited_as_configured(
    monkeypatch,
) -> None:
    clear_tokens(monkeypatch)
    monkeypatch.setenv("GEO_APPROVE_TOKEN", "approve")
    monkeypatch.setenv("GEO_PUBLISH_TOKEN", "publish")
    monkeypatch.setenv("GEO_ADMIN_TOKEN", "admin")
    client = TestClient(app_with_scopes())
    assert client.get("/read", headers=headers("publish")).status_code == 200
    assert client.post("/commit", headers=headers("publish")).status_code == 200
    assert client.post("/stage", headers=headers("publish")).status_code == 403
    assert client.post("/admin", headers=headers("publish")).status_code == 403
    assert client.post("/approve", headers=headers("publish")).status_code == 403
    assert client.post("/approve", headers=headers("approve")).status_code == 200
    assert client.post("/commit", headers=headers("approve")).status_code == 403
    routes = (
        ("/read", client.get),
        ("/stage", client.post),
        ("/admin", client.post),
    )
    for path, method in routes:
        assert method(path, headers=headers("admin")).status_code == 200
    assert client.post("/approve", headers=headers("admin")).status_code == 403
    assert client.post("/commit", headers=headers("admin")).status_code == 403
