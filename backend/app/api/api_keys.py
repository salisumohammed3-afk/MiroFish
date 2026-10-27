"""
Admin area, API keys: LangSync admins make, see and cancel the keys that let
other tools, Claude and agents use Forecast. In Forecast, LangSync staff are
the super_admin role. Client admins, and staff while the hub's client lock is
on, are refused. The full key is only ever in the answer that makes it.
"""

import functools
import re
from datetime import datetime, timezone

from flask import g, jsonify, request

from . import auth_bp
from ..middleware import auth as auth_mw
from ..utils.apikeys import active_key_label, create_api_key, list_api_keys, revoke_api_key
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.api_keys')

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _bad(error, status=400):
    return jsonify({"success": False, "error": error}), status


def key_admin(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        user = auth_mw._build_auth_user(header.split(" ", 1)[1]) if header.startswith("Bearer ") else None
        if not user:
            return _bad("Sign in first", 401)
        if user.role != "super_admin":
            return _bad("Only LangSync admins can manage API keys", 403)
        g.user = user
        return f(*args, **kwargs)
    return wrapper


def expiry_from(value):
    """A date from the form ("2026-12-31") means the end of that day; a full time is kept.

    None when there is none, "invalid" when it cannot be read.
    """
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        return "invalid"
    try:
        if _DATE.match(value):
            d = datetime.fromisoformat(f"{value}T23:59:59+00:00")
        else:
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
    except ValueError:
        return "invalid"
    return d.isoformat()


@auth_bp.route('/admin/api-keys', methods=['GET'])
@key_admin
def list_keys():
    try:
        return jsonify({"success": True, "data": list_api_keys()})
    except Exception as e:  # noqa: BLE001
        logger.error(f"[api-keys] list: {e}")
        return _bad("Could not load the API keys, please try again", 500)


@auth_bp.route('/admin/api-keys/count', methods=['GET'])
@key_admin
def count_keys():
    return jsonify({"success": True, "data": {"label": active_key_label()}})


@auth_bp.route('/admin/api-keys', methods=['POST'])
@key_admin
def make_key():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _bad("The request body was not JSON")
    name = body.get("name").strip() if isinstance(body.get("name"), str) else ""
    if not name:
        return _bad("Give the key a name")
    if len(name) > 80:
        return _bad("Keep the name under 80 characters")
    access = body.get("access") or "read"
    if access not in ("read", "write"):
        return _bad("Choose read only, or read and change")
    expires_at = expiry_from(body.get("expiresAt"))
    if expires_at == "invalid":
        return _bad("That expiry date could not be read")
    if expires_at and datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc):
        return _bad("The expiry date has already passed")
    try:
        made = create_api_key(name=name, access=access, expires_at=expires_at, created_by=g.user.email)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[api-keys] create: {e}")
        return _bad("Could not make the key, please try again", 500)
    return jsonify({"success": True, "data": made}), 201


@auth_bp.route('/admin/api-keys/<key_id>', methods=['DELETE'])
@key_admin
def cancel_key(key_id):
    """Cancels a key. It stops working on its very next request."""
    gone = "No such key, or it is already cancelled"
    if not _UUID.match(key_id):
        return _bad(gone, 404)
    try:
        if not revoke_api_key(key_id):
            return _bad(gone, 404)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[api-keys] cancel: {e}")
        return _bad("Could not cancel the key, please try again", 500)
    return jsonify({"success": True})
