"""Smoke tests for the Connect Control scaffold.

These tests verify the scaffold's honesty properties, not business logic:
healthz answers, configuration echoes, plane probes report real results, and
every mutation route returns 501 rather than pretending to work.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from connect_control.app import create_app
from connect_control.config import Settings
from connect_control.planes.base import MutationNotImplemented, PlaneClient


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(Settings()))


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "connect-control"
    assert "scaffold" in body["scope"]


def test_planes_echoes_configuration_only(client: TestClient) -> None:
    body = client.get("/planes").json()
    assert set(body) == {"agentconnect", "brainconnect", "computeconnect", "toolconnect"}
    assert body["toolconnect"]["url"] == "http://127.0.0.1:8095"


def test_unknown_plane_is_404(client: TestClient) -> None:
    assert client.get("/planes/nosuchplane/health").status_code == 404


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_mutation_routes_return_501(client: TestClient, method: str) -> None:
    response = getattr(client, method)("/planes/agentconnect/tasks")
    assert response.status_code == 501
    assert "not implemented" in response.json()["detail"].lower()


def test_plane_health_reports_real_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "healthy"})

    plane = PlaneClient("http://plane.test", transport=httpx.MockTransport(handler))
    health = plane.health()
    assert health.reachable is True
    assert health.status_code == 200
    assert health.body == {"status": "healthy"}


def test_plane_health_reports_unreachable_honestly() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    plane = PlaneClient("http://plane.test", transport=httpx.MockTransport(handler))
    health = plane.health()
    assert health.reachable is False
    assert health.status_code is None
    assert "ConnectError" in (health.error or "")


def test_mutate_always_raises() -> None:
    plane = PlaneClient("http://plane.test", transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(MutationNotImplemented):
        plane.mutate()


def test_settings_env_overrides() -> None:
    settings = Settings.from_env(
        {
            "CONNECT_CONTROL_TOOLCONNECT_URL": "http://127.0.0.1:9999",
            "CONNECT_CONTROL_BRAINCONNECT_TOKEN": "secret",
        }
    )
    assert settings.plane_urls["toolconnect"] == "http://127.0.0.1:9999"
    assert settings.plane_urls["agentconnect"] == "http://127.0.0.1:8790"
    assert settings.plane_tokens["brainconnect"] == "secret"
