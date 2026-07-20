- **Purpose:** Define the canonical detailed UX flows for Direct Chat and Group Chat as observable, step-by-step behavior (Phase 1 UX).
- **Scope:** Direct Chat (Gev + Bro), Group Chat rooms, the message lifecycle as UI steps, Bro's five room modes as visible behaviors, per-flow states, and the chat safety law. Trilingual product surface (HY/EN/RU).
- **Owner:** Gev.
- **Related:** [GROUP_CHAT.md](GROUP_CHAT.md), [USER_FLOWS.md](USER_FLOWS.md), [../AI_RUNTIME.md](../architecture/AI_RUNTIME.md), [INFORMATION_ARCHITECTURE.md](INFORMATION_ARCHITECTURE.md), [NAVIGATION.md](NAVIGATION.md), [WORKSPACES.md](WORKSPACES.md).
- **Last updated:** 2026-07-19.

# BroPS Chat Flows

Status: Draft canonical

This document specifies what the user actually sees and does. It is concrete and step-by-step. Every status name, lifecycle, and approval level used here is the one defined in [../AI_RUNTIME.md](../architecture/AI_RUNTIME.md) and MUST NOT drift. Agent statuses are `Offline, Idle, Observing, Thinking, Waiting approval, Working, Blocked, Review, Failed, Completed`. Bro operating modes are `Answer, Plan, Execute, Review, Coordinate, Recovery`. Approval levels are `A0, A1, A2, A3`. The message lifecycle is `Draft → Sent → Routed → Acknowledged → Working → Result posted → Evidence attached → Accepted | Reopened`.

---

## 1. Direct Chat flow (Gev + Bro)

Direct Chat is the one-to-one surface between Gev and Bro. It is the fastest path from a thought to controlled work without leaving the conversation.

### 1.1 Open

1. Gev opens **Chat** from the left navigation, or presses the global chat shortcut.
2. The center pane shows the Direct Chat with Bro. The most recent messages load first; older history is lazy-loaded on scroll-up.
3. The header shows `Bro` with a live status chip (`Idle`, `Thinking`, `Working`, `Waiting approval`, `Offline`).
4. The right context pane shows the current context scope, pinned items, and any open work objects created from this chat.
5. **First-time / empty state:** if there is no history, the center shows a quiet empty state ("Ask Bro anything, or describe what you want done") with three example prompts and the current context scope already visible.

### 1.2 Context scope selection

1. Above the composer a **Context scope** control shows the exact context Bro will use before Gev sends anything. Nothing is hidden.
2. Default scope is `Current conversation` plus `User identity and preferences` (per the Context engine layers).
3. Gev can add or remove scope chips: active project, a specific task, selected files, selected knowledge, selected memories.
4. Each chip shows source and freshness. Sensitive scope chips carry a lock marker and are included only when explicitly added and permitted.
5. When scope conflicts exist (for example two files disagree), Bro surfaces the conflict as a banner rather than silently merging.
6. The chosen scope is recorded on every message so the answer is auditable later.

### 1.3 Send

1. Gev types in the composer. State is `Draft`. A quiet "context: N sources" hint reflects the current scope.
2. Composer actions available: mention, attach file, insert command, create task, create decision, request approval.
3. Gev sends. The message flips to `Sent` and appears right-aligned with a timestamp and the scope snapshot attached.
4. Bro's status chip changes to `Thinking`; a typing indicator appears. This is the `Routed → Acknowledged` transition in a one-to-one context.

### 1.4 Bro answer / plan / execute modes

Bro always names the mode it is operating in so Gev is never guessing.

- **Answer mode.** For questions and low-risk analysis (A0). Bro replies inline with a cited answer. If knowledge was used, sources are shown. No side effects. Status returns to `Idle`.
- **Plan mode.** For anything that will change state. Bro posts a structured plan card: objective, steps, agents it would engage, risk level, expected effect, and required approval level. Nothing executes yet. Gev can edit, approve the plan, or ask for changes.
- **Execute mode.** Runs only after the plan's approval condition is met. Bro shows a live execution card following the command lifecycle `received → understood → planned → approved_if_needed → executing → verified → completed | failed | cancelled`. The status chip reads `Working`.
  - A0/A1 steps run automatically inside their policy envelope.
  - A2/A3 steps pause at `Waiting approval` and render an inline approval gate (see §5.4). Execution resumes only on explicit approval.
- **Review / Coordinate / Recovery** appear as labeled cards when Bro is verifying output, fanning work to specialists, or recovering from a failure. Each is explicitly named.

Completion is reported only when execution evidence and verification both exist. Bro attaches evidence (commit SHA, file checksum, test output, screenshot, or state readback) to the result before claiming done.

### 1.5 Create a work object from a message

