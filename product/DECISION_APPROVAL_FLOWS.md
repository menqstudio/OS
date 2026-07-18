- **Purpose:** Canonical, detailed UX flows for Decisions, Approvals, and Agent runs in BroPS (Phase 1 UX). This file makes the AI_RUNTIME decision states, approval levels, and agent statuses concrete and implementable at the screen level.
- **Scope:** The Decision lifecycle UX, the Approval queue and approval-gate UX (levels A0–A3), and the Agent profile / delegation / live-run UX, including per-flow loading, empty, error, offline, expired, and blocked states. Trilingual product surface (HY/EN/RU).
- **Owner:** Gev.
- **Related:** [../AI_RUNTIME.md](../AI_RUNTIME.md), [../DECISIONS.md](../DECISIONS.md), [PROJECT_TASK_FLOWS.md](PROJECT_TASK_FLOWS.md), [CHAT_FLOWS.md](CHAT_FLOWS.md), [USER_FLOWS.md](USER_FLOWS.md), [GROUP_CHAT.md](GROUP_CHAT.md).
- **Last updated:** 2026-07-19.

# BroPS Decision, Approval & Agent Flows

Status: Draft canonical

> This document is the UX-level expansion of three AI_RUNTIME sections: the **Decision engine**, the **Approval model**, and the **Agents** runtime. It MUST NOT invent new states, levels, or statuses. Every lifecycle token below is quoted from AI_RUNTIME and, where relevant, mapped to the ADR statuses in DECISIONS.md. All product copy ships in HY / EN / RU with equal quality.

---

## 0. Shared conventions

### Canonical vocabulary (do not diverge)
- **Decision states** (AI_RUNTIME → Decision engine): `proposed → under review → approved | rejected | deferred → superseded`.
- **Approval levels** (AI_RUNTIME → Approval model): `A0` no approval · `A1` policy-preapproved · `A2` explicit approval · `A3` dual confirmation.
- **Agent statuses** (AI_RUNTIME → Agents → Core statuses): `Offline, Idle, Observing, Thinking, Waiting approval, Working, Blocked, Review, Failed, Completed`.

### Decision-state vs ADR-status mapping
The runtime **Decision states** drive the live UX. When an approved decision is written to the repository it also carries a DECISIONS.md **Status value**. The two are distinct and must both be shown:

| Runtime decision state (UX) | DECISIONS.md ADR status (record) |
| --- | --- |
| proposed | Proposed |
| under review | Proposed (in active review) |
| approved | Approved → Implementing → Locked |
| rejected | Rejected |
| deferred | Proposed (parked, no mandate) |
| superseded | Superseded |

### Global rule (inherited)
No flow may hide execution state, approval state, ownership, failure, or uncertainty (USER_FLOWS Global Rule). Silence is never approval (AI_RUNTIME Decision rules; Approval rules).

---

## 1. Decision flow UX

### 1.1 Decision object shown in the UI
Every decision card and detail view renders the AI_RUNTIME **Required fields**: decision ID, title, context, options considered, chosen option, rationale, owner, approver, scope, effective date, consequences, rollback or replacement path. The card also shows the current runtime **state** and, once recorded, the ADR status.

### 1.2 State lifecycle at the screen level
`proposed → under review → approved | rejected | deferred → superseded`

1. **Proposed** — A decision is drafted (by Gev, by Bro, or recommended by an agent). The card shows a `Proposed` badge, the options considered, and a rationale draft. Agents MAY recommend but the approver field stays empty; an agent MUST NOT fill it (AI_RUNTIME: "Agents MAY recommend; they MUST NOT impersonate the approver").
2. **Under review** — The decision is opened for review. Options are compared side by side; each option lists pros, cost, risk, and reversibility. Reviewers (Gev and invited agents) can comment. No project truth changes yet.
3. **Approved** — The owner-designated approver approves. This is the point that emits events and updates downstream truth (see 1.4). The record is written to DECISIONS.md as `Approved`.
4. **Rejected** — Declined with a required reason. The chosen option is cleared; the card explains why and offers "Propose alternative".
5. **Deferred** — Parked without a mandate. A deferral MUST capture a reason and MAY capture a revisit date; until revisited it grants no authority.
6. **Superseded** — A later decision replaces this one. A superseding decision MUST reference the prior decision ID (AI_RUNTIME rule); the UI links both directions (`Supersedes` / `Superseded by`).

