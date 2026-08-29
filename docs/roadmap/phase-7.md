## Phase 7 — Group Chat · Խմբային Զրույց

**Objective.** Ship the collaboration hall (`group`) — a shared room where the owner and multiple agents
converse, hand off work, and reach consensus, with every agent turn governed and every action visible.

**Scope.** In: the `group` page (multi-participant room, handoffs, consensus, session log). Out:
non-Bro external chat integrations (Phase 9).

**Architecture.** A room is a conversation with multiple governed participants; each agent message is a
governed turn (verified receipt) and human messages are direct. The engine governs every agent action in
the room; the desktop renders the shared timeline, mentions, handoffs, and a consensus/□ readout.

**UI/UX work.** Full §D spec for `group`:
- **`group` ⧉ Համագործակցության Սրահ.** Components: room header (`grpTitle`/`grpSub`/`grpElapsed`/

**Backend work.** Room store + multi-participant turn orchestration through the bridge (each agent turn a
governed task); handoff + consensus computation; mention resolution.

**Contracts / schemas.** Each agent turn = `bridge.task-request`/`result`. A lightweight desktop **room**
+ **handoff** shape (product state); no new cross-boundary contract.

**Data models.** Desktop: `room`(participants), `room_message`(author, receipt_id, verified, kind),
`handoff`(from, to, task), `consensus`(snapshot). Engine holds each turn's receipt/evidence.

**Dependencies.** Phase 6 (multi-agent dispatch + per-agent governance).

**Security gates.** Every agent message is a verified governed turn (no verified receipt ⇒ no agent
message body). Human messages are direct but logged. A denied agent turn renders `blocked` inline.

**Tests.** Multi-participant room round-trip (mock supervisor OK, documented); per-agent verified receipt
in-room; handoff + consensus computation; `blocked` inline on denied turn.

**CI requirements.** Cockpit legs green; room path exercises the bridge leg per agent participant.

**Documentation updates.** `docs/ARCHITECTURE.md` (group governance model), this phase's spec,
`PROJECT_STATE.md`.

**Acceptance criteria.** Owner runs a multi-agent room where each agent turn is **verified**, handoffs
and consensus render, and denied turns show `blocked` inline. `group` meets full §D.

**Merge gate.** Per-agent in-room verified-receipt proven; Architect confirms room governance; Owner
approval.

**Stop conditions.** If a room turn is shown without a verified receipt → stop (invariant break). If
consensus/handoff needs engine changes → audited task.

> **⚖ Phase 7 was CHECKED AGAINST THE CODE before anything was built (2026-08-16).** The room,
> the governed per-agent turns, the handoff trail, mention resolution and a full consensus module
> (rules, tally, verdict, dissent) all existed. One §D component did not: the **room readout** —
> *participants / handoffs / messages* and `grpElapsed`.
>
> Building it surfaced the question worth the work: **what does a count mean when the page cannot
> see the thing it counts?** The delegation trail arrives on the LIVE event channel while a turn
> runs and is not reconstructable from stored messages. So a room the owner has merely opened must
> not report `0 handoffs` — that states *"no handoffs happened"* while meaning *"I cannot see
> handoffs"*. It reads `—`, and a message count of zero from a read that succeeded reads `0`,
> because that one **is** established. Both directions have a test.

**Definition of Done.**
- [x] `group` page to full §D incl. inline `blocked`. — the room is `<Conversations kind="group">` (thread `role=log aria-live=polite`, mentions, `↑` edit, per-agent receipt badges) plus the consensus deck; a blocked agent turn renders inline with the engine's reason and **no** persisted message. The room readout was the missing component and is built.
- [x] Each agent turn governed + verified in-room. — the same `receiptBadge` vocabulary as direct chat, which **fails closed on anything it does not recognise** — never a promotion to green.
- [x] Handoff + consensus render; mentions resolve. — `consensus.ts` computes the verdict from recorded positions under a stated rule, and **renders dissent for every outcome, `reached` included**: an outcome shown without the disagreement behind it is the defect that deck exists to prevent. Silence is counted as its own stance rather than folded into abstention.
- [x] Docs + `PROJECT_STATE.md` synced.

**Task checklist.**
- [x] Room store + multi-participant turn orchestration through the bridge.
- [x] `group` page (thread, participants, loom/handoff, consensus, badges) per §D. — including the readout added here, as a labelled `<dl>` so a screen reader never meets a bare number.
- [x] Handoff + consensus computation; mention resolution.
- [x] Tests: in-room verified receipts, handoff/consensus, inline `blocked`. — `GroupChat.render` · `GroupChat.delegation` · `Conversations.handoff` · and seven new readout cases, four of which exist only to keep *not established* and *measured zero* apart.

---
