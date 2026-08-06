"""FastAPI application factory for Connect Control.

What this serves today (scaffold, honestly stated):

- ``GET /healthz`` — this service's own liveness.
- ``GET /planes`` — the configured plane endpoints (configuration echo only).
- ``GET /planes/{name}/health`` — a read-only proxy of each plane's real
  health route, reporting exactly what the plane answered.
- Any state-changing request to a plane route — **501 Not Implemented**. The
  control plane mutates only through an owning plane's public API, and no such
  path is built yet.

R7 adds the four UI surfaces, server-rendered: Work Request creation and
status (the one mutation, through Connect-Governance's kernel-evaluated
intake), Decision + explanation, minimal marketplace/provider activation, and
the linked audit trail (the read-only Option-B projection over the three
planes' SQLite stores — see docs/ARCHITECTURE.md). Workspaces, onboarding,
and budgets are not built. See docs/ROADMAP.md.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from connect_control import __version__
from connect_control.config import Settings
from connect_control.planes import build_plane_clients
from connect_control.planes.base import MutationNotImplemented
from connect_control.routes import audit as audit_routes
from connect_control.routes import decisions as decision_routes
from connect_control.routes import marketplace as marketplace_routes
from connect_control.routes import work_requests as work_request_routes

_MUTATION_METHODS = ["POST", "PUT", "PATCH", "DELETE"]

_TEMPLATES_DIR = Path(__file__).parent / "ui" / "templates"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app. All plane access flows through read-only clients."""
    settings = settings or Settings.from_env()
    clients = build_plane_clients(settings)
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    app = FastAPI(
        title="Connect Control",
        version=__version__,
        description=(
            "The thin Control plane of the Connect ecosystem. Scaffold: "
            "read-only plane health only; workspaces, onboarding, budgets, "
            "and marketplace discovery are not built yet."
        ),
    )

    @app.get("/healthz")
    def healthz() -> dict[str, object]:
        return {
            "status": "ok",
            "service": "connect-control",
            "version": __version__,
            "scope": "scaffold — read-only plane coordination only",
        }

    @app.get("/planes")
    def list_planes() -> dict[str, object]:
        return {
            name: {"url": url, "access": "read-only (health probe implemented)"}
            for name, url in settings.plane_urls.items()
        }

    @app.get("/planes/{name}/health")
    def plane_health(name: str) -> dict[str, object]:
        client = clients.get(name)
        if client is None:
            raise HTTPException(status_code=404, detail=f"unknown plane: {name}")
        return asdict(client.health())

    @app.api_route("/planes/{name}/{path:path}", methods=_MUTATION_METHODS)
    def plane_mutation(name: str, path: str) -> JSONResponse:
        if name not in clients:
            raise HTTPException(status_code=404, detail=f"unknown plane: {name}")
        try:
            clients[name].mutate()
        except MutationNotImplemented as exc:
            return JSONResponse(
                status_code=501,
                content={
                    "detail": str(exc),
                    "plane": name,
                    "path": path,
                    "honesty_note": (
                        "501 is the truth: this route does nothing and cannot "
                        "be made to do anything by retrying."
                    ),
                },
            )
        raise AssertionError("unreachable: mutate() always raises")

    # The four R7 surfaces (S1–S4). S1's creation is the one mutation, and it
    # goes through the governance package's kernel-evaluated intake — not the
    # plane-proxy path above, which stays 501 for everything.
    app.include_router(work_request_routes.build_router(settings, templates))
    app.include_router(decision_routes.build_router(settings, templates))
    app.include_router(marketplace_routes.build_router(settings, templates, clients))
    app.include_router(audit_routes.build_router(settings, templates))

    return app