### 1.3 Create-decision-from-message
Entry point from Group Chat / any thread (see CHAT_FLOWS.md):
1. User selects a message (or a Bro summary) and picks **Turn into decision**.
2. Bro pre-fills title, context, and candidate options from the selected message and surrounding thread; provenance (source message IDs) is attached automatically — chat is not canonical until recorded (AI_RUNTIME Decision rules; DECISIONS.md rule 5).
3. User edits options, sets scope and owner, and either saves as `proposed` or sends to `under review`.
4. The originating message shows a persistent "Linked decision → D-xxx" chip so the thread and the decision stay connected.

### 1.4 What an approved decision changes
On transition to **approved**, the Decision engine emits explicit events (AI_RUNTIME: "Approved decisions update project truth, tasks, documentation, and affected runtime policies through explicit events"). In the UX this is shown as a **propagation panel** listing each downstream write before and after it happens:
- **Project** — objective, constraints, or plan updates linked to the decision.
- **Tasks** — tasks created, retargeted, or closed; each links back to the decision ID.
- **Docs** — the DECISIONS.md record (and any ADR file) written with `Approved` status.
- **Runtime policy** — any approval-policy or agent-scope change the decision authorizes.
Each row shows a status (`pending → written → verified`); nothing is claimed as done without evidence (AI_RUNTIME Completion rule). If a downstream write fails, the decision stays `approved` but the panel flags the failed propagation as **Blocked** and offers retry.

### 1.5 Per-state UI conditions (Decisions)
- **Loading** — Skeleton card with the ID visible; options and rationale shimmer. Never render a partial decision as if complete.
- **Empty** — No decisions yet: "No decisions recorded. Turn a message or a proposal into a decision to start the record."
- **Error** — Load/save failure: inline banner "Couldn't load this decision" with Retry; unsaved edits preserved locally.
- **Offline** — Read-only from last synced snapshot; a badge marks staleness; save/approve actions disabled until reconnect.
- **Expired approval** — If a decision's approval expired before propagation completed, it drops to `under review` and shows "Approval expired — re-approve to continue".
- **Blocked** — A propagation write failed or a dependency is missing: red "Blocked" chip with the reason and a Retry / Escalate action.

---

## 2. Approval flow UX

### 2.1 Approval queue / drawer
A global **Approval drawer** (reachable from anywhere; badge count on the app shell) lists pending approvals newest-first. Each queue item renders, verbatim from the AI_RUNTIME **Approval object** binding:
- **Exact action** — the operation to be performed, in plain language.
- **Target** — the exact object/file/endpoint affected.
- **Scope** — the exact boundary the approval binds to.
- **Consequences** — known effects, spelled out.
- **Reversibility** — reversible / partially reversible / irreversible.
- **Expiry** — when this approval request goes stale.
- **Requester** — the agent or command requesting, plus its correlation ID.
Additional shown context: risk class, the approval **level** (A0–A3), and, where applicable, the candidate **version or hash** the approval binds to.

### 2.2 The four approval levels
- **A0 — no approval.** Read-only, harmless analysis. Never enters the queue; shown only in the activity log. UX: no gate, just a record.
- **A1 — policy-preapproved.** A bounded, reversible action covered by an explicit policy envelope. UX: executes automatically; surfaces as a **post-hoc notice** ("Auto-approved under policy X") with an Undo affordance where reversible. Anything outside the envelope falls back to approval-required (AI_RUNTIME Auto-mode).
- **A2 — explicit approval.** A meaningful write or external communication. UX: a single **Approve / Reject / Request changes** gate with the full approval object visible; action does not run until Approve.
- **A3 — dual confirmation.** Destructive, security-sensitive, financial, or irreversible action. UX: **two-step confirmation** — Approve, then a distinct second confirmation (re-state the exact target, type-to-confirm for destructive/financial, and, where policy requires, a second approving identity). The irreversibility and recovery statement are shown at both steps.

### 2.3 Approve / Reject / Request changes
- **Approve** — Binds the approval to the exact action, target, scope, consequences, expiry, approving identity, and candidate version/hash. The bound approval carries an `approval_id` used by the event and tool-execution records.
- **Reject** — Requires a reason. The action stays blocked and MUST NOT execute unless a new approval is issued (AI_RUNTIME rule). The requesting agent moves to `Blocked`.
- **Request changes** — Sends the request back to the requester with notes; the item leaves the pending queue and returns as a revised request (new candidate version/hash).

### 2.4 Binding, invalidation, and emergency stop
- **Bind to exact scope** — Approval for one action MUST NOT be reused for another (AI_RUNTIME). The UI never offers "apply to all"; each action carries its own binding.
- **Invalidation on material change** — If the action, target, scope, or candidate hash changes after approval, the prior approval is invalidated automatically. The item returns to the queue marked **Changed since approval — re-approve required**; ambiguous approval is not approval.
- **Emergency stop** — A always-available **Stop** control overrides all active approvals (AI_RUNTIME: "Emergency stop overrides all active approvals"). It halts in-flight tool calls and agent runs, revokes A1 auto-execution, and moves affected agents to `Blocked` with reason `emergency_stop`. Resuming requires fresh approvals.

