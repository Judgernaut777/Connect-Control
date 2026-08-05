"""S4 — the linked audit trail.

``GET /audit/{identifier}`` resolves one identifier — any of
``work_request_id`` / ``decision_record_id`` / ``grant_id`` /
``correlation_id`` — into the joined trail across the three stores via
:mod:`connect_control.audit` (the read-only Option-B projection), with
per-chain verification status, rendered as a timeline. Read-only, always;
degraded surfaces say so on the page.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from connect_control import audit as audit_projection
from connect_control.config import Settings


def build_router(settings: Settings, templates: Jinja2Templates) -> APIRouter:
    router = APIRouter(tags=["audit"])

    @router.get("/audit/{identifier}", response_class=HTMLResponse)
    def audit_trail(request: Request, identifier: str) -> HTMLResponse:
        trail = audit_projection.resolve(
            identifier,
            governance_db_path=settings.governance_db_path,
            agentconnect_db_path=settings.agentconnect_db_path,
            toolconnect_db_path=settings.toolconnect_db_path,
        )
        return templates.TemplateResponse(request, "audit.html", {"trail": trail})

    return router