1. Gev hovers or long-presses any message and opens the message actions menu.
2. Options: **Create task**, **Create decision**, **Request approval**, **Save to knowledge**, **Pin**.
3. **Create task** opens a prefilled task drawer (title from the message, owner, status `planned`, evidence link back to the source message). On save, a task chip is attached under the message and the task appears in the right pane and in Tasks.
4. **Create decision** opens a decision drawer in state `proposed` with context copied from the thread; it moves through `proposed → under review → approved | rejected | deferred`.
5. **Request approval** creates an approval object bound to the exact action, target, scope, consequences, and expiry, and routes it to the Approvals queue.
6. Every created object keeps a back-link to the originating message, so the chat remains the provenance trail.

---

## 2. Group Chat flows

Group Chat is a first-class operating workspace where humans and agents reason, create work, decide, request approvals, and preserve shared context. Layout: left rooms list, center messages and threads, right context pane (members, files, tasks, decisions, approvals, activity), composer at the bottom.

### 2.1 Create a room

1. Gev clicks **New room** in the left pane.
2. Gev picks a **room type**:
   - **Direct** — Gev + Bro (private one-to-one, same as Direct Chat).
   - **Ad-hoc group** — temporary multi-agent conversation for a single question or burst of work.
   - **Team room** — persistent functional room (for example Engineering, Security).
   - **Project room** — automatically linked to exactly one project; inherits that project's scope.
   - **Review room** — scoped architecture, design, security, or release review.
3. Gev sets the **room goal** and **operating instructions** (these bound what agents may do inside the room).
4. The room is created with Bro already present as coordinator. Status: room opens in **empty state** with a goal banner and a prompt to invite members.

### 2.2 Invite humans and agents

1. Gev opens the **Members** panel in the right pane and clicks **Add**.
2. Gev invites humans (future collaborators, project- or room-scoped) and agents from the initial specialist set (Lens, Lezu, Forge, Tensor, Reviz, Mason, Pixel, Grid, Probe, Ops, Vault, Flow, Archi, Sigma, Steward, Pocket, Shield, Sentry, Hawk, Relay, Compass, Strat, Closer).
3. For each agent Gev sets a **response control**: respond only when mentioned, respond when domain is relevant, observe silently, propose without executing, or execute only within pre-approved scope.
4. Each member row shows role and permissions. Agents show a live status chip. Inviting a member emits an activity event; nothing about membership is hidden.

### 2.3 Mention → route (Bro router)

1. Gev types `@` in the composer; an autocomplete lists members (humans and agents) and routable objects (projects, tasks, files, decisions).
2. Gev can mention a specific agent (`@Forge`) or address the room generally.
3. On send, Bro acts as **Router**: if no specific agent was named, Bro assigns the question to the best-fit agent(s) and posts a short routing note ("Routed to @Forge — engineering scope"). The message reaches `Routed`.
4. The addressed agent moves `Offline/Idle → Observing → Thinking`, then posts an acknowledgement, reaching `Acknowledged`.
5. Bro prevents duplication: if two agents would answer the same point, Bro coordinates so only one owns it and notes the deduplication.

### 2.4 Agent live status

1. Every agent member shows a status chip that reflects the runtime status in real time: `Offline, Idle, Observing, Thinking, Waiting approval, Working, Blocked, Review, Failed, Completed`.
2. When an agent is `Working`, an inline progress row appears under its message with the current step and a stop control.
3. `Blocked` shows the blocking reason and what is needed to unblock. `Waiting approval` shows which approval it is waiting on with a jump link.
4. Status changes are also written to room activity, so the timeline and the live chip never disagree.

### 2.5 Message → task / decision / approval

1. Any message can be promoted via its actions menu, exactly as in Direct Chat (§1.5), but scoped to the room.
2. **Message → task:** creates a task owned by a member or agent; the task chip appears under the message and in the room's Tasks tab. Agent task execution follows `assigned → accepted → running → blocked | completed | failed | cancelled`.
3. **Message → decision:** opens a decision in state `proposed`. Chat agreement is not canonical until recorded here; silence is never approval; a superseding decision must reference the prior one.
4. **Message → approval:** creates an approval object at the required level (A1–A3) bound to the exact action and target, routed to the room's Approvals tab and the global Approvals queue.

### 2.6 Threads / replies

1. Gev clicks **Reply** on a message to open a thread in a right-side thread panel; the parent message shows a reply count.
2. Thread replies stay in the thread and do not flood the main timeline; a compact "N replies" summary remains inline.
3. Mentions, task/decision/approval creation, and pins all work inside threads with the same rules.

### 2.7 Pins

1. Any message, file, task, or decision can be **pinned** from its actions menu.
2. Pins appear in a **Pinned** strip at the top of the room and in the right context pane.
3. Pins are the room's quick-reference truth (goal, key decision, current blocker) and are included preferentially in room context assembly.

### 2.8 Room-scoped memory

1. The room has its own **memory** (conversation and project memory classes), separate from global memory.
2. When Bro or Gev marks a statement as room memory, it goes through `candidate → classify → deduplicate → verify source → approve policy → persist → index`; each entry stores source, scope, timestamp, confidence, and owner.
3. Room memory is inspectable in the right pane; Gev can correct, supersede, expire, or delete any entry. No hidden writes — the system always shows why a memory was used and where it came from.
4. Retrieval respects room and permission boundaries; memory from one room is not silently pulled into another.