### 2.5 Per-state UI conditions (Approvals)
- **Loading** — Queue skeleton; the badge count shows `…` until counts resolve.
- **Empty queue** — "No approvals waiting. Actions that need your sign-off will appear here."
- **Error** — "Couldn't load approvals" with Retry; already-fetched items remain actionable if their binding is still valid.
- **Offline** — Approvals are **disabled** while offline (an approval must bind to a verifiable candidate). Banner: "Approvals need a live connection." Emergency Stop remains available.
- **Expired approval** — Item greys out with an "Expired" badge; Approve is replaced by "Request a fresh action". Any partial execution is reported precisely, never hidden.
- **Blocked** — Requester is blocked pending this approval; the item shows the blocked agent/command and a link to its run.

---

## 3. Agent run flow UX

### 3.1 Agent profile view
Each agent has a profile rendering the AI_RUNTIME **Required agent profile**:
- Name and domain
- Mission
- Capabilities
- Tools (allowed tools only)
- Allowed data sources
- Prohibited actions
- Approval requirements (which actions demand A2/A3)
- Project access
- Memory scope
- Output contract
- Success metrics
- Failure and escalation rules
The header shows the agent's live **status** badge and its current/last run. Profiles are read-only to agents; only the owner (or an approved decision) can widen capabilities, tools, permissions, or memory scope — an agent cannot delegate authority it does not possess (AI_RUNTIME Runtime laws).

### 3.2 Delegation UX
Starting a run opens a **delegation form** enforcing the AI_RUNTIME **Delegation contract** — all seven fields are required before Start is enabled:
1. **Objective** — what the run must achieve.
2. **Context** — the minimum required context (Context engine assembles it; the form shows what was included and excluded).
3. **Allowed scope** — the exact boundary; the run cannot execute outside it.
4. **Expected output** — the output contract to be returned.
5. **Completion evidence** — what evidence proves done (commit SHA, file checksum, test output, screenshot, verified readback).
6. **Deadline or stop condition** — when to stop.
7. **Approval boundary** — which sub-actions the agent may take autonomously (A0/A1) vs. which must return to Gev (A2/A3).
The form refuses to start if any field is missing (AI_RUNTIME: refuse execution when scope/approval/contract is missing).

### 3.3 Live run view and statuses
A **run timeline** streams events (assigned, started, tool requested/executed, paused, completed/failed) and shows the agent's current status. The only valid statuses (AI_RUNTIME Core statuses), with their UX meaning:
- **Offline** — Agent not available; delegation disabled.
- **Idle** — Available, no active run.
- **Observing** — Watching a room/thread without acting.
- **Thinking** — Reasoning/planning; no side effects yet.
- **Waiting approval** — Paused at an approval boundary; a linked item sits in the Approval drawer (2.1). Nothing proceeds until resolved.
- **Working** — Executing within scope; the timeline shows each tool call and its evidence.
- **Blocked** — Cannot proceed (missing input, rejected approval, emergency stop); shows the reason.
- **Review** — Output produced, awaiting verification by Bro/owner before completion.
- **Failed** — Ended without meeting the objective; shows the failure reason (failure reported as failure, never disguised as progress).
- **Completed** — Objective met **with evidence** and verified (AI_RUNTIME Completion rule).

### 3.4 Result with evidence
On reaching **Review → Completed**, the run result view shows the returned output contract plus the **evidence bundle** (each evidence artifact from 3.2 item 5, with type and a link/readback). Per the Truth requirement, the result is exactly one of: completed with evidence, partially completed with evidence, blocked with reason, failed with reason, or not started — vague progress claims are rejected by the UI (no free-text "in progress" without a status).

### 3.5 Escalation
When an agent reaches its boundary it **escalates** rather than exceeding scope (AI_RUNTIME Personas P-003; agent contract escalation rules). The escalation card shows: what was reached (scope limit / approval boundary / conflict / repeated failure), what the agent recommends, and the decision Gev must make (approve, widen scope via an owner action, reassign, or stop). Escalation moves the agent to `Blocked` or `Waiting approval` depending on the cause.

