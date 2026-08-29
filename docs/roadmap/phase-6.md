## Phase 6 — Multi-Agent · Բազմա-գործակալ

**Objective.** Surface and govern Bro's pack model: the live agent network (`agents`), the command core
that dispatches governed work (`command`), and the mission/flow surfaces (`tasks`, `projects`) — so the
owner can watch and steer multiple specialized agents, each governed by its own lease.

**Scope.** In: the four pages, the dispatch path that asks the engine supervisor to run a **pack/task
force** of governed builders, and per-agent lease/receipt visibility. Out: real-time human+agent group
chat (Phase 7) and external triggers (Phase 9).

**Architecture.** The engine already models one-conductor + packs of governed builders; each builder gets
its own single-use lease. The desktop `command` core sends a governed dispatch (a task with a class that
fans out to a pack) and renders each agent's live lease/receipt state. **The desktop never holds a
lease**; it observes many governed builders. `agents` visualizes the lattice; `tasks`/`projects` track
missions and flows the packs execute.

**UI/UX work.** Full §D specs for four pages:
- **`agents` ⬡ Կենդանի Ցանց.** Components: agent lattice (`lattice`/`latStage`/`latLinks`), dossier
- **`command` ❖ Հրամանի Միջուկ.** Components: command dock/reactor (`cmdForm`/`cmdInput`/`reactor`),
- **`tasks` ◈ Առաքելություն.** Components: mission board (states: todo/in-progress/review/done/blocked),
- **`projects` ❖ Հոսքեր.** Components: flow view (pipelines of tasks), per-flow status, ownership. States

**Backend work.** Dispatch IPC → engine supervisor pack run; live subscription to per-builder
lease/receipt state; mission/flow stores mirrored from engine task contracts. **No desktop lease
holding.**

**Contracts / schemas.** Reuse `bridge.task-request` with a **pack/task-force class**; each builder's
result is a `bridge.result` with its own verified receipt. If fan-out needs a new task class field, that
is an engine-side change → audited task, flagged.

**Data models.** Desktop: `agent_view`(id, role, state, lease_id, receipt_id), `mission`(status, claim,
evidence), `flow`(steps, status). Engine holds authoritative leases/receipts/contracts.

**Dependencies.** Phase 4 (design system for lattice/board visuals) + Phase 5 (memory/knowledge the packs
consume). Parallel with Phase 8 (§E).

**Security gates.** Every agent runs under its own single-use lease issued **into** it; the desktop
observes, never holds. A dispatch denied by the wall renders `blocked` with the verdict reason. Per-agent
receipts are verified before their results are shown (verified-receipt-mandatory, per agent).

**Tests.** Dispatch → multi-builder round-trip (mock supervisor acceptable, documented); per-builder
receipt verification; lattice/board state rendering; `blocked` on denied dispatch; no desktop-held lease
(contract test).

**CI requirements.** Cockpit legs green; the dispatch path exercises the bridge leg; a test asserts the
desktop never serializes a lease/key.

**Documentation updates.** `docs/ARCHITECTURE.md` (pack dispatch + per-agent governance), this phase's
specs, `PROJECT_STATE.md`.

**Acceptance criteria.** Owner dispatches a governed pack run from `command`, watches agents live in
`agents`, tracks missions/flows in `tasks`/`projects`, and sees each agent's **verified** receipt. All
four pages meet §D incl. `blocked`. No desktop-held lease.

**Merge gate.** Per-agent verified-receipt proven; no lease leakage to desktop; Architect confirms pack
governance; Owner approval.

**Stop conditions.** If fan-out tempts the desktop to hold/relay a lease → stop (that breaks the whole
model). If pack dispatch needs an engine change → audited task.

> **⚖ Phase 6 was CHECKED AGAINST THE CODE before anything was built (2026-08-16).** All four
> pages and the dispatch service existed. The gap was the phase's **own stop condition**, left
> unasserted: *"If fan-out tempts the desktop to hold/relay a lease → stop (that breaks the whole
> model)."* The Definition of Done asks for the contract test in as many words, and the CI
> requirement names its shape — *"a test asserts the desktop never serializes a lease/key"*.
>
> One existed, in `governance.rs`, over the governance READ commands' signatures. **None existed
> for dispatch** — which is the surface the stop condition is actually about: dispatch is where a
> lease exists, where fan-out happens, and where relaying one would look like a convenience
> rather than a breach.
>
> The distinction the test pins: an accepted reply **names** a `lease_id`, and the parser refuses
> an accepted frame without one, because *an assignment with no lease was not governed*. Naming a
> lease and holding one are different acts, and **the direction of travel is the whole model**.

