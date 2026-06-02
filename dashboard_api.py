"""
dashboard_api.py
────────────────
Write-enabled REST endpoints for the Hubble web dashboard.

These wrap the SAME TicketService methods the Slack handlers already use, so
behaviour stays consistent across Slack and the web UI. Register this blueprint
in app.py (see DASHBOARD_DEPLOY.md) — it does NOT replace any existing routes.

Endpoints (all JSON):
    GET   /api/tickets                      -> list all tickets
    GET   /api/tickets/<id>                 -> one ticket
    POST  /api/tickets/<id>/status          {"status":"Open"|"Closed"}
    POST  /api/tickets/<id>/assignee        {"assignee":"@Name"}
    POST  /api/tickets/<id>/priority        {"priority":"Low|Medium|High|Urgent"}
    POST  /api/tickets/<id>                 {partial fields} -> general update

Security: every write checks an X-Dashboard-Token header against the
DASHBOARD_API_TOKEN env var. Set a long random value in your host's env.
If DASHBOARD_API_TOKEN is unset, writes are refused (fail closed).
"""

import os
import logging
from functools import wraps
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)

dashboard_api = Blueprint("dashboard_api", __name__)

VALID_STATUS = {"Open", "Closed"}
VALID_PRIORITY = {"Low", "Medium", "High", "Urgent"}

# Allow the GitHub Pages origin (and anything you add) to call these routes.
# Comma-separated list in DASHBOARD_ALLOWED_ORIGINS, e.g.
#   https://yourname.github.io
_ALLOWED = [o.strip() for o in os.environ.get("DASHBOARD_ALLOWED_ORIGINS", "*").split(",") if o.strip()] or ["*"]


def _cors(resp):
    origin = request.headers.get("Origin", "")
    if "*" in _ALLOWED:
        resp.headers["Access-Control-Allow-Origin"] = "*"
    elif origin in _ALLOWED:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Dashboard-Token"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


@dashboard_api.after_request
def add_cors(resp):
    return _cors(resp)


def require_token(fn):
    """Guard writes with a shared secret. Reads stay open."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        expected = os.environ.get("DASHBOARD_API_TOKEN", "")
        if not expected:
            return jsonify({"ok": False, "error": "Writes disabled: DASHBOARD_API_TOKEN not set on server."}), 503
        supplied = request.headers.get("X-Dashboard-Token", "")
        if supplied != expected:
            return jsonify({"ok": False, "error": "Unauthorized: bad or missing dashboard token."}), 401
        return fn(*args, **kwargs)
    return wrapper


def _svc():
    """Pull the shared TicketService created in app.py (avoids a 2nd Sheets client)."""
    from app import ticket_service
    return ticket_service


# ── OPTIONS preflight for every route ───────────────────────────────────────
@dashboard_api.route("/api/tickets", methods=["OPTIONS"])
@dashboard_api.route("/api/tickets/<ticket_id>", methods=["OPTIONS"])
@dashboard_api.route("/api/tickets/<ticket_id>/status", methods=["OPTIONS"])
@dashboard_api.route("/api/tickets/<ticket_id>/assignee", methods=["OPTIONS"])
@dashboard_api.route("/api/tickets/<ticket_id>/priority", methods=["OPTIONS"])
def _preflight(ticket_id=None):
    return ("", 204)


# ── Reads ────────────────────────────────────────────────────────────────────
@dashboard_api.route("/api/tickets", methods=["GET"])
def list_tickets():
    try:
        return jsonify(_svc().get_all_tickets())
    except Exception as e:
        logger.error(f"list_tickets error: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


@dashboard_api.route("/api/tickets/<ticket_id>", methods=["GET"])
def get_one(ticket_id):
    t = _svc().get_ticket(ticket_id)
    if not t:
        return jsonify({"ok": False, "error": "Ticket not found"}), 404
    return jsonify(t)


# ── Writes ───────────────────────────────────────────────────────────────────
@dashboard_api.route("/api/tickets/<ticket_id>/status", methods=["POST"])
@require_token
def set_status(ticket_id):
    status = (request.get_json(silent=True) or {}).get("status", "")
    if status not in VALID_STATUS:
        return jsonify({"ok": False, "error": f"status must be one of {sorted(VALID_STATUS)}"}), 400
    ok = _svc().update_ticket_status(ticket_id, status)
    return (jsonify({"ok": True, "ticket": _svc().get_ticket(ticket_id)})
            if ok else (jsonify({"ok": False, "error": "update failed"}), 500))


@dashboard_api.route("/api/tickets/<ticket_id>/assignee", methods=["POST"])
@require_token
def set_assignee(ticket_id):
    assignee = (request.get_json(silent=True) or {}).get("assignee", "").strip()
    if not assignee:
        return jsonify({"ok": False, "error": "assignee is required"}), 400
    if not assignee.startswith("@"):
        assignee = "@" + assignee
    ok = _svc().update_ticket_assignee(ticket_id, assignee)
    return (jsonify({"ok": True, "ticket": _svc().get_ticket(ticket_id)})
            if ok else (jsonify({"ok": False, "error": "update failed"}), 500))


@dashboard_api.route("/api/tickets/<ticket_id>/priority", methods=["POST"])
@require_token
def set_priority(ticket_id):
    priority = (request.get_json(silent=True) or {}).get("priority", "")
    if priority not in VALID_PRIORITY:
        return jsonify({"ok": False, "error": f"priority must be one of {sorted(VALID_PRIORITY)}"}), 400
    ok = _svc().update_ticket_priority(ticket_id, priority)
    return (jsonify({"ok": True, "ticket": _svc().get_ticket(ticket_id)})
            if ok else (jsonify({"ok": False, "error": "update failed"}), 500))


@dashboard_api.route("/api/tickets/<ticket_id>", methods=["POST"])
@require_token
def update_general(ticket_id):
    """Update several fields at once. Only validated fields are applied."""
    body = request.get_json(silent=True) or {}
    ticket = _svc().get_ticket(ticket_id)
    if not ticket:
        return jsonify({"ok": False, "error": "Ticket not found"}), 404

    applied = {}
    if "status" in body:
        if body["status"] not in VALID_STATUS:
            return jsonify({"ok": False, "error": "invalid status"}), 400
        _svc().update_ticket_status(ticket_id, body["status"]); applied["status"] = body["status"]
    if "priority" in body:
        if body["priority"] not in VALID_PRIORITY:
            return jsonify({"ok": False, "error": "invalid priority"}), 400
        _svc().update_ticket_priority(ticket_id, body["priority"]); applied["priority"] = body["priority"]
    if "assignee" in body:
        a = body["assignee"].strip()
        if a and not a.startswith("@"):
            a = "@" + a
        _svc().update_ticket_assignee(ticket_id, a); applied["assignee"] = a

    if not applied:
        return jsonify({"ok": False, "error": "no valid fields supplied"}), 400
    return jsonify({"ok": True, "applied": applied, "ticket": _svc().get_ticket(ticket_id)})
