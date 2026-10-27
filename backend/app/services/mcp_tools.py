"""
Forecast as tools for Claude and agents, served at /mcp. Every tool calls the
same functions as the /api/v1 routes (services/public_api.py), so the two
always agree. A read only key gets the reading tools; a read and change key
can also rename a project and ask a finished forecast a question. No tool can
change who has access, build a knowledge map or start a simulation.
"""

import json
from typing import Annotated, Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

from . import public_api
from .public_api import PublicApiError
from ..utils.logger import get_logger

logger = get_logger('mirofish.mcp')

INSTRUCTIONS = (
    "Forecast is LangSync's simulation-based forecasting tool. A project holds the documents and the question; "
    "a simulation plays it out with AI agents; a report sums up what happened. Start with list_projects or "
    "list_simulations, then read a report with get_report."
)


def _text(value) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(value, indent=2, ensure_ascii=False))])


def run(fn) -> CallToolResult:
    try:
        return _text(fn())
    except PublicApiError as e:
        return CallToolResult(content=[TextContent(type="text", text=e.message)], isError=True)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[forecast] mcp tool: {e}")
        return CallToolResult(content=[TextContent(type="text", text="Something went wrong, please try again")], isError=True)


READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
CHANGE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

ProjectId = Annotated[str, Field(description="A project id from list_projects, like proj_1a2b3c4d5e6f")]
SimulationId = Annotated[str, Field(description="A simulation id from list_simulations, like sim_1a2b3c4d5e6f")]


def register_forecast_tools(server: FastMCP, key: dict) -> None:
    def list_companies() -> CallToolResult:
        return run(public_api.list_companies)

    def list_projects(company_id: Annotated[Optional[str], Field(description="A company id from list_companies, for one client")] = None) -> CallToolResult:
        return run(lambda: public_api.list_projects(company_id))

    def get_project(project_id: ProjectId) -> CallToolResult:
        return run(lambda: public_api.get_project(project_id))

    def list_simulations(
        project_id: Annotated[Optional[str], Field(description="A project id, for that project's simulations")] = None,
        company_id: Annotated[Optional[str], Field(description="A company id, for one client")] = None,
    ) -> CallToolResult:
        return run(lambda: public_api.list_simulations(project_id, company_id))

    def get_simulation(simulation_id: SimulationId) -> CallToolResult:
        return run(lambda: public_api.get_simulation(simulation_id))

    def list_reports(simulation_id: Annotated[Optional[str], Field(description="A simulation id, for its reports")] = None) -> CallToolResult:
        return run(lambda: public_api.list_reports(simulation_id))

    def get_report(report_id: Annotated[str, Field(description="A report id from list_reports or a simulation's report_id")]) -> CallToolResult:
        return run(lambda: public_api.get_report(report_id))

    server.add_tool(list_companies, name="list_companies", title="List companies", annotations=READ_ONLY,
                    description="Every client company in Forecast, with its id, name and slug. Use the id to filter the other tools.")
    server.add_tool(list_projects, name="list_projects", title="List projects", annotations=READ_ONLY,
                    description="Forecast projects, newest first: the question being forecast, the documents it read, its status and its company.")
    server.add_tool(get_project, name="get_project", title="Get a project", annotations=READ_ONLY,
                    description="One project with its analysis summary and the ontology (the kinds of people and things) it found.")
    server.add_tool(list_simulations, name="list_simulations", title="List simulations", annotations=READ_ONLY,
                    description="Simulations, newest first, with their status, size and the id of their latest report.")
    server.add_tool(get_simulation, name="get_simulation", title="Get a simulation", annotations=READ_ONLY,
                    description="One simulation in full: its status, rounds, agents and the reasoning behind its set-up.")
    server.add_tool(list_reports, name="list_reports", title="List reports", annotations=READ_ONLY,
                    description="Forecast reports, newest first, with their title and status.")
    server.add_tool(get_report, name="get_report", title="Get a report", annotations=READ_ONLY,
                    description="One report in full: its outline and the whole text in Markdown.")

    if key.get("access") != "write":
        return

    def rename_project(project_id: ProjectId, name: Annotated[str, Field(description="The new name, up to 120 characters")]) -> CallToolResult:
        return run(lambda: public_api.rename_project(project_id, {"name": name}))

    def ask_forecast(
        simulation_id: SimulationId,
        message: Annotated[str, Field(description="The question, up to 4000 characters")],
    ) -> CallToolResult:
        return run(lambda: public_api.ask_forecast(simulation_id, {"message": message}))

    server.add_tool(rename_project, name="rename_project", title="Rename a project", annotations=CHANGE,
                    description="Changes a project's name. Nothing else about the project changes.")
    server.add_tool(ask_forecast, name="ask_forecast", title="Ask a forecast a question", annotations=CHANGE,
                    description="Asks the report agent a question about a finished simulation and returns its answer. "
                                "This uses AI credit and can take a minute.")


def build_server(key: dict) -> FastMCP:
    """A fresh, stateless server for one request, with the tools this key may use."""
    server = FastMCP(
        name="forecast",
        instructions=INSTRUCTIONS,
        stateless_http=True,
        json_response=True,
        streamable_http_path="/mcp",
        # Callers prove themselves with an API key in a header, not a cookie,
        # so the localhost-only host check does not apply.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    register_forecast_tools(server, key)
    return server
