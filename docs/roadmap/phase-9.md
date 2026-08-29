## Phase 9 — Integrations · Ինտեգրումներ

**Objective.** Connect OS to the outside world **through the wall**: `integrations` manages external
connectors (data sources, notification sinks, event triggers) so external input can start governed work
and governed output can reach external sinks — never ungoverned, never holding external secrets in the
desktop.

**Scope.** In: the `integrations` page, a connector registry, inbound triggers (external event →
**governed** task), outbound sinks (governed result → external channel), and secret handling delegated to
the engine/operator. Out: production packaging/rollout (Phase 10).

**Architecture.** Connectors are declared and enabled in the desktop, but **secrets and the actual
external call boundary live with the engine/operator sidecar**, not the desktop. An inbound event is
normalized into a `bridge.task-request` (governed); an outbound sink only sends a result that carries a
verified receipt. The desktop orchestrates and displays; it never stores an external credential.

**UI/UX work.** Full §D spec for `integrations`:
- **`integrations` ✦ Ինտեգրումներ.** Components: connector catalog (available/connected), per-connector

**Backend work.** Connector registry + config; inbound event → normalized governed task; outbound sink
(sends only verified results); **secret handling delegated** to engine/operator (desktop stores none);
health checks.

**Contracts / schemas.** Inbound events normalize to `bridge.task-request`; outbound uses a small
**sink-payload** shape carrying `{result, receipt_id, verified}` (never raw secrets). A **connector**
descriptor (type, config schema, auth-location=operator). If a connector needs an engine-side secret
holder, that is an operator/engine provisioning step, not desktop code.

**Data models.** Desktop: `connector`(type, config, enabled, health, auth_ref), `inbound_trigger`(map to
task class), `outbound_sink`(channel, filter). **No credential columns** on the desktop — only references
to operator/engine-held secrets.

**Dependencies.** Phase 7 (group/collaboration as an output surface) + Phase 8 (automation as a trigger
source). Both feed integrations (§E).

**Security gates.** The desktop stores **no external secrets** (auth handoff to engine/operator). Inbound
events cannot start ungoverned work; outbound sinks send only verified results. A connector that would
require the desktop to hold a secret or run ungoverned is refused (`blocked`). Verified-receipt-mandatory
on every inbound-triggered run.

**Tests.** Inbound event → governed task (receipt required); outbound sends only verified results; a
connector cannot be enabled if it would store a desktop secret (contract test); health/`blocked` states.

**CI requirements.** Cockpit legs green; integration paths exercise the bridge leg; a test asserts no
credential is persisted on the desktop.

**Documentation updates.** `docs/ARCHITECTURE.md` (integration boundary + secret delegation), a
`docs/SECURITY_MODEL.md` note on external-secret handling, this phase's spec, `PROJECT_STATE.md`.

**Acceptance criteria.** Owner connects an external source that triggers **governed** work and a sink that
receives **verified** output, with **no desktop-held secret**. `integrations` meets full §D incl.
`blocked`. Refuses connectors that would break governance.

**Merge gate.** No-desktop-secret proven; inbound-governed + outbound-verified proven; Architect security
review; Owner approval.

**Stop conditions.** If a connector needs a secret in the desktop, or would run ungoverned → stop, refuse
it. If the external boundary needs engine changes → audited task.

> **⚖ Phase 9 was CHECKED AGAINST THE CODE before anything was built (2026-08-16),** and it is
> the most thoroughly honest page in the cockpit before anyone touched it. `integrationsModel.ts`
> keeps **enabled** and **verified** as separate numbers and lets neither borrow the other's
> meaning: a locally enabled connector reads *“Enabled · unverified”*, a probe that could not run
> never upgrades anything, and only a real affirmative answer earns the word *connected*. Twelve
> model tests and twelve honesty tests already pinned that.
>
> Its inbound/outbound half **does not exist**, and the page says so where the feature would be:
> a `blocked` panel naming the missing command and how to provision it, rather than a control that
> would appear to work. So **box 2 stays unticked** — the same shape as Phase 8's, and for the same
> reason: the capability is engine work behind the shut gate.
>
> What was added: the **other half of the no-secret guarantee**. The honesty suite proved the page
> *offers no credential field* — the input side. Nothing proved that nothing it **sends** carries
> one. A UI with no credential box can still serialise a token it read from somewhere else, and
> *“we never built a text box for it”* is not the same claim as *“no secret crosses this
> boundary.”*

**Definition of Done.**
- [x] `integrations` page to full §D incl. `blocked`. — 759 lines, `role=list` catalog, per-connector detail, health probe run **only when the owner asks** (never on mount), and the honest `blocked` panel where inbound/outbound would be.
- [ ] Inbound events start **governed** tasks; outbound sends only **verified** results. — **no backing command exists**, and the page renders that as `blocked` with provisioning steps instead of a control that pretends. Unticked deliberately; engine work behind the same gate as `T-021`/`T-022`.
- [x] The page offers no field to type a secret into, and no command argument is secret-SHAPED (auth handoff to engine/operator). — **both halves**: no field to type one into (honesty suite), and a **contract test that no command the page issues carries a secret-shaped NAME, at any depth** — with a per-command **whitelist** of allowed arguments, so a new field fails the test rather than only a forbidden name doing so. Same shape as `agentsDispatch.nolease.test.ts`. &nbsp; **This row used to read "No external secret stored on the desktop", and it inherits the same over-reach** — sixth independent audit, `A-09`, whose three measured routes apply verbatim here because this test shares that file's helpers. A credential whose text contains no English keyword travels with the whitelist exact and the sweep silent. The row claims the property the test has: the shape is constrained and no word travels. &nbsp; **Two of the three routes closed 2026-08-18** — this suite's `flatten` now visits non-string leaves and decodes character-code arrays, and its `SECRET_SHAPED` pattern took the same compound `key` family (`api[-_ ]?key` caught one form and missed `pubkey`/`keystore`/`sessionkey`/`keychain`). The remaining route is free prose, and Phase 6's row 3 carries the decision and the declared-register property that replaces it. See `T-030`.
- [x] Refuses governance-breaking connectors. — the capability wall is reported **as a missing feature here, not as a dead service**: a command that was never granted and a connector that did not answer are different findings, and the page keeps them apart.
- [x] Docs (incl. security note) + `PROJECT_STATE.md` synced.

**Task checklist.**
- [x] Connector registry + config + health; `integrations` page per §D.
- [ ] Inbound trigger → normalized governed task; outbound verified-only sink. — see DoD row 2.
- [x] Secret-delegation to engine/operator; contract test: no desktop secret. — four cases including a positive control, so the sweep cannot pass over a page that made no calls at all.
- [x] Tests: inbound-governed, outbound-verified, refuse-secret/ungoverned. — refuse-secret and the refusal vocabulary are covered; inbound-governed and outbound-verified are **untestable until the commands exist**, and a test asserting that a nonexistent sink sends only verified results is a check that cannot fail — the shape this repository deletes rather than ships.

---