### 2.9 Automatic summaries

1. Bro periodically posts a **room summary** card (on demand, on major milestones, and on a cadence) as **Recorder**.
2. The summary lists: decisions made, tasks created and their status, open approvals, unresolved questions, and key evidence links.
3. The summary is a card, not a silent overwrite; earlier summaries remain in history. Gev can pin the latest summary.

---

## 3. Message lifecycle as concrete UI steps

The lifecycle is `Draft → Sent → Routed → Acknowledged → Working → Result posted → Evidence attached → Accepted | Reopened`. What the user sees at each step:

1. **Draft** — text sits in the composer; a "context: N sources" hint shows the scope that will be attached. Nothing is transmitted.
2. **Sent** — the message appears in the timeline, right-aligned, with a timestamp and a small scope snapshot. A single check mark indicates delivered.
3. **Routed** — a subtle routing note from Bro appears ("Routed to @Forge"). In Direct Chat this is Bro's own status flipping to `Thinking`. The message shows a "routed" marker.
4. **Acknowledged** — the target agent posts a short "On it" acknowledgement and its status chip reads `Thinking` or `Working`. A read receipt appears for human members.
5. **Working** — an inline progress row shows the current step, elapsed time, and a stop control; the agent chip reads `Working`. Long steps stream partial updates, never a frozen spinner alone.
6. **Result posted** — the agent posts its result message. The result is clearly labeled as one of: completed, partially completed, blocked, failed, or not started. Vague progress claims are not allowed.
7. **Evidence attached** — an evidence block is attached to the result (commit SHA, file checksum, API response id, test output, screenshot, or state readback). A result claiming "done" without evidence is blocked from reaching Accepted.
8. **Accepted** — Gev clicks **Accept**; the message gets an "Accepted" badge, linked work objects update, and an event is recorded. **Reopened** — Gev clicks **Reopen** with a reason; the message returns to `Working`, the agent status reflects it, and the reason is logged.

---

## 4. Bro's five room modes as observable UI behaviors

Each mode is a visible, labeled behavior — never invisible.

- **Moderator.** Bro shows turn-taking and duplication notes ("@Mason and @Forge overlap — @Forge owns backend"). It quiets duplicate answers and posts a short "who is doing what" strip when several agents are active.
- **Router.** Bro posts a routing note on each unassigned question ("Routed to @Probe — testing scope") and moves the message to `Routed`. Misroutes can be corrected with **Reassign**.
- **Synthesizer.** After multiple agents respond, Bro posts a single **Synthesis** card combining outputs into one recommendation, citing which agent contributed what and flagging disagreements instead of averaging them away.
- **Recorder.** Bro posts summary cards, and converts confirmed statements into tasks, decisions, and unresolved-question entries — each with a back-link to the source message.
- **Guardian.** Bro blocks unauthorized or risky actions with a visible guardrail card ("This is an A3 action — dual confirmation required") and holds execution at `Waiting approval`. Emergency stop overrides all active approvals and shows a red stop banner.

---

## 5. Per-flow states

Every flow renders its real state honestly. No flow hides execution state, approval state, ownership, failure, or uncertainty.

### 5.1 Loading

- Skeleton rows for the timeline and member list; the header status chip shows `…`. Older history loads on scroll with a small inline spinner. The composer is usable immediately (messages queue as `Draft`).

### 5.2 Empty room

- A goal banner plus a prompt: "Invite members and set the room goal." Three suggested next actions (invite agent, set goal, ask Bro). No fake activity is shown.

### 5.3 Agent thinking / blocked

- **Thinking:** agent chip `Thinking`, an inline typing/step indicator; a stop control is available.
- **Blocked:** agent chip `Blocked` in a warning color, an inline card stating the blocking reason and the exact unblock requirement (missing input, missing permission, dependency). A **Provide** action lets Gev unblock inline.

### 5.4 Awaiting approval

- Agent chip `Waiting approval`. An inline **Approval gate** card shows: action, target, scope, expected effect, risk class, rollback path, approval level (A1–A3), and expiry. Buttons: **Approve**, **Reject**, **Request changes**. Execution stays paused. A2 needs explicit approval; A3 needs dual confirmation. Approval binds to that exact action only and expires on material change.

### 5.5 Failed

- The result message is labeled **Failed** in an error color with a precise reason and the failed step. Partial success is reported precisely (what succeeded, what did not). Actions: **Retry** (bounded, idempotency-aware), **Reassign**, **Open recovery**. Failure is never disguised as progress.

### 5.6 Offline

- Agent chip `Offline`; mentions to it queue and show "will deliver when online." Bro can propose an available substitute agent. If Bro itself is `Offline`, a banner states that routing and execution are paused; drafts are preserved locally.

---

## 6. Safety

A chat message never silently grants authority. Sending, mentioning, or agreeing in chat does not by itself authorize execution. Execution authority comes only from explicit project permissions, agent scope, approval policy, and the specific request — and A2/A3 actions always stop at an explicit, visible approval gate before running. Bro as **Guardian** enforces this; emergency stop overrides all active approvals.

