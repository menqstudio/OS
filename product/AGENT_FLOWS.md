- **Purpose:** Define the canonical detailed UX flows for the Agents workspace — agent profile, team grouping, permissions, configuration, assignment, delegation, and the live execution lifecycle — completing the agent surface of Roadmap Phase 1.
- **Scope:** Agent gallery and profile, create/configure, assign to task or room, the delegation contract, the live-status lifecycle, pause/resume, escalation, and team grouping (Product / Architecture / Engineering / Security / Operations / Review). Grounded in [../AI_RUNTIME.md](../AI_RUNTIME.md). Trilingual product surface (HY/EN/RU).
- **Owner:** Gev.
- **Related:** [WORKSPACES.md](WORKSPACES.md), [USER_FLOWS.md](USER_FLOWS.md), [STATES.md](STATES.md), [WORKSPACE_FLOWS.md](WORKSPACE_FLOWS.md), [CHAT_FLOWS.md](CHAT_FLOWS.md), [PROJECT_TASK_FLOWS.md](PROJECT_TASK_FLOWS.md), [DECISION_APPROVAL_FLOWS.md](DECISION_APPROVAL_FLOWS.md), [../AI_RUNTIME.md](../AI_RUNTIME.md).
- **Last updated:** 2026-07-19.

# BroPS Agent Flows

Status: Draft canonical

This document specifies what Gev actually sees and does when working with specialist agents. It is the UX projection of the runtime; it never redefines the runtime. Every agent status, contract field, execution transition, and law used here is the one in [../AI_RUNTIME.md](../AI_RUNTIME.md) and MUST NOT drift. Every UI state (`loading`, `empty`, `populated`, `error`, `offline`, `permission-denied`, `blocked`, `awaiting-approval`, `destructive-confirmation`, `success`) is the canonical pattern in [STATES.md](STATES.md) and is referenced, not restated. Permissions and approval gates follow [../docs/architecture/NOTIFICATIONS_AND_PERMISSIONS.md](../docs/architecture/NOTIFICATIONS_AND_PERMISSIONS.md).

Canonical vocabulary reused verbatim below:

- **Core agent statuses:** `Offline, Idle, Observing, Thinking, Waiting approval, Working, Blocked, Review, Failed, Completed`.
- **Execution model (per delegated run):** `assigned → accepted → running → blocked | completed | failed | cancelled`.
- **Delegation contract (every run must contain):** 1) Objective, 2) Context, 3) Allowed scope, 4) Expected output, 5) Completion evidence, 6) Deadline or stop condition, 7) Approval boundary.
- **Approval levels:** `A0` (no approval), `A1` (policy-preapproved, bounded reversible), `A2` (explicit approval), `A3` (dual confirmation).
- **Truth requirement:** an agent may report only `completed with evidence`, `partially completed with evidence`, `blocked with reason`, `failed with reason`, or `not started`. Vague progress claims are invalid.

Bro is the single top-level conductor and stays accountable for integration and final verification; agents are bounded, scoped specialists and no agent is globally autonomous by default.

---

## 1. Agent gallery / Ագենտների պատկերասրահ

- **Entry point:** Sidebar → Core → **Agents**; also from an agent mention in chat, the Agent drawer on any object, and "Assign agent" on a task or room.
- **Primary action:** Find the right specialist and open its profile, or create/configure one.
- **What Gev sees:** A gallery of the specialist set (Lens, Lezu, Forge, Tensor, Reviz, Mason, Pixel, Grid, Probe, Ops, Vault, Flow, Archi, Sigma, Steward, Pocket, Shield, Sentry, Hawk, Relay, Compass, Strat, Closer). Each card shows name and domain, live status chip (from the core statuses), current work if any, health, and cost. Cards can be grouped by **team** (see §7) or filtered by domain, status, availability, and permission scope.
- **States:** `loading` (skeleton cards, names kept visible), `empty` (first-run: no agents configured yet — invite to add the first; no-results vs. filtered-empty distinguished), `populated` (each card shows live status + owner of current work inline), `error` (registry load failed; retry), `offline` (cached roster labeled stale; live status shown as last-known + offline marker, configuration disabled), `permission-denied` (restricted agents visible-but-disabled with reason), `success` (create/configure reflected in the gallery). See [STATES.md](STATES.md).

