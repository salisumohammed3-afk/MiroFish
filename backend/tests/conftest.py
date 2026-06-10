"""
Shared pytest fixtures for MiroFish backend tests.

Auth and ownership are stubbed at their seams so these tests never touch Supabase,
the filesystem, or any LLM. We replace:
  - middleware.access._build_auth_user  -> map a fake bearer token to an AuthUser
  - OwnershipService.check_*             -> deterministic per-company ownership
"""

import os
import sys

import pytest

# Make the backend package importable when running pytest from backend/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.middleware.auth import AuthUser  # noqa: E402
from app.middleware import access as access_module  # noqa: E402
from app.services.ownership import OwnershipService  # noqa: E402

# Fake bearer tokens -> the AuthUser each represents.
TOKENS = {
    "tok-super": AuthUser(id="u-super", email="super@x.io", company_id=None, role="super_admin"),
    "tok-acme": AuthUser(id="u-acme", email="a@acme.io", company_id="company-acme", role="member"),
    "tok-globex": AuthUser(id="u-globex", email="g@globex.io", company_id="company-globex", role="member"),
}

# Which company owns which resource id, for the stubbed ownership checks.
OWNED_BY = {
    "project_id": {"proj-acme": "company-acme", "proj-globex": "company-globex"},
    "simulation_id": {"sim-acme": "company-acme", "sim-globex": "company-globex"},
    "graph_id": {"graph-acme": "company-acme", "graph-globex": "company-globex"},
    "report_id": {"report-acme": "company-acme", "report-globex": "company-globex"},
}


def _fake_build_auth_user(token):
    return TOKENS.get(token)


def _make_check(resource_key):
    def check(resource_id, company_id, is_super_admin):
        if is_super_admin:
            return True
        if not company_id:
            return False
        return OWNED_BY[resource_key].get(resource_id) == company_id
    return check


def _company_ids(resource_key):
    def lister(company_id):
        return [rid for rid, owner in OWNED_BY[resource_key].items() if owner == company_id]
    return lister


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(access_module, "_build_auth_user", _fake_build_auth_user)
    monkeypatch.setattr(OwnershipService, "check_project_access", staticmethod(_make_check("project_id")))
    monkeypatch.setattr(OwnershipService, "check_simulation_access", staticmethod(_make_check("simulation_id")))
    monkeypatch.setattr(OwnershipService, "check_graph_access", staticmethod(_make_check("graph_id")))
    monkeypatch.setattr(OwnershipService, "check_report_access", staticmethod(_make_check("report_id")))
    monkeypatch.setattr(OwnershipService, "get_company_project_ids", staticmethod(_company_ids("project_id")))
    monkeypatch.setattr(OwnershipService, "get_company_simulation_ids", staticmethod(_company_ids("simulation_id")))
    application = create_app()
    application.config.update(TESTING=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def auth(token):
    return {"Authorization": f"Bearer {token}"}
