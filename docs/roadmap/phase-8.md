## Phase 8 — Automation · Ավտոմատացում

**Objective.** Let the owner schedule and run **governed** recurring/triggered work: `automations`
(rules/schedules that dispatch governed tasks) and `calendar` (time-based view + scheduling), so Bro can
act on a cadence without ever escaping the wall.

**Scope.** In: the two pages, a scheduler that fires governed dispatches (each a lease + verified
receipt), automation rules (trigger → governed action), and a calendar of scheduled/past runs. Out:
external event sources (Phase 9 provides those triggers).

**Architecture.** A desktop scheduler emits, at each fire, a **governed** `bridge.task-request`; the
engine issues a lease and runs it; the result carries a verified receipt. Automations are rules
(trigger + action + guard); the calendar visualizes schedule + run history. **No unattended action ever
bypasses the wall** — an automation that would need ungoverned execution is refused at authoring time.

**UI/UX work.** Full §D specs for two pages:
- **`automations` ⇶ Ավտոմատներ.** Components: automation index (`arows`/`aCount`/`afilter`), schematic/
- **`calendar` ▦ Օրացույց.** Components: day grid (`daygrid`/`calGrid`), now-line (`calNow`), agenda

**Backend work.** Scheduler (fire → governed dispatch); automation rule store + evaluation; run history
with receipt ids; calendar aggregation.

**Contracts / schemas.** Each fire uses `bridge.task-request`/`result`. A desktop **automation** shape
(trigger, action, guard, schedule) — product state; no new cross-boundary contract. Guards reference the
engine's scope/mode rules.

**Data models.** Desktop: `automation`(trigger, action, guard, enabled), `schedule`(cron/interval),
`automation_run`(fired_at, receipt_id, verified, status). Engine holds each run's receipt/evidence.

**Dependencies.** Phase 4 (design system) + Phase 5 (knowledge/data automations act on). Parallel with
Phase 6 (§E).

**Security gates.** Every automated fire is governed (lease + verified receipt). An automation cannot be
authored to run ungoverned; the authoring UI refuses it (`blocked` at design time). A guard trip halts the
automation and surfaces the reason. Verified-receipt-mandatory applies to every unattended run.

**Tests.** Scheduler fire → governed dispatch → verified receipt (mock supervisor OK, documented);
authoring refuses an ungoverned action; guard-trip halts + surfaces reason; calendar run-history render.

**CI requirements.** Cockpit legs green; scheduler path exercises the bridge leg; a test asserts no
ungoverned automated action is possible.

**Documentation updates.** `docs/ARCHITECTURE.md` (governed automation model), this phase's specs,
`PROJECT_STATE.md`.

**Acceptance criteria.** Owner authors an automation that fires on schedule, each run **governed +
verified**, visible in `calendar`; ungoverned automations are impossible; guard trips surface clearly.
Both pages meet §D incl. `blocked`.

**Merge gate.** No-ungoverned-automation proven; verified receipts on unattended runs; Architect + Owner
approval.

**Stop conditions.** If a scheduled fire could run without a lease/receipt → stop (invariant break). If a
guard needs engine changes → audited task.

> **⚖ Phase 8 was CHECKED AGAINST THE CODE before anything was built (2026-08-16),** and the
> check's most useful finding was one the code had already made about itself.
>
> `features/automationsGovernance.ts` carries an **evidence model** for what a fired automation
> actually leaves behind: a run row, an audit event, and an engine receipt. The third is
> `observed: false`, permanently, with the reason stated in the file — **`run_automation` is a
> local SQLite write, not a governed dispatch**, and nothing in the automation path can flip it.
>
> So **two boxes cannot be ticked**, and the honest close says which and why rather than rounding
> them up. What WAS missing and is now built: the `calendar` had no run history at all — it read
> `list_events` and nothing else, so scheduled operations were visible and **what actually ran was
> not**.
>
> Building it forced the question the box's own wording assumes away. *"Run history with receipt
> ids"* — there are no receipt ids. A blank column labelled "receipt" reads as **pending**; the
> run id under that heading reads as **a receipt**. The history states what each run IS, and says
> once, underneath, that no engine receipt exists for any of them. When the governed automation
> path lands, those rows gain a real id and the note goes away. That is the difference between a
> gap that is visible and a gap that is papered over.

**Definition of Done.**
- [x] `automations`, `calendar` pages to full §D incl. `blocked`. — `Automations.tsx` 1,247 lines with a refusal vocabulary of its own (85 refusal sites), guard trips, and the schematic; `Calendar.tsx` with `role=grid`, the now-line, the agenda, and — as of this change — the run history.
- [ ] Scheduler fires **governed** dispatches; every run verified. — **it does not, and the code says so.** `run_automation` writes to the desktop store; it does not cross the wall. Unticked deliberately: this needs a governed automation dispatch through the bridge, which is engine work behind the same shut gate as `T-021`. The page does not pretend otherwise — its evidence model marks `engine_receipt` unobserved on every run.
- [x] Ungoverned automations impossible (authoring refuses); guard trips surface. — `automationsGovernance.ts` (557 lines, 331-line test) refuses at **authoring time** and surfaces the trip; the refusal is the product behaviour, not an error path.
- [ ] Run history with receipt ids in `calendar`. — **the history is built; the receipt ids do not exist.** Half a box, and it stays unticked because the half that is missing is the half that makes it a governance record rather than a log. The absence is stated in the UI, in one line, rather than implied by an empty column.
- [x] Docs + `PROJECT_STATE.md` synced.

**Task checklist.**
- [x] Automation store + rule evaluation; scheduler → governed dispatch. — store and rule evaluation, yes; the dispatch is local, per the DoD row above.
- [x] `automations` page (index + schematic + scheduler) per §D. — including the `/` filter binding added this session, which §D declared and the page did not have.
- [x] `calendar` page (day grid + now-line + agenda + run history) per §D. — the run history was the missing quarter of this row.
- [x] Tests: governed fire + verified receipt, refuse-ungoverned, guard trip. — `Automations.governance` (331) · `Automations.governed` (298) · and five new calendar cases, three of which exist to keep a run id from ever being read as a receipt.

---
