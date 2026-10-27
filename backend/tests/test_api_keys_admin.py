"""Settings, API keys: only LangSync staff (Forecast's super_admin) may make, see or cancel keys."""

import pytest

from app.api import api_keys as admin_routes
from app.middleware import auth as auth_module
from app.middleware.auth import AuthUser
from app.utils.apikeys import KeyStoreError
from tests.conftest import TOKENS, auth

USERS = dict(TOKENS)
USERS["tok-client-admin"] = AuthUser(id="u-ca", email="boss@acme.io", company_id="company-acme", role="admin")
# Staff while the hub's client lock is on are narrowed to that client's admin.
USERS["tok-locked-staff"] = AuthUser(id="u-ls", email="sal@langsync.ai", company_id="company-acme", role="admin",
                                     client_lock={"uses_product": True})

ROW = {"id": "a0000000-0000-4000-8000-00000000000a", "product_id": "forecast", "name": "Claude", "prefix": "lsk_forecast_abcd1234",
       "access": "read", "created_by": "super@x.io", "created_at": "2026-10-27T10:00:00Z", "expires_at": None,
       "revoked_at": None, "last_used_at": None}


@pytest.fixture
def store(monkeypatch, app):
    monkeypatch.setattr(auth_module, "_build_auth_user", lambda token: USERS.get(token))
    made = []

    def create(name, access, expires_at, created_by):
        made.append({"name": name, "access": access, "expires_at": expires_at, "created_by": created_by})
        return {"key": "lsk_forecast_" + "a" * 64, "row": dict(ROW, name=name, access=access, expires_at=expires_at)}

    monkeypatch.setattr(admin_routes, "create_api_key", create)
    monkeypatch.setattr(admin_routes, "list_api_keys", lambda: [ROW])
    monkeypatch.setattr(admin_routes, "revoke_api_key", lambda key_id: key_id == ROW["id"])
    monkeypatch.setattr(admin_routes, "active_key_label", lambda: "1 active")
    return made


BASE = "/api/auth/admin/api-keys"


def test_signed_out_is_401(client, store):
    assert client.get(BASE).status_code == 401
    assert client.post(BASE, json={"name": "x"}).status_code == 401
    assert client.delete(f"{BASE}/{ROW['id']}").status_code == 401
    assert client.get(f"{BASE}/count").status_code == 401


@pytest.mark.parametrize("token", ["tok-acme", "tok-client-admin", "tok-locked-staff"])
def test_clients_and_locked_staff_are_403(client, store, token):
    h = auth(token)
    for res in (client.get(BASE, headers=h), client.post(BASE, json={"name": "x"}, headers=h),
                client.delete(f"{BASE}/{ROW['id']}", headers=h), client.get(f"{BASE}/count", headers=h)):
        assert res.status_code == 403
        assert res.get_json()["error"] == "Only LangSync admins can manage API keys"
    assert store == []


def test_staff_list_has_no_full_key_or_hash(client, store):
    res = client.get(BASE, headers=auth("tok-super"))
    assert res.status_code == 200
    body = res.get_json()
    assert body["data"] == [ROW]
    assert "key_hash" not in str(body)


def test_count(client, store):
    res = client.get(f"{BASE}/count", headers=auth("tok-super"))
    assert res.get_json()["data"] == {"label": "1 active"}


def test_make_needs_a_name(client, store):
    res = client.post(BASE, json={"name": "  "}, headers=auth("tok-super"))
    assert (res.status_code, res.get_json()["error"]) == (400, "Give the key a name")


def test_make_name_too_long(client, store):
    res = client.post(BASE, json={"name": "x" * 81}, headers=auth("tok-super"))
    assert (res.status_code, res.get_json()["error"]) == (400, "Keep the name under 80 characters")


def test_make_refuses_other_access(client, store):
    res = client.post(BASE, json={"name": "x", "access": "admin"}, headers=auth("tok-super"))
    assert (res.status_code, res.get_json()["error"]) == (400, "Choose read only, or read and change")


def test_make_refuses_past_expiry(client, store):
    res = client.post(BASE, json={"name": "x", "expiresAt": "2020-01-01"}, headers=auth("tok-super"))
    assert (res.status_code, res.get_json()["error"]) == (400, "The expiry date has already passed")


def test_make_refuses_unreadable_expiry(client, store):
    res = client.post(BASE, json={"name": "x", "expiresAt": "soon"}, headers=auth("tok-super"))
    assert (res.status_code, res.get_json()["error"]) == (400, "That expiry date could not be read")


def test_make_refuses_non_json(client, store):
    res = client.post(BASE, data="nope", headers=dict(auth("tok-super"), **{"Content-Type": "text/plain"}))
    assert (res.status_code, res.get_json()["error"]) == (400, "The request body was not JSON")


def test_make_defaults_to_read_and_returns_the_key_once(client, store):
    res = client.post(BASE, json={"name": " Claude on Sal's laptop "}, headers=auth("tok-super"))
    assert res.status_code == 201
    data = res.get_json()["data"]
    assert data["key"].startswith("lsk_forecast_")
    assert store == [{"name": "Claude on Sal's laptop", "access": "read", "expires_at": None, "created_by": "super@x.io"}]


def test_make_with_a_date_means_end_of_that_day(client, store):
    res = client.post(BASE, json={"name": "x", "access": "write", "expiresAt": "2999-12-31"}, headers=auth("tok-super"))
    assert res.status_code == 201
    assert store[0]["expires_at"] == "2999-12-31T23:59:59+00:00"
    assert store[0]["access"] == "write"


def test_cancel(client, store):
    assert client.delete(f"{BASE}/{ROW['id']}", headers=auth("tok-super")).get_json() == {"success": True}


def test_cancel_unknown_is_404(client, store):
    for key_id in ("b0000000-0000-4000-8000-00000000000b", "not-an-id"):
        res = client.delete(f"{BASE}/{key_id}", headers=auth("tok-super"))
        assert (res.status_code, res.get_json()["error"]) == (404, "No such key, or it is already cancelled")


def test_store_failure_is_500_without_detail(client, store, monkeypatch):
    def broken(*a, **k):
        raise KeyStoreError("relation does not exist, secret detail")

    monkeypatch.setattr(admin_routes, "list_api_keys", broken)
    monkeypatch.setattr(admin_routes, "create_api_key", broken)
    res = client.get(BASE, headers=auth("tok-super"))
    assert (res.status_code, res.get_json()["error"]) == (500, "Could not load the API keys, please try again")
    res = client.post(BASE, json={"name": "x"}, headers=auth("tok-super"))
    assert (res.status_code, res.get_json()["error"]) == (500, "Could not make the key, please try again")
