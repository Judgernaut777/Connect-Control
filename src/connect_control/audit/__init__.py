"""The linked audit trail — a read-only projection over three planes' stores.

This module is the R7 **Option B** decision (docs/ARCHITECTURE.md): an
explicit, *temporary* exception to Connect Control's standing rule that it
never opens another plane's database. The exception is narrow:

* every connection is opened read-only (``sqlite3.connect(..., mode=ro)``);
* the only queries are indexed SELECTs over the linkage ids
  (``work_request_id`` / ``decision_record_id`` / ``grant_id`` /
  ``correlation_id``), exactly the traversal Connect-Governance's
  EXECUTION_RECORD.md §5 reserves for R7;
* nothing here writes, and nothing here decides.

The exception expires when the planes expose record-read HTTP APIs
(earmarked R8/R9); at that point this module is deleted, not evolved.

Honesty rules this module keeps:

* an unconfigured DB path is a degraded surface, reported as such — never a
  fabricated empty trail;
* chain verification on read *imports* the owning plane's verifier. For
  AgentConnect records that is
  ``agentconnect.core.execution_records.verify_execution_record``; if the
  package is not importable, the chain status is reported as
  ``unverified (verifier unavailable)`` — the canonicalization is **not**
  re-implemented here. The ToolConnect audit chain is a plain
  SHA-256 ``kind‖body‖created_at‖prev_hash`` walk with a durable
  high-water-mark tail check (the formula ToolConnect documents in its own
  store), re-walked read-only.
* grant signatures are **not** re-verified here: the provider verified the
  signature at redemption and recorded that fact (the Provider Enforcement
  Record). This module checks only that the stored grant artifact's canonical
  bytes still parse and that its key ids match the indexed columns — and the
  UI says exactly that.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

try:  # The owning plane's read-side seal check. Never re-implemented here.
    from agentconnect.core.execution_records import (
        ExecutionRecord as _ACExecutionRecord,
    )
    from agentconnect.core.execution_records import (
        verify_execution_record as _ac_verify,
    )
except ImportError:  # pragma: no cover - exercised by honest-degradation tests
    _ACExecutionRecord = None
    _ac_verify = None


#: ToolConnect's audit-chain genesis prev_hash and hash formula, as documented
#: in toolconnect/store.py (SHA-256 of kind‖body‖created_at‖prev_hash, with
#: the durable high-water mark in ``meta`` making tail truncation detectable).
_TC_GENESIS = "0" * 64


def open_readonly(path: str) -> sqlite3.Connection:
    """Open a plane's SQLite store read-only. The only way this module reads."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@dataclass(frozen=True)
class ChainStatus:
    """The verification outcome for one chain (or one honestly-degraded side).

    ``status`` is one of ``ok`` / ``broken`` / ``unverified`` /
    ``not_configured`` / ``empty``. ``broken`` and ``unverified`` are
    different statements and are never conflated.
    """

    chain: str
    status: str
    detail: str


@dataclass
class AuditTrail:
    """Everything one identifier resolves to across the three stores."""

    identifier: str
    degraded: list[str] = field(default_factory=list)
    ids: dict[str, list[str]] = field(default_factory=dict)
    work_requests: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    grants: list[dict[str, Any]] = field(default_factory=list)
    redemptions: list[dict[str, Any]] = field(default_factory=list)
    enforcement: list[dict[str, Any]] = field(default_factory=list)
    executions: list[dict[str, Any]] = field(default_factory=list)
    chain_statuses: list[ChainStatus] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return any(
            (self.work_requests, self.decisions, self.grants, self.redemptions,
             self.enforcement, self.executions)
        )


def _rows(conn: sqlite3.Connection, sql: str, params: Iterable[Any]) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# AgentConnect side
# ---------------------------------------------------------------------------

_AC_ID_COLUMNS = (
    "id", "work_request_id", "decision_record_id", "grant_id", "correlation_id",
)


def _fetch_execution_records(conn: sqlite3.Connection, identifier: str) -> list[dict[str, Any]]:
    where = " OR ".join(f"{c} = ?" for c in _AC_ID_COLUMNS)
    return _rows(
        conn,
        f"SELECT rowid AS _rowid, * FROM execution_records WHERE {where} ORDER BY rowid",
        [identifier] * len(_AC_ID_COLUMNS),
    )


