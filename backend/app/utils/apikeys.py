"""
API keys: how LangSync admins connect Forecast to other tools, Claude and
agents. Keys for every LangSync product live in one store on the shared
database (public.hub_api_keys), so the hub can list and cancel any of them.
This module makes, reads and checks keys; only a hash of each key is stored.

A key looks like lsk_<hub product id>_<64 hex>. The product id in the key
means a key pasted into the wrong product is refused with a clear reason.

Contract: langsync-hub docs/superpowers/specs/2026-10-27-api-keys-design.md
"""

import hashlib
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from ..config import Config
from .logger import get_logger

logger = get_logger('mirofish.apikeys')

PRODUCT_ID = "forecast"
PRODUCT_NAME = "Forecast"

_KEY_SHAPE = re.compile(r"^lsk_([a-z][a-z-]*)_([0-9a-f]{64})$")


class KeyStoreError(Exception):
    """The key store could not be asked. Callers answer "try again", never "bad key"."""


def hash_key(key: str) -> str:
    return hashlib.sha256(key.strip().encode()).hexdigest()


def make_key(product_id: str) -> dict:
    secret = secrets.token_hex(32)
    key = f"lsk_{product_id}_{secret}"
    # The label shown in lists: the product part plus 8 random characters.
    return {"key": key, "prefix": f"lsk_{product_id}_{secret[:8]}", "hash": hash_key(key)}


def parse_key(raw: str) -> Optional[str]:
    """The product id inside a well formed key, else None."""
    m = _KEY_SHAPE.match((raw or "").strip())
    return m.group(1) if m else None


def rpc(fn: str, args: dict) -> Any:
    """Calls a function in the platform database's public schema with the service key.

    Forecast's own tables sit in another schema (SUPABASE_SCHEMA), so the
    profile header pins this call to public, where the key store lives.
    """
    url, key = Config.SUPABASE_URL, Config.SUPABASE_SERVICE_ROLE_KEY
    if not url or not key:
        raise KeyStoreError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are not set")
    try:
        res = httpx.post(
            f"{url.rstrip('/')}/rest/v1/rpc/{fn}",
            json=args,
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Content-Profile": "public",
                "Accept-Profile": "public",
            },
            timeout=10.0,
        )
    except httpx.HTTPError as e:
        raise KeyStoreError(f"{fn}: {e.__class__.__name__}") from e
    if res.status_code >= 300:
        raise KeyStoreError(f"{fn}: {res.status_code} {res.text[:200]}")
    return res.json() if res.content else None


def _to_row(r: dict) -> dict:
    return {
        "id": r["id"], "product_id": r["product_id"], "name": r["name"], "prefix": r["prefix"],
        "access": r["access"], "created_by": r["created_by"], "created_at": r["created_at"],
        "expires_at": r.get("expires_at"), "revoked_at": r.get("revoked_at"), "last_used_at": r.get("last_used_at"),
    }


def list_api_keys() -> list:
    return [_to_row(r) for r in (rpc("hub_api_key_list", {"p_product": PRODUCT_ID}) or [])]


def create_api_key(name: str, access: str, expires_at: Optional[str], created_by: str) -> dict:
    """Makes a key. The full key is in the answer this once and never again."""
    made = make_key(PRODUCT_ID)
    new_id = rpc("hub_api_key_create", {
        "p_product": PRODUCT_ID, "p_name": name, "p_access": access, "p_expires_at": expires_at,
        "p_created_by": created_by, "p_prefix": made["prefix"], "p_hash": made["hash"],
    })
    row = next((k for k in list_api_keys() if k["id"] == new_id), None)
    if row is None:
        raise KeyStoreError("The key was made but could not be read back")
    return {"key": made["key"], "row": row}


def revoke_api_key(key_id: str) -> bool:
    return bool(rpc("hub_api_key_revoke", {"p_product": PRODUCT_ID, "p_id": key_id}))


def check_api_key(raw: str) -> dict:
    """{"ok": True, "id", "access"} or {"ok": False, "reason", ["product_id"]}.

    Raises KeyStoreError when the store cannot be asked.
    """
    if not (raw or "").strip():
        return {"ok": False, "reason": "missing"}
    product = parse_key(raw)
    if not product:
        return {"ok": False, "reason": "malformed"}
    if product != PRODUCT_ID:
        return {"ok": False, "reason": "other-product", "product_id": product}
    rows = rpc("hub_api_key_check", {"p_product": PRODUCT_ID, "p_hash": hash_key(raw)}) or []
    if not rows:
        return {"ok": False, "reason": "unknown"}
    return {"ok": True, "id": rows[0]["id"], "access": rows[0]["access"]}


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def active_key_label() -> str:
    """The count shown in the admin area. A failure says so instead of breaking the page."""
    try:
        now = datetime.now(timezone.utc)
        live = [k for k in list_api_keys()
                if not k["revoked_at"] and (not k["expires_at"] or _parse_time(k["expires_at"]) > now)]
        return f"{len(live)} active"
    except Exception as e:  # noqa: BLE001
        logger.error(f"[api-keys] count: {e}")
        return "Could not count"