---

# Հայերեն

Կարգավիճակ․ Draft canonical

Այս փաստաթուղթը սահմանում է, թե իրականում ինչ է տեսնում և անում օգտատերը։ Այն կոնկրետ է և քայլ առ քայլ։ Բոլոր status-երը, lifecycle-ները և approval level-ները նույնն են, ինչ [../AI_RUNTIME.md](../architecture/AI_RUNTIME.md)-ում, և ՉՊԵՏՔ Է շեղվեն։ Ագենտի status-երն են՝ `Offline, Idle, Observing, Thinking, Waiting approval, Working, Blocked, Review, Failed, Completed`։ Bro-ի ռեժիմներն են՝ `Answer, Plan, Execute, Review, Coordinate, Recovery`։ Approval level-երն են՝ `A0, A1, A2, A3`։ Հաղորդագրության lifecycle-ն է՝ `Draft → Sent → Routed → Acknowledged → Working → Result posted → Evidence attached → Accepted | Reopened`։

---

## 1. Direct Chat հոսք (Gev + Bro)

Direct Chat-ը Gev-ի և Bro-ի մեկ առ մեկ մակերեսն է։ Այն մտքից դեպի վերահսկվող աշխատանք ամենաարագ ուղին է՝ առանց խոսակցությունից դուրս գալու։

### 1.1 Բացում

1. Gev-ը ձախ նավիգացիայից բացում է **Chat**-ը կամ սեղմում է chat-ի գլոբալ կոճակը։
2. Կենտրոնական վահանակը ցույց է տալիս Direct Chat-ը Bro-ի հետ։ Առաջինը բեռնվում են վերջին հաղորդագրությունները, հին պատմությունը՝ վերև scroll անելիս։
3. Header-ը ցույց է տալիս `Bro` անունը՝ live status chip-ով (`Idle`, `Thinking`, `Working`, `Waiting approval`, `Offline`)։
4. Աջ context վահանակը ցույց է տալիս ընթացիկ context scope-ը, pin արված items-ը և այս chat-ից ստեղծված open work object-երը։
5. **Առաջին անգամ / դատարկ վիճակ․** եթե պատմություն չկա, կենտրոնը ցույց է տալիս հանգիստ empty state ("Հարցրու Bro-ին ցանկացած բան կամ նկարագրիր, թե ինչ ես ուզում"), երեք օրինակ prompt-ով և արդեն տեսանելի context scope-ով։

### 1.2 Context scope-ի ընտրություն

1. Composer-ի վերևում **Context scope** կառավարիչը ցույց է տալիս ճշգրիտ context-ը, որը Bro-ն կօգտագործի՝ նախքան որևէ բան ուղարկելը։ Ոչինչ թաքցված չէ։
2. Default scope-ն է՝ `Ընթացիկ խոսակցություն` գումարած `Օգտատիրոջ ինքնություն և նախընտրություններ` (ըստ Context engine-ի շերտերի)։
3. Gev-ը կարող է ավելացնել կամ հեռացնել scope chip-եր՝ ակտիվ նախագիծ, կոնկրետ task, ընտրված ֆայլեր, ընտրված գիտելիք, ընտրված հիշողություններ։
4. Յուրաքանչյուր chip ցույց է տալիս աղբյուրն ու թարմությունը։ Զգայուն chip-երն ունեն կողպեքի նշան և ներառվում են միայն բացահայտ ավելացնելիս և թույլատրված լինելիս։
5. Երբ scope-ում հակասություն կա (օրինակ երկու ֆայլ իրար հակասում են), Bro-ն ցույց է տալիս հակասությունը banner-ով, ոչ թե լուռ միաձուլում։
6. Ընտրված scope-ը գրանցվում է յուրաքանչյուր հաղորդագրության վրա, որպեսզի պատասխանը հետագայում աուդիտվի։

### 1.3 Ուղարկում

1. Gev-ը գրում է composer-ում։ Վիճակը՝ `Draft`։ Հանգիստ "context: N sources" ակնարկ արտացոլում է ընթացիկ scope-ը։
2. Composer-ի հասանելի գործողություններ՝ mention, ֆայլ կցել, command, task ստեղծել, decision ստեղծել, approval պահանջել։
3. Gev-ը ուղարկում է։ Հաղորդագրությունը դառնում է `Sent`, հայտնվում աջ կողմում՝ ժամանակով և scope snapshot-ով։
4. Bro-ի status chip-ը դառնում է `Thinking`, հայտնվում է typing indicator։ Սա մեկ առ մեկ context-ում `Routed → Acknowledged` անցումն է։

### 1.4 Bro-ի answer / plan / execute ռեժիմներ

Bro-ն միշտ անվանում է իր ռեժիմը, որպեսզի Gev-ը երբեք չկռահի։

