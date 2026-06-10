"""
Access-control tests for the data blueprints (graph / simulation / report).

These prove the lockdown invariants without touching Supabase, the filesystem,
or any LLM (auth + ownership are stubbed in conftest.py):

  * No token            -> 401 on every data route
  * Authenticated, wrong company -> 403 on another company's resource
  * Authenticated, owning company -> NOT blocked (no 401/403)
  * super_admin         -> NOT blocked anywhere
  * auth blueprint + health stay reachable as before
"""

import pytest

from conftest import auth

# (method, path) covering URL-param and body-param routes across all three blueprints.
# Each carries an ACME-owned resource id where applicable.
PROTECTED_ROUTES = [
    ("GET", "/api/simulation/sim-acme"),
    ("GET", "/api/simulation/sim-acme/profiles"),
    ("GET", "/api/simulation/sim-acme/config/download"),
    ("GET", "/api/simulation/sim-acme/posts"),
    ("GET", "/api/simulation/list"),
    ("GET", "/api/simulation/history"),
    ("GET", "/api/simulation/entities/graph-acme"),
    ("GET", "/api/graph/project/proj-acme"),
    ("DELETE", "/api/graph/project/proj-acme"),
    ("GET", "/api/graph/data/graph-acme"),
    ("GET", "/api/graph/project/list"),
    ("GET", "/api/report/report-acme"),
    ("GET", "/api/report/report-acme/download"),
    ("DELETE", "/api/report/report-acme"),
    ("GET", "/api/report/list"),
]

# Body-param routes: the resource id arrives in the JSON body, not the URL.
BODY_ROUTES = [
    ("POST", "/api/simulation/start", {"simulation_id": "sim-acme"}),
    ("POST", "/api/simulation/stop", {"simulation_id": "sim-acme"}),
    ("POST", "/api/simulation/create", {"project_id": "proj-acme"}),
    ("POST", "/api/report/generate", {"simulation_id": "sim-acme"}),
    ("POST", "/api/report/chat", {"simulation_id": "sim-acme", "message": "hi"}),
    ("POST", "/api/report/tools/search", {"graph_id": "graph-acme", "query": "x"}),
]


def _call(client, method, path, json=None, headers=None):
    return client.open(path, method=method, json=json, headers=headers or {})


@pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
def test_no_token_is_401(client, method, path):
    resp = _call(client, method, path)
    assert resp.status_code == 401, f"{method} {path} should require auth"


@pytest.mark.parametrize("method,path,body", BODY_ROUTES)
def test_no_token_is_401_body_routes(client, method, path, body):
    resp = _call(client, method, path, json=body)
    assert resp.status_code == 401, f"{method} {path} should require auth"


@pytest.mark.parametrize("method,path", [r for r in PROTECTED_ROUTES if not r[1].endswith(("/list", "/history"))])
def test_wrong_company_is_403(client, method, path):
    # Globex user reaching for ACME-owned resources must be denied.
    resp = _call(client, method, path, headers=auth("tok-globex"))
    assert resp.status_code == 403, f"{method} {path} should deny cross-company access"


@pytest.mark.parametrize("method,path,body", BODY_ROUTES)
def test_wrong_company_is_403_body_routes(client, method, path, body):
    resp = _call(client, method, path, json=body, headers=auth("tok-globex"))
    assert resp.status_code == 403, f"{method} {path} should deny cross-company access"


@pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
def test_owner_not_blocked(client, method, path):
    # The owning company is never blocked by the guard. The handler may still 404/500
    # (no real data / no LLM), but it must not be 401/403.
    resp = _call(client, method, path, headers=auth("tok-acme"))
    assert resp.status_code not in (401, 403), f"{method} {path} blocked owner ({resp.status_code})"


@pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
def test_super_admin_not_blocked(client, method, path):
    resp = _call(client, method, path, headers=auth("tok-super"))
    assert resp.status_code not in (401, 403), f"{method} {path} blocked super_admin ({resp.status_code})"


def test_health_still_open(client):
    assert client.get("/health").status_code == 200


def test_auth_blueprint_unaffected(client):
    # /api/auth/me has its own decorator and is not behind the data guard;
    # without a token it returns 401 from its own require_auth, not our guard.
    assert client.get("/api/auth/me").status_code == 401
