"""S3 — Curated marketplace and provider activation (R8).

The marketplace is curated (RA v0.2 §9, ADR-040/ADR-055): listings are
operator-authored through the governance package, there is no self-publishing
flow, and activation is a governed act — kernel-evaluated with
``provider.activate`` authority, fail-closed, refusal persists nothing.

Reads are listing-driven: ``provider_listings``/``provider_activations`` are
read through the governance package's own query layer in-process (the
documented Option-B exception, extended to the marketplace in R8 — see
docs/ARCHITECTURE.md). Raw SQL writes are never performed here; the two
mutation routes go through ``connect_governance.providers``.

The classification badge is fail-closed. A listing's DECLARED classification
is displayed as "enforcing" only when every evidence leg is observable:

  a. the declaration is backed by stored classification evidence;
  b. an active activation exists, with its authorizing Decision Record;
  c. live ToolConnect ``/health`` shows ``gov_trust_root.configured`` and
     ``audit_chain_ok`` both true;
  d. ``provider_enforcement`` records are observable (live
     ``GET /audit?kind=provider_enforcement``, or the ToolConnect DB
     projection as fallback).

Anything missing degrades the badge to "unverified" and names the missing
evidence. A monitor-only listing is shown as monitor-only without the
live-evidence bar — and, per ADR-039, never as a preventative control.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from connect_control.audit import open_readonly
from connect_control.config import Settings
from connect_control.planes.base import PlaneClient

from ._governance import open_governance

_CLASSIFICATIONS = ("enforcing", "monitor_only")


def _read_catalog(client: PlaneClient) -> dict[str, Any]:
    """GET ToolConnect's catalog verbatim; unreachable is said, not hidden."""
    probe = client.get("/catalog")
    return {
        "reachable": probe.reachable,
        "status_code": probe.status_code,
        "body": probe.body,
        "error": probe.error,
    }


def _listings(settings: Settings) -> dict[str, Any]:
    """Curated listings and their activations, via the governance package."""
    handle = open_governance(settings.governance_db_path)
    if not handle.available:
        return {"available": False, "reason": handle.unavailable_reason}
    try:
        from connect_governance.queries import (
            activations_for_listing,
            list_listings,
        )
    except ImportError:
        return {
            "available": False,
            "reason": "connect-governance is installed without the R8 "
                      "marketplace model (the r8-marketplace branch or a "
                      "later release)",
        }
    try:
        with handle.session_factory() as session:
            rows = []
            for listing in list_listings(session):
                try:
                    evidence = json.loads(listing.classification_evidence_json)
                except Exception:
                    evidence = None
                rows.append({
                    "id": listing.id,
                    "provider_id": listing.provider_id,
                    "name": listing.name,
                    "metadata": json.loads(listing.metadata_json or "{}"),
                    "declared": listing.enforcement_classification,
                    "evidence": evidence,
                    "recorded_at": listing.recorded_at,
                    "activations": [
                        {
                            "id": act.id,
                            "state": act.state,
                            "decision_record_id": act.decision_record_id,
                            "recorded_at": act.recorded_at,
                        }
                        for act in activations_for_listing(session, listing.id)
                    ],
                })
        return {"available": True, "listings": rows}
    except Exception as exc:
        return {"available": False, "reason": f"governance store unreadable: {exc}"}


def _grants_for_providers(settings: Settings, provider_ids: list[str]) -> dict[str, Any]:
    """Execution grants issued to the listed providers (Option-B read)."""
    if not settings.governance_db_path:
        return {"configured": False, "grants": [], "revocation_lists": []}
    try:
        with open_readonly(settings.governance_db_path) as conn:
            grants: list[dict[str, Any]] = []
            for provider_id in provider_ids:
                grants.extend(
                    dict(r)
                    for r in conn.execute(
                        "SELECT id, provider_id, decision_record_id,"
                        " issuer_key_id, issued_at, not_before, not_after"
                        " FROM execution_grant_records WHERE provider_id = ?"
                        " ORDER BY id",
                        (provider_id,),
                    ).fetchall()
                )
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
        return {"configured": True, "grants": grants, "revocation_lists": revocation_rows}
    except Exception as exc:
        return {"configured": True, "error": f"governance store unreadable: {exc}",
                "grants": [], "revocation_lists": []}


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