- **Answer ռեժիմ։** Հարցերի և ցածր ռիսկի վերլուծության համար (A0)։ Bro-ն պատասխանում է inline՝ աղբյուրներով։ Կողմնակի ազդեցություն չկա։ Status-ը վերադառնում է `Idle`։
- **Plan ռեժիմ։** Ամեն ինչի համար, որ վիճակ կփոխի։ Bro-ն տեղադրում է structured plan card՝ objective, քայլեր, ներգրավվող ագենտներ, ռիսկ, ակնկալվող ազդեցություն և պահանջվող approval level։ Դեռ ոչինչ չի կատարվում։ Gev-ը կարող է խմբագրել, հաստատել կամ փոփոխություն խնդրել։
- **Execute ռեժիմ։** Կատարվում է միայն plan-ի approval պայմանը բավարարվելուց հետո։ Bro-ն ցույց է տալիս live execution card՝ command lifecycle-ով `received → understood → planned → approved_if_needed → executing → verified → completed | failed | cancelled`։ Status chip-ը՝ `Working`։
  - A0/A1 քայլերը կատարվում են ավտոմատ՝ իրենց policy envelope-ի ներսում։
  - A2/A3 քայլերը կանգ են առնում `Waiting approval`-ում և ցույց տալիս inline approval gate (տես §5.4)։ Կատարումը վերսկսվում է միայն բացահայտ approval-ից հետո։
- **Review / Coordinate / Recovery** հայտնվում են որպես անվանված card-եր, երբ Bro-ն ստուգում է արդյունքը, աշխատանք է բաժանում specialist-ներին կամ վերականգնվում ձախողումից։ Յուրաքանչյուրը բացահայտ անվանված է։

Ավարտը հայտարարվում է միայն կատարման ապացույցի և ստուգման առկայության դեպքում։ Bro-ն արդյունքին կցում է evidence (commit SHA, ֆայլի checksum, թեստի արդյունք, screenshot կամ վիճակի վերահաստատում)՝ նախքան «done» ասելը։

### 1.5 Հաղորդագրությունից work object ստեղծել

1. Gev-ը hover կամ long-press է անում ցանկացած հաղորդագրության վրա և բացում գործողությունների մենյուն։
2. Տարբերակներ՝ **Task ստեղծել**, **Decision ստեղծել**, **Approval պահանջել**, **Knowledge-ում պահել**, **Pin**։
3. **Task ստեղծել**՝ բացում է նախապես լրացված task drawer (վերնագիրը հաղորդագրությունից, owner, status `planned`, evidence link դեպի աղբյուր հաղորդագրություն)։ Պահելուց հետո task chip կցվում է հաղորդագրության տակ և հայտնվում աջ վահանակում ու Tasks-ում։
4. **Decision ստեղծել**՝ բացում է decision drawer `proposed` վիճակում, context-ը՝ thread-ից. այն անցնում է `proposed → under review → approved | rejected | deferred`։
5. **Approval պահանջել**՝ ստեղծում է approval object՝ կապված ճշգրիտ գործողությանը, target-ին, scope-ին, հետևանքներին և expiry-ին, ու ուղղորդում Approvals հերթ։
6. Յուրաքանչյուր ստեղծված object պահում է back-link դեպի սկզբնաղբյուր հաղորդագրություն, այնպես որ chat-ը մնում է provenance trail-ը։

---

## 2. Group Chat հոսքեր

Group Chat-ը առաջնակարգ աշխատանքային տարածք է, որտեղ մարդիկ և ագենտները մտածում են, աշխատանք ստեղծում, որոշում կայացնում, approval պահանջում և պահպանում համատեղ context։ Layout՝ ձախում՝ սենյակների ցանկ, կենտրոնում՝ հաղորդագրություններ և thread-եր, աջում՝ context վահանակ (անդամներ, ֆայլեր, task-եր, decision-ներ, approval-ներ, activity), ներքևում՝ composer։

### 2.1 Սենյակ ստեղծել

1. Gev-ը սեղմում է **New room** ձախ վահանակում։
2. Gev-ը ընտրում է **սենյակի տեսակ**․
   - **Direct** — Gev + Bro (անձնական մեկ առ մեկ)։
   - **Ad-hoc group** — ժամանակավոր multi-agent խոսակցություն մեկ հարցի կամ աշխատանքի փունջի համար։
   - **Team room** — մշտական ֆունկցիոնալ սենյակ (օրինակ Engineering, Security)։
   - **Project room** — ավտոմատ կապված ուղիղ մեկ նախագծի հետ. ժառանգում է այդ նախագծի scope-ը։
   - **Review room** — scope-ով architecture, design, security կամ release review։
3. Gev-ը սահմանում է **room goal**-ը և **operating instructions**-ը (դրանք սահմանում են, թե ինչ կարող են անել ագենտները սենյակում)։
4. Սենյակը ստեղծվում է՝ Bro-ն արդեն ներկա որպես coordinator։ Կարգավիճակ․ սենյակը բացվում է **empty state**-ում՝ goal banner-ով և անդամ հրավիրելու հուշումով։

### 2.2 Հրավիրել մարդկանց և ագենտներ

