"""GET /api/v1/health: is each paid service and key Forecast runs on still working.

Every vendor call is stubbed. The answer may only ever carry the fixed reasons,
never vendor or database text.
"""

import httpx
import pytest
import redis

from app.config import Config
from app.services import health
from app.utils import apiauth

READ = {"Authorization": "Bearer read-key"}
REASONS = {"Out of credit", "Key rejected", "Key not set", "Not answering", "Could not check"}


class Resp:
    def __init__(self, status, text=""):
        self.status_code = status
        self.text = text


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(Config, "LLM_API_KEY", "sk-ant-main")
    monkeypatch.setattr(Config, "LLM_BASE_URL", "https://api.anthropic.com/v1/")
    monkeypatch.setattr(Config, "REPORT_LLM_API_KEY", "sk-ant-main")
    monkeypatch.setattr(Config, "GRAPHITI_ANTHROPIC_API_KEY", "sk-ant-main")
    monkeypatch.setattr(Config, "FALKORDB_HOST", "falkordb.internal")
    monkeypatch.setattr(Config, "FALKORDB_PASSWORD", "pw")
    monkeypatch.setattr(Config, "SUPABASE_URL", "https://db.example")
    monkeypatch.setattr(Config, "SUPABASE_SERVICE_ROLE_KEY", "service")


@pytest.fixture
def keys(monkeypatch):
    apiauth._seen.clear()
    monkeypatch.setattr(apiauth, "check_api_key", lambda raw: (
        {"ok": True, "id": "k-read", "access": "read"} if raw.strip() == "read-key" else {"ok": False, "reason": "unknown"}))
    yield
    apiauth._seen.clear()


# The Anthropic answer mapping

@pytest.mark.parametrize("resp,expected", [
    (Resp(200, '{"content":[]}'), {"status": "working"}),
    (Resp(400, '{"error":{"message":"Your credit balance is too low to access the Anthropic API."}}'),
     {"status": "broken", "reason": "Out of credit"}),
    (Resp(401, '{"error":{"type":"authentication_error"}}'), {"status": "broken", "reason": "Key rejected"}),
    (Resp(403, '{"error":{"type":"permission_error"}}'), {"status": "broken", "reason": "Key rejected"}),
    (Resp(400, '{"error":{"message":"something else entirely"}}'), {"status": "unknown", "reason": "Could not check"}),
    (Resp(529, 'overloaded'), {"status": "unknown", "reason": "Could not check"}),
])
def test_anthropic_answers_map_to_plain_reasons(monkeypatch, resp, expected):
    sent = {}

    def post(url, json=None, headers=None, timeout=None):
        sent.update(url=url, json=json, headers=headers, timeout=timeout)
        return resp

    monkeypatch.setattr(health.httpx, "post", post)
    assert health.check_anthropic("sk-ant-x") == expected
    assert sent["url"] == "https://api.anthropic.com/v1/messages"
    assert sent["json"]["model"] == "claude-haiku-4-5"
    assert sent["json"]["max_tokens"] == 1
    assert sent["headers"]["x-api-key"] == "sk-ant-x"
    assert sent["timeout"] <= 5


def test_anthropic_timeout_is_not_answering(monkeypatch):
    def post(*a, **k):
        raise httpx.ReadTimeout("slow")
    monkeypatch.setattr(health.httpx, "post", post)
    assert health.check_anthropic("sk-ant-x") == {"status": "broken", "reason": "Not answering"}


def test_anthropic_key_missing_is_key_not_set(monkeypatch, env):
    monkeypatch.setattr(Config, "REPORT_LLM_API_KEY", None)
    called = []
    monkeypatch.setattr(health.httpx, "post", lambda *a, **k: called.append(1) or Resp(200))
    assert health.claude_service()["status"] == "broken"
    assert health.claude_service()["reason"] == "Key not set"


def test_each_distinct_claude_key_is_checked_once_and_the_worst_wins(monkeypatch, env):
    monkeypatch.setattr(Config, "REPORT_LLM_API_KEY", "sk-ant-reports")
    seen = []

    def post(url, json=None, headers=None, timeout=None):
        seen.append(headers["x-api-key"])
        return Resp(200) if headers["x-api-key"] == "sk-ant-main" else Resp(400, "credit balance is too low")

    monkeypatch.setattr(health.httpx, "post", post)
    out = health.claude_service()
    assert sorted(seen) == ["sk-ant-main", "sk-ant-reports"]
    assert out == {"id": "anthropic", "name": "Anthropic (Claude)", "status": "broken", "reason": "Out of credit"}


# The knowledge map database (FalkorDB)

class FakeRedis:
    def __init__(self, error=None):
        self.error = error

    def ping(self):
        if self.error:
            raise self.error
        return True

    def close(self):
        pass