---

## 2. Agent profile / Ագենտի պրոֆիլ

Opening a card opens the profile — the full, honest picture of one specialist. It renders exactly the required agent profile from [../AI_RUNTIME.md](../AI_RUNTIME.md):

- **Identity & domain** — name, domain, mission.
- **Capabilities** — what it can do.
- **Tools** — allowed tools only (the tool-execution boundary is explicit).
- **Allowed data sources** and **prohibited actions**.
- **Provider / model** — the provider and model backing this agent, plus any per-task model overrides.
- **Permissions** — role (Agent), scoped grants (workspace / project / conversation / file / task / automation / provider / secret / system setting), deny-by-default; the **approval boundary** (which actions need A2/A3) is shown, not buried. Secrets are never displayed in plaintext.
- **Budget** — cost/spend limits and current consumption, with the high-cost-run gate noted.
- **Memory scope** — which memory classes and project/room scopes this agent may read or write; no hidden memory.
- **Project access** and **success metrics / failure & escalation rules**.
- **Run history** — every past delegated run with its terminal status (`completed | failed | cancelled`), evidence, and a link to the execution log; failed and blocked runs are shown honestly, never hidden.

- **States:** `loading` (skeleton profile with name/domain visible), `populated` (live status chip + current run inline), `error`, `offline` (profile cached and marked stale; edit/run disabled), `permission-denied` (viewing/editing a restricted agent gated with reason). See [STATES.md](STATES.md).

---

## 3. Create / configure an agent / Ագենտ ստեղծել և կարգավորել

- **Entry point:** Agent gallery → **New agent**, or **Configure** on an existing profile (or duplicate from a Library template).
- **Primary action:** Declare a complete, valid agent contract before the agent can be assigned any work.
- **Key sub-flows:**
  1. **Define the contract.** Fill every required field: identity & domain, mission, capabilities, allowed tools, input contract, output contract, authority limits, escalation rules, timeout & retry policy — plus provider/model, permissions, budget, memory scope, and project access. Configuration changes are drafts until saved; saving is blocked until the contract is complete, and an incomplete contract is a `blocked` state, not a silent partial save.
  2. **Set the approval boundary.** Choose which action classes run at A0/A1 automatically and which require A2/A3. Granting an agent scopes beyond read-only, or provider/secret access, is itself a permission change and a mandatory approval gate.
  3. **Set budget & limits.** Cost ceiling, timeout, retry policy; high-cost runs are flagged to require approval.
  4. **Dry-run / validate.** Optionally validate the agent against a sample task before enabling it.
