"""The audit projection: join across three stores, chain status, tamper evidence.

Mirrors test_app.py's honesty discipline: a resolved trail reports exactly
what the stores contain, a mutated record breaks the chain status (never
silently passes), and an unconfigured path degrades honestly rather than
fabricating an empty trail.
"""

from __future__ import annotations

import sqlite3

import pytest

# These tests build real stores with the sibling planes' own libraries.
pytest.importorskip("connect_governance", reason="audit extra not installed")
pytest.importorskip("agentconnect.core", reason="audit extra not installed")
pytest.importorskip("toolconnect", reason="audit extra not installed")

from connect_control.audit import open_readonly, resolve

from tests.conftest import IDS


def test_resolve_from_each_linkage_id(seeded) -> None:
    for identifier in IDS.values():
        trail = resolve(identifier, **{k: v for k, v in seeded.items() if k != "ids"})
        assert trail.found, identifier
        assert len(trail.decisions) == 1
        assert len(trail.grants) == 1
        assert len(trail.redemptions) == 1
        assert len(trail.enforcement) == 1
        assert len(trail.executions) == 2
        assert len(trail.work_requests) == 1
        assert trail.degraded == []
        statuses = {c.chain: c.status for c in trail.chain_statuses}
        assert statuses == {"agentconnect": "ok", "toolconnect": "ok"}


def test_unknown_identifier_finds_nothing_but_stays_honest(seeded) -> None:
    trail = resolve("nope", **{k: v for k, v in seeded.items() if k != "ids"})
    assert not trail.found
    # The chains themselves still verify: empty trail ≠ broken store.
    assert {c.status for c in trail.chain_statuses} == {"ok"}


def test_grant_artifact_check_reports_redemption_time_signature_note(seeded) -> None:
    trail = resolve("g-1", **{k: v for k, v in seeded.items() if k != "ids"})
    check = trail.grants[0]["artifact_check"]
    assert check["ok"] is True
    assert check["artifact_parses"] is True
    assert check["payload_issuer_key_id_matches"] is True
    assert "verified by the provider at redemption" in check["note"]
    assert "not re-verified here" in check["note"]


def test_agentconnect_tamper_breaks_chain_status(seeded) -> None:
    conn = sqlite3.connect(seeded["agentconnect_db_path"])
    conn.execute(
        "UPDATE execution_records SET record_json = replace(record_json,"
        " 'succeeded', 'failed') WHERE id = 'execrec_000000000001'"
    )
    conn.commit()
    conn.close()
    trail = resolve("corr-1", **{k: v for k, v in seeded.items() if k != "ids"})
    ac = next(c for c in trail.chain_statuses if c.chain == "agentconnect")
    assert ac.status == "broken"
    assert "execrec_000000000001" in ac.detail


def test_toolconnect_tamper_breaks_chain_status(seeded) -> None:
    conn = sqlite3.connect(seeded["toolconnect_db_path"])
    conn.execute(
        "UPDATE audit SET body = replace(body, 'redeemed', 'denied:bogus')"
        " WHERE kind = 'provider_enforcement'"
    )
    conn.commit()
    conn.close()
    trail = resolve("corr-1", **{k: v for k, v in seeded.items() if k != "ids"})
    tc = next(c for c in trail.chain_statuses if c.chain == "toolconnect")
    assert tc.status == "broken"


def test_honest_degradation_without_db_paths() -> None:
    trail = resolve("anything")
    assert not trail.found
    assert len(trail.degraded) == 3
    statuses = {c.chain: c.status for c in trail.chain_statuses}
    assert statuses["agentconnect"] == "not_configured"
    assert statuses["toolconnect"] == "not_configured"


def test_unreadable_store_is_degraded_not_fatal(tmp_path) -> None:
    missing = tmp_path / "absent.db"
    trail = resolve(
        "x",
        governance_db_path=str(missing),
        agentconnect_db_path=str(missing),
        toolconnect_db_path=str(missing),
    )
    assert not trail.found
    assert any("unreadable" in note for note in trail.degraded)


def test_open_readonly_refuses_writes(seeded) -> None:
    with open_readonly(seeded["toolconnect_db_path"]) as conn:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO meta(key, value) VALUES ('x', 'y')")


def test_timeline_orders_governance_before_execution(seeded) -> None:
    trail = resolve("corr-1", **{k: v for k, v in seeded.items() if k != "ids"})
    kinds = [e["kind"] for e in trail.timeline]
    # The governance half precedes the provider half, which precedes execution.
    assert kinds.index("work_request") < kinds.index("decision")
    assert kinds.index("decision") < kinds.index("grant")
    assert kinds.index("provider_enforcement") < kinds.index("execution_record")
    assert len(kinds) == 7
