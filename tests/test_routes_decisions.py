"""S2 — Decision and explanation (read-only render of stored evidence)."""

from __future__ import annotations

import pytest

pytest.importorskip("connect_governance", reason="audit extra not installed")

from fastapi.testclient import TestClient

from connect_control.app import create_app
from connect_control.config import Settings

from tests.conftest import seed_governance


@pytest.fixture()
def client(tmp_path) -> TestClient:
    path = tmp_path / "governance.db"
    seed_governance(path)
    return TestClient(create_app(Settings(governance_db_path=str(path))))


def test_decision_page_renders_explanation(client) -> None:
    response = client.get("/decisions/dr-create-wr-1")
    assert response.status_code == 200
    text = response.text
    assert "dr-create-wr-1" in text
    assert "Allowed" in text
    assert "Operator view" in text
    assert "Proof view" in text
    assert '/audit/dr-create-wr-1' in text


def test_unknown_decision_is_404(client) -> None:
    assert client.get("/decisions/nope").status_code == 404


def test_decision_surface_without_governance_db_is_503() -> None:
    client = TestClient(create_app(Settings()))
    response = client.get("/decisions/dr-create-wr-1")
    assert response.status_code == 503
    assert "no governance DB path configured" in response.json()["detail"]["reason"]
