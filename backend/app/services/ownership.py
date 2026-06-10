"""
Ownership service — tracks which company owns which project/simulation.
Uses the Supabase admin client (bypasses RLS) since the backend is the authority.
"""

from typing import Optional, List
from ..services.supabase_client import get_supabase_admin
from ..utils.logger import get_logger

logger = get_logger('mirofish.ownership')


class OwnershipService:
    """Manages project and simulation ownership in Supabase."""

    @staticmethod
    def register_project(project_id: str, company_id: str, user_id: str) -> None:
        sb = get_supabase_admin()
        sb.table("project_ownership").upsert({
            "project_id": project_id,
            "company_id": company_id,
            "created_by": user_id,
        }).execute()
        logger.info(f"Registered project {project_id} → company {company_id}")

    @staticmethod
    def register_simulation(simulation_id: str, company_id: str, project_id: str, user_id: str) -> None:
        sb = get_supabase_admin()
        sb.table("simulation_ownership").upsert({
            "simulation_id": simulation_id,
            "company_id": company_id,
            "project_id": project_id,
            "created_by": user_id,
        }).execute()
        logger.info(f"Registered simulation {simulation_id} → company {company_id}")

    @staticmethod
    def get_company_project_ids(company_id: str) -> List[str]:
        """Get all project IDs belonging to a company."""
        sb = get_supabase_admin()
        result = sb.table("project_ownership").select("project_id").eq("company_id", company_id).execute()
        return [row["project_id"] for row in result.data]

    @staticmethod
    def get_company_simulation_ids(company_id: str) -> List[str]:
        """Get all simulation IDs belonging to a company."""
        sb = get_supabase_admin()
        result = sb.table("simulation_ownership").select("simulation_id").eq("company_id", company_id).execute()
        return [row["simulation_id"] for row in result.data]

    @staticmethod
    def check_project_access(project_id: str, company_id: Optional[str], is_super_admin: bool) -> bool:
        """Check if a company (or super_admin) can access a project."""
        if is_super_admin:
            return True
        if not company_id:
            return False
        sb = get_supabase_admin()
        result = sb.table("project_ownership").select("project_id").eq("project_id", project_id).eq("company_id", company_id).execute()
        return len(result.data) > 0

    @staticmethod
    def check_simulation_access(simulation_id: str, company_id: Optional[str], is_super_admin: bool) -> bool:
        """Check if a company (or super_admin) can access a simulation."""
        if is_super_admin:
            return True
        if not company_id:
            return False
        sb = get_supabase_admin()
        result = sb.table("simulation_ownership").select("simulation_id").eq("simulation_id", simulation_id).eq("company_id", company_id).execute()
        return len(result.data) > 0

    @staticmethod
    def check_report_access(report_id: str, company_id: Optional[str], is_super_admin: bool) -> bool:
        """Check report access by resolving the report to its simulation owner.

        A report has no ownership row of its own; it inherits the ownership of the
        simulation it was generated from. If the report does not exist, access is
        allowed so the route can return its own 404 (rather than masking it as 403).
        """
        if is_super_admin:
            return True
        if not company_id:
            return False
        # Lazy import to avoid a circular import at module load.
        from .report_agent import ReportManager
        report = ReportManager.get_report(report_id)
        if not report:
            return True  # let the handler 404
        return OwnershipService.check_simulation_access(report.simulation_id, company_id, False)

    @staticmethod
    def check_graph_access(graph_id: str, company_id: Optional[str], is_super_admin: bool) -> bool:
        """Check access to a Zep graph by resolving it to the owning project/simulation.

        A graph belongs to the project that built it (and to the simulations created
        from that project). Ownership is tracked at the project/simulation level, so we
        resolve graph_id -> project_id / simulation_id and defer to those checks. An
        unresolvable graph is denied for non-super-admins (it is not theirs).
        """
        if is_super_admin:
            return True
        if not company_id:
            return False
        # Lazy imports to avoid circular imports at module load.
        from ..models.project import ProjectManager
        from .simulation_manager import SimulationManager

        for project in ProjectManager.list_projects(limit=1000):
            if getattr(project, "graph_id", None) == graph_id:
                return OwnershipService.check_project_access(project.project_id, company_id, False)

        for state in SimulationManager().list_simulations():
            if getattr(state, "graph_id", None) == graph_id:
                return OwnershipService.check_simulation_access(state.simulation_id, company_id, False)

        return False