def _enforcement_records(settings: Settings, client: PlaneClient | None) -> dict[str, Any]:
    """Observable provider_enforcement records: live API first, DB fallback."""
    if client is not None:
        probe = client.get("/audit?kind=provider_enforcement")
        if probe.reachable and probe.status_code == 200 and isinstance(probe.body, dict):
            records = probe.body.get("records") or []
            return {
                "observed": bool(records),
                "source": "live ToolConnect /audit API",
                "count": len(records),
            }
    # Fallback: the ToolConnect DB projection (the Option-B read exception).
    if settings.toolconnect_db_path:
        try:
            with open_readonly(settings.toolconnect_db_path) as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM audit WHERE kind = 'provider_enforcement'"
                ).fetchone()[0]
            return {
                "observed": count > 0,
                "source": "ToolConnect DB projection (read-only fallback)",
                "count": count,
            }
        except Exception as exc:
            return {"observed": False, "source": None,
                    "detail": f"ToolConnect store unreadable: {exc}"}
    return {"observed": False, "source": None,
            "detail": "no live answer and no ToolConnect DB path configured"}


def _classification(
    listing: dict[str, Any],
    health: Any | None,
    enforcement: dict[str, Any],
) -> dict[str, Any]:
    """The fail-closed classification badge for one listing.

    Monitor-only is taken as declared, with the ADR-039 framing. Enforcing
    requires every evidence leg; each missing leg is named, and the badge
    degrades to "unverified".
    """
    declared = listing["declared"]
    if declared == "monitor_only":
        return {
            "badge": "monitor-only",
            "missing": [],
            "note": "Monitor-only (ADR-039): observes and produces audit "
                    "evidence; it is never presented as a preventative "
                    "control.",
        }
    missing: list[str] = []
    if not listing.get("evidence"):
        missing.append("stored classification evidence on the listing")
    active = next(
        (a for a in listing["activations"] if a["state"] == "active"), None
    )
    if active is None or not active.get("decision_record_id"):
        missing.append("an active activation with its decision record")
    body = health.body if health is not None and health.reachable else None
    if not isinstance(body, dict):
        missing.append("live ToolConnect /health (unreachable)")
    else:
        trust_root = body.get("gov_trust_root")
        if not isinstance(trust_root, dict) or trust_root.get("configured") is not True:
            missing.append("live /health gov_trust_root.configured == true")
        if body.get("audit_chain_ok") is not True:
            missing.append("live /health audit_chain_ok == true")
    if not enforcement.get("observed"):
        missing.append("observable provider_enforcement records")
    return {
        "badge": "enforcing" if not missing else "unverified",
        "missing": missing,
        "note": None if not missing else
                "Declared 'enforcing' but the evidence is incomplete; shown "
                "as unverified, never as enforcing.",
    }


def _unavailable(reason: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "error": "marketplace mutation surface unavailable",
            "reason": reason,
            "honesty_note": (
                "503 is the truth: without the governance store this surface "
                "cannot list or activate providers, and it does not pretend."
            ),
        },
    )