### 3.6 Per-state UI conditions (Agent runs)
- **Loading** — Run timeline skeleton with the agent identity and status badge resolved first.
- **Empty** — Profile with no runs: "No runs yet. Delegate a task to start."
- **Error** — Timeline fetch failure: "Couldn't load this run" with Retry; last known status preserved.
- **Offline** — Agent `Offline`: delegation disabled, banner "This agent is offline"; any in-flight run shows its last synced state.
- **Expired approval** — A run left in `Waiting approval` past expiry moves to `Blocked` with reason `approval_expired` and offers a re-request.
- **Blocked** — Full-width reason banner plus the resolving action (approve, provide input, widen scope, or stop); the run cannot silently resume.

---

# Հայերեն

Կարգավիճակ՝ Draft canonical

> Այս փաստաթուղթը AI_RUNTIME-ի երեք բաժինների UX-մակարդակի ընդլայնումն է՝ **Decision engine**, **Approval model** և **Agents** runtime։ Այն ՉՊԵՏՔ Է հորինի նոր վիճակներ, մակարդակներ կամ կարգավիճակներ։ Ստորև բերված յուրաքանչյուր lifecycle token մեջբերված է AI_RUNTIME-ից և, ըստ անհրաժեշտության, կապակցված DECISIONS.md-ի ADR կարգավիճակներին։ Ամբողջ product copy-ն մատուցվում է HY / EN / RU՝ հավասար որակով։

---

## 0. Ընդհանուր պայմանավորվածություններ

### Canonical բառապաշար (շեղում չի թույլատրվում)
- **Որոշման վիճակներ** (AI_RUNTIME → Decision engine)՝ `proposed → under review → approved | rejected | deferred → superseded`։
- **Հաստատման մակարդակներ** (AI_RUNTIME → Approval model)՝ `A0` առանց հաստատման · `A1` policy-ով նախահաստատված · `A2` հստակ հաստատում · `A3` կրկնակի հաստատում։
- **Ագենտի կարգավիճակներ** (AI_RUNTIME → Agents → Core statuses)՝ `Offline, Idle, Observing, Thinking, Waiting approval, Working, Blocked, Review, Failed, Completed`։

### Որոշման-վիճակի և ADR-կարգավիճակի համապատասխանություն
Runtime-ի **որոշման վիճակները** վարում են կենդանի UX-ը։ Երբ հաստատված որոշումը գրվում է repository, այն կրում է նաև DECISIONS.md-ի **Status** արժեք։ Երկուսը տարբեր են և երկուսն էլ պետք է ցուցադրվեն.

| Runtime որոշման վիճակ (UX) | DECISIONS.md ADR կարգավիճակ (գրառում) |
| --- | --- |
| proposed | Proposed |
| under review | Proposed (ակտիվ վերանայում) |
| approved | Approved → Implementing → Locked |
| rejected | Rejected |
| deferred | Proposed (կասեցված, mandate չկա) |
| superseded | Superseded |

### Համընդհանուր կանոն (ժառանգված)
Ոչ մի հոսք չի կարող թաքցնել կատարման վիճակը, հաստատման վիճակը, պատասխանատուին, ձախողումը կամ անորոշությունը (USER_FLOWS Global Rule)։ Լռությունը երբեք հաստատում չէ (AI_RUNTIME Decision rules; Approval rules)։

---

## 1. Որոշման հոսքի UX

### 1.1 UI-ում ցուցադրվող որոշման օբյեկտ
Յուրաքանչյուր որոշման քարտ և մանրամասն տեսք ցուցադրում է AI_RUNTIME-ի **Պարտադիր դաշտերը**՝ decision ID, վերնագիր, համատեքստ, դիտարկված տարբերակներ, ընտրված տարբերակ, հիմնավորում, owner, approver, scope, ուժի մեջ մտնելու ամսաթիվ, հետևանքներ, rollback կամ replacement path։ Քարտը ցույց է տալիս նաև ընթացիկ runtime **վիճակը** և, գրանցվելուց հետո, ADR կարգավիճակը։

### 1.2 Վիճակների ցիկլը էկրանի մակարդակում
`proposed → under review → approved | rejected | deferred → superseded`

