"""
The client lock: while one of us is showing a client their work, no screen
names another client. The hub sets the `ls_client_lock` cookie on
.langsync.ai; Forecast only reads it. Contract:
langsync-hub/docs/client-lock-contract.md

The cookie is not signed, so it may only ever narrow what staff see. It is
applied to super_admin only; clients are never affected.
"""

import base64
import json
import time
from typing import Optional

CLIENT_LOCK_COOKIE = "ls_client_lock"
HUB_PRODUCT_ID = "forecast"
# A company id that matches nothing, used when the locked client has no
# Forecast company, so every company-scoped list comes back empty.
NO_COMPANY = "00000000-0000-0000-0000-000000000000"


def active_client_lock(value: Optional[str]) -> Optional[dict]:
    """The lock if the cookie holds one that has not run out yet, otherwise None."""
    if not value:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict) or raw.get("v") != 1:
        return None
    if not isinstance(raw.get("company"), str) or not raw["company"]:
        return None
    exp = raw.get("exp")
    if not isinstance(exp, (int, float)) or exp <= time.time():
        return None
    products = raw.get("products") if isinstance(raw.get("products"), dict) else {}
    return {
        "company": raw["company"],
        "name": raw.get("name") if isinstance(raw.get("name"), str) else "",
        "products": {k: v for k, v in products.items() if isinstance(v, str) and v},
        "exp": exp,
    }
