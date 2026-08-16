# Connect-Control roadmap

> **Status: plan.** C0 is done (this scaffold). Nothing past C0 is built, and
> each milestone below says what "done" means so the docs cannot drift ahead
> of the code.

Ordering rule, inherited from the thin-control-plane principle: **read-only
before mutation, always.** Every milestone lands visibility first; the first
mutation in this application happens only through an owning plane's public
API, never through direct database or filesystem access to another plane's
state.

## C0 — scaffold ✅ done (2026-08-04)

- [x] Repository created per ADR 0002 (Accepted 2026-08-04, Option A).
- [x] Apache-2.0 LICENSE and NOTICE.
- [x] FastAPI backend skeleton: app factory, `/healthz`, configuration module,
      read-only plane-client stubs, honest 501s for mutation routes.
- [x] Smoke tests (11 passing) covering the scaffold's honesty properties.

## R7 — the four UI surfaces + linked audit trail ✅ done (2026-08)

The ecosystem's R7 milestone landed here ahead of the C1–C4 ordering (the
roadmap language places S1/S4 around C1 and S3 around C4; the milestone
pulled them together):

- [x] **S1 Work Request creation and status** (`/work-requests`) — the app's
      first mutation, and still its only one: kernel-evaluated, fail-closed,
      through Connect-Governance's intake in-process (the documented Option-B
      exception, see ARCHITECTURE.md). Not the plane-proxy path — that stays
      501 for everything.
- [x] **S2 Decision and explanation** (`/decisions/{record_id}`) — read-only
      rehydration + pure on-read explanation.
- [x] **S3 Marketplace and provider activation, minimal** (`/marketplace`) —
      ToolConnect catalog/health reads + grant-derived activation status +
      ADR-052 revocation-list meta. Full marketplace stays R8 (= C4).
- [x] **S4 Linked audit trail** (`/audit/{identifier}`) — single-identifier
      join across the governance/AgentConnect/ToolConnect stores (read-only
      audit projection, Option B), chains verified on read, rendered as a
      timeline; degraded surfaces labeled, never faked.
- [x] Tests: 11 scaffold smoke tests + seeded end-to-end R7 tests (join,
      tamper detection, honest degradation, S1 happy/denial, S2 render, S4
      ordering).
- Expiry owed: replace the audit projection's direct reads with per-plane
      record-read HTTP APIs (**R8/R9**, Option A), then delete the exception.

## R8 — curated marketplace surface ✅ done (2026-08)

The ecosystem's R8 milestone (RA v0.2 §9, ADR-039/040/041/055) extended S3
from the R7 minimal view to the curated marketplace:

- [x] **Curated listings, operator-authored** — `POST /marketplace/listings`
      through `connect_governance.providers.create_listing`
      (kernel-evaluated, `provider.list` authority, fail-closed). There is no
      self-publishing flow (ADR-040). An `enforcing` listing without
      classification evidence is refused before kernel evaluation (ADR-041).
- [x] **Governed provider activation** — `POST /marketplace/activate`
      through `connect_governance.providers.activate_provider`
      (`provider.activate` authority); operator-triggered from the UI. A
      refusal rolls everything back and answers 422 with the Kernel's reason.
- [x] **Enforcement classification badge, fail-closed** — `enforcing` is
      displayed only with every evidence leg observable (stored evidence,
      active activation + decision record, live ToolConnect `/health`
      trust-root and audit-chain posture, observable `provider_enforcement`
      records); any gap degrades to `unverified` with the missing evidence
      named. Monitor-only is never presented as preventative (ADR-039).
- [x] Listing-driven reads replace the R7 hard-coded `provider_id` query
      (listings/activations via `connect_governance.queries`; grants per
      listed provider via the read-only projection — the Option-B exception
      extended, same expiry condition, see ARCHITECTURE.md).
- Deferred per ADR-040: third-party publishing, pricing/entitlements
      (OD-010 open), certification programs (OD-011 open), reviews/rankings.
      The disable/revoke lifecycle is deferred; Connect-Governance reserves
      the `provider.deactivate` authority key.

## C1 — read-only workspace & planes status dashboard *(not built)*

- Live plane health and version display, built on the C0 probes.
- Read-only workspace list projected from AgentConnect's public API
  (AgentConnect owns workspace lifecycle; this app does not duplicate it).
- Read-only event-bus projection for a cross-plane activity view.
- Done means: a running app shows real data from real planes, and degrades
  honestly (labeled unreachable) when a plane is down.

## C2 — guided onboarding flow *(not built)*

- Implements the human-guided setup direction from Connect's
  `docs/SETUP_HUMAN_GUIDED.md` and the agent-led flow from
  `docs/SETUP_AGENT_LED.md` (zero-trust: agent proposes, human approves,
  temporary grants, revoke).
- Detection of installed planes and versions against the ecosystem manifest.
- Done means: a fresh machine reaches a working, verified plane stack through
  the UI; every privileged step is human-approved and its grant revoked after.

## C3 — budget visibility *(not built)*

- Read-only budget views consuming the Work plane's budget model
  (AgentConnect `docs/BUDGET_MODEL.md`).
- Cross-resource cost visibility (owned, rented, external, marketplace) as the
  planes expose it.
- Done means: real spend/budget data rendered from plane APIs. Budget
  *enforcement* stays in the Work plane; this app displays, it does not
  enforce. Mutation (setting budgets) is a separate, later, API-mediated step.

## C4 — marketplace discovery *(partially built — the curated slice landed in R8)*

- [x] Curated marketplace (R8): operator-authored listings, governed
      activation, fail-closed enforcement classification badge — see the R8
      entry above. Real listings are browsable; curation is by the operator,
      and there is no self-publishing flow (ADR-040).
- [ ] Neutral discovery and comparison per Connect's MARKETPLACE_ARCHITECTURE.md,
  shipped as a **module of this application** (ADR 0002 placement note), not a
  separate service.
- [ ] Neutral sorting, transparent verification labels, no pay-to-rank, ever.
- Done means: browsing real listings — met for the curated slice; the neutral
  discovery/comparison surface is still open. Transactions — the only revenue
  event — come after discovery, with the transparency commitments in
  TRANSPARENCY.md enforced in code, not just prose.
