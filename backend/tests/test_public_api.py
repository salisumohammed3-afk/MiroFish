"""What Forecast's API keys reach: one service shared by /api/v1 and /mcp."""

from types import SimpleNamespace

import pytest

from app.services import public_api
from app.services.public_api import PublicApiError

P1 = "proj_aaaaaaaaaaaa"
P2 = "proj_bbbbbbbbbbbb"
S1 = "sim_aaaaaaaaaaaa"
R1 = "report_aaaaaaaaaaaa"
ACME = "11111111-1111-4111-8111-111111111111"


class FakeProject(SimpleNamespace):
    def to_dict(self):
        return dict(self.__dict__)


def project(pid, name, **kw):
    base = dict(project_id=pid, name=name, status="graph_completed", created_at="2026-10-01", updated_at="2026-10-02",
                files=[{"filename": "brief.pdf", "path": "/app/backend/uploads/x.pdf", "size": 10}], total_text_length=5,
                ontology={"entity_types": []}, analysis_summary="sum", graph_id="g1", graph_build_task_id="t",
                simulation_requirement="What if", chunk_size=500, chunk_overlap=50, error=None)
    base.update(kw)
    return FakeProject(**base)


class FakeProjects:
    store = {}
    saved = []

    @classmethod
    def list_projects(cls, limit=50):
        return list(cls.store.values())[:limit]

    @classmethod
    def get_project(cls, pid):
        return cls.store.get(pid)

    @classmethod
    def save_project(cls, p):
        cls.saved.append(p)


class FakeSim(SimpleNamespace):
    def to_dict(self):
        return dict(self.__dict__)

    def to_simple_dict(self):
        return {k: v for k, v in self.__dict__.items() if k != "config_reasoning"}


class FakeSims:
    sims = {S1: FakeSim(simulation_id=S1, project_id=P1, graph_id="g1", status="completed", created_at="2026-10-03",
                        updated_at="2026-10-04", config_reasoning="long")}

    def list_simulations(self, project_id=None):
        return [s for s in self.sims.values() if project_id is None or s.project_id == project_id]

    def get_simulation(self, sid):
        return self.sims.get(sid)


class FakeReport(SimpleNamespace):
    def to_dict(self):
        return {"report_id": self.report_id, "simulation_id": self.simulation_id, "status": "completed",
                "outline": {"title": "The outlook", "summary": "s", "sections": []}, "markdown_content": "# The outlook",
                "created_at": "2026-10-05", "completed_at": "2026-10-05", "error": None, "graph_id": "g1",
                "simulation_requirement": "What if"}


class FakeReports:
    reports = {R1: FakeReport(report_id=R1, simulation_id=S1)}

    @classmethod
    def list_reports(cls, simulation_id=None, limit=50):
        return [r for r in cls.reports.values() if simulation_id is None or r.simulation_id == simulation_id]

    @classmethod
    def get_report(cls, rid):
        return cls.reports.get(rid)


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    FakeProjects.store = {P1: project(P1, "Acme launch"), P2: project(P2, "Untracked")}
    FakeProjects.saved = []
    monkeypatch.setattr(public_api, "ProjectManager", FakeProjects)
    monkeypatch.setattr(public_api, "SimulationManager", FakeSims)
    monkeypatch.setattr(public_api, "ReportManager", FakeReports)
    monkeypatch.setattr(public_api, "_owners", lambda table, col: {P1: ACME, S1: ACME})
    monkeypatch.setattr(public_api, "_companies", lambda: [{"id": ACME, "name": "Acme", "slug": "acme"}])


def test_list_companies():
    assert public_api.list_companies() == [{"id": ACME, "name": "Acme", "slug": "acme"}]


def test_list_projects_has_company_and_no_server_paths():
    rows = public_api.list_projects()
    assert [r["project_id"] for r in rows] == [P1, P2]
    assert rows[0]["company_id"] == ACME and rows[1]["company_id"] is None
    assert rows[0]["files"] == [{"filename": "brief.pdf"}]
    assert "ontology" not in rows[0]
    assert "/app/backend" not in str(rows)