1. **Proposed / Առաջարկված** — Որոշումը սևագրվում է (Gev-ի, Bro-ի կողմից կամ ագենտի առաջարկով)։ Քարտը ցույց է տալիս `Proposed` badge, դիտարկված տարբերակները և հիմնավորման սևագիրը։ Ագենտը ԿԱՐՈՂ Է առաջարկել, բայց approver դաշտը մնում է դատարկ. ագենտը ՉՊԵՏՔ Է լրացնի այն (AI_RUNTIME. «Agents MAY recommend; they MUST NOT impersonate the approver»)։
2. **Under review / Վերանայման մեջ** — Որոշումը բացվում է վերանայման։ Տարբերակները համեմատվում են կողք կողքի. յուրաքանչյուրը թվարկում է pros, cost, risk և reversibility։ Վերանայողները (Gev և հրավիրված ագենտները) կարող են մեկնաբանել։ Project truth-ը դեռ չի փոխվում։
3. **Approved / Հաստատված** — Owner-ի նշանակած approver-ը հաստատում է։ Հենց այս կետն է emit անում events և թարմացնում ներքևի truth-ը (տես 1.4)։ Գրառումը DECISIONS.md-ում գրվում է `Approved` կարգավիճակով։
4. **Rejected / Մերժված** — Մերժվում է պարտադիր պատճառով։ Ընտրված տարբերակը մաքրվում է. քարտը բացատրում է ինչու և առաջարկում «Առաջարկել այլընտրանք»։
5. **Deferred / Հետաձգված** — Կասեցվում է առանց mandate-ի։ Հետաձգումը ՊԵՏՔ Է գրանցի պատճառ և ԿԱՐՈՂ Է գրանցել վերադարձի ամսաթիվ. մինչ վերադարձը այն ոչ մի լիազորություն չի տալիս։
6. **Superseded / Փոխարինված** — Հետագա որոշումը փոխարինում է սրան։ Փոխարինող որոշումը ՊԵՏՔ Է հղում անի նախորդ decision ID-ին (AI_RUNTIME կանոն). UI-ն կապում է երկու ուղղությամբ (`Supersedes` / `Superseded by`)։

### 1.3 Որոշում ստեղծել հաղորդագրությունից
Մուտքի կետը Group Chat-ից / ցանկացած thread-ից (տես CHAT_FLOWS.md).
1. Օգտատերն ընտրում է հաղորդագրություն (կամ Bro-ի ամփոփում) և ընտրում **Դարձնել որոշում**։
2. Bro-ն նախապես լրացնում է վերնագիրը, համատեքստը և թեկնածու տարբերակները ընտրված հաղորդագրությունից և շրջակա thread-ից. provenance-ը (աղբյուր message ID-ները) կցվում է ավտոմատ — chat-ը canonical չէ, քանի դեռ չի գրանցվել (AI_RUNTIME Decision rules; DECISIONS.md կանոն 5)։
3. Օգտատերը խմբագրում է տարբերակները, սահմանում scope և owner և պահում է որպես `proposed` կամ ուղարկում է `under review`։
4. Ելակետային հաղորդագրությունը ցույց է տալիս մշտական «Կապված որոշում → D-xxx» chip՝ thread-ն ու որոշումը կապված պահելու համար։

### 1.4 Ինչ է փոխում հաստատված որոշումը
**approved** անցման պահին Decision engine-ը emit է անում հստակ events (AI_RUNTIME. «Approved decisions update project truth, tasks, documentation, and affected runtime policies through explicit events»)։ UX-ում սա ցուցադրվում է **propagation panel**-ով, որը թվարկում է ներքևի յուրաքանչյուր write՝ առաջ և հետո.
- **Project** — որոշման հետ կապված objective, constraints կամ plan-ի թարմացումներ։
- **Tasks** — ստեղծված, վերաուղղորդված կամ փակված task-եր. յուրաքանչյուրը հղում է decision ID-ին։
- **Docs** — DECISIONS.md գրառումը (և ցանկացած ADR ֆայլ)՝ գրված `Approved` կարգավիճակով։
- **Runtime policy** — ցանկացած approval-policy կամ agent-scope փոփոխություն, որ որոշումը թույլատրում է։
Յուրաքանչյուր տող ցույց է տալիս կարգավիճակ (`pending → written → verified`). ոչինչ չի հայտարարվում կատարված՝ առանց ապացույցի (AI_RUNTIME Completion rule)։ Եթե ներքևի write-ը ձախողվի, որոշումը մնում է `approved`, բայց panel-ը ձախողված propagation-ը նշում է որպես **Blocked** և առաջարկում retry։

### 1.5 Ըստ վիճակի UI պայմաններ (Որոշումներ)
- **Loading** — Skeleton քարտ՝ ID-ն տեսանելի. տարբերակներն ու հիմնավորումը shimmer։ Երբեք չցուցադրել մասնակի որոշումն իբրև ավարտված։
- **Empty** — Դեռ որոշումներ չկան. «Որոշումներ չեն գրանցվել։ Գրառումը սկսելու համար հաղորդագրությունը կամ առաջարկը դարձրու որոշում»։
- **Error** — Load/save ձախողում. inline banner «Չհաջողվեց բեռնել այս որոշումը» Retry-ով. չպահված խմբագրումները պահվում են տեղում։
- **Offline** — Read-only վերջին synced snapshot-ից. badge-ը նշում է հնությունը. save/approve գործողությունները անջատված են մինչ վերամիացում։
- **Expired approval** — Եթե որոշման հաստատումը լրացել է մինչ propagation-ի ավարտը, այն իջնում է `under review` և ցույց տալիս «Հաստատումը լրացել է — վերահաստատիր շարունակելու համար»։
- **Blocked** — Propagation write-ը ձախողվել է կամ dependency բացակայում է. կարմիր «Blocked» chip՝ պատճառով և Retry / Escalate գործողությամբ։