def _verify_agentconnect_chain(conn: sqlite3.Connection) -> ChainStatus:
    """Re-walk the whole ledger on read: every seal and every prev_hash link.

    Uses the owning plane's ``verify_execution_record``; when AgentConnect is
    not importable the chain is reported unverified, not re-implemented.
    """
    rows = _rows(
        conn,
        "SELECT id, record_json, record_hash, prev_hash FROM execution_records"
        " ORDER BY rowid",
        [],
    )
    if not rows:
        return ChainStatus("agentconnect", "empty", "no execution records stored")
    if _ac_verify is None or _ACExecutionRecord is None:
        return ChainStatus(
            "agentconnect",
            "unverified",
            "unverified (verifier unavailable): the agentconnect-core package is "
            "not importable, and Connect Control does not re-implement its "
            "canonicalization",
        )
    prev: Optional[str] = None
    checked = 0
    for row in rows:
        try:
            record = _ACExecutionRecord.model_validate(json.loads(row["record_json"]))
        except Exception as exc:  # malformed stored bytes = tamper evidence
            return ChainStatus(
                "agentconnect", "broken",
                f"record {row['id']!r} does not parse as an Execution Record "
                f"({type(exc).__name__}); first break after {checked} records",
            )
        if not _ac_verify(record):
            return ChainStatus(
                "agentconnect", "broken",
                f"record_hash mismatch at {row['id']!r} after {checked} records",
            )
        if record.record_hash != row["record_hash"]:
            return ChainStatus(
                "agentconnect", "broken",
                f"stored record_hash does not match the sealed record at "
                f"{row['id']!r} after {checked} records",
            )
        if row["prev_hash"] != prev:
            return ChainStatus(
                "agentconnect", "broken",
                f"prev_hash link broken at {row['id']!r} after {checked} records",
            )
        prev = row["record_hash"]
        checked += 1
    return ChainStatus("agentconnect", "ok", f"{checked} records verified")


# ---------------------------------------------------------------------------
# Governance side
# ---------------------------------------------------------------------------


