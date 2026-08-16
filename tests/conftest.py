"""End-to-end seeded fixture for the R7 surfaces.

Builds three REAL SQLite stores with the sibling planes' own libraries (the
optional ``audit`` extra), writing one complete linked chain:

    Work Request wr-1 → intake Decision Record dr-create-wr-1 → execution
    grant g-1 → ToolConnect redemption + provider_enforcement records →
    two hash-chained AgentConnect Execution Records.

The fixed governance test keypair below is the same fixture key
Connect-Governance's own grant tests publish (private key material in a test
fixture is deliberate: it makes the signed artifacts reproducible).

This conftest is importable WITHOUT the audit extra: every sibling import is
lazy, inside the seed functions. Test modules that need the siblings skip
themselves with ``pytest.importorskip`` at module top — the standard idiom,
so a dev-only install collects cleanly (skips, never a collection error).
"""

from __future__ import annotations

import json

import pytest

# Genesis is recorded in the past so the founding authority it grants is
# effective at any real wall-clock "now" (the kernel evaluates intake at the
# caller-supplied instant; Connect Control supplies real now).
T = "2020-08-10T09:30:00Z"
AT = "2026-08-10T10:00:00Z"

# Connect-Governance's published test keypair (tests/test_grants.py).
PRIVATE_KEY_PEM = (
    "-----BEGIN PRIVATE KEY-----\n"
    "MC4CAQAwBQYDK2VwBCIEIDkN5Il+uD9CLnuM+KTlqM+bKDnJql49TksMqQZ8Z3Kh\n"
    "-----END PRIVATE KEY-----\n"
)
PUBLIC_KEY_PEM = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MCowBQYDK2VwAyEA/XluIVKX4rL4Za5ar1AYWE26XHAjLGGYAoycsyl+/m0=\n"
    "-----END PUBLIC KEY-----\n"
)
KEY_ID = "ed25519:f294dcbe2bea2831af6df47eaf039ec5b7b223644dd1689f63be2d90bb5d800a"

IDS = {
    "work_request_id": "wr-1",
    "decision_record_id": "dr-create-wr-1",
    "grant_id": "g-1",
    "correlation_id": "corr-1",
}


def seed_governance(gov_path):
    from connect_governance.db.models import (
        AuthorityRelationship,
        ExecutionGrantRecord,
    )
    from connect_governance.db.session import (
        create_all,
        make_engine,
        session_factory,
    )
    from connect_governance.genesis import GenesisRequest, initialize_deployment
    from connect_governance.grants import issue_grant
    from connect_governance.providers import create_listing
    from connect_governance.work_requests import create_work_request

    engine = make_engine(f"sqlite+pysqlite:///{gov_path}")
    create_all(engine)
    with session_factory(engine)() as session:
        initialize_deployment(
            session,
            GenesisRequest(
                deployment_root_fingerprint="SHA256:deadbeef",
                installer="installer",
                software_version="0.0.1",
                initial_policy_hash="sha256:p",
                initial_config_hash="sha256:c",
                organization_id="org-1",
                organization_name="Org",
                workspace_id="ws-1",
                workspace_name="WS",
                founding_person_id="person-1",
                founding_person_name="Founder",
                initial_agent_id="agent-1",
                initial_agent_name="Agent",
                authority_id="auth-genesis",
                recorded_at=T,
            ),
        )
        # R8: the operator principal holds the marketplace curation
        # vocabulary (provider.list / provider.activate), recorded as the
        # ordinary AuthorityRelationship row such a grant would write —
        # the same pattern as Connect-Governance's own provider fixtures.
        session.add(
            AuthorityRelationship(
                id="auth-operator",
                relationship_type="OperatorGrant",
                principal_id="person-1",
                target_id="org-1",
                granted_authorities=json.dumps(
                    ["provider.list", "provider.activate"]
                ),
                effective_from=T,
                effective_until=None,
                revoked_at=None,
                recorded_at=T,
                provenance="auth-genesis",
            )
        )
        session.flush()
        # One curated listing for the seeded toolconnect provider
        # (monitor-only: the seeded deployment's classification declaration).
        create_listing(
            session,
            listing_id="lst-1",
            provider_id="toolconnect",
            name="ToolConnect",
            metadata={"capabilities": ["tool.invoke"], "version": "0.1.0"},
            enforcement_classification="monitor_only",
            classification_evidence={},
            listed_by_principal_id="person-1",
            transition_id="t-list-lst-1",
            decision_record_id="dr-list-lst-1",
            recorded_at=T,
        )
        create_work_request(
            session,
            work_request_id="wr-1",
            owner_organization_id="org-1",
            workspace_id="ws-1",
            created_by_principal_id="person-1",
            revision_id="rev-wr-1-1",
            state_revision="sr-wr-1-1",
            governance={"title": "Quarterly close", "scope": "finance"},
            granted_authorities=("work_request.create",),
            budget_ceiling_usd=5000.0,
            transition_id="t-create-wr-1",
            decision_record_id="dr-create-wr-1",
            recorded_at=T,
            correlation_id="corr-1",
        )
        issue_grant(
            session,
            decision_record_id="dr-create-wr-1",
            grant_id="g-1",
            private_key_pem=PRIVATE_KEY_PEM,
            issuer_key_id=KEY_ID,
            work_request_id="wr-1",
            work_request_revision="sr-wr-1-1",
            requesting_principal_id="agent-1",
            organization_id="org-1",
            workspace_id="ws-1",
            provider_id="toolconnect",
            permitted_operations=("tool.invoke",),
            issued_at=T,
            not_before="2020-01-01T00:00:00Z",
            not_after="2030-01-01T00:00:00Z",
            argument_constraints={"tool": "reader", "source": "s", "path": "/srv/in"},
            data_classifications=("internal",),
            correlation_id="corr-1",
        )
        session.commit()
        grant_artifact = json.loads(
            session.get(ExecutionGrantRecord, "g-1").grant_json
        )
    return grant_artifact


