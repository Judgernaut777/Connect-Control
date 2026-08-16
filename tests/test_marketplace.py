"""R8 — the curated marketplace surface.

Listings and activations are governed mutations through
``connect_governance.providers`` (kernel-evaluated, fail-closed: a refusal
rolls everything back and answers 422). The classification badge is
fail-closed too: "enforcing" is displayed only when every evidence leg is
observable (stored evidence, active activation with its decision record,
live /health trust-root + audit chain, observable provider_enforcement
records); anything missing degrades to "unverified" and names the gap.
"""

from __future__ import annotations

import httpx
import pytest

# The seeded fixture builds all three real stores.
pytest.importorskip("connect_governance", reason="audit extra not installed")
pytest.importorskip("agentconnect.core", reason="audit extra not installed")
pytest.importorskip("toolconnect", reason="audit extra not installed")

from fastapi.testclient import TestClient

from connect_control.app import create_app
from connect_control.config import Settings
from connect_control.planes.base import PlaneClient


def _client(seeded, monkeypatch=None, health_body=None, **over) -> TestClient:
    paths = {k: v for k, v in seeded.items() if k != "ids"}
    if monkeypatch is not None:
        # A live, healthy ToolConnect stand-in: trust root configured, audit
        # chain ok, provider_enforcement records observable.
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(200, json=health_body)
            if request.url.path == "/catalog":
                return httpx.Response(200, json={"sources": [], "tools": []})
            if request.url.path == "/audit":
                return httpx.Response(
                    200, json={"records": [{"kind": "provider_enforcement"}]}
                )
            return httpx.Response(404, json={"error": "unknown"})

        fake = PlaneClient(
            "http://toolconnect.test", transport=httpx.MockTransport(handler)
        )
        monkeypatch.setattr(
            "connect_control.app.build_plane_clients",
            lambda settings: {"toolconnect": fake},
        )
    return TestClient(create_app(Settings(**{**paths, **over})))


HEALTHY = {
    "status": "ok",
    "audit_chain_ok": True,
    "gov_trust_root": {"configured": True, "key_ids": ["ed25519:test"]},
    "gov_provider_id": "toolconnect",
}

EVIDENCE = {"conformance": ["redemption-contract-vectors: pass"]}


def _listing_payload(**over):
    body = {
        "listing_id": "lst-2",
        "provider_id": "toolconnect",
        "name": "ToolConnect (enforcing)",
        "listed_by_principal_id": "person-1",
        "enforcement_classification": "enforcing",
        "metadata": {"capabilities": ["tool.invoke"], "version": "0.1.0"},
        "classification_evidence": dict(EVIDENCE),
    }
    body.update(over)
    return body


def _provider_rows(gov_db):
    from sqlalchemy import select

    from connect_governance.db.models import (
        DecisionRecord,
        ProviderActivation,
        ProviderListing,
    )
    from connect_governance.db.session import make_engine, session_factory

    engine = make_engine(f"sqlite+pysqlite:///{gov_db}")
    with session_factory(engine)() as session:
        return (
            [r.id for r in session.scalars(select(ProviderListing)).all()],
            [r.id for r in session.scalars(select(ProviderActivation)).all()],
            [r.id for r in session.scalars(select(DecisionRecord)).all()],
        )


def test_listing_create_happy_path(seeded) -> None:
    client = _client(seeded)
    response = client.post("/marketplace/listings", json=_listing_payload())
    assert response.status_code == 201
    body = response.json()
    assert body["created"] is True
    assert body["listing_id"] == "lst-2"
    listings, _activations, decisions = _provider_rows(
        seeded["governance_db_path"]
    )
    assert "lst-2" in listings
    assert body["decision_record_id"] in decisions


def test_enforcing_listing_without_evidence_refused(seeded) -> None:
    client = _client(seeded)
    before = _provider_rows(seeded["governance_db_path"])
    response = client.post(
        "/marketplace/listings",
        json=_listing_payload(classification_evidence={}),
    )
    assert response.status_code == 422
    assert "without" in response.json()["detail"]["reason"]
    # Zero rows: no listing, no activation, no new Decision Record.
    assert _provider_rows(seeded["governance_db_path"]) == before


def test_unauthorized_listing_refused(seeded) -> None:
    client = _client(seeded)
    before = _provider_rows(seeded["governance_db_path"])
    response = client.post(
        "/marketplace/listings",
        json=_listing_payload(listed_by_principal_id="agent-1"),
    )
    assert response.status_code == 422
    assert _provider_rows(seeded["governance_db_path"]) == before


def test_listing_mutation_unconfigured_is_honest_503() -> None:
    client = TestClient(create_app(Settings()))
    response = client.post("/marketplace/listings", json=_listing_payload())
    assert response.status_code == 503
    assert "no governance DB path configured" in str(response.json()["detail"])