1. Gev-ը աջ վահանակում բացում է **Members** և սեղմում **Add**։
2. Gev-ը հրավիրում է մարդկանց (ապագա collaborator-ներ, project/room-scoped) և ագենտներ սկզբնական մասնագետների հավաքածուից (Lens, Lezu, Forge, Tensor, Reviz, Mason, Pixel, Grid, Probe, Ops, Vault, Flow, Archi, Sigma, Steward, Pocket, Shield, Sentry, Hawk, Relay, Compass, Strat, Closer)։
3. Յուրաքանչյուր ագենտի համար Gev-ը սահմանում է **response control**․ պատասխանել միայն mention-ի դեպքում, պատասխանել երբ domain-ը relevant է, դիտել լուռ, առաջարկել առանց կատարելու կամ կատարել միայն նախապես հաստատված scope-ում։
4. Յուրաքանչյուր անդամի տողը ցույց է տալիս role-ը և permission-ները։ Ագենտները ցույց են տալիս live status chip։ Անդամ հրավիրելը ստեղծում է activity event. անդամության մեջ ոչինչ թաքցված չէ։

### 2.3 Mention → route (Bro router)

1. Gev-ը composer-ում գրում է `@`. autocomplete-ը ցույց է տալիս անդամներ (մարդ և ագենտ) և routable object-եր (project, task, file, decision)։
2. Gev-ը կարող է mention անել կոնկրետ ագենտ (`@Forge`) կամ դիմել սենյակին ընդհանուր։
3. Ուղարկելիս Bro-ն հանդես է գալիս որպես **Router**․ եթե կոնկրետ ագենտ նշված չէ, Bro-ն հարցը հանձնարարում է լավագույն ագենտ(ներ)ին և տեղադրում կարճ routing note ("Routed to @Forge — engineering scope")։ Հաղորդագրությունը հասնում է `Routed`։
4. Դիմված ագենտը անցնում է `Offline/Idle → Observing → Thinking`, ապա տեղադրում acknowledgement՝ հասնելով `Acknowledged`-ի։
5. Bro-ն կանխում է կրկնությունը․ եթե երկու ագենտ նույն կետին կպատասխանեին, Bro-ն համակարգում է, որ միայն մեկը տիրանա և նշում է deduplication-ը։

### 2.4 Ագենտի live status

1. Յուրաքանչյուր ագենտ-անդամ ցույց է տալիս status chip, որն իրական ժամանակում արտացոլում է runtime status-ը՝ `Offline, Idle, Observing, Thinking, Waiting approval, Working, Blocked, Review, Failed, Completed`։
2. Երբ ագենտը `Working` է, նրա հաղորդագրության տակ հայտնվում է inline progress տող՝ ընթացիկ քայլով և stop կոճակով։
3. `Blocked`-ը ցույց է տալիս արգելափակման պատճառը և ինչ է պետք unblock անելու համար։ `Waiting approval`-ը ցույց է տալիս, թե որ approval-ին է սպասում՝ jump link-ով։
4. Status-ի փոփոխությունները նաև գրվում են room activity-ում, այնպես որ timeline-ը և live chip-ը երբեք չեն հակասում։

### 2.5 Հաղորդագրություն → task / decision / approval

1. Ցանկացած հաղորդագրություն կարելի է promote անել գործողությունների մենյուից՝ ճիշտ ինչպես Direct Chat-ում (§1.5), բայց scope-ով սենյակի ներսում։
2. **Message → task․** ստեղծում է task, որի owner-ը անդամ կամ ագենտ է. task chip-ը հայտնվում է հաղորդագրության տակ և սենյակի Tasks tab-ում։ Ագենտի task execution-ը հետևում է `assigned → accepted → running → blocked | completed | failed | cancelled`-ին։
3. **Message → decision․** բացում է decision `proposed` վիճակում։ Chat-ի համաձայնությունը canonical չէ, քանի դեռ այստեղ գրանցված չէ. լռությունը երբեք approval չէ. superseding decision-ը պետք է հղում անի նախորդին։
4. **Message → approval․** ստեղծում է approval object պահանջվող level-ով (A1–A3)՝ կապված ճշգրիտ գործողությանն ու target-ին, ուղղորդված սենյակի Approvals tab և գլոբալ Approvals հերթ։

### 2.6 Thread-եր / պատասխաններ

1. Gev-ը սեղմում է **Reply** հաղորդագրության վրա՝ բացելով thread աջ կողմի thread վահանակում. ծնող հաղորդագրությունը ցույց է տալիս reply count։
2. Thread-ի պատասխանները մնում են thread-ում և չեն ողողում գլխավոր timeline-ը. inline մնում է կոմպակտ "N replies" ամփոփումը։
3. Mention-ները, task/decision/approval ստեղծելը և pin-երն աշխատում են thread-ի ներսում նույն կանոններով։

### 2.7 Pin-եր

