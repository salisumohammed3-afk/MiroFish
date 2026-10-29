"""
Forecast API v1, for other tools and agents holding a LangSync API key. These
routes skip the sign-in guard on purpose: each one checks the key first
(utils/apiauth.py) and only then reads anything. Reads need any live key;
changes need a read and change key.
"""

from flask import Blueprint, jsonify, request

from ..services import health, public_api
from ..services.public_api import PublicApiError
from ..utils.apiauth import require_api_key
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.v1')

v1_bp = Blueprint('v1', __name__)


def answer(fn, status=200):
    """Caller mistakes go back as they are; anything else is logged and answered plainly,
    so database or file detail never reaches an outside tool."""
    try:
        return jsonify({"data": fn()}), status
    except PublicApiError as e:
        return jsonify({"error": e.message}), e.status
    except Exception as e:  # noqa: BLE001
        logger.error(f"[forecast] api: {e}")
        return jsonify({"error": "Something went wrong, please try again"}), 500


def keyed(need):
    def wrap(f):
        def inner(*args, **kwargs):
            key, refusal = require_api_key(need)
            if refusal:
                return refusal
            return f(key, *args, **kwargs)
        inner.__name__ = f.__name__
        return inner
    return wrap


@v1_bp.route('/health', methods=['GET'])
@keyed("read")
def service_health(key):
    """Whether each paid service and key Forecast runs on works. Read only, starts no paid work."""
    try:
        return jsonify(health.build_health()), 200
    except Exception as e:  # noqa: BLE001
        logger.error(f"[forecast] health: {e}")
        return jsonify({"error": "Something went wrong, please try again"}), 500


@v1_bp.route('/companies', methods=['GET'])
@keyed("read")
def companies(key):
    return answer(public_api.list_companies)


@v1_bp.route('/projects', methods=['GET'])
@keyed("read")
def projects(key):
    return answer(lambda: public_api.list_projects(request.args.get("company")))


@v1_bp.route('/projects/<project_id>', methods=['GET'])
@keyed("read")
def project(key, project_id):
    return answer(lambda: public_api.get_project(project_id))


@v1_bp.route('/projects/<project_id>', methods=['PATCH'])
@keyed("write")
def rename_project(key, project_id):
    return answer(lambda: public_api.rename_project(project_id, request.get_json(silent=True)))


@v1_bp.route('/simulations', methods=['GET'])
@keyed("read")
def simulations(key):
    return answer(lambda: public_api.list_simulations(request.args.get("project"), request.args.get("company")))


@v1_bp.route('/simulations/<simulation_id>', methods=['GET'])
@keyed("read")
def simulation(key, simulation_id):
    return answer(lambda: public_api.get_simulation(simulation_id))


@v1_bp.route('/simulations/<simulation_id>/ask', methods=['POST'])
@keyed("write")
def ask(key, simulation_id):
    return answer(lambda: public_api.ask_forecast(simulation_id, request.get_json(silent=True)))


@v1_bp.route('/reports', methods=['GET'])
@keyed("read")
def reports(key):
    return answer(lambda: public_api.list_reports(request.args.get("simulation")))


@v1_bp.route('/reports/<report_id>', methods=['GET'])
@keyed("read")
def report(key, report_id):
    return answer(lambda: public_api.get_report(report_id))