def _fetch_governance(
    conn: sqlite3.Connection, ids: Mapping[str, set[str]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    decisions: dict[str, dict[str, Any]] = {}
    grants: dict[str, dict[str, Any]] = {}
    work_requests: dict[str, dict[str, Any]] = {}

    def _in(column: str, values: set[str]) -> tuple[str, list[str]]:
        vals = sorted(values)
        return f"{column} IN ({','.join('?' * len(vals))})", vals

    wanted = ids["decision_record_id"] | ids["work_request_id"] | ids["correlation_id"]
    if wanted:
        clauses, params = [], []
        for col in ("id", "work_request_id", "correlation_id"):
            values = set(ids["decision_record_id"] if col == "id" else ids[col])
            if not values:
                continue
            c, p = _in(col, values)
            clauses.append(c)
            params.extend(p)
        for row in _rows(
            conn,
            f"SELECT * FROM decision_records WHERE {' OR '.join(clauses)} ORDER BY id",
            params,
        ):
            decisions[row["id"]] = row

    if wanted or ids["grant_id"]:
        clauses, params = [], []
        for col in ("id", "decision_record_id", "work_request_id", "correlation_id"):
            values = set(ids["grant_id"] if col == "id" else ids[col])
            if not values:
                continue
            c, p = _in(col, values)
            clauses.append(c)
            params.extend(p)
        if clauses:
            for row in _rows(
                conn,
                "SELECT * FROM execution_grant_records "
                f"WHERE {' OR '.join(clauses)} ORDER BY id",
                params,
            ):
                grants[row["id"]] = row

    if _table_exists(conn, "work_requests") and ids["work_request_id"]:
        c, p = _in("id", ids["work_request_id"])
        for row in _rows(conn, f"SELECT * FROM work_requests WHERE {c} ORDER BY id", p):
            work_requests[row["id"]] = row

    return list(decisions.values()), list(grants.values()), list(work_requests.values())


def _check_grant_artifacts(grants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse each stored grant artifact; compare key ids with indexed columns.

    The grant *signature* is deliberately not re-verified here: the provider
    verified it at redemption and recorded the outcome (the Provider
    Enforcement Record). What this check adds on read is tamper evidence for
    the stored bytes themselves.
    """
    for grant in grants:
        try:
            artifact = json.loads(grant["grant_json"])
            payload = artifact["payload"]
            checks = {
                "artifact_parses": True,
                "payload_grant_id_matches": payload.get("grant_id") == grant["id"],
                "payload_issuer_key_id_matches": (
                    payload.get("issuer_key_id") == grant["issuer_key_id"]
                ),
                "payload_decision_record_id_matches": (
                    payload.get("decision_record_id") == grant["decision_record_id"]
                ),
            }
            ok = all(v for k, v in checks.items() if k != "artifact_parses")
            grant["artifact_check"] = {
                **checks,
                "ok": ok,
                "note": (
                    "The grant signature was verified by the provider at "
                    "redemption; it is not re-verified here. This check confirms "
                    "the stored canonical bytes still parse and that the signed "
                    "payload's ids match the indexed record."
                ),
            }
        except Exception as exc:
            grant["artifact_check"] = {
                "artifact_parses": False,
                "ok": False,
                "note": (
                    f"stored grant artifact does not parse ({type(exc).__name__}) "
                    "— the bytes changed after issuance or were never canonical"
                ),
            }
    return grants


# ---------------------------------------------------------------------------
# ToolConnect side
# ---------------------------------------------------------------------------


def _fetch_toolconnect(
    conn: sqlite3.Connection, ids: Mapping[str, set[str]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    redemptions: list[dict[str, Any]] = []
    if _table_exists(conn, "grant_redemptions"):
        clauses, params = [], []
        for col, key in (("grant_id", "grant_id"),
                         ("decision_record_id", "decision_record_id"),
                         ("correlation_id", "correlation_id")):
            values = sorted(ids[key])
            if not values:
                continue
            clauses.append(f"{col} IN ({','.join('?' * len(values))})")
            params.extend(values)
        if clauses:
            redemptions = _rows(
                conn,
                f"SELECT * FROM grant_redemptions WHERE {' OR '.join(clauses)}"
                " ORDER BY grant_id",
                params,
            )

    enforcement: list[dict[str, Any]] = []
    if _table_exists(conn, "audit"):
        wanted_grants = set(ids["grant_id"])
        wanted_decisions = set(ids["decision_record_id"])
        wanted_corr = set(ids["correlation_id"])
        for row in _rows(
            conn,
            "SELECT seq, kind, body, created_at, record_hash FROM audit"
            " WHERE kind = 'provider_enforcement' ORDER BY seq",
            [],
        ):
            try:
                body = json.loads(row["body"])
            except ValueError:
                continue
            if (
                body.get("grant_id") in wanted_grants
                or (body.get("decision_record_id") in wanted_decisions
                    and body.get("decision_record_id") is not None)
                or (body.get("correlation_id") in wanted_corr
                    and body.get("correlation_id") is not None)
            ):
                row["body_json"] = body
                enforcement.append(row)
    return redemptions, enforcement


def _verify_toolconnect_chain(conn: sqlite3.Connection) -> ChainStatus:
    """Re-walk ToolConnect's hash-chained audit, including the tail check.

    This is the formula ToolConnect documents in its own store (SHA-256 of
    ``kind\\x1fbody\\x1fcreated_at\\x1fprev_hash``) plus the durable
    high-water mark in ``meta`` that makes tail truncation detectable.
    """
    if not _table_exists(conn, "audit"):
        return ChainStatus("toolconnect", "empty", "no audit table present")
    rows = _rows(
        conn,
        "SELECT seq, kind, body, created_at, prev_hash, record_hash"
        " FROM audit ORDER BY seq",
        [],
    )
    if not rows:
        return ChainStatus("toolconnect", "empty", "no audit records stored")
    prev = _TC_GENESIS
    checked = 0
    last_seq, last_hash = None, _TC_GENESIS
    for row in rows:
        if row["prev_hash"] != prev:
            return ChainStatus(
                "toolconnect", "broken",
                f"prev_hash mismatch at seq {row['seq']} after {checked} records",
            )
        expect = hashlib.sha256(
            f"{row['kind']}\x1f{row['body']}\x1f{row['created_at']}\x1f{prev}"
            .encode("utf-8")
        ).hexdigest()
        if row["record_hash"] != expect:
            return ChainStatus(
                "toolconnect", "broken",
                f"record_hash mismatch at seq {row['seq']} after {checked} records",
            )
        prev = row["record_hash"]
        last_seq, last_hash = row["seq"], row["record_hash"]
        checked += 1
    if _table_exists(conn, "meta"):
        head_seq = conn.execute(
            "SELECT value FROM meta WHERE key='audit_head_seq'").fetchone()
        head_hash = conn.execute(
            "SELECT value FROM meta WHERE key='audit_head_hash'").fetchone()
        if head_seq is not None:
            recorded_seq = int(head_seq[0])
            recorded_hash = head_hash[0] if head_hash is not None else None
            if last_seq != recorded_seq or (
                recorded_hash is not None and last_hash != recorded_hash
            ):
                return ChainStatus(
                    "toolconnect", "broken",
                    f"tail truncation: recorded head seq {recorded_seq} but the "
                    f"chain ends at seq {last_seq} after {checked} records",
                )
    return ChainStatus("toolconnect", "ok", f"{checked} audit records verified")


# ---------------------------------------------------------------------------
# The join
# ---------------------------------------------------------------------------


def resolve(
    identifier: str,
    *,
    governance_db_path: str = "",
    agentconnect_db_path: str = "",
    toolconnect_db_path: str = "",
) -> AuditTrail:
    """Resolve one identifier into the full linked trail across three stores.

    Join order (discovery §5): (1) AgentConnect ``execution_records`` by each
    indexed id column yields the full id set; (2) governance
    ``decision_records`` + ``execution_grant_records`` (+ ``work_requests``
    when present); (3) ToolConnect ``grant_redemptions`` +
    ``provider_enforcement`` audit rows by grant id; (4) chains verified on
    read; (5) the timeline assembled.
    """
    trail = AuditTrail(identifier=identifier)
    ids: dict[str, set[str]] = {
        "work_request_id": set(),
        "decision_record_id": set(),
        "grant_id": set(),
        "correlation_id": set(),
    }

    # (1) AgentConnect: any indexed column may be the identifier.
    if agentconnect_db_path:
        try:
            with open_readonly(agentconnect_db_path) as conn:
                executions = _fetch_execution_records(conn, identifier)
                for row in executions:
                    ids["work_request_id"].add(row["work_request_id"])
                    ids["decision_record_id"].add(row["decision_record_id"])
                    ids["grant_id"].add(row["grant_id"])
                    ids["correlation_id"].add(row["correlation_id"])
                trail.executions = executions
                trail.chain_statuses.append(_verify_agentconnect_chain(conn))
        except sqlite3.Error as exc:
            trail.degraded.append(f"agentconnect store unreadable: {exc}")
            trail.chain_statuses.append(
                ChainStatus("agentconnect", "unverified", f"store unreadable: {exc}")
            )
    else:
        trail.degraded.append(
            "agentconnect: no DB path configured (CONNECT_CONTROL_AGENTCONNECT_DB_PATH)"
        )
        trail.chain_statuses.append(
            ChainStatus("agentconnect", "not_configured",
                        "no AgentConnect DB path configured")
        )

    # The identifier itself may be any of the four ids; seed every slot.
    for key in ("work_request_id", "decision_record_id", "grant_id", "correlation_id"):
        ids[key].add(identifier)

    # (2) Governance: decisions + grants (+ work requests when present).
    if governance_db_path:
        try:
            with open_readonly(governance_db_path) as conn:
                decisions, grants, work_requests = _fetch_governance(conn, ids)
            trail.decisions = decisions
            trail.grants = _check_grant_artifacts(grants)
            trail.work_requests = work_requests
            for row in decisions:
                if row.get("work_request_id"):
                    ids["work_request_id"].add(row["work_request_id"])
                if row.get("correlation_id"):
                    ids["correlation_id"].add(row["correlation_id"])
            for row in grants:
                ids["decision_record_id"].add(row["decision_record_id"])
                if row.get("correlation_id"):
                    ids["correlation_id"].add(row["correlation_id"])
            for row in work_requests:
                ids["work_request_id"].add(row["id"])
            # Second pass picks up rows linked only through ids learned above
            # (e.g. sibling grants sharing a decision record).
            with open_readonly(governance_db_path) as conn:
                decisions2, grants2, work_requests2 = _fetch_governance(conn, ids)
            known = {r["id"] for r in trail.decisions}
            trail.decisions += [r for r in decisions2 if r["id"] not in known]
            known = {r["id"] for r in trail.grants}
            new_grants = [r for r in grants2 if r["id"] not in known]
            trail.grants = _check_grant_artifacts(trail.grants + new_grants)
            known = {r["id"] for r in trail.work_requests}
            trail.work_requests += [r for r in work_requests2 if r["id"] not in known]
            for row in trail.grants:
                ids["grant_id"].add(row["id"])
            for row in trail.decisions:
                ids["decision_record_id"].add(row["id"])
        except sqlite3.Error as exc:
            trail.degraded.append(f"governance store unreadable: {exc}")
    else:
        trail.degraded.append(
            "governance: no DB path configured (CONNECT_CONTROL_GOVERNANCE_DB_PATH)"
        )

    # (3) ToolConnect: redemption rows + provider-enforcement evidence.
    if toolconnect_db_path:
        try:
            with open_readonly(toolconnect_db_path) as conn:
                trail.redemptions, trail.enforcement = _fetch_toolconnect(conn, ids)
                trail.chain_statuses.append(_verify_toolconnect_chain(conn))
        except sqlite3.Error as exc:
            trail.degraded.append(f"toolconnect store unreadable: {exc}")
            trail.chain_statuses.append(
                ChainStatus("toolconnect", "unverified", f"store unreadable: {exc}")
            )
    else:
        trail.degraded.append(
            "toolconnect: no DB path configured (CONNECT_CONTROL_TOOLCONNECT_DB_PATH)"
        )
        trail.chain_statuses.append(
            ChainStatus("toolconnect", "not_configured",
                        "no ToolConnect DB path configured")
        )

    # AgentConnect rows may also be linkable through ids learned from the
    # governance side (e.g. the identifier was a grant id unknown to the
    # execution ledger's queried columns only after the join).
    if agentconnect_db_path and trail.executions == [] and any(
        ids[k] for k in ("work_request_id", "decision_record_id", "grant_id",
                         "correlation_id")
    ):
        try:
            with open_readonly(agentconnect_db_path) as conn:
                seen: set[str] = set()
                rows: list[dict[str, Any]] = []
                for col, key in (("work_request_id", "work_request_id"),
                                 ("decision_record_id", "decision_record_id"),
                                 ("grant_id", "grant_id"),
                                 ("correlation_id", "correlation_id")):
                    for value in sorted(ids[key]):
                        for row in _fetch_execution_records(conn, value):
                            if row["id"] not in seen:
                                seen.add(row["id"])
                                rows.append(row)
                trail.executions = sorted(rows, key=lambda r: r["_rowid"])
        except sqlite3.Error:
            pass  # already reported above

    trail.ids = {k: sorted(v) for k, v in ids.items() if not k.startswith("_")}
    # (5) The timeline.
    trail.timeline = _assemble_timeline(trail)
    return trail


def _assemble_timeline(trail: AuditTrail) -> list[dict[str, Any]]:
    """Order the trail's events: work request → decision → grant →
    redemption/enforcement → execution records. Entries link by id."""
    events: list[dict[str, Any]] = []

    def add(sort_key: str, order: int, kind: str, summary: str, links: dict[str, str]):
        events.append({
            "sort_key": sort_key, "order": order, "kind": kind,
            "summary": summary, "links": links,
        })

    for wr in trail.work_requests:
        add(wr.get("recorded_at", ""), 0, "work_request",
            f"Work Request {wr['id']} recorded", {"work_request_id": wr["id"]})
    for dec in trail.decisions:
        add(dec.get("recorded_at") or dec.get("evaluated_at") or "", 1, "decision",
            f"Decision {dec['id']}: {dec.get('outcome', '?')}",
            {"decision_record_id": dec["id"],
             **({"work_request_id": dec["work_request_id"]}
                if dec.get("work_request_id") else {})})
    for grant in trail.grants:
        add(grant.get("issued_at", ""), 2, "grant",
            f"Execution grant {grant['id']} issued to {grant.get('provider_id', '?')}",
            {"grant_id": grant["id"], "decision_record_id": grant["decision_record_id"]})
    for red in trail.redemptions:
        add(red.get("redeemed_at", ""), 3, "redemption",
            f"Grant {red['grant_id']} redeemed by {red.get('principal_id', '?')}",
            {"grant_id": red["grant_id"],
             "decision_record_id": red["decision_record_id"]})
    for enf in trail.enforcement:
        body = enf.get("body_json", {})
        add(body.get("verification_at") or enf.get("created_at", ""), 3,
            "provider_enforcement",
            f"Provider enforcement: {body.get('outcome', '?')} "
            f"(grant {body.get('grant_id') or 'unknown'})",
            {k: v for k, v in (("grant_id", body.get("grant_id")),
                               ("decision_record_id", body.get("decision_record_id")))
             if v})
    for ex in trail.executions:
        try:
            record = json.loads(ex["record_json"])
        except ValueError:
            record = {}
        add(record.get("finished_at") or str(ex.get("created_at", "")), 4,
            "execution_record",
            f"Execution {ex['id']}: {ex.get('outcome', '?')}",
            {"work_request_id": ex["work_request_id"],
             "decision_record_id": ex["decision_record_id"],
             "grant_id": ex["grant_id"]})

    events.sort(key=lambda e: (e["sort_key"], e["order"]))
    for event in events:
        del event["sort_key"]
        del event["order"]
    return events
