"""The front door for requests that carry an API key instead of a sign-in."""

import pytest
from flask import Flask

from app.utils import apiauth
from app.utils.apikeys import KeyStoreError, make_key

app = Flask(__name__)


def call(need, headers=None, check=None, monkeypatch=None):
    if check is not None:
        monkeypatch.setattr(apiauth, "check_api_key", check)
    with app.test_request_context("/api/v1/x", headers=headers or {}):
        key, refusal = apiauth.require_api_key(need)
        if refusal is None:
            return key, None, None
        resp, status = refusal
        return None, status, resp.get_json()


@pytest.fixture(autouse=True)
def fresh_limits():
    apiauth._seen.clear()
    yield
    apiauth._seen.clear()


def good(access):
    return lambda raw: {"ok": True, "id": "key-1", "access": access}


def test_missing_key(monkeypatch):
    _, status, body = call("read", {}, lambda raw: {"ok": False, "reason": "missing"}, monkeypatch)
    assert (status, body) == (401, {"error": "Add your API key as Authorization: Bearer lsk_..."})


def test_unknown_or_malformed_key(monkeypatch):
    for reason in ("unknown", "malformed"):
        _, status, body = call("read", {"Authorization": "Bearer x"}, lambda raw, r=reason: {"ok": False, "reason": r}, monkeypatch)
        assert (status, body) == (401, {"error": "This API key is not valid, or has been cancelled or has expired"})


def test_other_products_key_names_the_product(monkeypatch):
    other = make_key("story-boss")["key"]
    _, status, body = call("read", {"Authorization": f"Bearer {other}"}, None, monkeypatch)
    assert (status, body) == (401, {"error": "This key is for Story Boss, not Forecast"})


def test_unknown_other_product_falls_back_to_its_id(monkeypatch):
    other = make_key("brand-new")["key"]
    _, status, body = call("read", {"Authorization": f"Bearer {other}"}, None, monkeypatch)
    assert body == {"error": "This key is for brand-new, not Forecast"}


def test_read_key_on_a_change_is_403(monkeypatch):
    _, status, body = call("write", {"Authorization": "Bearer k"}, good("read"), monkeypatch)
    assert (status, body) == (403, {"error": "This key is read only"})


def test_write_key_passes_both(monkeypatch):
    for need in ("read", "write"):
        key, status, _ = call(need, {"Authorization": "Bearer k"}, good("write"), monkeypatch)
        assert status is None and key == {"id": "key-1", "access": "write"}


def test_store_down_is_503(monkeypatch):
    def broken(raw):
        raise KeyStoreError("connection refused")

    _, status, body = call("read", {"Authorization": "Bearer k"}, broken, monkeypatch)
    assert (status, body) == (503, {"error": "Could not check the API key, please try again"})


def test_trailing_space_and_x_api_key_header(monkeypatch):
    seen = []

    def check(raw):
        seen.append(raw)
        return {"ok": True, "id": "key-1", "access": "read"}

    call("read", {"Authorization": "Bearer abc \t "}, check, monkeypatch)
    call("read", {"X-Api-Key": "def"}, check, monkeypatch)
    assert seen[0].strip() == "abc"
    assert seen[1] == "def"


def test_121st_request_in_a_minute_is_429(monkeypatch):
    monkeypatch.setattr(apiauth, "check_api_key", good("read"))
    for _ in range(120):
        assert call("read", {"Authorization": "Bearer k"})[1] is None
    _, status, body = call("read", {"Authorization": "Bearer k"})
    assert (status, body) == (429, {"error": "Too many requests, slow down"})
