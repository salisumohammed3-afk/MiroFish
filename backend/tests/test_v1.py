"""Forecast API v1 routes: the key decides what a request may do."""

import pytest

from app.services import public_api
from app.services.public_api import PublicApiError
from app.utils import apiauth

READ = {"Authorization": "Bearer read-key"}
WRITE = {"Authorization": "Bearer write-key"}


@pytest.fixture
def keys(monkeypatch):
    apiauth._seen.clear()

    def check(raw):
        return {"read-key": {"ok": True, "id": "k-read", "access": "read"},
                "write-key": {"ok": True, "id": "k-write", "access": "write"}}.get(raw.strip(), {"ok": False, "reason": "unknown"})

    monkeypatch.setattr(apiauth, "check_api_key", check)
    calls = []

    def fake(name, value=None):
        def fn(*args):
            calls.append((name, args))
            return value if value is not None else {"called": name}
        return fn

    for name in ("list_companies", "list_projects", "get_project", "rename_project", "list_simulations",
                 "get_simulation", "ask_forecast", "list_reports", "get_report"):
        monkeypatch.setattr(public_api, name, fake(name))
    yield calls
    apiauth._seen.clear()


@pytest.mark.parametrize("path,fn", [
    ("/api/v1/companies", "list_companies"),
    ("/api/v1/projects?company=c1", "list_projects"),
    ("/api/v1/projects/proj_aaaaaaaaaaaa", "get_project"),
    ("/api/v1/simulations?project=p1", "list_simulations"),
    ("/api/v1/simulations/sim_aaaaaaaaaaaa", "get_simulation"),
    ("/api/v1/reports?simulation=s1", "list_reports"),
    ("/api/v1/reports/report_aaaaaaaaaaaa", "get_report"),
])
def test_read_key_reads(client, keys, path, fn):
    res = client.get(path, headers=READ)
    assert res.status_code == 200
    assert res.get_json() == {"data": {"called": fn}}


def test_query_filters_reach_the_service(client, keys):
    client.get("/api/v1/projects?company=c1", headers=READ)
    client.get("/api/v1/simulations?project=p1&company=c2", headers=READ)
    assert keys[0] == ("list_projects", ("c1",))
    assert keys[1] == ("list_simulations", ("p1", "c2"))


@pytest.mark.parametrize("method,path", [
    ("patch", "/api/v1/projects/proj_aaaaaaaaaaaa"),
    ("post", "/api/v1/simulations/sim_aaaaaaaaaaaa/ask"),
])
def test_read_key_cannot_change(client, keys, method, path):
    res = getattr(client, method)(path, json={"name": "x", "message": "x"}, headers=READ)
    assert (res.status_code, res.get_json()) == (403, {"error": "This key is read only"})
    assert keys == []


def test_write_key_renames_and_asks(client, keys):
    res = client.patch("/api/v1/projects/proj_aaaaaaaaaaaa", json={"name": "New"}, headers=WRITE)
    assert res.status_code == 200
    res = client.post("/api/v1/simulations/sim_aaaaaaaaaaaa/ask", json={"message": "Why?"}, headers=WRITE)
    assert res.status_code == 200
    assert keys == [("rename_project", ("proj_aaaaaaaaaaaa", {"name": "New"})),
                    ("ask_forecast", ("sim_aaaaaaaaaaaa", {"message": "Why?"}))]


def test_write_key_also_reads(client, keys):
    assert client.get("/api/v1/companies", headers=WRITE).status_code == 200


def test_caller_mistakes_come_back_as_they_are(client, keys, monkeypatch):
    def boom(*a):
        raise PublicApiError(404, "No such project")

    monkeypatch.setattr(public_api, "get_project", boom)
    res = client.get("/api/v1/projects/proj_cccccccccccc", headers=READ)
    assert (res.status_code, res.get_json()) == (404, {"error": "No such project"})


def test_unexpected_errors_hide_the_detail(client, keys, monkeypatch):
    def boom(*a):
        raise RuntimeError("relation forecast.companies does not exist")

    monkeypatch.setattr(public_api, "list_companies", boom)
    res = client.get("/api/v1/companies", headers=READ)
    assert (res.status_code, res.get_json()) == (500, {"error": "Something went wrong, please try again"})


def test_cancelled_key_is_401(client, keys):
    res = client.get("/api/v1/companies", headers={"Authorization": "Bearer cancelled"})
    assert (res.status_code, res.get_json()) == (401, {"error": "This API key is not valid, or has been cancelled or has expired"})


def test_a_sign_in_token_does_not_open_v1(client, keys):
    # The old sign-in guard does not apply here, and a Supabase sign-in is not a key.
    res = client.get("/api/v1/companies", headers={"Authorization": "Bearer tok-super"})
    assert res.status_code == 401