1. Ցանկացած հաղորդագրություն, ֆայլ, task կամ decision կարելի է **pin** անել գործողությունների մենյուից։
2. Pin-երը հայտնվում են սենյակի վերևի **Pinned** շերտում և աջ context վահանակում։
3. Pin-երը սենյակի արագ-հղման ճշմարտությունն են (goal, key decision, ընթացիկ blocker) և առաջնահերթ ներառվում են room context-ի հավաքման մեջ։

### 2.8 Room-scoped հիշողություն

1. Սենյակն ունի իր **հիշողությունը** (conversation և project memory դասեր)՝ առանձին գլոբալ հիշողությունից։
2. Երբ Bro-ն կամ Gev-ը հայտարարությունը նշում է որպես room memory, այն անցնում է `candidate → classify → deduplicate → verify source → approve policy → persist → index`. յուրաքանչյուր գրառում պահում է source, scope, timestamp, confidence և owner։
3. Room memory-ն inspectable է աջ վահանակում. Gev-ը կարող է ուղղել, supersede, expire կամ ջնջել ցանկացած գրառում։ Թաքնված գրառումներ չկան — համակարգը միշտ ցույց է տալիս, թե ինչու է հիշողությունն օգտագործվել և որտեղից է եկել։
4. Retrieval-ը հարգում է room և permission սահմանները. մի սենյակի հիշողությունը լուռ չի քաշվում մյուսը։

### 2.9 Ավտոմատ ամփոփումներ

1. Bro-ն պարբերաբար տեղադրում է **room summary** card (ըստ պահանջի, կարևոր milestone-ների ժամանակ և cadence-ով)՝ որպես **Recorder**։
2. Ամփոփումը թվարկում է՝ կայացված decision-ներ, ստեղծված task-եր և դրանց status, բաց approval-ներ, չլուծված հարցեր և key evidence link-եր։
3. Ամփոփումը card է, ոչ լուռ վերագրում. նախորդ ամփոփումները մնում են պատմության մեջ։ Gev-ը կարող է pin անել վերջին ամփոփումը։

---

## 3. Հաղորդագրության lifecycle-ը որպես կոնկրետ UI քայլեր

Lifecycle-ն է՝ `Draft → Sent → Routed → Acknowledged → Working → Result posted → Evidence attached → Accepted | Reopened`։ Ինչ է տեսնում օգտատերը յուրաքանչյուր քայլում․

1. **Draft** — տեքստը composer-ում է. "context: N sources" ակնարկը ցույց է տալիս կցվող scope-ը։ Ոչինչ չի փոխանցվում։
2. **Sent** — հաղորդագրությունը հայտնվում է timeline-ում, աջ կողմում, ժամանակով և փոքր scope snapshot-ով։ Մեկ check mark նշանակում է delivered։
3. **Routed** — Bro-ից հայտնվում է նուրբ routing note ("Routed to @Forge")։ Direct Chat-ում սա Bro-ի status-ի `Thinking`-ի անցումն է։ Հաղորդագրությունը ցույց է տալիս "routed" նշան։
4. **Acknowledged** — target ագենտը տեղադրում է կարճ "On it" acknowledgement, և իր status chip-ը `Thinking` կամ `Working` է։ Մարդ անդամների համար հայտնվում է read receipt։
5. **Working** — inline progress տողը ցույց է տալիս ընթացիկ քայլը, անցած ժամանակը և stop կոճակ. ագենտ chip-ը `Working` է։ Երկար քայլերը stream են անում մասնակի update-ներ, երբեք միայն սառած spinner։
6. **Result posted** — ագենտը տեղադրում է իր արդյունքի հաղորդագրությունը։ Արդյունքը հստակ պիտակավորված է որպես մեկը՝ completed, partially completed, blocked, failed կամ not started։ Անորոշ progress պնդումներ չեն թույլատրվում։
7. **Evidence attached** — արդյունքին կցվում է evidence block (commit SHA, ֆայլի checksum, API response id, թեստի արդյունք, screenshot կամ վիճակի վերահաստատում)։ «Done» պնդող, բայց առանց evidence արդյունքը արգելափակվում է Accepted հասնելուց։
8. **Accepted** — Gev-ը սեղմում է **Accept**. հաղորդագրությունը ստանում է "Accepted" badge, կապակցված work object-երը թարմանում են, և event գրանցվում է։ **Reopened** — Gev-ը սեղմում է **Reopen**՝ պատճառով. հաղորդագրությունը վերադառնում է `Working`, ագենտի status-ը դա արտացոլում է, և պատճառը գրանցվում է։

---

## 4. Bro-ի հինգ room ռեժիմները՝ որպես դիտելի UI վարք

Յուրաքանչյուր ռեժիմ տեսանելի, պիտակավորված վարք է — երբեք անտեսանելի։