def test_activation_happy_path_shows_enforcing_badge(seeded, monkeypatch) -> None:
    client = _client(seeded, monkeypatch=monkeypatch, health_body=dict(HEALTHY))
    assert client.post("/marketplace/listings", json=_listing_payload()).status_code == 201
    response = client.post(
        "/marketplace/activate",
        json={"listing_id": "lst-2", "activated_by_principal_id": "person-1"},
    )
    assert response.status_code == 201, response.text
    activation_id = response.json()["activation_id"]
    listings, activations, decisions = _provider_rows(
        seeded["governance_db_path"]
    )
    assert activation_id in activations
    assert response.json()["decision_record_id"] in decisions

    text = client.get("/marketplace").text
    assert "<strong class=\"ok\">enforcing</strong>" in text
    assert response.json()["decision_record_id"] in text  # evidence link


def test_unverified_when_no_active_activation(seeded, monkeypatch) -> None:
    # Enforcing declared with stored evidence and live health, but leg (b) —
    # the active activation — is missing.
    client = _client(seeded, monkeypatch=monkeypatch, health_body=dict(HEALTHY))
    assert client.post("/marketplace/listings", json=_listing_payload()).status_code == 201
    text = client.get("/marketplace").text
    assert "<strong class=\"degraded\">unverified</strong>" in text
    assert "an active activation with its decision record" in text


def test_unverified_when_stored_evidence_missing(seeded, monkeypatch) -> None:
    # Leg (a) cannot be missing via the governed API (it is refused), so this
    # simulates a pre-R8 row directly, then activates it legitimately.
    import json as _json

    from connect_governance.db.models import ProviderListing
    from connect_governance.db.session import make_engine, session_factory
    from connect_governance_kernel import canonical_json

    engine = make_engine(f"sqlite+pysqlite:///{seeded['governance_db_path']}")
    with session_factory(engine)() as session:
        session.add(
            ProviderListing(
                id="lst-legacy",
                provider_id="toolconnect",
                name="Legacy listing",
                metadata_json=canonical_json({}),
                enforcement_classification="enforcing",
                classification_evidence_json=_json.dumps({}),
                recorded_at="2020-08-10T09:30:00Z",
                provenance="pre-r8",
            )
        )
        session.commit()
    client = _client(seeded, monkeypatch=monkeypatch, health_body=dict(HEALTHY))
    assert client.post(
        "/marketplace/activate",
        json={"listing_id": "lst-legacy", "activated_by_principal_id": "person-1"},
    ).status_code == 201
    text = client.get("/marketplace").text
    assert "stored classification evidence on the listing" in text
    assert "<strong class=\"degraded\">unverified</strong>" in text


def test_unverified_when_health_evidence_missing(seeded, monkeypatch) -> None:
    # Leg (c): live /health reachable but no trust root configured.
    client = _client(
        seeded,
        monkeypatch=monkeypatch,
        health_body={
            "status": "ok",
            "audit_chain_ok": True,
            "gov_trust_root": {"configured": False, "key_ids": []},
        },
    )
    assert client.post("/marketplace/listings", json=_listing_payload()).status_code == 201
    assert client.post(
        "/marketplace/activate",
        json={"listing_id": "lst-2", "activated_by_principal_id": "person-1"},
    ).status_code == 201
    text = client.get("/marketplace").text
    assert "gov_trust_root.configured == true" in text
    assert "<strong class=\"degraded\">unverified</strong>" in text


def test_unverified_when_enforcement_records_missing(seeded, monkeypatch) -> None:
    # Leg (d): no observable provider_enforcement records anywhere.
    # The fake client answers /health and /catalog but /audit 404s.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json=dict(HEALTHY))
        return httpx.Response(404, json={"error": "unknown"})

    fake = PlaneClient(
        "http://toolconnect.test", transport=httpx.MockTransport(handler)
    )
    monkeypatch.setattr(
        "connect_control.app.build_plane_clients",
        lambda settings: {"toolconnect": fake},
    )
    client = _client(seeded, toolconnect_db_path="")  # no DB fallback either
    assert client.post("/marketplace/listings", json=_listing_payload()).status_code == 201
    assert client.post(
        "/marketplace/activate",
        json={"listing_id": "lst-2", "activated_by_principal_id": "person-1"},
    ).status_code == 201
    text = client.get("/marketplace").text
    assert "observable provider_enforcement records" in text
    assert "<strong class=\"degraded\">unverified</strong>" in text


def test_monitor_only_never_presented_as_preventative(seeded, monkeypatch) -> None:
    client = _client(seeded, monkeypatch=monkeypatch, health_body=dict(HEALTHY))
    text = client.get("/marketplace").text
    assert "<strong>monitor-only</strong>" in text
    assert "never presented as a preventative" in text
    # The seeded listing is monitor-only: no enforcing badge, no evidence bar.
    assert "<strong class=\"ok\">enforcing</strong>" not in text


def test_unauthorized_activation_refused_and_persists_nothing(seeded) -> None:
    client = _client(seeded)
    assert client.post("/marketplace/listings", json=_listing_payload()).status_code == 201
    before = _provider_rows(seeded["governance_db_path"])
    response = client.post(
        "/marketplace/activate",
        json={"listing_id": "lst-2", "activated_by_principal_id": "agent-1"},
    )
    assert response.status_code == 422
    assert "provider.activate" in response.json()["detail"]["reason"]
    assert _provider_rows(seeded["governance_db_path"]) == before
