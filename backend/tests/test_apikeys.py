"""Making, reading and checking Forecast's API keys (the shared LangSync key store)."""

import hashlib
import re

import pytest

from app.utils import apikeys
from app.utils.apikeys import (
    KeyStoreError, active_key_label, check_api_key, hash_key, make_key, parse_key,
)

SHAPE = re.compile(r"^lsk_([a-z][a-z-]*)_([0-9a-f]{64})$")


def test_make_key_shape_hash_and_prefix():
    made = make_key("forecast")
    assert SHAPE.match(made["key"])
    assert made["hash"] == hashlib.sha256(made["key"].encode()).hexdigest()
    assert made["hash"] == hash_key(made["key"])
    secret = made["key"].split("_")[-1]
    assert made["prefix"] == f"lsk_forecast_{secret[:8]}"


def test_two_keys_differ():
    assert make_key("forecast")["key"] != make_key("forecast")["key"]


def test_parse_key_trims_spaces_and_newlines():
    key = make_key("forecast")["key"]
    assert parse_key("  " + key + "\n") == "forecast"
    assert hash_key("  " + key + "\n") == hash_key(key)


def test_parse_key_refuses_bad_shapes():
    assert parse_key("lsk_forecast_abc") is None
    assert parse_key("") is None
    assert parse_key("sk-" + "a" * 64) is None


class Calls(list):
    fake = None


@pytest.fixture
def calls(monkeypatch):
    seen = Calls()

    def fake_rpc(fn, args):
        seen.append((fn, args))
        return fake_rpc.answer

    fake_rpc.answer = []
    monkeypatch.setattr(apikeys, "rpc", fake_rpc)
    seen.fake = fake_rpc
    return seen


def test_check_missing_key(calls):
    assert check_api_key("") == {"ok": False, "reason": "missing"}
    assert check_api_key("   ") == {"ok": False, "reason": "missing"}
    assert calls == []


def test_check_malformed_key(calls):
    assert check_api_key("lsk_forecast_nothex") == {"ok": False, "reason": "malformed"}
    assert calls == []


def test_check_other_products_key_never_asks_the_store(calls):
    key = make_key("story-boss")["key"]
    assert check_api_key(key) == {"ok": False, "reason": "other-product", "product_id": "story-boss"}
    assert calls == []


def test_check_unknown_key(calls):
    key = make_key("forecast")["key"]
    assert check_api_key(key) == {"ok": False, "reason": "unknown"}
    assert calls == [("hub_api_key_check", {"p_product": "forecast", "p_hash": hash_key(key)})]


def test_check_good_key(calls):
    key = make_key("forecast")["key"]
    calls.fake.answer = [{"id": "k1", "access": "write"}]
    assert check_api_key(key + "\n") == {"ok": True, "id": "k1", "access": "write"}


def test_check_store_failure_raises(monkeypatch):
    def broken(fn, args):
        raise KeyStoreError("down")

    monkeypatch.setattr(apikeys, "rpc", broken)
    with pytest.raises(KeyStoreError):
        check_api_key(make_key("forecast")["key"])


def test_create_list_revoke_use_the_forecast_product(calls):
    calls.fake.answer = []
    apikeys.list_api_keys()
    apikeys.revoke_api_key("abc")
    assert calls[0] == ("hub_api_key_list", {"p_product": "forecast"})
    assert calls[1] == ("hub_api_key_revoke", {"p_product": "forecast", "p_id": "abc"})


def test_create_sends_only_the_hash_and_returns_the_key_once(monkeypatch):
    sent = {}

    def fake_rpc(fn, args):
        if fn == "hub_api_key_create":
            sent.update(args)
            return "new-id"
        return [{
            "id": "new-id", "product_id": "forecast", "name": "Claude", "prefix": sent["p_prefix"], "access": "read",
            "created_by": "sal@langsync.ai", "created_at": "2026-10-27T10:00:00Z", "expires_at": None,
            "revoked_at": None, "last_used_at": None,
        }]

    monkeypatch.setattr(apikeys, "rpc", fake_rpc)
    made = apikeys.create_api_key(name="Claude", access="read", expires_at=None, created_by="sal@langsync.ai")
    assert SHAPE.match(made["key"])
    assert sent["p_hash"] == hash_key(made["key"])
    assert made["key"] not in str(sent)
    assert made["row"]["id"] == "new-id"
    assert made["row"]["prefix"] == sent["p_prefix"]
    assert "key_hash" not in made["row"]


def test_active_key_label_counts_live_keys(monkeypatch):
    rows = [
        {"id": "1", "revoked_at": None, "expires_at": None},
        {"id": "2", "revoked_at": "2026-10-01T00:00:00Z", "expires_at": None},
        {"id": "3", "revoked_at": None, "expires_at": "2020-01-01T00:00:00Z"},
        {"id": "4", "revoked_at": None, "expires_at": "2999-01-01T00:00:00Z"},
    ]
    full = [dict(r, product_id="forecast", name="n", prefix="p", access="read", created_by="x",
                 created_at="2026-10-01T00:00:00Z", last_used_at=None) for r in rows]
    monkeypatch.setattr(apikeys, "rpc", lambda fn, args: full)
    assert active_key_label() == "2 active"


def test_active_key_label_says_could_not_count(monkeypatch):
    def broken(fn, args):
        raise KeyStoreError("down")

    monkeypatch.setattr(apikeys, "rpc", broken)
    assert active_key_label() == "Could not count"
