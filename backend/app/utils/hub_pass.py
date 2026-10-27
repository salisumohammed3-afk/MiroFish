"""
One sign-in across LangSync: reading the hub's pass.

The hub (hub.langsync.ai) is the only place anyone signs in. When someone
opens Forecast, the hub gives their browser a short-lived signed pass, the
cookie ls_pass on .langsync.ai, valid 15 minutes. Forecast checks the pass
against the hub's public key and never makes one: only the hub holds the
private key.

A valid pass for someone with Forecast access becomes a normal Forecast
(Supabase) session, made here on the server with the service key, which the
browser never sees. Contract: langsync-hub
docs/superpowers/specs/2026-10-27-single-sign-on-design.md
"""

from dataclasses import dataclass
from typing import List, Optional

import httpx
import jwt
from jwt import PyJWKClient

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger('mirofish.hub_pass')

HUB = "https://hub.langsync.ai"
PASS_COOKIE = "ls_pass"
PASS_ISSUER = HUB
PASS_AUDIENCE = "langsync-products"
HUB_PRODUCT_ID = "forecast"

# The hub's public keys, fetched once and kept for ten minutes.
_jwks = PyJWKClient(f"{HUB}/.well-known/jwks.json", cache_jwk_set=True, lifespan=600, timeout=5)


@dataclass
class Pass:
    email: str  # lowercased
    name: str
    company: str
    role: str
    products: List[str]
    iat: int
    exp: int


def read_pass(token: Optional[str]) -> Optional[Pass]:
    """The pass checked against the hub's key: signature, issuer, audience,
    expiry and shape. None when any of it fails."""
    if not token:
        return None
    try:
        key = _jwks.get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token, key, algorithms=["ES256"], audience=PASS_AUDIENCE, issuer=PASS_ISSUER,
            options={"require": ["sub", "iat", "exp", "iss", "aud"]},
        )
    except Exception as e:  # bad signature, wrong key, expired, malformed
        logger.debug(f"pass refused: {type(e).__name__}")
        return None
    sub = claims.get("sub")
    products = claims.get("products")
    if not isinstance(sub, str) or "@" not in sub:
        return None
    if not isinstance(products, list) or not all(isinstance(p, str) for p in products):
        return None
    return Pass(
        email=sub.strip().lower(),
        name=claims.get("name") if isinstance(claims.get("name"), str) else "",
        company=claims.get("company") if isinstance(claims.get("company"), str) else "",
        role=claims.get("role") if isinstance(claims.get("role"), str) else "client",
        products=products,
        iat=int(claims["iat"]),
        exp=int(claims["exp"]),
    )


def _admin_headers() -> dict:
    key = Config.SUPABASE_SERVICE_ROLE_KEY
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def auth_user_email(user_id: str) -> Optional[str]:
    """The sign-in account's email for this id, or None if there is no such
    account. Raises when the sign-in service cannot be reached."""
    r = httpx.get(f"{Config.SUPABASE_URL}/auth/v1/admin/users/{user_id}", headers=_admin_headers(), timeout=10)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    email = (r.json() or {}).get("email")
    return email.strip().lower() if isinstance(email, str) else None


def mint_session(email: str) -> dict:
    """A fresh Supabase session for an existing account, made on the server.

    The admin API makes a one-time sign-in token without sending any email,
    and verifying it straight away returns the session. Only ever called for
    an account that is already known to exist, so it never creates anyone.
    """
    base = Config.SUPABASE_URL
    r = httpx.post(f"{base}/auth/v1/admin/generate_link", headers=_admin_headers(),
                   json={"type": "magiclink", "email": email}, timeout=10)
    r.raise_for_status()
    token_hash = (r.json() or {}).get("hashed_token")
    if not token_hash:
        raise RuntimeError("no sign-in token came back")
    anon = Config.SUPABASE_ANON_KEY
    v = httpx.post(f"{base}/auth/v1/verify",
                   headers={"apikey": anon, "Authorization": f"Bearer {anon}", "Content-Type": "application/json"},
                   json={"type": "magiclink", "token_hash": token_hash}, timeout=10)
    v.raise_for_status()
    s = v.json() or {}
    if not s.get("access_token") or not s.get("refresh_token"):
        raise RuntimeError("no session came back")
    return {"access_token": s["access_token"], "refresh_token": s["refresh_token"]}
