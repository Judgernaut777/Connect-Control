# Connect-Control

The user-facing **control-plane application** of the
[Connect ecosystem](https://github.com/Judgernaut777/Connect): visual workspaces,
guided onboarding, budget visibility, and marketplace discovery — the thin
**Control plane** made usable.

> **Status: scaffold — no runtime product yet.** What exists today is a FastAPI
> skeleton (`/healthz`, configuration echo, read-only plane health probes, and
> honest 501s for everything that would mutate). Workspaces, onboarding,
> budgets, and marketplace discovery **do not exist**. Nothing in this
> repository should be read as a claim that they do. See
> [docs/ROADMAP.md](docs/ROADMAP.md).

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
database or filesystem access to another plane's state.**

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
                    health probes, 501 for all mutation routes
    config.py       plane endpoint configuration (env-overridable defaults)
    cli.py          `connect-control` console entry (uvicorn, 127.0.0.1:8800)
    planes/         read-only HTTP client stubs, one per infrastructure plane
docs/
    ARCHITECTURE.md the intended shape of the application
    ROADMAP.md      milestones C0–C4, read-only before any mutation
tests/              smoke tests for the scaffold's honesty properties
```

Plane endpoints default to the ecosystem port registry
([COMPATIBILITY.md](https://github.com/Judgernaut777/Connect/blob/main/COMPATIBILITY.md)):
AgentConnect `127.0.0.1:8790`, BrainConnect `127.0.0.1:8787`,
ComputeConnect `:8090`, ToolConnect `127.0.0.1:8095`.

## Development

```bash
pip install -e ".[dev]"   # Python 3.11+
pytest
connect-control           # serves the scaffold on http://127.0.0.1:8800
```

## License

Apache-2.0 — the entire Connect ecosystem is Apache-2.0. See [LICENSE](LICENSE)
and [NOTICE](NOTICE).
