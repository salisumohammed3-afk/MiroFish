"""
What Forecast's API keys reach. The /api/v1 routes and the /mcp tools both call
these functions, so the two always agree. Every key covers every client, the
way LangSync staff see Forecast. Nothing here changes who has access (users,
companies, roles or keys), and nothing here starts a knowledge map build or a
simulation.
"""

import re
from typing import Optional

from ..models.project import ProjectManager
from .report_agent import ReportManager
from .simulation_manager import SimulationManager
from .supabase_client import get_supabase_admin


class PublicApiError(Exception):
    """A mistake the caller can fix; its message is safe to show them."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


_IDS = {
    "project": re.compile(r"^proj_[0-9A-Za-z]{6,40}$"),
    "simulation": re.compile(r"^sim_[0-9A-Za-z]{6,40}$"),
    "report": re.compile(r"^report_[0-9A-Za-z]{6,40}$"),
}
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _check_id(kind: str, value) -> str:
    if not isinstance(value, str) or not _IDS[kind].match(value):
        raise PublicApiError(400, f"Not a valid {kind} id")
    return value


def _check_company(company_id: Optional[str]) -> Optional[str]:
    if company_id is None or company_id == "":
        return None
    if not _UUID.match(company_id):
        raise PublicApiError(400, "Not a valid company id")
    return company_id


def _companies() -> list:
    res = get_supabase_admin().table("companies").select("id, name, slug").order("name").execute()
    return [{"id": c["id"], "name": c.get("name") or "", "slug": c.get("slug") or ""} for c in res.data or []]


def _owners(table: str, id_col: str) -> dict:
    """Which company owns each project or simulation, from Forecast's ownership tables."""
    res = get_supabase_admin().table(table).select(f"{id_col}, company_id").execute()
    return {r[id_col]: r["company_id"] for r in res.data or []}


def _project_summary(p, owners: dict) -> dict:
    d = p.to_dict()
    return {
        "project_id": d["project_id"],
        "name": d["name"],
        "company_id": owners.get(d["project_id"]),
        "status": d["status"],
        "simulation_requirement": d.get("simulation_requirement"),
        "analysis_summary": d.get("analysis_summary"),
        "graph_id": d.get("graph_id"),
        "files": [{"filename": f.get("filename", "")} for f in d.get("files") or []],
        "created_at": d.get("created_at"),
        "updated_at": d.get("updated_at"),
        "error": d.get("error"),
    }


def list_companies() -> list:
    return _companies()


def list_projects(company_id: Optional[str] = None) -> list:
    company_id = _check_company(company_id)
    owners = _owners("project_ownership", "project_id")
    rows = [_project_summary(p, owners) for p in ProjectManager.list_projects(limit=1000)]
    return [r for r in rows if company_id is None or r["company_id"] == company_id]


def _project(project_id: str):
    p = ProjectManager.get_project(_check_id("project", project_id))
    if not p:
        raise PublicApiError(404, "No such project")
    return p


def get_project(project_id: str) -> dict:
    p = _project(project_id)
    out = _project_summary(p, _owners("project_ownership", "project_id"))
    out["ontology"] = p.to_dict().get("ontology")
    return out


def _latest_report_id(simulation_id: str) -> Optional[str]:
    reports = ReportManager.list_reports(simulation_id=simulation_id, limit=1)
    return reports[0].report_id if reports else None


def list_simulations(project_id: Optional[str] = None, company_id: Optional[str] = None) -> list:
    if project_id:
        _check_id("project", project_id)
    company_id = _check_company(company_id)
    owners = _owners("simulation_ownership", "simulation_id")
    out = []
    for s in SimulationManager().list_simulations(project_id=project_id or None):
        d = s.to_simple_dict()
        d.update(company_id=owners.get(s.simulation_id), created_at=getattr(s, "created_at", None),
                 updated_at=getattr(s, "updated_at", None), report_id=_latest_report_id(s.simulation_id))
        if company_id is None or d["company_id"] == company_id:
            out.append(d)
    out.sort(key=lambda d: d.get("created_at") or "", reverse=True)
    return out


def _simulation(simulation_id: str):
    s = SimulationManager().get_simulation(_check_id("simulation", simulation_id))
    if not s:
        raise PublicApiError(404, "No such simulation")
    return s


def get_simulation(simulation_id: str) -> dict:
    s = _simulation(simulation_id)
    d = s.to_dict()
    d["company_id"] = _owners("simulation_ownership", "simulation_id").get(s.simulation_id)
    d["report_id"] = _latest_report_id(s.simulation_id)
    return d


def list_reports(simulation_id: Optional[str] = None) -> list:
    if simulation_id:
        _check_id("simulation", simulation_id)
    out = []
    for r in ReportManager.list_reports(simulation_id=simulation_id or None, limit=1000):
        d = r.to_dict()
        out.append({
            "report_id": d["report_id"], "simulation_id": d["simulation_id"],
            "title": (d.get("outline") or {}).get("title"), "status": d["status"],
            "created_at": d.get("created_at"), "completed_at": d.get("completed_at"),
        })
    return out


def get_report(report_id: str) -> dict:
    r = ReportManager.get_report(_check_id("report", report_id))
    if not r:
        raise PublicApiError(404, "No such report")
    return r.to_dict()


def rename_project(project_id: str, body) -> dict:
    """The one change to a project a key may make: its name."""
    if not isinstance(body, dict):
        raise PublicApiError(400, "The request body was not JSON")
    if set(body) - {"name"}:
        raise PublicApiError(400, "Only name can be changed")
    name = body.get("name").strip() if isinstance(body.get("name"), str) else ""
    if not name:
        raise PublicApiError(400, "name is required")
    if len(name) > 120:
        raise PublicApiError(400, "Keep the name under 120 characters")
    p = _project(project_id)
    p.name = name
    ProjectManager.save_project(p)
    return _project_summary(p, _owners("project_ownership", "project_id"))


def _report_agent(simulation, project, graph_id):
    # Lazy: the report agent pulls in the AI and knowledge map clients.
    from ..api.report import _create_report_llm_and_tools
    from .report_agent import ReportAgent

    llm, zep = _create_report_llm_and_tools()
    return ReportAgent(graph_id=graph_id, simulation_id=simulation.simulation_id,
                       simulation_requirement=project.simulation_requirement or "", llm_client=llm, zep_tools=zep)


def ask_forecast(simulation_id: str, body) -> dict:
    """Asks the report agent a question about a finished simulation. Spends AI credit."""
    if not isinstance(body, dict):
        raise PublicApiError(400, "The request body was not JSON")
    message = body.get("message").strip() if isinstance(body.get("message"), str) else ""
    if not message:
        raise PublicApiError(400, "message is required")
    if len(message) > 4000:
        raise PublicApiError(400, "Keep the message under 4000 characters")
    history = body.get("history", [])
    if not isinstance(history, list) or len(history) > 40 or not all(
        isinstance(h, dict) and h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str) for h in history
    ):
        raise PublicApiError(400, "history must be a list of {role, content}")
    simulation = _simulation(simulation_id)
    project = ProjectManager.get_project(simulation.project_id)
    if not project:
        raise PublicApiError(404, "No such project")
    graph_id = simulation.graph_id or project.graph_id
    if not graph_id:
        raise PublicApiError(409, "This forecast has no knowledge map yet, so it cannot answer questions")
    result = _report_agent(simulation, project, graph_id).chat(message=message, chat_history=history)
    return {"answer": result.get("response", ""), "sources": result.get("sources", [])}