def seed_agentconnect(ac_path, artifact_dir) -> None:
    from agentconnect.core import AgentConnectService, CreateTaskRequest
    from agentconnect.core.execution_record_store import ExecutionRecordLedger
    from agentconnect.core.execution_records import (
        ExecutorIdentity,
        ProviderEnforcementRef,
        ToolIdentity,
        build_execution_record,
    )

    svc = AgentConnectService.create(
        db_path=str(ac_path), artifact_dir=str(artifact_dir), workers=[]
    )
    task = svc.create_task(CreateTaskRequest(title="T"))
    ledger = ExecutionRecordLedger(svc.storage)
    for n in (1, 2):
        ledger.record(
            build_execution_record(
                execution_record_id=f"execrec_{n:012d}",
                work_request_id="wr-1",
                task_id=task.id,
                decision_record_id="dr-create-wr-1",
                grant_id="g-1",
                correlation_id="corr-1",
                provider_enforcement=ProviderEnforcementRef(
                    provider_id="toolconnect",
                    grant_id="g-1",
                    redemption_outcome="redeemed",
                    verified=True,
                    args_hash="ab12" * 16,
                    enforced_at=AT,
                ),
                executor=ExecutorIdentity(
                    executor_id="worker-1", harness="agentconnect-runtime"
                ),
                tool=ToolIdentity(source_id="agentconnect-runtime", name="reader"),
                outcome="succeeded",
                started_at=AT,
                finished_at="2026-08-10T10:00:01Z",
            )
        )


def seed_toolconnect(tc_path, grant_artifact) -> None:
    from toolconnect.policy import CedarPolicyEngine
    from toolconnect.service import ToolConnectService
    from toolconnect.store import SqliteStore

    store = SqliteStore(tc_path)
    svc = ToolConnectService(store, CedarPolicyEngine(""), gov_trust_root_pem=PUBLIC_KEY_PEM)
    result = svc.redeem_governance_grant(
        grant_artifact,
        principal={"id": "agent-1"},
        source_id="s",
        name="reader",
        args={"path": "/srv/in"},
        at=AT,
    )
    assert result["redeemed"] is True, result
    store.close()


@pytest.fixture()
def seeded(tmp_path):
    """Three linked stores on disk; returns their paths and the shared ids."""
    gov_path = tmp_path / "governance.db"
    ac_path = tmp_path / "agentconnect.db"
    tc_path = tmp_path / "toolconnect.db"
    grant_artifact = seed_governance(gov_path)
    seed_agentconnect(ac_path, tmp_path / "artifacts")
    seed_toolconnect(tc_path, grant_artifact)
    return {
        "governance_db_path": str(gov_path),
        "agentconnect_db_path": str(ac_path),
        "toolconnect_db_path": str(tc_path),
        "ids": dict(IDS),
    }
