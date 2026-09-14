import os
import re
import secrets
from collections.abc import Callable

from fastapi import Header, HTTPException

READ = "geo.read"
STAGE = "geo.stage"
APPROVE = "geo.approve"
PUBLISH = "geo.publish"
ADMIN = "geo.admin"


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _credentials() -> dict[str, tuple[str, frozenset[str]]]:
    tokens = {
        "GEO_READ_TOKEN": ("geo-read", frozenset({READ})),
        "GEO_STAGE_TOKEN": ("geo-stage", frozenset({READ, STAGE})),
        "GEO_APPROVE_TOKEN": ("geo-approve", frozenset({READ, APPROVE})),
        "GEO_PUBLISH_TOKEN": ("geo-publish", frozenset({READ, PUBLISH})),
        "GEO_ADMIN_TOKEN": ("geo-admin", frozenset({READ, STAGE, ADMIN})),
    }
    return {
        token: credential
        for name, credential in tokens.items()
        if (token := os.getenv(name))
    }


def _credential_for(authorization: str | None) -> tuple[str, frozenset[str]]:
    if not authorization or not authorization.startswith("Bearer "):
        raise _unauthorized("Authentication required")
    presented = authorization.removeprefix("Bearer ")
    for token, credential in _credentials().items():
        if secrets.compare_digest(presented, token):
            return credential
    raise _unauthorized("Invalid authentication credentials")


def require_scope(scope: str) -> Callable[[str | None], None]:
    def dependency(authorization: str | None = Header(default=None)) -> None:
        if scope not in _credential_for(authorization)[1]:
            raise HTTPException(status_code=403, detail="Insufficient scope")

    return dependency


def require_actor(scope: str) -> Callable[[str | None], str]:
    def dependency(authorization: str | None = Header(default=None)) -> str:
        actor, scopes = _credential_for(authorization)
        if scope not in scopes:
            raise HTTPException(status_code=403, detail="Insufficient scope")
        return actor

    return dependency


APPROVER_IDENTITY_HEADER = "X-Approver-Identity"
_APPROVER_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@+-]{0,99}$")


def require_approver(scope: str = APPROVE) -> Callable[[str | None, str | None], str]:
    """Resolve the approver identity for the human-approval route.

    The trusted server-side approver component (Geo Admin) authenticates with the
    approve credential and asserts the authenticated human subject in a header.
    The header is only honoured on this route, so a browser that never holds the
    credential cannot spoof it. Without the header the credential label is used,
    which keeps non-UI clients and tests working.
    """

    def dependency(
        authorization: str | None = Header(default=None),
        x_approver_identity: str | None = Header(
            default=None, alias=APPROVER_IDENTITY_HEADER
        ),
    ) -> str:
        actor, scopes = _credential_for(authorization)
        if scope not in scopes:
            raise HTTPException(status_code=403, detail="Insufficient scope")
        if x_approver_identity is None:
            return actor
        identity = x_approver_identity.strip()
        if not _APPROVER_IDENTITY.match(identity):
            raise HTTPException(status_code=400, detail="Invalid approver identity")
        return identity

    return dependency
