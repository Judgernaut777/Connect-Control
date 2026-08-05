"""S3 (marketplace/provider activation) and S4 (linked audit trail) routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from connect_control.app import create_app
from connect_control.config import Settings


def _client(seeded, **over) -> TestClient:
    paths = {k: v for k, v in seeded.items() if k != "ids"}
    return TestClient(create_app(Settings(**{**paths, **over})))


def test_marketplace_shows_activation_and_honest_unreachable(seeded) -> None:
    # No ToolConnect server is listening in tests: the page must say so.
    client = _client(seeded)
    response = client.get("/marketplace")
    assert response.status_code == 200
    text = response.text
    assert "unreachable" in text  # live probe honesty, not fabrication
    assert "g-1" in text  # the grant activating the toolconnect provider
    assert "no revocation list loaded" in text  # meta table read, honestly empty


def test_marketplace_degrades_without_any_paths() -> None:
    client = TestClient(create_app(Settings()))
    response = client.get("/marketplace")
    assert response.status_code == 200
    assert "no governance DB path configured" in response.text


def test_audit_page_renders_joined_timeline(seeded) -> None:
    client = _client(seeded)
    response = client.get("/audit/corr-1")
    assert response.status_code == 200
    text = response.text
    for fragment in (
        "Work Request wr-1 recorded",
        "Decision dr-create-wr-1: Allowed",
        "Execution grant g-1 issued to toolconnect",
        "Grant g-1 redeemed by agent-1",
        "Provider enforcement: redeemed",
        "Execution execrec_000000000001: succeeded",
    ):
        assert fragment in text, fragment
    assert text.count('class="ok"') >= 2  # both chain statuses verified ok
    assert "parses, key ids match" in text


def test_audit_page_says_degraded_surfaces_aloud() -> None:
    client = TestClient(create_app(Settings()))
    response = client.get("/audit/corr-1")
    assert response.status_code == 200
    text = response.text
    assert "Degraded surfaces" in text
    assert "CONNECT_CONTROL_GOVERNANCE_DB_PATH" in text
    assert "No records found" in text


def test_audit_page_timeline_ordering(seeded) -> None:
    client = _client(seeded)
    text = client.get("/audit/corr-1").text
    positions = [
        text.index("Work Request wr-1 recorded"),
        text.index("Decision dr-create-wr-1"),
        text.index("Execution grant g-1 issued"),
        text.index("Provider enforcement: redeemed"),
        text.index("Execution execrec_000000000001"),
    ]
    assert positions == sorted(positions)
