"""
Every /api/v1 route and /mcp skip the sign-in guard, so each must demand an
API key itself. This walks every one in the app's URL map and calls every
method with no key: each must answer 401 before it reads anything.
"""

import pytest

from app.services import public_api
from app.utils import apikeys


class Untouchable:
    def __getattr__(self, name):
        raise AssertionError(f"{name} was reached before the key was checked")

    def __call__(self, *a, **k):
        raise AssertionError("reached before the key was checked")


@pytest.fixture
def sealed(monkeypatch):
    monkeypatch.setattr(apikeys, "rpc", Untouchable())
    for name in ("ProjectManager", "SimulationManager", "ReportManager", "get_supabase_admin"):
        monkeypatch.setattr(public_api, name, Untouchable())


def key_routes(app):
    out = []
    for rule in app.url_map.iter_rules():
        if rule.rule.startswith("/api/v1/") or rule.rule == "/mcp":
            for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
                path = rule.rule
                for arg in rule.arguments:
                    path = path.replace(f"<{arg}>", "proj_aaaaaaaaaaaa")
                out.append((method, path))
    return out


def test_routes_are_found(app):
    routes = key_routes(app)
    assert len(routes) >= 10
    assert ("POST", "/mcp") in routes


def test_no_key_is_401_before_anything_is_read(app, client, sealed):
    results = []
    for method, path in key_routes(app):
        res = client.open(path, method=method, json={})
        results.append((method, path, res.status_code, res.get_json()))
    for method, path, status, body in results:
        assert (method, path, status, body) == (method, path, 401, {"error": "Add your API key as Authorization: Bearer lsk_..."})
