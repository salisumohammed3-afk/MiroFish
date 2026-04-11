"""
Authentication middleware for Flask routes.
Validates Supabase JWTs via the Supabase Auth API and attaches user context to Flask's g object.
"""

import functools
from dataclasses import dataclass
from typing import Optional

from flask import request, g, jsonify

from ..services.supabase_client import get_supabase_admin
from ..utils.logger import get_logger

logger = get_logger('mirofish.auth')


@dataclass
class AuthUser:
    """Authenticated user context attached to Flask g."""
    id: str
    email: str
    company_id: Optional[str]
    role: str  # super_admin | admin | member | viewer
    display_name: Optional[str] = None
    must_change_password: bool = False


def _validate_token(token: str) -> Optional[dict]:
    """Validate a Supabase access token by calling the Auth Admin API."""
    try:
        sb = get_supabase_admin()
        user_response = sb.auth.admin.get_user_by_id  # existence check
        # Use the GoTrue admin endpoint to get user from token
        result = sb.auth.get_user(token)
        if result and result.user:
            return {"sub": result.user.id, "email": result.user.email}
    except Exception as e:
        logger.debug(f"Token validation failed: {e}")
    return None


def _get_user_profile(user_id: str) -> Optional[dict]:
    """Fetch user profile from Supabase (admin client bypasses RLS)."""
    sb = get_supabase_admin()
    result = sb.table("user_profiles").select("*").eq("id", user_id).execute()
    if result.data:
        return result.data[0]
    return None


def _build_auth_user(token: str) -> Optional[AuthUser]:
    """Validate token and build AuthUser, or return None."""
    payload = _validate_token(token)
    if not payload:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    profile = _get_user_profile(user_id)
    if not profile or not profile.get("is_active", True):
        return None

    return AuthUser(
        id=user_id,
        email=profile["email"],
        company_id=profile.get("company_id"),
        role=profile.get("role", "member"),
        display_name=profile.get("display_name"),
        must_change_password=profile.get("must_change_password", False),
    )


def require_auth(f):
    """Decorator: require a valid Supabase JWT. Attaches AuthUser to g.user."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"success": False, "error": "Missing or invalid Authorization header"}), 401

        token = auth_header.split(" ", 1)[1]
        user = _build_auth_user(token)

        if not user:
            return jsonify({"success": False, "error": "Invalid or expired token"}), 401

        g.user = user
        return f(*args, **kwargs)
    return wrapper


def require_admin(f):
    """Decorator: require super_admin role."""
    @functools.wraps(f)
    @require_auth
    def wrapper(*args, **kwargs):
        if g.user.role != "super_admin":
            return jsonify({"success": False, "error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return wrapper


def require_company_admin(f):
    """Decorator: require admin or super_admin role."""
    @functools.wraps(f)
    @require_auth
    def wrapper(*args, **kwargs):
        if g.user.role not in ("super_admin", "admin"):
            return jsonify({"success": False, "error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return wrapper


def optional_auth(f):
    """Decorator: attach user if token present, but don't require it."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        g.user = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
            g.user = _build_auth_user(token)
        return f(*args, **kwargs)
    return wrapper