- **Rules:** an agent cannot self-expand permissions or delegate authority it does not possess; scope growth requires visible justification and, where needed, approval; every saved change records an audit event.
- **States:** `loading`, `empty` (blank new-agent form), `populated` (draft contract with validation inline), `error` (save/validate failed; retry, input preserved), `offline` (create/save disabled), `permission-denied` (only Owner/Admin may create or widen an agent's scope), `blocked` (contract incomplete — names the missing field), `awaiting-approval` (scope/provider/secret/budget grants pause at the gate), `destructive-confirmation` (delete/retire an agent names dependents and running work), `success` (agent saved and available). See [STATES.md](STATES.md).

---

## 4. Assign an agent to a task or room / Ագենտ նշանակել

- **Entry point:** "Assign agent" on a task (see [PROJECT_TASK_FLOWS.md](PROJECT_TASK_FLOWS.md)), "@mention" or "Add agent" in a room (see [CHAT_FLOWS.md](CHAT_FLOWS.md)), or "Delegate" from a Bro plan card / the Command workspace.
- **Primary action:** Bind a specialist to a unit of work under a complete delegation contract.
- **Key sub-flows:**
  1. **Pick the specialist.** Choose by domain/capability; unavailable or out-of-scope agents are visible-but-disabled with a reason, never silently absent.
  2. **Compose the delegation contract.** The assignment UI requires all seven fields — Objective, Context, Allowed scope, Expected output, Completion evidence, Deadline or stop condition, Approval boundary — before the run can start. Context is assembled to the minimum required (Context engine) and its sources are visible.
  3. **Confirm & dispatch.** On confirm, the run enters `assigned`; the agent moves to `accepted` then `running`. A run event is emitted.
- **States:** `loading`, `empty` (no eligible agent for this work — offers to configure one), `populated` (contract preview with resolved scope + evidence requirement), `error` (dispatch failed; retry), `offline` (assignment disabled), `permission-denied` (assigning beyond your grant is disabled with reason), `blocked` (missing a required contract field, or an unmet prerequisite on the target), `awaiting-approval` (an A2/A3 approval boundary means the run holds until approved), `success` (agent assigned; run visible on the object and in run history). See [STATES.md](STATES.md).

---

## 5. Live-status lifecycle / Live-status կյանքի ցիկլ

Once a run is dispatched, its status is always visible on the task/room, on the agent card, and in the execution log — never hidden behind a click. The visible lifecycle maps the core statuses onto the execution model:

1. **`assigned` → Idle/Observing:** the agent has the run but has not started; ownership and the objective are shown.
2. **`accepted` → Thinking:** the agent is planning its approach; the current step label is shown, never a bare spinner.
3. **`running` → Working:** live progress with a determinate step label and the agent name; each meaningful transition emits an event.
4. **Waiting approval:** if the run hits an A2/A3 step, execution visibly holds at `Waiting approval` (see approval hold below) — nothing proceeds quietly.
5. **`blocked` → Blocked:** an unmet dependency, prerequisite, or unverifiable result stops progress; the exact blocker and who/what resolves it are named honestly (uncertainty is shown, never smoothed into success).
6. **Review:** Bro verifies the output against the expected result and completion evidence before anything is called done.
7. **Terminal — `completed | failed | cancelled` → Completed / Failed:** completion is claimed only when execution evidence and verification both exist. A partial/unverified result is reported as `partially completed with evidence` or `blocked`, never `success`. `blocked` and `failed` always surface a reason.

- **Approval hold:** at `Waiting approval`, the approver sees the exact action, target, scope, consequences, rollback, and expiry (Approval model), and Approves/Rejects with a reason. See [DECISION_APPROVAL_FLOWS.md](DECISION_APPROVAL_FLOWS.md).
- **States:** `loading` (determinate progress + live step, ownership visible), `populated` (inline live status on the item), `error` (run failed with a plain-language reason; retry/inspect log), `offline` (last-known status marked stale; live tail paused visibly), `blocked` (blocker named), `awaiting-approval` (execution held at the gate), `success` (completed with attached evidence and a link to the execution log). See [STATES.md](STATES.md).

---

## 6. Pause / resume, cancel, and escalation / Դադար / վերսկսում և escalation

- **Pause / resume.** Gev can pause a `running` agent; the run holds its state and shows a paused indicator (no false progress). Resume returns it to `running`. Pausing never discards captured evidence.
- **Cancel.** Cancelling moves the run to `cancelled` (terminal). Because cancelling in-flight work is high-impact, it uses `destructive-confirmation`; the run's partial evidence and reason are preserved and recorded.
- **Emergency stop.** An emergency stop overrides all active approvals and halts the agent immediately; the halt and its cause are recorded as events.
- **Escalation.** When an agent reaches its authority limit, an unmet dependency, or an ambiguous decision, it escalates per its escalation rules rather than exceeding scope. Escalation surfaces to Bro (and to Gev where owner input is required) as a `blocked` state naming what is needed — for example an approval, a missing input, or a decision. Agents may recommend but must not impersonate the approver.
- **States:** `populated` (paused/running/escalated indicator inline), `blocked` (escalation naming the required resolver), `awaiting-approval` (escalation that needs an approval), `destructive-confirmation` (cancel/stop names the run and its effect), `offline` (pause/resume/cancel that require the server are disabled with reason), `success` (resumed/cancelled/stopped confirmed and recorded). See [STATES.md](STATES.md).

---

## 7. Team grouping / Թիմային խմբավորում

Agents may be grouped into persistent teams — **Product, Architecture, Engineering, Security, Operations, Review** — exactly as in [../AI_RUNTIME.md](../AI_RUNTIME.md). Bro coordinates cross-team work and prevents conflicting execution.

- **Entry point:** Agent gallery → group-by **Team**, or open a team room (see [CHAT_FLOWS.md](CHAT_FLOWS.md)).
- **Primary action:** See a team's members, their combined live status, and the work in flight across the team.
- **Key sub-flows:**
  1. **View a team.** Members, per-agent status, current runs, and aggregate health/cost for the team.
  2. **Assign within a team.** Delegate to the best-fit member; conflicting or duplicate work is flagged so parallel runs use isolated state where mutation conflicts are possible.
  3. **Team room link.** A team maps to a persistent team room where its agents reason and where runs, decisions, and approvals stay visible.
- **States:** `loading`, `empty` (a team with no members yet), `populated` (each member's live status + current run inline), `error`, `offline` (cached team view marked stale), `permission-denied` (restricted teams gated), `blocked` (a team run waiting on an upstream dependency), `success` (assignment reflected across the team view). See [STATES.md](STATES.md).

---

## 8. Safety

Agent authority never comes from a mention, an assignment, or a chat agreement alone. It comes only from the agent's declared contract, its permission scope, the approval policy, and the specific delegated run — and A2/A3 actions always stop at a visible approval gate before running. Bro stays accountable for integration and final verification; no agent reports completion without execution evidence.

---

# Հայերեն

Կարգավիճակ․ Draft canonical

Այս փաստաթուղթը սահմանում է, թե իրականում ինչ է տեսնում և անում Gev-ը specialist agent-ների հետ աշխատելիս։ Այն runtime-ի UX projection-ն է; երբեք չի վերասահմանում runtime-ը։ Այստեղ օգտագործված յուրաքանչյուր ագենտի status, contract field, execution transition և law նույնն է, ինչ [../AI_RUNTIME.md](../AI_RUNTIME.md)-ում, և ՉՊԵՏՔ Է շեղվի։ Յուրաքանչյուր UI state (`loading`, `empty`, `populated`, `error`, `offline`, `permission-denied`, `blocked`, `awaiting-approval`, `destructive-confirmation`, `success`) կանոնական օրինաչափությունն է [STATES.md](STATES.md)-ում և հղվում է, ոչ վերասահմանվում։ Permission-ներն ու approval gate-երը հետևում են [../docs/architecture/NOTIFICATIONS_AND_PERMISSIONS.md](../docs/architecture/NOTIFICATIONS_AND_PERMISSIONS.md)-ին։

Կանոնական բառապաշար՝ վերարտադրված ճշգրիտ․

- **Ագենտի հիմնական status-եր․** `Offline, Idle, Observing, Thinking, Waiting approval, Working, Blocked, Review, Failed, Completed`։
- **Execution model (ամեն delegated run-ի)․** `assigned → accepted → running → blocked | completed | failed | cancelled`։
- **Delegation պայմանագիր (ամեն run-ը պարտադիր պարունակում է)․** 1) Objective, 2) Context, 3) Allowed scope, 4) Expected output, 5) Completion evidence, 6) Deadline կամ stop condition, 7) Approval boundary։
- **Approval level-եր․** `A0` (առանց approval), `A1` (policy-preapproved, սահմանափակ reversible), `A2` (բացահայտ approval), `A3` (dual confirmation)։
- **Ճշմարտության պահանջ․** ագենտը կարող է report անել միայն `completed with evidence`, `partially completed with evidence`, `blocked with reason`, `failed with reason` կամ `not started`։ Անորոշ progress claim-երն անվավեր են։