---

## 2. Հաստատման հոսքի UX

### 2.1 Հաստատման հերթ / drawer
Գլոբալ **Approval drawer** (հասանելի ամենուրից. badge count app shell-ի վրա) թվարկում է սպասող հաստատումները՝ նորից հին։ Յուրաքանչյուր հերթի տարր ցուցադրում է AI_RUNTIME **Approval object** binding-ը բառացի.
- **Exact action / Ճշգրիտ գործողություն** — կատարվելիք գործողությունը՝ պարզ լեզվով։
- **Target / Թիրախ** — ազդվող ճշգրիտ object/file/endpoint-ը։
- **Scope / Շրջանակ** — ճշգրիտ սահմանը, որին կապվում է հաստատումը։
- **Consequences / Հետևանքներ** — հայտնի ազդեցությունները՝ բացված։
- **Reversibility / Շրջելիություն** — շրջելի / մասամբ շրջելի / անշրջելի։
- **Expiry / Ժամկետ** — երբ է այս հարցումը հնանում։
- **Requester / Հայցող** — հայցող ագենտը կամ command-ը՝ իր correlation ID-ով։
Լրացուցիչ ցուցադրվող համատեքստ՝ risk class, հաստատման **մակարդակ** (A0–A3), և, ըստ կիրառելիության, թեկնածու **version կամ hash**, որին կապվում է հաստատումը։

### 2.2 Հաստատման չորս մակարդակները
- **A0 — առանց հաստատման։** Read-only, անվնաս վերլուծություն։ Երբեք չի մտնում հերթ. ցուցադրվում է միայն activity log-ում։ UX՝ gate չկա, միայն գրառում։
- **A1 — policy-ով նախահաստատված։** Սահմանափակ, շրջելի գործողություն՝ ծածկված հստակ policy envelope-ով։ UX՝ կատարվում է ավտոմատ. երևում է որպես **post-hoc notice** («Auto-approved under policy X»)՝ Undo հնարավորությամբ, որտեղ շրջելի է։ Envelope-ից դուրս ամեն ինչ վերադառնում է հաստատում պահանջող վիճակի (AI_RUNTIME Auto-mode)։
- **A2 — հստակ հաստատում։** Նշանակալի write կամ արտաքին հաղորդակցություն։ UX՝ մեկ **Approve / Reject / Request changes** gate՝ ամբողջ approval object-ը տեսանելի. գործողությունը չի կատարվում մինչ Approve։
- **A3 — կրկնակի հաստատում։** Կործանարար, security-զգայուն, ֆինանսական կամ անշրջելի գործողություն։ UX՝ **երկքայլ հաստատում** — Approve, ապա առանձին երկրորդ հաստատում (կրկնել ճշգրիտ target-ը, type-to-confirm կործանարար/ֆինանսականի համար, և, որտեղ policy-ն պահանջում է, երկրորդ հաստատող identity)։ Անշրջելիությունն ու recovery statement-ը ցուցադրվում են երկու քայլում էլ։

### 2.3 Approve / Reject / Request changes
- **Approve / Հաստատել** — Կապում է հաստատումը ճշգրիտ action-ին, target-ին, scope-ին, consequences-ին, expiry-ին, հաստատող identity-ին և թեկնածու version/hash-ին։ Կապված հաստատումը կրում է `approval_id`, որն օգտագործվում է event և tool-execution գրառումների կողմից։
- **Reject / Մերժել** — Պահանջում է պատճառ։ Գործողությունը մնում է blocked և ՉՊԵՏՔ Է կատարվի, քանի դեռ նոր հաստատում չի տրվել (AI_RUNTIME կանոն)։ Հայցող ագենտն անցնում է `Blocked`։
- **Request changes / Խնդրել փոփոխություններ** — Հարցումը վերադարձնում է հայցողին նշումներով. տարրը լքում է սպասող հերթը և վերադառնում որպես վերանայված հարցում (նոր թեկնածու version/hash)։