def test_list_projects_for_one_company():
    assert [r["project_id"] for r in public_api.list_projects(ACME)] == [P1]


def test_list_projects_bad_company_id():
    with pytest.raises(PublicApiError) as e:
        public_api.list_projects("../etc")
    assert (e.value.status, e.value.message) == (400, "Not a valid company id")


def test_get_project_includes_ontology_but_no_paths():
    p = public_api.get_project(P1)
    assert p["ontology"] == {"entity_types": []}
    assert "/app/backend" not in str(p)


@pytest.mark.parametrize("bad", ["../../etc/passwd", "proj_", "sim_aaaaaaaaaaaa", ""])
def test_get_project_refuses_bad_ids(bad):
    with pytest.raises(PublicApiError) as e:
        public_api.get_project(bad)
    assert e.value.status == 400


def test_get_project_unknown():
    with pytest.raises(PublicApiError) as e:
        public_api.get_project("proj_cccccccccccc")
    assert (e.value.status, e.value.message) == (404, "No such project")


def test_simulations_and_reports():
    sims = public_api.list_simulations()
    assert sims[0]["simulation_id"] == S1 and sims[0]["company_id"] == ACME and sims[0]["report_id"] == R1
    assert public_api.list_simulations(project_id=P2) == []
    assert public_api.get_simulation(S1)["report_id"] == R1
    reports = public_api.list_reports()
    assert reports == [{"report_id": R1, "simulation_id": S1, "title": "The outlook", "status": "completed",
                        "created_at": "2026-10-05", "completed_at": "2026-10-05"}]
    assert public_api.get_report(R1)["markdown_content"] == "# The outlook"
    with pytest.raises(PublicApiError):
        public_api.get_report("report_dddddddddddd")


def test_rename_project():
    out = public_api.rename_project(P1, {"name": "  New name "})
    assert out["name"] == "New name"
    assert FakeProjects.saved[0].name == "New name"


@pytest.mark.parametrize("body,message", [
    ({}, "name is required"),
    ({"name": "  "}, "name is required"),
    ({"name": "x" * 121}, "Keep the name under 120 characters"),
    ({"name": "x", "company_id": ACME}, "Only name can be changed"),
    ("nope", "The request body was not JSON"),
])
def test_rename_refuses_bad_bodies(body, message):
    with pytest.raises(PublicApiError) as e:
        public_api.rename_project(P1, body)
    assert (e.value.status, e.value.message) == (400, message)
    assert FakeProjects.saved == []


def test_ask_checks_the_body_before_any_ai(monkeypatch):
    monkeypatch.setattr(public_api, "_report_agent", lambda *a: pytest.fail("AI started"))
    for body, msg in [({}, "message is required"), ({"message": "x" * 4001}, "Keep the message under 4000 characters"),
                      ({"message": "hi", "history": "no"}, "history must be a list of {role, content}")]:
        with pytest.raises(PublicApiError) as e:
            public_api.ask_forecast(S1, body)
        assert (e.value.status, e.value.message) == (400, msg)
    with pytest.raises(PublicApiError) as e:
        public_api.ask_forecast("sim_dddddddddddd", {"message": "hi"})
    assert e.value.status == 404


def test_ask_runs_the_report_agent(monkeypatch):
    seen = {}

    class Agent:
        def chat(self, message, chat_history):
            seen.update(message=message, history=chat_history)
            return {"response": "Up", "tool_calls": [{"name": "search"}], "sources": ["q"]}

    monkeypatch.setattr(public_api, "_report_agent", lambda sim, proj, graph_id: Agent())
    out = public_api.ask_forecast(S1, {"message": "Where next?", "history": [{"role": "user", "content": "hi"}]})
    assert out == {"answer": "Up", "sources": ["q"]}
    assert seen == {"message": "Where next?", "history": [{"role": "user", "content": "hi"}]}
