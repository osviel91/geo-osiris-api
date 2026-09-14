"""Narrow one-shot publication executor for Geo Hub.

Its only responsibility is to call
``POST /api/v1/admin/imports/{import_id}/commit`` with ``GEO_PUBLISH_TOKEN`` for
an import that a human has already approved. Geo Hub owns approval state,
fingerprint verification, expiry, locking, commit readiness, feature creation
and provenance. This process owns none of that and never retries.

Configuration (environment only):
- ``GEO_API_URL``        trusted internal Geo Hub base URL, e.g. http://geo-api:8000
- ``GEO_PUBLISH_TOKEN``  publication credential, scope ``geo.publish``

The token is never printed or included in output.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

DEFAULT_TIMEOUT_SECONDS = 30.0
COMMIT_PATH = "/api/v1/admin/imports/{import_id}/commit"

_HTTP_MESSAGES = {
    401: "publisher authentication failure",
    403: "publisher lacks required scope",
    404: "import not found",
    409: "approval or import is not executable",
    422: "invalid request",
}


class PublisherError(Exception):
    """A bounded, secret-free publication failure."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.http_status = http_status
        self.detail = detail


def execute(
    import_id: str,
    *,
    api_url: str,
    token: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, str | None]:
    """Execute an already-approved import. Raises PublisherError on failure."""
    try:
        uuid.UUID(import_id)
    except (AttributeError, TypeError, ValueError):
        raise PublisherError("import_id must be a UUID") from None

    url = api_url.rstrip("/") + COMMIT_PATH.format(import_id=import_id)
    request = urllib.request.Request(
        url,
        data=b"{}",
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        raise _http_error(error) from None
    except (TimeoutError, urllib.error.URLError, OSError):
        raise PublisherError("Geo Hub is unreachable") from None
    except json.JSONDecodeError:
        raise PublisherError("Geo Hub returned an unreadable response") from None

    if not isinstance(body, dict):
        raise PublisherError("Geo Hub returned an unreadable response")
    return {
        "import_id": import_id,
        "status": "executed",
        "committed_at": body.get("committed_at"),
        "approval_state": "executed",
    }


def _http_error(error: urllib.error.HTTPError) -> PublisherError:
    status = error.code
    detail: str | None = None
    try:
        payload = json.loads(error.read() or b"{}")
        if isinstance(payload, dict):
            raw = payload.get("detail")
            detail = raw if isinstance(raw, str) else None
    except (json.JSONDecodeError, OSError):
        detail = None
    message = _HTTP_MESSAGES.get(status, f"Geo Hub rejected the request ({status})")
    return PublisherError(message, http_status=status, detail=detail)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="geo-publisher",
        description="Execute an already-approved Geo Hub import.",
    )
    parser.add_argument("import_id", help="UUID of the approved import")
    args = parser.parse_args(argv)

    api_url = os.environ.get("GEO_API_URL", "")
    token = os.environ.get("GEO_PUBLISH_TOKEN", "")
    if not api_url:
        return _fail(args.import_id, "GEO_API_URL is not configured")
    if not token:
        return _fail(args.import_id, "GEO_PUBLISH_TOKEN is not configured")
    try:
        timeout = float(
            os.environ.get("GEO_PUBLISHER_TIMEOUT", DEFAULT_TIMEOUT_SECONDS)
        )
    except ValueError:
        return _fail(args.import_id, "GEO_PUBLISHER_TIMEOUT is not a number")

    try:
        result = execute(args.import_id, api_url=api_url, token=token, timeout=timeout)
    except PublisherError as error:
        return _fail(
            args.import_id,
            error.message,
            http_status=error.http_status,
            detail=error.detail,
        )
    print(json.dumps(result, sort_keys=True))
    return 0


def _fail(
    import_id: str,
    message: str,
    *,
    http_status: int | None = None,
    detail: str | None = None,
) -> int:
    payload: dict[str, object] = {
        "import_id": import_id,
        "status": "error",
        "error": message,
    }
    if http_status is not None:
        payload["http_status"] = http_status
    if detail is not None:
        payload["detail"] = detail
    print(json.dumps(payload, sort_keys=True))
    return 1


if __name__ == "__main__":
    sys.exit(main())