### 2.4 Binding, invalidation և emergency stop
- **Կապում ճշգրիտ scope-ին** — Մեկ գործողության հաստատումը ՉՊԵՏՔ Է վերաօգտագործվի մեկ ուրիշի համար (AI_RUNTIME)։ UI-ն երբեք չի առաջարկում «apply to all». յուրաքանչյուր գործողություն կրում է իր binding-ը։
- **Invalidation material change-ի դեպքում** — Եթե action-ը, target-ը, scope-ը կամ թեկնածու hash-ը փոխվում է հաստատումից հետո, նախորդ հաստատումն ավտոմատ անվավեր է։ Տարրը վերադառնում է հերթ՝ նշված **Changed since approval — re-approve required**. երկիմաստ հաստատումը հաստատում չէ։
- **Emergency stop** — Միշտ հասանելի **Stop** control-ը գերակայում է բոլոր ակտիվ հաստատումներին (AI_RUNTIME. «Emergency stop overrides all active approvals»)։ Այն կանգնեցնում է ընթացիկ tool call-երն ու agent run-երը, չեղարկում A1 auto-execution-ը և ազդված ագենտներին տեղափոխում `Blocked`՝ `emergency_stop` պատճառով։ Վերսկսումը պահանջում է թարմ հաստատումներ։

### 2.5 Ըստ վիճակի UI պայմաններ (Հաստատումներ)
- **Loading** — Հերթի skeleton. badge count-ը ցույց է տալիս `…` մինչ հաշվարկը լուծվի։
- **Empty queue** — «Սպասող հաստատումներ չկան։ Քո հաստատումը պահանջող գործողությունները կհայտնվեն այստեղ»։
- **Error** — «Չհաջողվեց բեռնել հաստատումները» Retry-ով. արդեն բեռնված տարրերը մնում են գործող, եթե binding-ը դեռ վավեր է։
- **Offline** — Հաստատումներն **անջատված** են offline-ի ընթացքում (հաստատումը պետք է կապվի ստուգելի թեկնածուին)։ Banner՝ «Հաստատումները պահանջում են կենդանի կապ»։ Emergency Stop-ը մնում է հասանելի։
- **Expired approval** — Տարրը մոխրագունում է «Expired» badge-ով. Approve-ը փոխարինվում է «Խնդրել թարմ գործողություն»-ով։ Ցանկացած մասնակի կատարում հաղորդվում է ճշգրիտ, երբեք չի թաքցվում։
- **Blocked** — Հայցողը blocked է՝ սպասելով այս հաստատմանը. տարրը ցույց է տալիս blocked ագենտը/command-ը և հղում դեպի իր run-ը։

---

## 3. Ագենտի run-ի հոսքի UX

### 3.1 Ագենտի պրոֆիլի տեսք
Յուրաքանչյուր ագենտ ունի պրոֆիլ, որ ցուցադրում է AI_RUNTIME **Required agent profile**-ը.
- Անուն և domain
- Mission
- Կարողություններ (Capabilities)
- Tools (միայն թույլատրելի tools)
- Թույլատրելի data sources
- Արգելված գործողություններ (Prohibited actions)
- Հաստատման պահանջներ (որ գործողություններն են պահանջում A2/A3)
- Project access
- Memory scope
- Output contract
- Success metrics
- Failure և escalation կանոններ
Header-ը ցույց է տալիս ագենտի կենդանի **status** badge-ը և ընթացիկ/վերջին run-ը։ Պրոֆիլները ագենտների համար read-only են. միայն owner-ը (կամ հաստատված որոշումը) կարող է ընդլայնել capabilities, tools, permissions կամ memory scope — ագենտը չի կարող փոխանցել չունեցած լիազորություն (AI_RUNTIME Runtime laws)։

### 3.2 Delegation UX
Run-ը սկսելը բացում է **delegation form**, որը կիրառում է AI_RUNTIME **Delegation contract**-ը — բոլոր յոթ դաշտերը պարտադիր են մինչ Start-ի ակտիվացումը.
1. **Objective** — ինչ պետք է հասնի run-ը։
2. **Context** — նվազագույն անհրաժեշտ context (Context engine-ն է հավաքում. form-ը ցույց է տալիս ինչ ներառվեց և ինչ բացառվեց)։
3. **Allowed scope** — ճշգրիտ սահման. run-ը չի կարող կատարվել դրանից դուրս։
4. **Expected output** — վերադարձվող output contract-ը։
5. **Completion evidence** — ինչ ապացույց է հաստատում ավարտը (commit SHA, file checksum, test output, screenshot, verified readback)։
6. **Deadline or stop condition** — երբ կանգնել։
7. **Approval boundary** — որ ենթա-գործողությունները կարող է ագենտն ինքնուրույն կատարել (A0/A1) և որոնք պետք է վերադառնան Gev (A2/A3)։
Form-ը հրաժարվում է start անել, եթե որևէ դաշտ բացակայում է (AI_RUNTIME. հրաժարվել կատարումից, երբ scope/approval/contract բացակայում է)։

