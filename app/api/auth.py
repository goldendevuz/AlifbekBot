"""Admin authentication and Role-Based Access Control (RBAC)."""
import hashlib
import hmac
import os
import time
from typing import List, Optional
from fastapi import Cookie, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel

ADMIN_SECRET = os.getenv("ADMIN_SECRET_KEY", "alifbo_admin_secret_key_2026")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "alifbo2026")
ADMIN_ID = os.getenv("ADMIN_ID", "557407324")


class LoginRequest(BaseModel):
    username: str
    password: str


class AdminUser:
    def __init__(self, username: str, role: str):
        self.username = username
        self.role = role


def generate_token(username: str, role: str) -> str:
    """Generate a signed HMAC token for admin session."""
    ts = str(int(time.time()))
    payload = f"{username}:{role}:{ts}"
    signature = hmac.new(ADMIN_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def verify_token(token: str) -> Optional[AdminUser]:
    try:
        parts = token.split(":")
        if len(parts) != 4:
            return None
        username, role, ts, signature = parts
        # Token valid for 7 days
        if int(time.time()) - int(ts) > 7 * 86400:
            return None
        expected = hmac.new(ADMIN_SECRET.encode(), f"{username}:{role}:{ts}".encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, signature):
            return AdminUser(username=username, role=role)
        return None
    except Exception:
        return None


def get_current_admin(
    authorization: Optional[str] = Header(None),
    alifbo_admin_token: Optional[str] = Cookie(None),
) -> AdminUser:
    """Extract and verify admin identity from Authorization header or cookie."""
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ")[1].strip()
    elif alifbo_admin_token:
        token = alifbo_admin_token

    if not token:
        # Default fallback for local single-admin mode if no token provided yet
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to access Alifbo Admin Suite",
        )

    admin = verify_token(token)
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired admin session token",
        )
    return admin


def require_role(allowed_roles: List[str]):
    """RBAC dependency to enforce permission tiers."""
    def dependency(admin: AdminUser = Depends(get_current_admin)):
        if admin.role != "superadmin" and admin.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Action requires one of the following roles: {allowed_roles}",
            )
        return admin
    return dependency
