import os

from fastapi import Header, HTTPException


def require_admin(authorization: str | None = Header(default=None)) -> None:
    token = os.getenv("ADMIN_API_TOKEN")
    if not token or authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="Invalid administrator token")
