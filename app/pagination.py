"""Opaque keyset cursors for bounded admin/public collection queries."""

import base64
import binascii
import json
from typing import Any

from fastapi import HTTPException

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


def clamp_limit(limit: int) -> int:
    if limit < 1:
        raise HTTPException(status_code=422, detail="limit must be positive")
    return min(limit, MAX_LIMIT)


def encode_cursor(values: dict[str, Any]) -> str:
    raw = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def decode_cursor(cursor: str, required: set[str]) -> dict[str, Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
    except (binascii.Error, ValueError) as error:
        raise HTTPException(status_code=422, detail="Invalid cursor") from error
    if not isinstance(data, dict) or not required.issubset(data):
        raise HTTPException(status_code=422, detail="Invalid cursor")
    return data
