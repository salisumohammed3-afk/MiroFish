"""
Central access-control guard for the data blueprints (graph / simulation / report).

This runs as a blueprint-level ``before_request`` hook, so EVERY route in those
blueprints is protected without having to decorate each handler individually.
Two things are enforced, fail-closed, on every request:

1. Authentication. A valid Supabase JWT must be present, otherwise 401. The
   authenticated user is attached to ``g.user`` for downstream handlers.
2. Company ownership. Any resource id present in the URL or request body
   (project / simulation / graph / report) must belong to the caller's company,
   otherwise 403. The super_admin role bypasses ownership checks.

List endpoints carry no resource id; they pass this guard (auth still required)
and filter their results by company inside the handler.
"""

from flask import request, g, jsonify

from .auth import _build_auth_user
from ..services.ownership import OwnershipService

# URL/body parameter names that identify an owned resource, mapped to the name of
# the OwnershipService check that decides whether the caller's company owns it.
# Resolved by name at request time so the live implementation is always used.
_OWNERSHIP_CHECKS = {
    "project_id": "check_project_access",
    "simulation_id": "check_simulation_access",
    "graph_id": "check_graph_access",
    "report_id": "check_report_access",
}


def _collect_resource_ids():
    """Pull any owned-resource ids from the URL, JSON body, then form data.

    Returns a dict of ``{param_name: value}`` for every ownership key found.
    ``get_json(silent=True)`` caches the parsed body so the handler can still
    read it afterwards.
    """
    ids = {}

    view_args = request.view_args or {}
    for key in _OWNERSHIP_CHECKS:
        value = view_args.get(key)
        if value:
            ids[key] = value

    body = request.get_json(silent=True)
    if isinstance(body, dict):
        for key in _OWNERSHIP_CHECKS:
            if key not in ids and body.get(key):
                ids[key] = body[key]

    if request.form:
        for key in _OWNERSHIP_CHECKS:
            if key not in ids and request.form.get(key):
                ids[key] = request.form[key]

    return ids


def company_access_guard():
    """Blueprint ``before_request`` hook. Returns a response to short-circuit, or None."""
    # Let CORS preflight through untouched (no Authorization header is sent on it).
    if request.method == "OPTIONS":
        return None

    auth_header = request.headers.get("Authorization", "")
    user = None
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
        user = _build_auth_user(token)

    g.user = user
    if user is None:
        return jsonify({"success": False, "error": "Authentication required"}), 401

    # super_admin sees everything; skip ownership resolution.
    if user.role == "super_admin":
        return None

    for key, value in _collect_resource_ids().items():
        check = getattr(OwnershipService, _OWNERSHIP_CHECKS[key])
        if not check(value, user.company_id, False):
            return jsonify({"success": False, "error": "Access denied"}), 403

    return None


def init_access_control(*blueprints):
    """Attach the access guard to each given blueprint."""
    for bp in blueprints:
        bp.before_request(company_access_guard)