- **Moderator.** Bro-ն ցույց է տալիս հերթականությունն ու կրկնության նշումները ("@Mason և @Forge համընկնում են — @Forge-ը տիրում է backend-ին")։ Այն հանգստացնում է կրկնվող պատասխանները և տեղադրում կարճ "ով ինչ է անում" շերտ, երբ մի քանի ագենտ ակտիվ են։
- **Router.** Bro-ն յուրաքանչյուր չհանձնարարված հարցի վրա տեղադրում է routing note ("Routed to @Probe — testing scope") և հաղորդագրությունը տանում `Routed`։ Սխալ route-ը կարելի է ուղղել **Reassign**-ով։
- **Synthesizer.** Մի քանի ագենտ պատասխանելուց հետո Bro-ն տեղադրում է մեկ **Synthesis** card՝ միավորելով output-ները մեկ առաջարկի, նշելով թե որ ագենտն ինչ ներդրեց և ընդգծելով անհամաձայնությունները՝ չմիջինացնելով դրանք։
- **Recorder.** Bro-ն տեղադրում է summary card-եր և հաստատված հայտարարությունները վերածում task-երի, decision-ների և չլուծված հարցերի գրառումների — յուրաքանչյուրը՝ back-link-ով դեպի աղբյուր հաղորդագրություն։
- **Guardian.** Bro-ն արգելափակում է չլիազորված կամ ռիսկային գործողությունները տեսանելի guardrail card-ով ("Սա A3 գործողություն է — պահանջվում է dual confirmation") և պահում կատարումը `Waiting approval`-ում։ Emergency stop-ը գերակայում է բոլոր ակտիվ approval-ներին և ցույց է տալիս կարմիր stop banner։

---

## 5. Ըստ հոսքի վիճակներ

Յուրաքանչյուր հոսք ազնվորեն ցույց է տալիս իր իրական վիճակը։ Ոչ մի հոսք չի թաքցնում կատարման վիճակը, approval վիճակը, պատասխանատուին, ձախողումը կամ անորոշությունը։

### 5.1 Loading

- Skeleton տողեր timeline-ի և անդամների ցանկի համար. header status chip-ը ցույց է տալիս `…`։ Հին պատմությունը բեռնվում է scroll-ի ժամանակ փոքր inline spinner-ով։ Composer-ը անմիջապես օգտագործելի է (հաղորդագրությունները հերթ են կանգնում որպես `Draft`)։

### 5.2 Empty room

- Goal banner գումարած հուշում․ "Հրավիրիր անդամներ և սահմանիր room goal-ը"։ Երեք առաջարկվող հաջորդ գործողություն (ագենտ հրավիրել, goal սահմանել, Bro-ին հարցնել)։ Կեղծ activity չի ցուցադրվում։

### 5.3 Ագենտը thinking / blocked

- **Thinking․** ագենտ chip `Thinking`, inline typing/step indicator. հասանելի է stop կոճակ։
- **Blocked․** ագենտ chip `Blocked` warning գույնով, inline card՝ արգելափակման պատճառով և unblock-ի ճշգրիտ պահանջով (բացակայող input, բացակայող permission, dependency)։ **Provide** գործողությունը թույլ է տալիս Gev-ին inline unblock անել։

### 5.4 Approval-ի սպասում

- Ագենտ chip `Waiting approval`։ Inline **Approval gate** card-ը ցույց է տալիս՝ գործողություն, target, scope, ակնկալվող ազդեցություն, ռիսկի class, rollback path, approval level (A1–A3) և expiry։ Կոճակներ՝ **Approve**, **Reject**, **Request changes**։ Կատարումը մնում է դադարեցված։ A2-ը պահանջում է բացահայտ approval. A3-ը՝ dual confirmation։ Approval-ը կապվում է միայն այդ ճշգրիտ գործողությանը և expire է լինում material change-ի դեպքում։

### 5.5 Failed

- Արդյունքի հաղորդագրությունը պիտակավորված է **Failed** error գույնով՝ ճշգրիտ պատճառով և ձախողված քայլով։ Մասնակի հաջողությունը ներկայացվում է ճշգրիտ (ինչը հաջողվեց, ինչը՝ ոչ)։ Գործողություններ՝ **Retry** (սահմանափակ, idempotency-aware), **Reassign**, **Open recovery**։ Ձախողումը երբեք չի քողարկվում որպես progress։

### 5.6 Offline

- Ագենտ chip `Offline`. նրան ուղղված mention-ները հերթ են կանգնում և ցույց տալիս "will deliver when online"։ Bro-ն կարող է առաջարկել հասանելի փոխարինող ագենտ։ Եթե Bro-ն ինքն է `Offline`, banner-ը նշում է, որ routing-ը և execution-ը դադարեցված են. draft-երը պահվում են տեղական։

---

## 6. Անվտանգություն

Chat հաղորդագրությունը երբեք լուռ լիազորություն չի տալիս։ Chat-ում ուղարկելը, mention անելը կամ համաձայնվելը ինքնին չի թույլատրում կատարում։ Կատարման լիազորությունը գալիս է միայն բացահայտ project permission-ներից, agent scope-ից, approval policy-ից և կոնկրետ հարցումից — և A2/A3 գործողությունները միշտ կանգ են առնում բացահայտ, տեսանելի approval gate-ի մոտ՝ նախքան կատարվելը։ Bro-ն որպես **Guardian** կիրառում է սա. emergency stop-ը գերակայում է բոլոր ակտիվ approval-ներին։