Bro-ն միակ top-level conductor-ն է և մնում է պատասխանատու ինտեգրման ու վերջնական ստուգման համար; ագենտները սահմանափակ, scope-ով specialist-ներ են, և ոչ մի ագենտ default-ով գլոբալ ինքնավար չէ։

---

## 1. Ագենտների պատկերասրահ

- **Մուտքի կետ․** Sidebar → Core → **Agents**; նաև chat-ի agent mention-ից, ցանկացած object-ի Agent drawer-ից և task/room-ի «Assign agent»-ից։
- **Հիմնական գործողություն․** Գտնել ճիշտ specialist-ին և բացել իր պրոֆիլը, կամ ստեղծել/կարգավորել մեկը։
- **Ինչ է տեսնում Gev-ը․** Specialist set-ի պատկերասրահ (Lens, Lezu, Forge, Tensor, Reviz, Mason, Pixel, Grid, Probe, Ops, Vault, Flow, Archi, Sigma, Steward, Pocket, Shield, Sentry, Hawk, Relay, Compass, Strat, Closer)։ Ամեն card ցույց է տալիս անուն և domain, live status chip (հիմնական status-երից), ընթացիկ աշխատանք եթե կա, health և cost։ Card-երը կարող են խմբավորվել ըստ **team**-ի (տես §7) կամ filter լինել ըստ domain, status, availability և permission scope-ի։
- **Վիճակներ․** `loading` (skeleton card-եր, անունները տեսանելի), `empty` (first-run՝ դեռ ագենտ չկա — հրավեր ավելացնել առաջինը; no-results vs. filtered-empty տարբերվող), `populated` (ամեն card ցույց է տալիս live status + ընթացիկ աշխատանքի owner inline), `error` (registry load ձախողվեց; retry), `offline` (cached roster՝ stale; status-ը որպես last-known + offline marker, configuration անջատված), `permission-denied` (restricted ագենտները՝ տեսանելի-բայց-անջատված պատճառով), `success` (create/configure արտացոլված)։ Տես [STATES.md](STATES.md)։