def _providers_module() -> Any:
    from connect_governance import providers

    return providers


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
        listings_result = _listings(settings)
        enforcement = _enforcement_records(settings, toolconnect)
        listings = []
        for listing in listings_result.get("listings", []):
            listings.append({
                **listing,
                "classification": _classification(listing, health, enforcement),
            })
        provider_ids = [row["provider_id"] for row in listings]
        grants = _grants_for_providers(settings, provider_ids)
        return templates.TemplateResponse(
            request,
            "marketplace.html",
            {
                "health": health,
                "catalog": catalog,
                "listings_available": listings_result.get("available", False),
                "listings_reason": listings_result.get("reason"),
                "listings": listings,
                "enforcement": enforcement,
                "grants": grants,
                "revocation_meta": _toolconnect_revocation_meta(settings),
            },
        )

    @router.post("/marketplace/listings", status_code=201)
    def create_listing(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Write a curated listing (operator-only; kernel-evaluated)."""
        handle = open_governance(settings.governance_db_path)
        if not handle.available:
            raise _unavailable(handle.unavailable_reason or "unavailable")
        try:
            providers = _providers_module()
        except ImportError:
            raise _unavailable(
                "connect-governance is installed without the R8 marketplace "
                "model (the r8-marketplace branch or a later release)"
            )

        required = (
            "listing_id", "provider_id", "name",
            "enforcement_classification", "listed_by_principal_id",
        )
        missing = [k for k in required if not payload.get(k)]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"missing required fields: {', '.join(missing)}",
            )
        if payload["enforcement_classification"] not in _CLASSIFICATIONS:
            raise HTTPException(
                status_code=400,
                detail="enforcement_classification must be one of: "
                       + ", ".join(_CLASSIFICATIONS),
            )
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            raise HTTPException(status_code=400, detail="metadata must be an object")
        evidence = payload.get("classification_evidence", {})
        if not isinstance(evidence, (dict, list)):
            raise HTTPException(
                status_code=400,
                detail="classification_evidence must be an object or array",
            )
        recorded_at = datetime.now(timezone.utc).isoformat()
        decision_record_id = f"dr-{uuid.uuid4().hex}"

        session = handle.session_factory()
        try:
            with session.begin():
                providers.create_listing(
                    session,
                    listing_id=payload["listing_id"],
                    provider_id=payload["provider_id"],
                    name=payload["name"],
                    metadata=metadata,
                    enforcement_classification=payload["enforcement_classification"],
                    classification_evidence=evidence,
                    listed_by_principal_id=payload["listed_by_principal_id"],
                    transition_id=f"tr-{uuid.uuid4().hex}",
                    decision_record_id=decision_record_id,
                    recorded_at=recorded_at,
                    correlation_id=payload.get("correlation_id"),
                )
        except providers.ProviderListingRefused as exc:
            # Fail-closed: session.begin() rolled back the recorded Decision
            # together with any partial listing state.
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "provider listing refused",
                    "reason": str(exc),
                    "decision_record_id": decision_record_id,
                    "honesty_note": (
                        "Nothing was persisted: the refusal unwound the "
                        "recorded Decision and the listing writes together."
                    ),
                },
            )
        finally:
            session.close()
        return {
            "created": True,
            "listing_id": payload["listing_id"],
            "provider_id": payload["provider_id"],
            "decision_record_id": decision_record_id,
            "recorded_at": recorded_at,
            "marketplace_url": "/marketplace",
            "decision_url": f"/decisions/{decision_record_id}",
        }

    @router.post("/marketplace/activate", status_code=201)
    def activate(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Activate a listed provider (operator-triggered; kernel-evaluated)."""
        handle = open_governance(settings.governance_db_path)
        if not handle.available:
            raise _unavailable(handle.unavailable_reason or "unavailable")
        try:
            providers = _providers_module()
        except ImportError:
            raise _unavailable(
                "connect-governance is installed without the R8 marketplace "
                "model (the r8-marketplace branch or a later release)"
            )

        required = ("listing_id", "activated_by_principal_id")
        missing = [k for k in required if not payload.get(k)]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"missing required fields: {', '.join(missing)}",
            )
        activation_id = payload.get("activation_id") or f"act-{uuid.uuid4().hex}"
        recorded_at = datetime.now(timezone.utc).isoformat()
        decision_record_id = f"dr-{uuid.uuid4().hex}"

        session = handle.session_factory()
        try:
            with session.begin():
                providers.activate_provider(
                    session,
                    activation_id=activation_id,
                    listing_id=payload["listing_id"],
                    activated_by_principal_id=payload["activated_by_principal_id"],
                    transition_id=f"tr-{uuid.uuid4().hex}",
                    decision_record_id=decision_record_id,
                    recorded_at=recorded_at,
                    correlation_id=payload.get("correlation_id"),
                )
        except providers.ProviderActivationRefused as exc:
            # Fail-closed: session.begin() rolled back the recorded Decision
            # together with any partial activation state.
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "provider activation refused by the governance kernel",
                    "reason": str(exc),
                    "decision_record_id": decision_record_id,
                    "honesty_note": (
                        "Nothing was persisted: the refusal unwound the "
                        "recorded Decision and the activation writes together."
                    ),
                },
            )
        finally:
            session.close()
        return {
            "activated": True,
            "activation_id": activation_id,
            "listing_id": payload["listing_id"],
            "decision_record_id": decision_record_id,
            "recorded_at": recorded_at,
            "marketplace_url": "/marketplace",
            "decision_url": f"/decisions/{decision_record_id}",
        }

    return router
