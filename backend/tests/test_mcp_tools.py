"""Forecast's MCP tools: what each kind of key is offered, and how errors come back."""

import asyncio

import pytest

from app.services import mcp_tools, public_api
from app.services.public_api import PublicApiError

READ_TOOLS = {"list_companies", "list_projects", "get_project", "list_simulations", "get_simulation", "list_reports", "get_report"}


def tool_names(access):
    server = mcp_tools.build_server({"id": "k", "access": access})
    return {t.name for t in asyncio.run(server.list_tools())}


def call(access, name, args):
    server = mcp_tools.build_server({"id": "k", "access": access})
    return asyncio.run(server.call_tool(name, args))


def first_text(result):
    blocks = result.content if hasattr(result, "content") else result[0] if isinstance(result, tuple) else result
    return blocks[0].text


def is_error(result):
    return bool(getattr(result, "isError", False))


def test_read_key_gets_the_reading_tools_only():
    assert tool_names("read") == READ_TOOLS


def test_write_key_also_gets_the_change_tools():
    assert tool_names("write") == READ_TOOLS | {"rename_project", "ask_forecast"}


def test_read_tools_are_marked_read_only():
    server = mcp_tools.build_server({"id": "k", "access": "write"})
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    assert all(tools[n].annotations.readOnlyHint for n in READ_TOOLS)
    assert tools["rename_project"].annotations.readOnlyHint is False


def test_unknown_project_is_an_error_result_not_a_throw(monkeypatch):
    def missing(pid):
        raise PublicApiError(404, "No such project")

    monkeypatch.setattr(public_api, "get_project", missing)
    result = call("read", "get_project", {"project_id": "proj_cccccccccccc"})
    assert is_error(result)
    assert first_text(result) == "No such project"


def test_unexpected_errors_hide_the_detail(monkeypatch):
    def boom():
        raise RuntimeError("secret database detail")

    monkeypatch.setattr(public_api, "list_companies", boom)
    result = call("read", "list_companies", {})
    assert is_error(result)
    assert first_text(result) == "Something went wrong, please try again"


def test_tools_call_the_shared_service(monkeypatch):
    seen = []
    monkeypatch.setattr(public_api, "list_projects", lambda company_id=None: seen.append(company_id) or [{"project_id": "p"}])
    monkeypatch.setattr(public_api, "rename_project", lambda pid, body: seen.append((pid, body)) or {"name": body["name"]})
    assert '"project_id": "p"' in first_text(call("read", "list_projects", {"company_id": "c1"}))
    assert '"name": "New"' in first_text(call("write", "rename_project", {"project_id": "proj_aaaaaaaaaaaa", "name": "New"}))
    assert seen == ["c1", ("proj_aaaaaaaaaaaa", {"name": "New"})]


def test_read_key_cannot_call_a_change_tool(monkeypatch):
    monkeypatch.setattr(public_api, "rename_project", lambda *a: pytest.fail("renamed with a read key"))
    try:
        result = call("read", "rename_project", {"project_id": "proj_aaaaaaaaaaaa", "name": "x"})
    except Exception as e:  # noqa: BLE001
        assert "rename_project" in str(e)
    else:
        assert is_error(result)