---

## 2. Ագենտի պրոֆիլ

Card բացելը բացում է պրոֆիլը՝ մեկ specialist-ի ամբողջական, ազնիվ պատկերը։ Այն ցուցադրում է ճշգրիտ [../AI_RUNTIME.md](../AI_RUNTIME.md)-ի պարտադիր պրոֆիլը․

- **Identity & domain** — անուն, domain, mission։
- **Capabilities** — ինչ կարող է անել։
- **Tools** — միայն allowed tool-ներ (tool-execution boundary-ն բացահայտ է)։
- **Allowed data sources** և **prohibited actions**։
- **Provider / model** — այս ագենտի provider-ն ու model-ը, plus per-task model override-ները։
- **Permissions** — role (Agent), scoped grant-ներ (workspace / project / conversation / file / task / automation / provider / secret / system setting), deny-by-default; **approval boundary**-ն (որ գործողությունները պահանջում են A2/A3) ցուցադրված է, ոչ թաղված։ Secret-ները երբեք plaintext-ով չեն ցուցադրվում։
- **Budget** — cost/spend limit-ներ և ընթացիկ consumption, high-cost-run gate-ի նշումով։
- **Memory scope** — որ memory class-երը և project/room scope-ները ագենտը կարող է read/write անել; թաքնված memory չկա։
- **Project access** և **success metrics / failure & escalation rules**։
- **Run history** — ամեն անցյալ delegated run իր terminal status-ով (`completed | failed | cancelled`), evidence-ով և execution log-ի հղումով; ձախողված և blocked run-երը ցուցադրվում են ազնվորեն, երբեք չեն թաքցվում։

- **Վիճակներ․** `loading` (skeleton պրոֆիլ՝ անուն/domain տեսանելի), `populated` (live status chip + ընթացիկ run inline), `error`, `offline` (պրոֆիլը cached և stale; edit/run անջատված), `permission-denied` (restricted ագենտի դիտում/խմբագրում gated պատճառով)։ Տես [STATES.md](STATES.md)։

