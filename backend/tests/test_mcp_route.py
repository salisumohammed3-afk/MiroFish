"""The /mcp endpoint: key first, then the official MCP SDK answers initialize and tools/list."""

import pytest

from app.services import public_api
from app.utils import apiauth

ACCEPT = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture
def keys(monkeypatch):
    apiauth._seen.clear()
    monkeypatch.setattr(apiauth, "check_api_key", lambda raw: {
        "read-key": {"ok": True, "id": "k-read", "access": "read"},
        "write-key": {"ok": True, "id": "k-write", "access": "write"},
    }.get(raw.strip(), {"ok": False, "reason": "unknown" if raw.strip() else "missing"}))
    yield
    apiauth._seen.clear()


def rpc(client, key, method, params=None, id_=1):
    body = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", json=body, headers=dict(ACCEPT, Authorization=f"Bearer {key}"))


INIT = {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}


def test_no_key_is_401(client, keys):
    res = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": INIT}, headers=ACCEPT)
    assert (res.status_code, res.get_json()) == (401, {"error": "Add your API key as Authorization: Bearer lsk_..."})


def test_initialize(client, keys):
    res = rpc(client, "read-key", "initialize", INIT)
    assert res.status_code == 200
    body = res.get_json()
    assert body["result"]["serverInfo"]["name"] == "forecast"
    assert "tools" in body["result"]["capabilities"]


@pytest.mark.parametrize("key,count", [("read-key", 7), ("write-key", 9)])
def test_tools_list(client, keys, key, count):
    res = rpc(client, key, "tools/list", {})
    assert res.status_code == 200
    names = [t["name"] for t in res.get_json()["result"]["tools"]]
    assert len(names) == count
    assert ("ask_forecast" in names) == (key == "write-key")


def test_tool_call_through_the_route(client, keys, monkeypatch):
    monkeypatch.setattr(public_api, "list_companies", lambda: [{"id": "c1", "name": "Acme", "slug": "acme"}])
    res = rpc(client, "read-key", "tools/call", {"name": "list_companies", "arguments": {}})
    result = res.get_json()["result"]
    assert result["isError"] is False
    assert "Acme" in result["content"][0]["text"]


def test_read_key_calling_a_change_tool_is_refused(client, keys, monkeypatch):
    monkeypatch.setattr(public_api, "rename_project", lambda *a: pytest.fail("renamed with a read key"))
    res = rpc(client, "read-key", "tools/call", {"name": "rename_project", "arguments": {"project_id": "proj_aaaaaaaaaaaa", "name": "x"}})
    body = res.get_json()
    assert body.get("error") or body["result"]["isError"] is True
