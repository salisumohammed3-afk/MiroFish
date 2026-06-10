"""
API route module
"""

from flask import Blueprint

graph_bp = Blueprint('graph', __name__)
simulation_bp = Blueprint('simulation', __name__)
report_bp = Blueprint('report', __name__)
auth_bp = Blueprint('auth', __name__)

from . import graph  # noqa: E402, F401
from . import simulation  # noqa: E402, F401
from . import report  # noqa: E402, F401
from . import auth  # noqa: E402, F401

# Attach the auth + company-ownership guard to every data blueprint.
# Done here (at blueprint definition time, before any app registers them) so the
# before_request hook is set exactly once. auth_bp is intentionally excluded; its
# routes carry their own decorators for login / profile / admin.
from ..middleware.access import init_access_control  # noqa: E402

init_access_control(graph_bp, simulation_bp, report_bp)

