"""S3 — Marketplace and provider activation (minimal; full marketplace is R8).

Read-only, three honest ingredients:

* ToolConnect's live health and catalog, read over HTTP through the existing
  plane-client idiom (verbatim answers; unreachable is reported, not hidden);
* provider activation, derived from the governance store: execution grants
  issued for ``provider_id='toolconnect'`` (read through the audit
  projection's read-only exception);
* the ADR-052 revocation list ToolConnect has loaded, read from its ``meta``
  table (list id + issued-at), when a ToolConnect DB path is configured.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from connect_control.audit import open_readonly
from connect_control.config import Settings
from connect_control.planes.base import PlaneClient


def _read_catalog(client: PlaneClient) -> dict[str, Any]:
    """GET ToolConnect's catalog verbatim; unreachable is said, not hidden."""
    probe = client.get("/catalog")
    return {
        "reachable": probe.reachable,
        "status_code": probe.status_code,
        "body": probe.body,
        "error": probe.error,
    }


def _provider_activation(settings: Settings) -> dict[str, Any]:
    """Grants issued to the toolconnect provider, from the governance store."""
    if not settings.governance_db_path:
        return {
            "configured": False,
            "reason": "no governance DB path configured "
                      "(CONNECT_CONTROL_GOVERNANCE_DB_PATH)",
        }
    try:
        with open_readonly(settings.governance_db_path) as conn:
            rows = [
                dict(r)
                for r in conn.execute(
                    "SELECT id, decision_record_id, issuer_key_id, issued_at,"
                    " not_before, not_after FROM execution_grant_records"
                    " WHERE provider_id = 'toolconnect' ORDER BY id"
                ).fetchall()
            ]
            try:
                revocation_rows = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT list_id, issuer_key_id, issued_at, supersedes"
                        " FROM revocation_list_records ORDER BY issued_at"
                    ).fetchall()
                ]
            except Exception:
                revocation_rows = []
        return {"configured": True, "grants": rows, "revocation_lists": revocation_rows}
    except Exception as exc:
        return {"configured": True, "error": f"governance store unreadable: {exc}"}


def _toolconnect_revocation_meta(settings: Settings) -> dict[str, Any]:
    """The revocation list ToolConnect reports it loaded (its meta table)."""
    if not settings.toolconnect_db_path:
        return {
            "configured": False,
            "reason": "no ToolConnect DB path configured "
                      "(CONNECT_CONTROL_TOOLCONNECT_DB_PATH)",
        }
    try:
        with open_readonly(settings.toolconnect_db_path) as conn:
            meta = {
                row[0]: row[1]
                for row in conn.execute(
                    "SELECT key, value FROM meta WHERE key IN"
                    " ('gov_revocation_list_id', 'gov_revocation_list_issued_at')"
                ).fetchall()
            }
        return {
            "configured": True,
            "list_id": meta.get("gov_revocation_list_id"),
            "issued_at": meta.get("gov_revocation_list_issued_at"),
        }
    except Exception as exc:
        return {"configured": True, "error": f"toolconnect store unreadable: {exc}"}


def build_router(
    settings: Settings,
    templates: Jinja2Templates,
    clients: dict[str, PlaneClient],
) -> APIRouter:
    router = APIRouter(tags=["marketplace"])

    @router.get("/marketplace", response_class=HTMLResponse)
    def marketplace(request: Request) -> HTMLResponse:
        toolconnect = clients.get("toolconnect")
        health = toolconnect.health() if toolconnect is not None else None
        catalog = _read_catalog(toolconnect) if toolconnect is not None else None
        return templates.TemplateResponse(
            request,
            "marketplace.html",
            {
                "health": health,
                "catalog": catalog,
                "activation": _provider_activation(settings),
                "revocation_meta": _toolconnect_revocation_meta(settings),
            },
        )

    return router