@pytest.mark.parametrize("error,expected", [
    (None, {"status": "working"}),
    (redis.exceptions.AuthenticationError("invalid password"), {"status": "broken", "reason": "Key rejected"}),
    (redis.exceptions.ResponseError("WRONGPASS invalid username-password pair"), {"status": "broken", "reason": "Key rejected"}),
    (redis.exceptions.TimeoutError("timed out"), {"status": "broken", "reason": "Not answering"}),
    (redis.exceptions.ConnectionError("refused"), {"status": "broken", "reason": "Not answering"}),
    (RuntimeError("odd"), {"status": "unknown", "reason": "Could not check"}),
])
def test_falkordb_ping(monkeypatch, env, error, expected):
    made = {}

    def factory(**kw):
        made.update(kw)
        return FakeRedis(error)

    monkeypatch.setattr(health.redis, "Redis", factory)
    out = health.falkordb_service()
    assert {k: v for k, v in out.items() if k in ("status", "reason")} == expected
    assert out["name"] == "Knowledge map database"
    assert made["socket_timeout"] <= 5 and made["socket_connect_timeout"] <= 5


def test_falkordb_host_missing_is_key_not_set(monkeypatch, env):
    monkeypatch.setattr(Config, "FALKORDB_HOST", None)
    assert health.falkordb_service()["reason"] == "Key not set"


# The platform database

@pytest.mark.parametrize("resp,expected", [
    (Resp(200, "[]"), {"status": "working"}),
    (Resp(401, '{"message":"Invalid API key"}'), {"status": "broken", "reason": "Key rejected"}),
    (Resp(500, "boom"), {"status": "unknown", "reason": "Could not check"}),
])
def test_platform_database(monkeypatch, env, resp, expected):
    monkeypatch.setattr(health.httpx, "get", lambda *a, **k: resp)
    out = health.supabase_service()
    assert {k: v for k, v in out.items() if k in ("status", "reason")} == expected


def test_platform_database_key_missing(monkeypatch, env):
    monkeypatch.setattr(Config, "SUPABASE_SERVICE_ROLE_KEY", None)
    assert health.supabase_service()["reason"] == "Key not set"


# The route

def test_no_key_is_401_and_no_vendor_is_called(client, monkeypatch, env):
    def boom(*a, **k):
        raise AssertionError("a vendor was called without a key")
    monkeypatch.setattr(health.httpx, "post", boom)
    monkeypatch.setattr(health.httpx, "get", boom)
    monkeypatch.setattr(health.redis, "Redis", boom)
    res = client.get("/api/v1/health")
    assert res.status_code == 401
    assert res.get_json() == {"error": "Add your API key as Authorization: Bearer lsk_..."}


def test_wrong_key_is_401_like_other_routes(client, keys, env):
    res = client.get("/api/v1/health", headers={"Authorization": "Bearer nope"})
    assert res.status_code == 401
    assert res.get_json() == {"error": "This API key is not valid, or has been cancelled or has expired"}


def test_route_answers_the_contract_shape(client, keys, env, monkeypatch):
    monkeypatch.setattr(health.httpx, "post", lambda *a, **k: Resp(400, "Your credit balance is too low"))
    monkeypatch.setattr(health.httpx, "get", lambda *a, **k: Resp(200, "[]"))
    monkeypatch.setattr(health.redis, "Redis", lambda **kw: FakeRedis())
    res = client.get("/api/v1/health", headers=READ)
    assert res.status_code == 200
    body = res.get_json()
    assert body["product"] == "forecast"
    assert body["checkedAt"].endswith("Z") or "+00:00" in body["checkedAt"]
    assert "sources" not in body
    by_id = {s["id"]: s for s in body["services"]}
    assert set(by_id) == {"anthropic", "falkordb", "supabase"}
    assert by_id["anthropic"] == {"id": "anthropic", "name": "Anthropic (Claude)", "status": "broken", "reason": "Out of credit"}
    assert by_id["falkordb"]["status"] == "working" and "reason" not in by_id["falkordb"]
    assert by_id["supabase"]["status"] == "working"


def test_vendor_text_never_reaches_the_answer(client, keys, env, monkeypatch):
    secret_text = "SECRET-VENDOR-DETAIL sk-ant-main"
    monkeypatch.setattr(health.httpx, "post", lambda *a, **k: Resp(418, secret_text))
    monkeypatch.setattr(health.httpx, "get", lambda *a, **k: Resp(502, secret_text))
    monkeypatch.setattr(health.redis, "Redis", lambda **kw: FakeRedis(RuntimeError(secret_text)))
    res = client.get("/api/v1/health", headers=READ)
    raw = res.get_data(as_text=True)
    assert "SECRET-VENDOR-DETAIL" not in raw and "sk-ant" not in raw
    for s in res.get_json()["services"]:
        assert s["status"] in ("working", "broken", "unknown")
        assert s.get("reason") is None or s["reason"] in REASONS


def test_a_check_that_hangs_is_cut_off(client, keys, env, monkeypatch):
    import time
    monkeypatch.setattr(health, "ROUTE_BUDGET_SECONDS", 0.3)
    monkeypatch.setattr(health.httpx, "post", lambda *a, **k: (time.sleep(1), Resp(200))[1])
    monkeypatch.setattr(health.httpx, "get", lambda *a, **k: Resp(200, "[]"))
    monkeypatch.setattr(health.redis, "Redis", lambda **kw: FakeRedis())
    started = time.monotonic()
    res = client.get("/api/v1/health", headers=READ)
    assert time.monotonic() - started < 0.9
    by_id = {s["id"]: s for s in res.get_json()["services"]}
    assert by_id["anthropic"] == {"id": "anthropic", "name": "Anthropic (Claude)", "status": "broken", "reason": "Not answering"}
    assert by_id["falkordb"]["status"] == "working"
