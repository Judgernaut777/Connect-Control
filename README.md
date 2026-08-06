# Connect-Control

The user-facing **control-plane application** of the
[Connect ecosystem](https://github.com/Judgernaut777/Connect): visual workspaces,
guided onboarding, budget visibility, and marketplace discovery — the thin
**Control plane** made usable.

> **Status: R7 — the four UI surfaces and the linked audit trail landed.**
> What exists today: the C0 scaffold (`/healthz`, configuration echo,
> read-only plane health probes, honest 501s on the plane-proxy path) **plus**
> server-rendered surfaces for Work Request creation/status, Decision +
> explanation, minimal marketplace/provider activation, and the linked audit
> trail with chain verification on read. Workspaces, onboarding, and budgets
> **do not exist**. See [docs/ROADMAP.md](docs/ROADMAP.md) and the Option-B
> exception in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

This repository exists by decision of
[ADR 0002](https://github.com/Judgernaut777/Connect/blob/main/docs/adr/0002-control-plane-repository-boundary.md)
(Accepted 2026-08-04, Option A): the Connect umbrella repository stays
docs-only, and the control-plane application lives here.

## The thin-control-plane principle

Connect-Control is the fifth plane of the ecosystem and deliberately the
thinnest. It **coordinates** the four infrastructure planes; it is never a
fifth authority competing with them. Concretely:

- It **runs no workloads** — the Work plane (AgentConnect) executes.
- It **holds no trust** — the Knowledge plane (BrainConnect) decides what is trusted.
- It **decides no authorization** — the Capability plane (ToolConnect) decides.
- It **places no compute** — the Compute plane (ComputeConnect) places.

Every read in this application comes from the owning plane's public API over
the ecosystem's versioned contracts, and — when mutation is eventually built —
every write will go through the owning plane's public API too. **Never direct
database or filesystem access to another plane's state** — with exactly one
documented, temporary exception: the R7 read-only audit projection and the
governance in-process intake, recorded with its expiry condition in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#the-r7-option-b-exception).

## What Connect-Control will not do

Inherited from the ecosystem's
[PRODUCT_THESIS.md](https://github.com/Judgernaut777/Connect/blob/main/PRODUCT_THESIS.md)
and MANIFESTO, these are refusals, not roadmap gaps:

- It is **not another coding harness** and does not compete with Claude Code,
  Codex, Hermes, OpenHands, or any other executor — harnesses stay native and
  interchangeable.
- It is **not** a hosting provider, GPU cloud, inference host, managed-memory
  host, hosted-workspace operator, data custodian, consulting organization, or
  subscription vendor.
- No Connect subscriptions, no per-seat licensing, no feature-gated
  "enterprise edition," no charging for customer-owned resources. The free
  path is never degraded.
- Customer content (prompts, outputs, code, memory, secrets, tool payloads,
  workspace files) stays on customer-controlled infrastructure; the control
  plane is architected to handle as little of it as technically possible.

## What is here today

```text
src/connect_control/
    app.py          FastAPI app factory: /healthz, /planes, read-only plane
                    health probes, 501 for all plane-proxy mutation routes
    config.py       plane endpoint + audit-projection DB path configuration
    cli.py          `connect-control` console entry (uvicorn, 127.0.0.1:8800)
    planes/         read-only HTTP clients, one per infrastructure plane
    audit/          R7 read-only audit projection: single-identifier join
                    across the governance/AgentConnect/ToolConnect SQLite
                    stores (mode=ro) + chain verification on read
    routes/         the four R7 surfaces:
                    work_requests.py  S1 creation (the one mutation, through
                                      Connect-Governance's kernel-evaluated
                                      intake) + status
                    decisions.py      S2 decision + explanation (read-only)
                    marketplace.py    S3 minimal catalog/provider activation
                    audit.py          S4 linked audit trail timeline
    ui/templates/   Jinja2 server-rendered pages for S1–S4
docs/
    ARCHITECTURE.md the intended shape + the R7 Option-B exception record
    ROADMAP.md      milestones C0–C4 + the R7 entry
tests/              scaffold honesty tests + end-to-end seeded R7 tests
```

Plane endpoints default to the ecosystem port registry
([COMPATIBILITY.md](https://github.com/Judgernaut777/Connect/blob/main/COMPATIBILITY.md)):
AgentConnect `127.0.0.1:8790`, BrainConnect `127.0.0.1:8787`,
ComputeConnect `:8090`, ToolConnect `127.0.0.1:8095`.

## R7 dependencies (read before installing)

The app runs with **no sibling packages installed**: every R7 surface degrades
honestly and says why (503s on S1/S2, labeled degraded panels on S3/S4). That
is a feature, not a fallback — it is the same honesty idiom as the scaffold's
501s.

Full functionality needs the sibling planes' R7 work, installable as the
optional `audit` extra (plain package names, deliberately **not** pinned to
branch URLs):

```bash
pip install -e ".[dev,audit]"
```

Until the sibling R7 PRs merge and release, install them from their branches
for local testing:

```bash
pip install "connect-governance[app] @ git+https://github.com/Judgernaut777/Connect-Governance.git@r7-audit-trail"
pip install "agentconnect-core @ git+https://github.com/Judgernaut777/AgentConnect.git@r7-audit-trail#subdirectory=packages/agentconnect-core"
pip install "toolconnect @ git+https://github.com/Judgernaut777/ToolConnect.git@r7-revocation-propagation"
```

Merge order: Connect-Governance `r7-audit-trail` (work-request intake, query
layer, ADR-052 issuance) and AgentConnect `r7-audit-trail` (read-side chain
verification) first; ToolConnect `r7-revocation-propagation` next; this repo's
`r7-four-surfaces` last — it consumes all three but degrades without any.

The audit projection is pointed at the three stores with:

```bash
export CONNECT_CONTROL_GOVERNANCE_DB_PATH=/path/to/governance.db
export CONNECT_CONTROL_AGENTCONNECT_DB_PATH=/path/to/agentconnect.db
export CONNECT_CONTROL_TOOLCONNECT_DB_PATH=/path/to/toolconnect.db
```

## Development

```bash
pip install -e ".[dev]"   # Python 3.11+; add ,audit for the R7 surfaces
pytest
connect-control           # serves on http://127.0.0.1:8800
```

## License

Apache-2.0 — the entire Connect ecosystem is Apache-2.0. See [LICENSE](LICENSE)
and [NOTICE](NOTICE).
