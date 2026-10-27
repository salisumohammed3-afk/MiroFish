"""
Forecast for Claude and agents at /mcp, using the official MCP Python SDK in
stateless streamable HTTP mode. Every request carries an API key; the tools
offered depend on what that key may do. Forecast's server is Flask, so each
request is handed to a fresh MCP server through a small ASGI bridge.
"""

import asyncio

import anyio
from flask import Blueprint, Response, request

from ..services.mcp_tools import build_server
from ..utils.apiauth import require_api_key
from ..utils.logger import get_logger

logger = get_logger('mirofish.mcp')

mcp_bp = Blueprint('mcp', __name__)

_SKIP_HEADERS = {"content-length", "transfer-encoding", "connection"}


async def _serve(server, method: str, query: bytes, headers: list, body: bytes):
    server.streamable_http_app()  # builds the session manager
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
        "scheme": "https", "path": "/mcp", "raw_path": b"/mcp", "root_path": "", "query_string": query,
        "headers": headers, "client": ("127.0.0.1", 0), "server": ("forecast", 443),
    }
    done = anyio.Event()
    body_sent = False
    out = {"status": 500, "headers": [], "body": []}

    async def receive():
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await done.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            out["status"] = message["status"]
            out["headers"] = [(k.decode(), v.decode()) for k, v in message.get("headers", [])]
        elif message["type"] == "http.response.body":
            out["body"].append(message.get("body", b""))
            if not message.get("more_body"):
                done.set()

    async with server.session_manager.run():
        await server.session_manager.handle_request(scope, receive, send)
    done.set()
    return out["status"], out["headers"], b"".join(out["body"])


@mcp_bp.route('/mcp', methods=['GET', 'POST', 'DELETE'])
def mcp():
    key, refusal = require_api_key("read")
    if refusal:
        return refusal
    headers = [(k.lower().encode(), v.encode()) for k, v in request.headers.items()]
    try:
        status, out_headers, body = asyncio.run(
            _serve(build_server(key), request.method, request.query_string, headers, request.get_data())
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"[forecast] mcp: {e}")
        return {"error": "Something went wrong, please try again"}, 500
    return Response(body, status=status, headers=[(k, v) for k, v in out_headers if k.lower() not in _SKIP_HEADERS])