---

## 3. Ագենտ ստեղծել և կարգավորել

- **Մուտքի կետ․** Agent gallery → **New agent**, կամ գոյություն ունեցող պրոֆիլի **Configure** (կամ duplicate Library template-ից)։
- **Հիմնական գործողություն․** Հայտարարել ամբողջական, վավեր ագենտի contract՝ նախքան որևէ աշխատանք նշանակելը։
- **Հիմնական ենթահոսքեր․**
  1. **Սահմանել contract-ը.** Լրացնել ամեն պարտադիր field՝ identity & domain, mission, capabilities, allowed tools, input contract, output contract, authority limits, escalation rules, timeout & retry policy — plus provider/model, permissions, budget, memory scope և project access։ Կարգավորման փոփոխությունները draft են մինչ save-ը; save-ը արգելափակված է, մինչ contract-ն ամբողջական չէ, և անավարտ contract-ը `blocked` վիճակ է, ոչ լուռ մասնակի save։
  2. **Սահմանել approval boundary-ն.** Ընտրել որ action class-երը կաշխատեն A0/A1 ավտոմատ և որոնք պահանջում են A2/A3։ Ագենտին read-only-ից դուրս scope, կամ provider/secret access տալը ինքնին permission change է և պարտադիր approval gate։
  3. **Սահմանել budget & limit-ներ.** Cost ceiling, timeout, retry policy; high-cost run-երը նշվում են՝ approval պահանջելով։
  4. **Dry-run / validate.** Ընտրովի՝ validate ագենտը sample task-ի դեմ նախքան enable անելը։
- **Կանոններ․** ագենտը չի կարող ինքնուրույն ընդլայնել իր permission-ները կամ delegate անել չունեցած authority; scope-ի աճը պահանջում է տեսանելի հիմնավորում և, ըստ անհրաժեշտության, approval; ամեն պահված փոփոխություն գրանցում է audit event։
- **Վիճակներ․** `loading`, `empty` (դատարկ new-agent form), `populated` (draft contract՝ validation inline), `error` (save/validate ձախողվեց; retry, input պահված), `offline` (create/save անջատված), `permission-denied` (միայն Owner/Admin-ը կարող է ստեղծել կամ լայնացնել ագենտի scope), `blocked` (contract անավարտ — անվանում է բացակայող field-ը), `awaiting-approval` (scope/provider/secret/budget grant-ները կասեցվում են gate-ում), `destructive-confirmation` (ագենտի delete/retire-ը անվանում է dependents և running work), `success` (ագենտ պահված և հասանելի)։ Տես [STATES.md](STATES.md)։

---

## 4. Ագենտ նշանակել task-ի կամ room-ի

- **Մուտքի կետ․** Task-ի «Assign agent» (տես [PROJECT_TASK_FLOWS.md](PROJECT_TASK_FLOWS.md)), room-ի «@mention» կամ «Add agent» (տես [CHAT_FLOWS.md](CHAT_FLOWS.md)), կամ Bro plan card-ի «Delegate» / Command workspace-ը։
- **Հիմնական գործողություն․** Կապել specialist-ին աշխատանքի միավորին՝ ամբողջական delegation contract-ի ներքո։
- **Հիմնական ենթահոսքեր․**
  1. **Ընտրել specialist-ին.** Ըստ domain/capability; անհասանելի կամ out-of-scope ագենտները տեսանելի-բայց-անջատված են պատճառով, երբեք լուռ բացակա։
  2. **Կազմել delegation contract-ը.** Assignment UI-ն պահանջում է բոլոր յոթ field-ը — Objective, Context, Allowed scope, Expected output, Completion evidence, Deadline կամ stop condition, Approval boundary — նախքան run-ը սկսելը։ Context-ը հավաքվում է նվազագույն անհրաժեշտի (Context engine), և իր աղբյուրները տեսանելի են։
  3. **Հաստատել & dispatch.** Հաստատելիս run-ը մտնում է `assigned`; ագենտը դառնում է `accepted` ապա `running`։ Run event-ը emit է լինում։
