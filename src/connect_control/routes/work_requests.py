"""S1 — Work Request creation and status.

Creation is Connect Control's ONE mutation surface, and it mutates only
through ``connect_governance.work_requests.create_work_request`` imported
in-process against the governance DB (the documented Option-B exception —
docs/ARCHITECTURE.md). Intake is kernel-evaluated and fail-closed: anything
other than an Allowed Decision raises, the transaction rolls back, and the
caller gets a 4xx with the Kernel's reason. Nothing is ever half-written.

Status reads go through the governance package's models and query layer
(``connect_governance.queries``), never raw SQL.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from connect_control.config import Settings

from ._governance import open_governance


def _unavailable(reason: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "error": "work-request surface unavailable",
            "reason": reason,
            "honesty_note": (
                "503 is the truth: without the governance store this surface "
                "cannot create or read Work Requests, and it does not pretend."
            ),
        },
    )


def build_router(settings: Settings, templates: Jinja2Templates) -> APIRouter:
    router = APIRouter(tags=["work-requests"])

    @router.get("/work-requests", response_class=HTMLResponse)
    def work_requests_home(request: Request) -> HTMLResponse:
        handle = open_governance(settings.governance_db_path)
        recent: list[dict[str, Any]] = []
        if handle.available:
            from sqlalchemy import select

            from connect_governance.db.models import WorkRequest

            with handle.session_factory() as session:
                rows = session.scalars(
                    select(WorkRequest).order_by(WorkRequest.id).limit(100)
                ).all()
                recent = [
                    {
                        "id": row.id,
                        "owner_organization_id": row.owner_organization_id,
                        "workspace_id": row.workspace_id,
                        "created_by_principal_id": row.created_by_principal_id,
                        "recorded_at": row.recorded_at,
                    }
                    for row in rows
                ]
        return templates.TemplateResponse(
            request,
            "work_requests.html",
            {
                "available": handle.available,
                "unavailable_reason": handle.unavailable_reason,
                "work_requests": recent,
            },
        )

    @router.post("/work-requests", status_code=201)
    def create_work_request(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        handle = open_governance(settings.governance_db_path)
        if not handle.available:
            raise _unavailable(handle.unavailable_reason or "unavailable")
        try:
            from connect_governance.work_requests import (
                WorkRequestRefused,
                create_work_request as intake,
            )
        except ImportError:
            raise _unavailable(
                "connect-governance is installed without the R7 work-request "
                "intake (the r7-audit-trail branch or a later release)"
            )

        required = (
            "work_request_id", "owner_organization_id", "workspace_id",
            "created_by_principal_id",
        )
        missing = [k for k in required if not payload.get(k)]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"missing required fields: {', '.join(missing)}",
            )
        governance = payload.get("governance", {})
        if not isinstance(governance, dict):
            raise HTTPException(status_code=400, detail="governance must be an object")
        recorded_at = datetime.now(timezone.utc).isoformat()
        decision_record_id = f"dr-{uuid.uuid4().hex}"

        session = handle.session_factory()
        try:
            with session.begin():
                intake(
                    session,
                    work_request_id=payload["work_request_id"],
                    owner_organization_id=payload["owner_organization_id"],
                    workspace_id=payload["workspace_id"],
                    created_by_principal_id=payload["created_by_principal_id"],
                    revision_id=f"rev-{uuid.uuid4().hex}",
                    state_revision=f"sr-{uuid.uuid4().hex}",
                    governance=governance,
                    granted_authorities=tuple(payload.get("granted_authorities", ())),
                    budget_ceiling_usd=payload.get("budget_ceiling_usd"),
                    transition_id=f"tr-{uuid.uuid4().hex}",
                    decision_record_id=decision_record_id,
                    recorded_at=recorded_at,
                    correlation_id=payload.get("correlation_id"),
                )
        except WorkRequestRefused as exc:
            # Fail-closed: session.begin() rolled back the recorded Decision
            # together with any partial intake state.
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "work request refused by the governance kernel",
                    "reason": str(exc),
                    "decision_record_id": decision_record_id,
                    "honesty_note": (
                        "Nothing was persisted: the refusal unwound the "
                        "recorded Decision and the intake writes together."
                    ),
                },
            )
        finally:
            session.close()
        return {
            "created": True,
            "work_request_id": payload["work_request_id"],
            "decision_record_id": decision_record_id,
            "recorded_at": recorded_at,
            "status_url": f"/work-requests/{payload['work_request_id']}",
            "audit_url": f"/audit/{payload['work_request_id']}",
        }

    @router.get("/work-requests/{work_request_id}", response_class=HTMLResponse)
    def work_request_status(request: Request, work_request_id: str) -> HTMLResponse:
        handle = open_governance(settings.governance_db_path)
        if not handle.available:
            raise _unavailable(handle.unavailable_reason or "unavailable")
        from sqlalchemy import select

        from connect_governance.db.models import WorkRequest, WorkRequestRevision
        from connect_governance.queries import (
            decisions_for_work_request,
            grants_for_work_request,
        )

        with handle.session_factory() as session:
            row = session.get(WorkRequest, work_request_id)
            if row is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"no Work Request {work_request_id!r}",
                )
            revisions = session.scalars(
                select(WorkRequestRevision)
                .where(WorkRequestRevision.work_request_id == work_request_id)
                .order_by(WorkRequestRevision.revision_number)
            ).all()
            decisions = decisions_for_work_request(session, work_request_id)
            grants = grants_for_work_request(session, work_request_id)
            context = {
                "work_request": {
                    "id": row.id,
                    "owner_organization_id": row.owner_organization_id,
                    "workspace_id": row.workspace_id,
                    "created_by_principal_id": row.created_by_principal_id,
                    "recorded_at": row.recorded_at,
                },
                "revisions": [
                    {
                        "id": rev.id,
                        "revision_number": rev.revision_number,
                        "state_revision": rev.state_revision,
                        "governance_json": rev.governance_json,
                        "granted_authorities": rev.granted_authorities,
                        "budget_ceiling_usd": rev.budget_ceiling_usd,
                        "recorded_at": rev.recorded_at,
                    }
                    for rev in revisions
                ],
                "decisions": [
                    {
                        "id": dec.id,
                        "outcome": dec.outcome,
                        "evaluated_at": dec.evaluated_at,
                        "correlation_id": dec.correlation_id,
                    }
                    for dec in decisions
                ],
                "grants": [
                    {
                        "id": grant.id,
                        "provider_id": grant.provider_id,
                        "issuer_key_id": grant.issuer_key_id,
                        "issued_at": grant.issued_at,
                        "decision_record_id": grant.decision_record_id,
                    }
                    for grant in grants
                ],
            }
        return templates.TemplateResponse(request, "work_request_status.html", context)

    return router
