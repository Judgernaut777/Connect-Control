"""S2 — Decision and explanation.

Read-only: rehydrate the stored Decision Record through
``connect_governance.decisions.load_record`` and render the explanation
computed on read by ``connect_governance.explanation.explain`` (a pure
projection — nothing rendered here is or was ever stored).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from connect_control.config import Settings

from ._governance import open_governance


def build_router(settings: Settings, templates: Jinja2Templates) -> APIRouter:
    router = APIRouter(tags=["decisions"])

    @router.get("/decisions/{record_id}", response_class=HTMLResponse)
    def decision_detail(request: Request, record_id: str) -> HTMLResponse:
        handle = open_governance(settings.governance_db_path)
        if not handle.available:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "decision surface unavailable",
                    "reason": handle.unavailable_reason,
                    "honesty_note": (
                        "503 is the truth: without the governance store no "
                        "Decision Record can be rehydrated, and none is faked."
                    ),
                },
            )
        from connect_governance.decisions import load_record
        from connect_governance.explanation import explain

        with handle.session_factory() as session:
            try:
                decision_request, decision = load_record(session, record_id)
            except KeyError:
                raise HTTPException(
                    status_code=404, detail=f"no Decision Record {record_id!r}"
                )
        explanation = explain(decision_request, decision)
        return templates.TemplateResponse(
            request,
            "decision.html",
            {
                "record_id": record_id,
                "request": decision_request.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json"),
                "operator": explanation["operator"],
                "proof": explanation["proof"],
            },
        )

    return router
