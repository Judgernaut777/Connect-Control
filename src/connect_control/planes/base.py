"""Read-only plane HTTP client.

Design rule (thin control plane): the Control plane *coordinates*; it never
runs workloads, holds trust, decides authorization, or places compute. These
clients therefore only read. Anything that would change a plane's state is
explicitly refused here and surfaced as HTTP 501 by the API layer until it is
implemented through the owning plane's public API — never through direct
database or filesystem access.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class PlaneHealth:
    """What one health probe actually observed. No success is fabricated."""

    plane: str
    url: str
    reachable: bool
    status_code: int | None = None
    body: Any | None = None
    error: str | None = None


class MutationNotImplemented(NotImplementedError):
    """Raised when a caller asks the control plane to change plane state.

    The control plane is deliberately thin: mutation happens only through the
    owning plane's public API, and none of those mutation paths are built yet.
    """


class PlaneClient:
    """A read-only HTTP client for one Connect plane.

    ``health_path`` is the plane's best-known health route per Connect's
    COMPATIBILITY.md. The probe reports exactly what the plane answers —
    including 404 — and never infers health from anything else.
    """

    name: str = "plane"
    health_path: str = "/health"

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        timeout: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {token}"} if token else None
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers=headers,
            transport=transport,
        )

    def health(self) -> PlaneHealth:
        """GET the plane's health route and report what came back, verbatim."""
        try:
            response = self._client.get(self.health_path)
        except httpx.HTTPError as exc:
            return PlaneHealth(
                plane=self.name,
                url=f"{self.base_url}{self.health_path}",
                reachable=False,
                error=f"{type(exc).__name__}: {exc}",
            )
        body: Any
        try:
            body = response.json()
        except ValueError:
            body = response.text[:500]
        return PlaneHealth(
            plane=self.name,
            url=f"{self.base_url}{self.health_path}",
            reachable=True,
            status_code=response.status_code,
            body=body,
        )

    def mutate(self, *_args: Any, **_kwargs: Any) -> None:
        """No mutation path exists yet. This always raises."""
        raise MutationNotImplemented(
            f"{self.name}: mutation is not implemented. The control plane may "
            "only mutate through the owning plane's public API, and no such "
            "path is built yet. Direct database or filesystem mutation is "
            "refused by design."
        )

    def close(self) -> None:
        self._client.close()