- **Վիճակներ․** `loading`, `empty` (այս աշխատանքի համար eligible ագենտ չկա — առաջարկում է configure անել), `populated` (contract preview՝ resolved scope + evidence requirement), `error` (dispatch ձախողվեց; retry), `offline` (assignment անջատված), `permission-denied` (քո grant-ից դուրս նշանակումն անջատված է պատճառով), `blocked` (բացակայող contract field կամ target-ի չբավարարված prerequisite), `awaiting-approval` (A2/A3 approval boundary-ն նշանակում է, որ run-ը պահվում է մինչ approval), `success` (ագենտ նշանակված; run-ը տեսանելի object-ի վրա և run history-ում)։ Տես [STATES.md](STATES.md)։

---

## 5. Live-status կյանքի ցիկլ

Run-ը dispatch լինելուց հետո իր status-ը միշտ տեսանելի է task/room-ի վրա, ագենտի card-ի վրա և execution log-ում — երբեք թաքցված click-ի ետևում։ Տեսանելի lifecycle-ը map է անում հիմնական status-երը execution model-ի վրա․

1. **`assigned` → Idle/Observing․** ագենտն ունի run-ը, բայց չի սկսել; ownership-ն ու objective-ը ցուցադրված են։
2. **`accepted` → Thinking․** ագենտը պլանավորում է իր մոտեցումը; ընթացիկ step label-ը ցուցադրված է, ոչ bare spinner։
3. **`running` → Working․** live progress՝ դետերմինիստիկ step label-ով և ագենտի անունով; ամեն էական transition emit է event։
4. **Waiting approval․** եթե run-ը հասնում է A2/A3 քայլի, կատարումը տեսանելիորեն պահվում է `Waiting approval`-ում — ոչինչ լուռ չի ընթանում։
5. **`blocked` → Blocked․** չբավարարված dependency, prerequisite կամ չստուգելի արդյունքը կանգնեցնում է progress-ը; ճշգրիտ blocker-ն ու ով/ինչ է լուծում՝ ազնվորեն անվանված (անորոշությունը ցուցադրվում է, երբեք չի հարթվում success-ի)։
6. **Review․** Bro-ն ստուգում է output-ը expected result-ի և completion evidence-ի դեմ՝ նախքան որևէ բան done կոչելը։
7. **Terminal — `completed | failed | cancelled` → Completed / Failed․** completion-ը հայտարարվում է միայն երբ execution evidence-ն ու verification-ը երկուսն էլ կան։ Մասնակի/չստուգված արդյունքը report է լինում որպես `partially completed with evidence` կամ `blocked`, երբեք `success`։ `blocked`-ն ու `failed`-ը միշտ ցույց են տալիս պատճառ։

- **Approval hold․** `Waiting approval`-ում approver-ը տեսնում է ճշգրիտ action, target, scope, consequences, rollback և expiry (Approval model), և Approve/Reject է անում պատճառով։ Տես [DECISION_APPROVAL_FLOWS.md](DECISION_APPROVAL_FLOWS.md)։
- **Վիճակներ․** `loading` (դետերմինիստիկ progress + live step, ownership տեսանելի), `populated` (item-ի վրա inline live status), `error` (run ձախողվեց պարզ պատճառով; retry/inspect log), `offline` (last-known status՝ stale; live tail-ը դադարեցված տեսանելի), `blocked` (blocker անվանված), `awaiting-approval` (կատարումը պահված gate-ում), `success` (completed՝ կցված evidence-ով և execution log-ի հղումով)։ Տես [STATES.md](STATES.md)։

---

## 6. Դադար / վերսկսում, cancel և escalation

