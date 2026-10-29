"""
Is each paid service and key Forecast runs on still working? Read only, for the
hub's Monitoring page (GET /api/v1/health). Each check is the cheapest honest
call, they run side by side, each is capped at 5 seconds and the whole answer
at 7. The answer only ever carries one of the fixed reasons below; vendor and
database detail goes to the server log, never to the caller.
"""

from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone

import httpx
import redis

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger('mirofish.health')

PRODUCT_ID = "forecast"
CHECK_TIMEOUT_SECONDS = 5.0
ROUTE_BUDGET_SECONDS = 7.0

OUT_OF_CREDIT = "Out of credit"
KEY_REJECTED = "Key rejected"
KEY_NOT_SET = "Key not set"
NOT_ANSWERING = "Not answering"
COULD_NOT_CHECK = "Could not check"

WORKING = {"status": "working"}


def broken(reason):
    return {"status": "broken", "reason": reason}


def unknown():
    return {"status": "unknown", "reason": COULD_NOT_CHECK}


def check_anthropic(key):
    """One 1-token Haiku message: the only Anthropic call that shows an empty balance."""
    try:
        res = httpx.post(
            "https://api.anthropic.com/v1/messages",
            json={"model": "claude-haiku-4-5", "max_tokens": 1, "messages": [{"role": "user", "content": "ok"}]},
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            timeout=CHECK_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as e:
        logger.warning(f"[health] anthropic: {e.__class__.__name__}")
        return broken(NOT_ANSWERING)
    if res.status_code == 200:
        return dict(WORKING)
    logger.warning(f"[health] anthropic: {res.status_code} {res.text[:200]}")
    if res.status_code == 400 and "credit balance" in res.text.lower():
        return broken(OUT_OF_CREDIT)
    if res.status_code in (401, 403):
        return broken(KEY_REJECTED)
    return unknown()


_RANK = {"working": 0, "unknown": 1, "broken": 2}


def claude_service():
    """Forecast's main AI (LLM_*, through Anthropic's OpenAI-compatible endpoint), its
    reports (REPORT_LLM_*) and its knowledge map reading (GRAPHITI_*) all run on Claude.
    Each distinct key is checked once; the worst answer is the one shown."""
    entry = {"id": "anthropic", "name": "Anthropic (Claude)"}
    wanted = [Config.REPORT_LLM_API_KEY, Config.GRAPHITI_ANTHROPIC_API_KEY]
    if "anthropic.com" in (Config.LLM_BASE_URL or ""):
        wanted.append(Config.LLM_API_KEY)
    if not all(wanted):
        return {**entry, **broken(KEY_NOT_SET)}
    results = [check_anthropic(k) for k in dict.fromkeys(wanted)]
    worst = max(results, key=lambda r: _RANK[r["status"]])
    return {**entry, **worst}


def falkordb_service():
    """A ping to the knowledge map database (FalkorDB, Railway private network)."""
    entry = {"id": "falkordb", "name": "Knowledge map database"}
    if not Config.FALKORDB_HOST:
        return {**entry, **broken(KEY_NOT_SET)}
    client = None
    try:
        client = redis.Redis(
            host=Config.FALKORDB_HOST,
            port=Config.FALKORDB_PORT,
            username=Config.FALKORDB_USERNAME,
            password=Config.FALKORDB_PASSWORD,
            socket_timeout=CHECK_TIMEOUT_SECONDS,
            socket_connect_timeout=CHECK_TIMEOUT_SECONDS,
        )
        client.ping()
        return {**entry, **WORKING}
    except redis.exceptions.AuthenticationError as e:
        logger.warning(f"[health] falkordb: {e.__class__.__name__}")
        return {**entry, **broken(KEY_REJECTED)}
    except redis.exceptions.ResponseError as e:
        text = str(e).upper()
        logger.warning(f"[health] falkordb: {e.__class__.__name__}")
        if "WRONGPASS" in text or "NOAUTH" in text:
            return {**entry, **broken(KEY_REJECTED)}
        return {**entry, **unknown()}
    except (redis.exceptions.TimeoutError, redis.exceptions.ConnectionError) as e:
        logger.warning(f"[health] falkordb: {e.__class__.__name__}")
        return {**entry, **broken(NOT_ANSWERING)}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[health] falkordb: {e.__class__.__name__}")
        return {**entry, **unknown()}
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass


def supabase_service():
    """One row from Forecast's companies table with the platform service key."""
    entry = {"id": "supabase", "name": "Platform database"}
    url, key = Config.SUPABASE_URL, Config.SUPABASE_SERVICE_ROLE_KEY
    if not url or not key:
        return {**entry, **broken(KEY_NOT_SET)}
    try:
        res = httpx.get(
            f"{url.rstrip('/')}/rest/v1/companies",
            params={"select": "id", "limit": "1"},
            headers={"apikey": key, "Authorization": f"Bearer {key}", "Accept-Profile": Config.SUPABASE_SCHEMA},
            timeout=CHECK_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as e:
        logger.warning(f"[health] supabase: {e.__class__.__name__}")
        return {**entry, **broken(NOT_ANSWERING)}
    if res.status_code == 200:
        return {**entry, **WORKING}
    logger.warning(f"[health] supabase: {res.status_code} {res.text[:200]}")
    if res.status_code in (401, 403):
        return {**entry, **broken(KEY_REJECTED)}
    return {**entry, **unknown()}


CHECKS = [
    ({"id": "anthropic", "name": "Anthropic (Claude)"}, lambda: claude_service()),
    ({"id": "falkordb", "name": "Knowledge map database"}, lambda: falkordb_service()),
    ({"id": "supabase", "name": "Platform database"}, lambda: supabase_service()),
]


def build_health():
    pool = ThreadPoolExecutor(max_workers=len(CHECKS))
    try:
        futures = [(entry, pool.submit(fn)) for entry, fn in CHECKS]
        wait([f for _, f in futures], timeout=ROUTE_BUDGET_SECONDS)
        services = []
        for entry, f in futures:
            if not f.done():
                services.append({**entry, **broken(NOT_ANSWERING)})
                continue
            try:
                services.append(f.result())
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[health] {entry['id']}: {e.__class__.__name__}")
                services.append({**entry, **unknown()})
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return {
        "product": PRODUCT_ID,
        "checkedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "services": services,
    }
