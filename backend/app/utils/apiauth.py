"""
The front door for requests that carry an API key instead of a sign-in:
Forecast's /api/v1 routes and its /mcp endpoint. Every refusal is one plain
sentence an admin can act on, and a database hiccup says "try again" rather
than pretending the key is dead.
"""

import threading
import time

from flask import jsonify, request

from .apikeys import PRODUCT_NAME, KeyStoreError, check_api_key
from .logger import get_logger

logger = get_logger('mirofish.apiauth')

# Hub product ids and their names, for "This key is for X, not Y".
# Copied from langsync-hub src/lib/config.ts.
PRODUCT_NAMES = {
    "aiscan": "AIScan",
    "atlas": "Atlas",
    "metrics": "Metrics",
    "content-mapper": "Content Mapper",
    "adhub": "Content Hub",
    "onboarding": "Onboarding",
    "prompt-review": "Prompt Review",
    "answer-map": "Answer Map",
    "audits": "Audit Generator",
    "cut-room": "Cut Room",
    "sales-engine": "Sales Engine",
    "learning-centre": "Learning Centre",
    "forecast": "Forecast",
    "inspo": "Inspo Wheel",
    "pods": "Pods",
    "story-boss": "Story Boss",
}

# Requests per key per minute, counted in this server process only. A soft
# brake on a runaway agent, not a guarantee across instances.
LIMIT = 120
WINDOW_SECONDS = 60
_seen = {}
_lock = threading.Lock()


def _over_limit(key_id: str) -> bool:
    now = time.monotonic()
    with _lock:
        w = _seen.get(key_id)
        if not w or now - w[0] >= WINDOW_SECONDS:
            _seen[key_id] = [now, 1]
            return False
        w[1] += 1
        return w[1] > LIMIT


def refuse(status: int, error: str):
    return jsonify({"error": error}), status


def require_api_key(need: str):
    """Returns (key, None) when the request may go on, else (None, (response, status)).

    need is "read" or "write". key is {"id", "access"}.
    """
    auth = request.headers.get("Authorization", "")
    raw = auth[7:] if auth[:7].lower() == "bearer " else ""
    raw = raw or request.headers.get("X-Api-Key", "")
    try:
        result = check_api_key(raw)
    except KeyStoreError as e:
        logger.error(f"[forecast] API key check: {e}")
        return None, refuse(503, "Could not check the API key, please try again")
    if not result["ok"]:
        if result["reason"] == "missing":
            return None, refuse(401, "Add your API key as Authorization: Bearer lsk_...")
        if result["reason"] == "other-product":
            pid = result.get("product_id", "")
            return None, refuse(401, f"This key is for {PRODUCT_NAMES.get(pid, pid)}, not {PRODUCT_NAME}")
        return None, refuse(401, "This API key is not valid, or has been cancelled or has expired")
    if need == "write" and result["access"] != "write":
        return None, refuse(403, "This key is read only")
    if _over_limit(result["id"]):
        return None, refuse(429, "Too many requests, slow down")
    return {"id": result["id"], "access": result["access"]}, None