- **Pause / resume.** Gev-ը կարող է pause անել `running` ագենտին; run-ը պահում է իր state-ը և ցույց տալիս paused ցուցիչ (ոչ false progress)։ Resume-ը վերադարձնում է `running`։ Pause-ը երբեք չի ջնջում captured evidence-ը։
- **Cancel.** Cancel-ը run-ը տանում է `cancelled` (terminal)։ Քանի որ in-flight աշխատանք cancel անելը high-impact է, օգտագործվում է `destructive-confirmation`; run-ի մասնակի evidence-ն ու պատճառը պահվում և գրանցվում են։
- **Emergency stop.** Emergency stop-ը override է անում բոլոր active approval-ները և անմիջապես կանգնեցնում ագենտին; halt-ն ու իր պատճառը գրանցվում են որպես event-ներ։
- **Escalation.** Երբ ագենտը հասնում է իր authority limit-ին, չբավարարված dependency-ի կամ ambiguous decision-ի, այն escalate է անում ըստ իր escalation rule-ների՝ ոչ թե scope-ը գերազանցում։ Escalation-ը surface է լինում Bro-ին (և Gev-ին, երբ owner input է պահանջվում) որպես `blocked` վիճակ՝ անվանելով ինչ է պետք — օրինակ approval, բացակայող input կամ decision։ Ագենտները կարող են recommend անել, բայց չեն կարող approver-ի կերպար ընդունել։
- **Վիճակներ․** `populated` (paused/running/escalated ցուցիչ inline), `blocked` (escalation՝ պահանջվող resolver-ի անունով), `awaiting-approval` (approval պահանջող escalation), `destructive-confirmation` (cancel/stop՝ run-ն ու էֆեկտն անվանելով), `offline` (server պահանջող pause/resume/cancel անջատված պատճառով), `success` (resumed/cancelled/stopped հաստատված և գրանցված)։ Տես [STATES.md](STATES.md)։

---

## 7. Թիմային խմբավորում

Ագենտները կարող են խմբավորվել մշտական թիմերում — **Product, Architecture, Engineering, Security, Operations, Review** — ճշգրիտ ինչպես [../AI_RUNTIME.md](../AI_RUNTIME.md)-ում։ Bro-ն համակարգում է cross-team աշխատանքը և կանխում հակասող կատարումը։

- **Մուտքի կետ․** Agent gallery → group-by **Team**, կամ բացել team room (տես [CHAT_FLOWS.md](CHAT_FLOWS.md))։
- **Հիմնական գործողություն․** Տեսնել թիմի անդամներին, նրանց միացյալ live status-ը և թիմով ընթացող աշխատանքը։
- **Հիմնական ենթահոսքեր․**
  1. **View team.** Անդամներ, per-agent status, ընթացիկ run-եր և թիմի aggregate health/cost։
  2. **Assign within team.** Delegate best-fit անդամին; հակասող կամ կրկնվող աշխատանքը նշվում է, որպեսզի զուգահեռ run-երը օգտագործեն isolated state, երբ mutation conflict հնարավոր է։
  3. **Team room link.** Թիմը map է լինում persistent team room-ի, որտեղ իր ագենտները reason են անում և որտեղ run-երը, decision-ներն ու approval-ները մնում են տեսանելի։
- **Վիճակներ․** `loading`, `empty` (դեռ անդամ չունեցող թիմ), `populated` (ամեն անդամի live status + ընթացիկ run inline), `error`, `offline` (cached team view՝ stale), `permission-denied` (restricted թիմերը gated), `blocked` (upstream dependency-ի սպասող team run), `success` (assignment արտացոլված team view-ում)։ Տես [STATES.md](STATES.md)։

---

## 8. Անվտանգություն

Ագենտի authority-ն երբեք չի գալիս միայն mention-ից, assignment-ից կամ chat համաձայնությունից։ Այն գալիս է միայն ագենտի հայտարարված contract-ից, իր permission scope-ից, approval policy-ից և կոնկրետ delegated run-ից — և A2/A3 գործողությունները միշտ կանգ են առնում տեսանելի approval gate-ում նախքան աշխատելը։ Bro-ն մնում է պատասխանատու ինտեգրման ու վերջնական ստուգման համար; ոչ մի ագենտ completion չի report անում առանց execution evidence-ի։
