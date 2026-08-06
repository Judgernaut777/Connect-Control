"""Configuration for Connect Control.

Connect Control coordinates the four Connect infrastructure planes over their
HTTP APIs. Defaults match the ecosystem port registry in Connect's
COMPATIBILITY.md; every URL can be overridden by environment variable.

R7 adds three *optional* SQLite paths for the read-only audit projection
(Option B, docs/ARCHITECTURE.md): the linked audit trail joins the governance,
AgentConnect, and ToolConnect stores by id. An empty path is an honest
configuration statement — the corresponding surface degrades and says so,
rather than fabricating an empty trail.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# Default endpoints, per the port registry in Judgernaut777/Connect COMPATIBILITY.md.
# 127.0.0.1:8790 is the shipped agentconnect-api default.
DEFAULT_PLANE_URLS: dict[str, str] = {
    "agentconnect": "http://127.0.0.1:8790",
    "brainconnect": "http://127.0.0.1:8787",
    "computeconnect": "http://127.0.0.1:8090",
    "toolconnect": "http://127.0.0.1:8095",
}


@dataclass(frozen=True)
class Settings:
    """Runtime settings. Frozen: the control plane holds no mutable authority."""

    plane_urls: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PLANE_URLS))
    plane_tokens: dict[str, str | None] = field(
        default_factory=lambda: {name: None for name in DEFAULT_PLANE_URLS}
    )
    http_timeout: float = 5.0
    # Read-only audit projection (Option B, temporary documented exception to
    # the "never direct database access" rule — see docs/ARCHITECTURE.md).
    # Empty string = not configured: the surface degrades honestly.
    governance_db_path: str = ""
    agentconnect_db_path: str = ""
    toolconnect_db_path: str = ""

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "Settings":
        """Build settings from CONNECT_CONTROL_* environment variables.

        CONNECT_CONTROL_AGENTCONNECT_URL, CONNECT_CONTROL_BRAINCONNECT_URL,
        CONNECT_CONTROL_COMPUTECONNECT_URL, CONNECT_CONTROL_TOOLCONNECT_URL
        override the default plane URLs; CONNECT_CONTROL_<PLANE>_TOKEN sets an
        optional bearer token per plane (BrainConnect supports one).

        CONNECT_CONTROL_GOVERNANCE_DB_PATH, CONNECT_CONTROL_AGENTCONNECT_DB_PATH,
        CONNECT_CONTROL_TOOLCONNECT_DB_PATH point the read-only audit
        projection at the three planes' SQLite stores (R7, Option B).
        """
        env = os.environ if environ is None else environ
        urls: dict[str, str] = {}
        tokens: dict[str, str | None] = {}
        for name, default in DEFAULT_PLANE_URLS.items():
            key = name.upper()
            urls[name] = env.get(f"CONNECT_CONTROL_{key}_URL", default)
            tokens[name] = env.get(f"CONNECT_CONTROL_{key}_TOKEN") or None
        timeout = float(env.get("CONNECT_CONTROL_HTTP_TIMEOUT", "5.0"))
        return cls(
            plane_urls=urls,
            plane_tokens=tokens,
            http_timeout=timeout,
            governance_db_path=env.get("CONNECT_CONTROL_GOVERNANCE_DB_PATH", ""),
            agentconnect_db_path=env.get("CONNECT_CONTROL_AGENTCONNECT_DB_PATH", ""),
            toolconnect_db_path=env.get("CONNECT_CONTROL_TOOLCONNECT_DB_PATH", ""),
        )
