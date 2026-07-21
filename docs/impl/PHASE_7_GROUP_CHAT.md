# Phase 7 — Group Chat · Implementation Spec

> ⚠️ **PROPOSAL — NOT EXECUTION AUTHORITY.** This spec is a *proposal* for review, not canonical.
> It does NOT authorize execution. Its architecture / trust / contract decisions are **§I controlled
> changes** requiring Architect audit + Owner approval before any build, and are **superseded where they
> conflict with the Challenger-Deep audit** (round 1) — esp. the receipt/sidecar/provider findings.


> Blueprint for a next session. Grounds `MASTER_EXECUTION_ROADMAP.md` §"Phase 7" in the real code.
> Ships the collaboration hall (`group`) — a shared room where the owner and multiple agents
> converse, hand off work, and reach consensus, **with every agent turn a governed, verified turn.**
> **Depends on Phase 6** (multi-agent dispatch + per-agent governance), per roadmap §E. Read
> `PHASE_6_MULTI_AGENT.md` first — this phase reuses its bridge fan-out and per-agent receipt model.

---

## 1. Objective & current state

**Roadmap intent.** A room = a conversation with multiple governed participants. Each **agent**
message is a governed turn carrying a verified receipt; **human** messages are direct but logged.
The engine governs every agent action in the room; the desktop renders the shared timeline, mentions,
handoffs, and a consensus readout. A denied agent turn renders `blocked` **inline** — no result.

**What exists today (prototype / mock):**

| Surface | File | Today |
|---|---|---|
| `group` page | `apps/desktop/src/features/GroupChat.tsx` | 6 lines: `return <Conversations kind="group" />` — a thin reuse of the direct-chat component. |
| Conversation store | `services/desktop.ts` | `listConversations('group')`, `createConversation`, `postMessage`, `streamReply` → all **ungoverned** `ai.rs` provider. |
| Message model | `domain/entities.ts:104` | `Message{id, conversationId, role:'user'\|'agent', author, body, receipt?: 'verified'\|'blocked'\|null}`. **The receipt badge vocabulary already exists** but is never populated. |

**The gap.** `group` today is a single-agent chat wearing a group label: one reply stream, no
multi-participant orchestration, no per-turn governance, no handoff/consensus, no verified receipts.
Phase 7 makes each agent turn a governed bridge turn and adds the room mechanics — building directly
on Phase 6's fan-out (`run_governed_turn` per agent, one lease into one builder per turn).

---

## 2. Phase 7 specifics — the collaboration hall

### Each agent turn is one governed, verified turn

Reuse the Phase-1/6 primitive exactly. When it is agent *A*'s turn in room *R*:

1. The desktop builds a `bridge.task-request` (`task_class: standard-builder`, rationale = the room
   prompt + `@`-mention context; **no lease/key/env**) and sends it via the sidecar
   (`engine_sidecar.py` → `run_governed_turn` in `engine_adapter.py`).
2. The supervisor (`bro_supervisor.run_task`) issues a **single-use lease into a separate builder**,
   runs it behind the wall, returns a `SupervisorResult`.