### 3.3 Կենդանի run-ի տեսք և կարգավիճակներ
**Run timeline**-ը հոսքով ցույց է տալիս events (assigned, started, tool requested/executed, paused, completed/failed) և ագենտի ընթացիկ status-ը։ Միակ վավեր կարգավիճակները (AI_RUNTIME Core statuses)՝ իրենց UX իմաստով.
- **Offline** — Ագենտն անհասանելի է. delegation-ն անջատված է։
- **Idle** — Հասանելի, ակտիվ run չկա։
- **Observing** — Դիտում է room/thread՝ առանց գործելու։
- **Thinking** — Reasoning/planning. դեռ side effect չկա։
- **Waiting approval** — Դադարեցված approval boundary-ի մոտ. կապված տարրը գտնվում է Approval drawer-ում (2.1)։ Ոչինչ չի առաջընթաց ապրում մինչ լուծումը։
- **Working** — Կատարում է scope-ի ներսում. timeline-ը ցույց է տալիս յուրաքանչյուր tool call և իր ապացույցը։
- **Blocked** — Չի կարող առաջ գնալ (բացակայող input, մերժված հաստատում, emergency stop). ցույց է տալիս պատճառը։
- **Review** — Output-ը ստեղծված է, սպասում է Bro/owner-ի ստուգմանը մինչ ավարտ։
- **Failed** — Ավարտվել է առանց objective-ին հասնելու. ցույց է տալիս ձախողման պատճառը (ձախողումը հաղորդվում է որպես ձախողում, երբեք չի քողարկվում որպես առաջընթաց)։
- **Completed** — Objective-ը հասված է **ապացույցով** և ստուգված (AI_RUNTIME Completion rule)։

### 3.4 Արդյունք ապացույցով
**Review → Completed** հասնելիս run-ի արդյունքի տեսքը ցույց է տալիս վերադարձված output contract-ը գումարած **evidence bundle**-ը (3.2-ի 5-րդ կետի յուրաքանչյուր evidence artifact՝ տեսակով և link/readback-ով)։ Truth requirement-ի համաձայն արդյունքը ճշգրիտ մեկն է հետևյալից՝ completed with evidence, partially completed with evidence, blocked with reason, failed with reason, կամ not started — երկիմաստ առաջընթացի հայտարարությունները մերժվում են UI-ի կողմից (ոչ մի ազատ տեքստ «in progress»՝ առանց status-ի)։

### 3.5 Escalation
Երբ ագենտը հասնում է իր սահմանին, նա **escalate** է անում, ոչ թե գերազանցում scope-ը (AI_RUNTIME Personas P-003; agent contract escalation rules)։ Escalation քարտը ցույց է տալիս՝ ինչին է հասել (scope limit / approval boundary / conflict / repeated failure), ինչ է ագենտն առաջարկում, և ինչ որոշում պետք է կայացնի Gev-ը (approve, ընդլայնել scope owner-ի գործողությամբ, reassign կամ stop)։ Escalation-ը ագենտին տեղափոխում է `Blocked` կամ `Waiting approval`՝ ըստ պատճառի։

### 3.6 Ըստ վիճակի UI պայմաններ (Ագենտի run-եր)
- **Loading** — Run timeline skeleton. նախ լուծվում է ագենտի identity-ն ու status badge-ը։
- **Empty** — Առանց run-երի պրոֆիլ. «Դեռ run-եր չկան։ Task delegate արա սկսելու համար»։
- **Error** — Timeline-ի բեռնման ձախողում. «Չհաջողվեց բեռնել այս run-ը» Retry-ով. վերջին հայտնի status-ը պահվում է։
- **Offline** — Ագենտը `Offline`. delegation-ն անջատված, banner «Այս ագենտն offline է». ցանկացած ընթացիկ run ցույց է տալիս իր վերջին synced վիճակը։
- **Expired approval** — `Waiting approval`-ում ժամկետը լրացրած run-ը անցնում է `Blocked`՝ `approval_expired` պատճառով և առաջարկում re-request։
- **Blocked** — Ամբողջ լայնությամբ պատճառի banner գումարած լուծող գործողությունը (approve, տրամադրել input, ընդլայնել scope կամ stop). run-ը չի կարող լուռ վերսկսվել։
