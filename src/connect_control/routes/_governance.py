"""In-process access to the governance plane (the documented exception).

The R7 Option-B decision (docs/ARCHITECTURE.md) lets Connect Control open
the governance SQLite store in-process: read-only through the audit
projection (:mod:`connect_control.audit`), and — for the single mutation
surface, Work Request creation — through the governance package's own
application function ``connect_governance.work_requests.create_work_request``.
Raw SQL writes are never performed here; the mutation goes through the same
kernel-evaluated intake path any governance caller uses.

Every helper degrades honestly: an unconfigured path or a missing
``connect_governance`` package is reported, never worked around.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GovernanceHandle:
    """A live session factory, or the honest reason there isn't one."""

    session_factory: Any | None
    unavailable_reason: str | None = None

    @property
    def available(self) -> bool:
        return self.session_factory is not None


def open_governance(governance_db_path: str) -> GovernanceHandle:
    """Build a SQLAlchemy session factory against the governance DB.

    Returns an unavailable handle (with the reason) when the path is not
    configured, the file does not exist, or ``connect_governance`` is not
    installed (the optional ``audit`` extra).
    """
    if not governance_db_path:
        return GovernanceHandle(
            None,
            "no governance DB path configured "
            "(CONNECT_CONTROL_GOVERNANCE_DB_PATH)",
        )
    try:
        from sqlalchemy import text

        from connect_governance.db.session import make_engine, session_factory
    except ImportError:
        return GovernanceHandle(
            None,
            "the connect-governance package is not installed "
            "(install connect-control with the 'audit' extra)",
        )
    try:
        engine = make_engine(f"sqlite+pysqlite:///{governance_db_path}")
        factory = session_factory(engine)
        with factory() as session:
            session.execute(text("SELECT 1"))
    except Exception as exc:
        return GovernanceHandle(
            None, f"governance DB at {governance_db_path!r} is unreadable: {exc}"
        )
    return GovernanceHandle(factory)
