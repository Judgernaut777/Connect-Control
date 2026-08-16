"""S1 — Work Request creation (the one mutation) and status.

Creation goes through Connect-Governance's kernel-evaluated intake in-process
(the documented Option-B exception): an authorized principal gets a 201 with
the recorded Decision's id; an unauthorized principal gets a 422 with the
Kernel's reason and NOTHING persists (fail-closed rollback). Without the
governance store the surface answers 503, honestly.
"""

from __future__ import annotations

import pytest

pytest.importorskip("connect_governance", reason="audit extra not installed")

from fastapi.testclient import TestClient

from connect_control.app import create_app
from connect_control.config import Settings

from tests.conftest import seed_governance


@pytest.fixture()
def gov_db(tmp_path):
    path = tmp_path / "governance.db"
    seed_governance(path)
    return str(path)


@pytest.fixture()
def client(gov_db) -> TestClient:
    return TestClient(create_app(Settings(governance_db_path=gov_db)))


def _payload(**over):
    body = {
        "work_request_id": "wr-2",
        "owner_organization_id": "org-1",
        "workspace_id": "ws-1",
        "created_by_principal_id": "person-1",
        "governance": {"title": "Audit prep"},
        "granted_authorities": ["work_request.create"],
        "budget_ceiling_usd": 250.0,
        "correlation_id": "corr-2",
    }
    body.update(over)
    return body


def test_creation_happy_path_persists_through_kernel(client, gov_db) -> None:
    response = client.post("/work-requests", json=_payload())
    assert response.status_code == 201
    body = response.json()
    assert body["created"] is True
    assert body["work_request_id"] == "wr-2"
    decision_record_id = body["decision_record_id"]

    from connect_governance.db.models import DecisionRecord, WorkRequest
    from connect_governance.db.session import make_engine, session_factory

    engine = make_engine(f"sqlite+pysqlite:///{gov_db}")
    with session_factory(engine)() as session:
        assert session.get(WorkRequest, "wr-2") is not None
        record = session.get(DecisionRecord, decision_record_id)
        assert record is not None
        assert record.outcome == "Allowed"
        assert record.work_request_id == "wr-2"


def test_denied_creation_rolls_everything_back(client, gov_db) -> None:
    # agent-1 is active but holds no work_request.create authority.
    response = client.post(
        "/work-requests",
        json=_payload(work_request_id="wr-3", created_by_principal_id="agent-1"),
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "not created" in detail["reason"]
    assert detail["decision_record_id"]

    from sqlalchemy import select

    from connect_governance.db.models import (
        DecisionRecord,
        WorkRequest,
        WorkRequestRevision,
    )
    from connect_governance.db.session import make_engine, session_factory

    engine = make_engine(f"sqlite+pysqlite:///{gov_db}")
    with session_factory(engine)() as session:
        assert session.get(WorkRequest, "wr-3") is None
        # Fail-closed: the recorded refusal Decision did not survive either —
        # only the seeded records remain (the R8 curated listing's intake
        # Decision plus the Work Request intake Decision).
        records = session.scalars(select(DecisionRecord)).all()
        assert [r.id for r in records] == ["dr-list-lst-1", "dr-create-wr-1"]
        revisions = session.scalars(select(WorkRequestRevision)).all()
        assert all(r.work_request_id != "wr-3" for r in revisions)


def test_creation_without_governance_db_is_503() -> None:
    client = TestClient(create_app(Settings()))
    response = client.post("/work-requests", json=_payload())
    assert response.status_code == 503
    assert "no governance DB path configured" in response.json()["detail"]["reason"]


def test_creation_missing_fields_is_400(client) -> None:
    response = client.post("/work-requests", json={"work_request_id": "wr-9"})
    assert response.status_code == 400


def test_status_page_lists_revisions_decisions_and_grants(client) -> None:
    response = client.get("/work-requests/wr-1")
    assert response.status_code == 200
    text = response.text
    assert "wr-1" in text
    assert "sr-wr-1-1" in text  # the first revision's state token
    assert "dr-create-wr-1" in text  # the intake Decision Record
    assert "g-1" in text  # the issued grant
    assert '/audit/wr-1' in text  # link into S4


def test_status_unknown_work_request_is_404(client) -> None:
    assert client.get("/work-requests/nope").status_code == 404


def test_status_without_governance_db_is_503() -> None:
    client = TestClient(create_app(Settings()))
    assert client.get("/work-requests/wr-1").status_code == 503


def test_home_page_renders_and_lists_seeded_request(client) -> None:
    response = client.get("/work-requests")
    assert response.status_code == 200
    assert "wr-1" in response.text
    assert "kernel-evaluated" in response.text
