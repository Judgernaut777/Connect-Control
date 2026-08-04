"""Per-plane client wiring.

Each subclass exists only to pin the plane's name and its best-known health
route from Connect's COMPATIBILITY.md. No plane-specific behavior beyond that
is implemented yet.
"""

from __future__ import annotations

from connect_control.config import Settings
from connect_control.planes.base import PlaneClient


class AgentConnectClient(PlaneClient):
    """Work plane. agentconnect-api; authorization on every route except /health."""

    name = "agentconnect"
    health_path = "/health"


class BrainConnectClient(PlaneClient):
    """Knowledge plane. brainconnect serve, default 127.0.0.1:8787, optional bearer token."""

    name = "brainconnect"
    health_path = "/health"


class ComputeConnectClient(PlaneClient):
    """Compute plane. computeconnect serve, default port 8090; GET /health is a contract route."""

    name = "computeconnect"
    health_path = "/health"


class ToolConnectClient(PlaneClient):
    """Capability plane. toolconnect serve, loopback 127.0.0.1:8095; decision point only."""

    name = "toolconnect"
    health_path = "/health"


_CLIENT_CLASSES: dict[str, type[PlaneClient]] = {
    cls.name: cls
    for cls in (AgentConnectClient, BrainConnectClient, ComputeConnectClient, ToolConnectClient)
}


def build_plane_clients(settings: Settings) -> dict[str, PlaneClient]:
    """Construct one read-only client per configured plane."""
    return {
        name: _CLIENT_CLASSES[name](
            settings.plane_urls[name],
            token=settings.plane_tokens.get(name),
            timeout=settings.http_timeout,
        )
        for name in _CLIENT_CLASSES
    }