**Definition of Done.**
- [x] `agents`, `command`, `tasks`, `projects` pages to full §D incl. `blocked`. — `Agents.tsx` 705 · `Command.tsx` 491 · `Tasks.tsx` 810 · `Projects.tsx` 541, each with the real state set and a `blocked` path. `command`'s `blocked` was rebuilt earlier this session so a governed **refusal** no longer renders identically to a dropped connection; `tasks`' lanes became real lists in the same sweep.
- [x] Governed pack dispatch; per-builder verified receipts rendered. — `services/agentsDispatch.ts` builds a `brops.agent-dispatch.v1` frame, validates the draft **before** sending (the renderer does not ask for what it already knows is wrong; the engine validates again), and parses the reply **fail-closed**: an accepted frame with no `contract_digest`, no `lease_id` or no sealed repository binding degrades to `unreachable` rather than being upgraded into success.
- [x] The dispatch FRAME is fixed, and no lease-shaped word travels in it (contract test green). — **six cases**, and the mutation that matters: rewriting the builder to spread the assignment instead of naming its fields turns two of them red. The frame is checked against a **whitelist** of its six declared fields, not a blacklist of forbidden names — a blacklist protects against the names someone thought of, a whitelist fails the moment any new field appears. A lease smuggled onto the assignment does not reach the wire; a reply's `lease_id` is read and never echoed into a later request; the refusal path is checked too, because a failure path is exactly where a loophole would hide; and a positive control keeps the sweep from passing over an empty object. &nbsp; **This row used to read "Desktop never holds a lease/key", and the tests do not establish that** — sixth independent audit, `A-09`. Measured with the shipped helpers verbatim: an opaque JWT placed in `rollbackStrategy` reaches `contract_draft.rollback.strategy` with the FORBIDDEN sweep at zero offenders and the whitelist still exact, because `buildAssignment` copies that field verbatim and the value contains no English keyword; `(?<![a-z])key(?![a-z])` matches none of `pubkey`/`apikey`/`keystore`/`sessionkey`; and `flatten()` drops every non-string leaf, so a `number[]` decoding to `"lease-7f2a91"` is invisible. **Two of those three routes are now CLOSED (2026-08-18), and the third is declared rather than swept.** The `key` clause takes an optional prefix and suffix, so `pubkey`/`apikey`/`keystore`/`sessionkey`/`keychain`/`keyring`/`keypair`/`key_id` all match while `monkey`/`keyboard`/`keyword` still do not; and `flatten` now visits non-string leaves and decodes an all-printable-ASCII `number[]`, so `[108,101,97,115,101,…]` is swept as the text `"lease-7f2a91"` it becomes. Each has its **mutant in the same file** — the superseded pattern and the string-only sweep are kept executable, so a later tidy-up that restores either turns the suite red. &nbsp; **Route 1 stays open and is now bounded instead of denied.** A credential cannot be told from a sentence by any check in this process — that decision is taken and written in `agentsDispatch.boundary.test.ts`, and a grammar for the free-text fields fails from the other side (tight enough to exclude a JWT also excludes a commit sha, a path and an Armenian sentence). What the file now proves instead is **enumeration**: every leaf of the frame is either shape-constrained against the module's own validator — `isContractId`, `isWorkPath`, `isRepoPath`, `MODES`, `RISKS`, `CAPABILITY_TIERS`, the UUIDv4 and the protocol const — or listed in a **declared free-text register of exactly eight leaves**, each with the reason it must stay prose. A ninth turns the suite red on the commit that adds it. `T-030`'s open question is answered: the stronger property is not "no credential" but "the places one could ride are counted".
- [x] Missions/flows mirror engine task contracts. — `Tasks.tsx` carries the contract surface and its dispatch test; `agentsDispatch` mirrors `engine/schemas/task-contract.schema.json`'s path grammar with a drift-guard corpus, so the renderer cannot bless a scope the engine will not honour.
- [x] Docs + `PROJECT_STATE.md` synced.

**Task checklist.**
- [x] `agents` lattice page (+ list fallback) per §D. — `role=list` fallback beside the lattice; the ring geometry is the extracted, tested `charts/geometry.ts` and the stateful lattice stays bespoke by documented decision (`DESIGN_SYSTEM.md` §3.1).
- [x] `command` core dispatch page (governed) per §D. — including the `role=log` trace and the refusal-vs-failure distinction added this session.
- [x] `tasks` mission board per §D; `projects` flow view per §D. — board lanes are `role=list` with named lanes and a spoken empty state; `projects` carries its step-list fallback.
- [x] Dispatch IPC → engine pack run; per-builder receipt verification. — the dispatch channel is probed rather than assumed (`probeDispatchChannel`), and `present` deliberately says nothing about acceptance.
- [x] Contract test: no desktop-held lease/key; `blocked` on denied dispatch. — see DoD row 3; the refusal reasons are a **closed set**, and a reason outside it degrades to `unreachable` instead of being shown as a refusal the engine did not give.

---