3. `run_governed_turn` sets `verified=true` **only** after the injected verifier confirms signed
   evidence; **no verified receipt ⇒ no agent message body** (the room's hardest invariant).
4. The desktop appends a `room_message` with `receipt: 'verified'`, or renders `blocked` **inline** in
   the thread (never a modal, never a dead end) carrying the wall's verdict reason.

A multi-agent room is Phase 6's pack model applied conversationally: N sequential governed turns, each
its own lease, the desktop holding nothing. Where several agents respond to one prompt, reuse Phase 6's
`dispatch_pack` fan-out (one member per responding agent); where they take ordered turns, issue them
one governed turn at a time.

### Handoffs & consensus

- **Handoff** = agent *A* passes the active task to agent *B* (`@B` in a turn, or an explicit handoff
  action). Recorded as `handoff(from, to, task, at)`; the loom/handoff view (`grpLoom`) renders the
  chain. A handoff is product state (bridge-only), **not** a new cross-boundary contract.
- **Consensus** = a desktop-computed snapshot over the room (participants / handoffs / messages /
  consensus %). Pure product computation from `room_message`s; the meter has a text value for a11y.
  It **does not** gate governance — it is a readout, not an authority.

### Inline blocked state (mandatory, unique to a governed cockpit)

A denied/verify-failed agent turn renders as a `blocked` message bubble in `grpLog`: the author, the
governance verdict reason (from `bridge.result.error`), and the lawful next step ("request approval" →
Phase 2 `approvals`). Human turns never block. Because real-mode receipt verification is the
Architect-pending seam (`engine_sidecar._real_callables` fails closed), a real agent turn shows
`blocked` until that seam lands — this is expected, and the `--self-test` path proves the `verified`
timeline in CI.

---

## 3. Data models / contracts

**No new cross-boundary contract.** Each agent turn = the existing `bridge.task-request` /
`bridge.result` (and Phase 6's `task-force-request` when several agents answer at once). Room, handoff,
and consensus are desktop **product** shapes.

**Desktop product tables (SQLite):**

- `room(id, title, participants[], created_at)` — participants are `{agent_id | 'owner', role}`.
- `room_message(id, room_id, author, kind:'human'|'agent'|'handoff'|'system', body, receipt_id?,
  verified, created_at)` — `kind='agent'` requires `verified=true` to carry a body.
- `handoff(id, room_id, from_participant, to_participant, task, at)`.
- `consensus(room_id, participants, handoffs, messages, consensus_pct, snapshot_at)` — recomputed
  client-side; not persisted authority.

Engine holds each agent turn's receipt/evidence. Extend `domain/entities.ts` with `Room`,
`RoomMessage`, `Handoff`, `Consensus`; reuse `Message.receipt`'s `'verified'|'blocked'|null` union as
`RoomMessage.receipt`.

---

## 4. UI wiring & states — `group` ⧉ Համագործակցության Սրահ (full §D)

| Facet | Spec |
|---|---|
| **Components** | Room header (`grpTitle`/`grpSub`/`grpElapsed`/`grpPill`), shared thread (`grpLog`), participants (`grpSess`), loom/handoff (`grpLoom`), composer with `@`-mentions, per-agent verified-receipt badges, consensus readout. |
| **Layout** | Thread center; participants + loom in a right rail (Phase-4 `grp-rail`); collapses to single column <1024. |
| **States** | `default` (active room), `loading` (joining — skeleton, not spinner), `empty` (new-room hint HY + "invite agents" CTA), `error` (participant/turn failed), **`blocked`** (agent turn denied → inline bubble, no result). |
| **Motion** | message `emit`/`stream`, handoff `--enter`, consensus meter `--slow`; honors `prefers-reduced-motion`. |
| **Keyboard** | `Enter` send, `@` mention participant, `↑` edit last, `Esc` leave, arrow-navigate log. |
| **A11y** | thread `role=log aria-live=polite`; each message names its author **and** governance state; consensus meter has a text value; receipt id as `aria-label`. |
| **Data** | desktop `room` store + bridge governed turn per agent participant (Phase 6 fan-out). |

`GroupChat.tsx` stops delegating to `Conversations` and becomes a real room component (or `Conversations`
gains a governed multi-participant mode — prefer a dedicated `Room` component to keep direct chat simple).

---

## 5. Exact files to touch

**Frontend (`apps/desktop/src`):**
- `features/GroupChat.tsx` — replace the `Conversations` passthrough with the room UI (thread,
  participants, loom, composer, consensus, per-turn badges, inline blocked).
- `services/desktop.ts` — `listRooms`, `createRoom`, `listRoomMessages`, `postHumanMessage`,
  `runAgentTurn(roomId, agentId, onEvent)` (governed, via the Phase-6 sidecar path), `listHandoffs`.
- `domain/entities.ts` — `Room`, `RoomMessage`, `Handoff`, `Consensus`.
- `app/nav.ts` — `groupChat` route already registered (icon 👥); no change.

**Backend (`apps/desktop/src-tauri`):** room/handoff tables + read/write commands in `core/`; the
`run_agent_turn` command reusing Phase 6's `dispatch_pack`/sidecar spawn (one governed member per
agent turn). Consensus computed client-side; no backend authority.

**Bridge (`bridge/`):** none new — reuse `task-request`/`bridge-result` and Phase 6's
`task-force-request`. **No `engine/` edit.**

---

## 6. Tests & acceptance

- **Frontend:** multi-participant room round-trip (mock/`--self-test` supervisor OK, documented);
  an agent message renders **only** with `receipt:'verified'`; a denied turn renders `blocked` inline
  and shows no body; handoff chain + consensus % compute correctly; `@`-mention resolves to a
  participant; a11y (jest-axe) on `grpLog` `role=log`.
- **Invariant test (merge gate):** a `room_message` of `kind='agent'` with `verified=false` (or no
  receipt) is never rendered with a body — assert at the store boundary, mirroring
  `desktop.ts`'s `normalizeMessage` role-coercion pattern.
- **Bridge leg:** each agent participant exercises the bridge path in CI (`--self-test` for the
  verified timeline; real mode asserted fail-closed → inline `blocked`).
- **Acceptance (roadmap DoD):** owner runs a multi-agent room where each agent turn is **verified**,
  handoffs and consensus render, mentions resolve, and denied turns show `blocked` inline. `group`
  meets full §D.

---

## 7. Security notes (📐 Audit: "in-room governance / per-turn verified" — roadmap §G Phase 7)

- **Per-turn verified-receipt-mandatory.** No verified receipt ⇒ no agent message body. This is the
  room's core invariant; the store-boundary test enforces it. Reuses `run_governed_turn` unchanged.
- **Desktop holds nothing.** Every agent turn is a `task-request` (no lease/key/env); the lease is
  issued into the builder only (`bro_supervisor`), and the desktop stores only `receipt_id`+`verified`.
- **Human turns are direct but logged** — never governed, never able to forge an agent/receipt badge
  (`role`/`kind` coerced at the IPC boundary, as `desktop.ts` already does for message roles).
- **Consensus is a readout, not an authority** — it never overrides a governance verdict or unblocks a
  turn.
- **Inline blocked, never bypass.** A denied turn shows the verdict + "request approval"; it must never
  fall back to the ungoverned `streamReply` path to "get an answer anyway."
- **No engine change.** Handoff/consensus are product state. If either is ever tempted to need an engine
  change (e.g. a shared multi-agent lease), that is a **🛑 Architect-audited engine task** (roadmap §E
  serialization + §I) — **stop** and raise a controlled-change proposal; do not edit `engine/`.

---

## 8. Dependencies

- **Phase 6** (multi-agent) — the fan-out, per-agent receipts, and `agent_view` model this phase
  drives conversationally. **Hard dependency** (roadmap §E: P6 → P7).
- Transitively Phase 4 (room/rail UI primitives) + Phase 5 (memory the participants recall) + Phase 1
  (operator-provisioned governed sidecar).
- **Feeds Phase 9** (integrations use the room as an output surface).
