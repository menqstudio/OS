## Phase 5 — Memory & Knowledge · Հիշողություն և Գիտելիք

**Objective.** Give Bro durable memory and a knowledge substrate the owner can see and curate: `memory`
(what Bro remembers), `knowledge` (curated facts/docs), `research` (governed information-gathering runs),
and `files` (the document plane) — all local-first and, where they trigger AI work, governed.

**Scope.** In: the four pages, their desktop stores, retrieval (search/recall) surfaced in `chat`'s
context rail, and governed research runs that produce receipts. Out: multi-agent memory sharing (that is
Phase 6) and external knowledge integrations (Phase 9).

**Architecture.** Desktop SQLite is the product store for memory/knowledge/files; retrieval feeds the
`chat` context rail (`ctxRecalls`/`crCount`). A **research run** is a governed task through the bridge
(Phase 1) — it produces a verified receipt like any AI turn. Files are local; content that crosses the
wall (e.g. a file handed to a governed turn) obeys the engine's scope rules.

**UI/UX work.** Full §D specs for four pages:
- **`memory` ❖ Հիշողություն.** Components: memory list (typed: user/feedback/project/reference), detail,
- **`knowledge` ⁂ Գիտելիք.** Components: knowledge base (collections, articles), editor, citation view,
- **`research` ⌖ Հետազոտում.** Components: research query, run status (governed — with **verified-receipt
- **`files` ▤ Ֆայլեր.** Components: file index (`frows`/`fCount`), query (`fQuery`/`fHits`/`fChips`),

**Backend work.** Desktop stores + CRUD IPC for memory/knowledge/files; retrieval/search; wiring
`research` runs through the Phase-1 bridge; feeding recalls into `chat`'s context rail.

**Contracts / schemas.** No new cross-boundary contract for storage (local). A **research run** uses the
existing `bridge.task-request`/`bridge.result` (research is a governed task class). If file content
crosses the wall, it travels inside a governed task's declared `protected_scope` (exact paths only).

**Data models.** Desktop: `memory`(type, body, links, confidence), `knowledge_collection`,
`knowledge_article`(citations), `research_run`(query, receipt_id, verified, sources[]), `file`(path,
guard, index). Engine ledger holds the research receipt/evidence.

**Dependencies.** Phase 3 (shell + governed chat + context rail). Parallel with Phase 4 (§E).

**Security gates.** Research runs are governed (verified-receipt-mandatory). Sealed files cannot be opened
or handed to a turn; the `blocked` state shows the engine guard reason. No file content leaves the machine
except inside a governed task's declared scope. Local-first: memory/knowledge stay on-device.

**Tests.** Store CRUD + search tests; a governed-research test (receipt required, fail-closed on
verifier-negative); a files guard test (sealed → blocked, no open); recall-into-chat wiring test.

**CI requirements.** Cockpit legs green with new stores/pages; the governed-research path exercises the
bridge leg (mock supervisor acceptable, documented).

**Documentation updates.** `docs/ARCHITECTURE.md` (memory/knowledge/files + retrieval), this phase's
specs, `PROJECT_STATE.md`.

**Acceptance criteria.** Owner can create/curate memory + knowledge, run a **governed** research that
yields a verified result and saves to knowledge, browse files with guard states honored, and see recalls
in `chat`. All four pages meet §D incl. `blocked`.

**Merge gate.** Governed research proven verified + fail-closed; files guard proven; local-first upheld;
Architect + Owner approval.

**Stop conditions.** If research is tempted to bypass the governed path for speed → stop. If a file guard
can be circumvented from the desktop → stop, it is a wall issue → audited engine task.

> **⚖ Phase 5 was CHECKED AGAINST THE CODE before anything was built (2026-08-16).** All four
> pages existed, three of them substantially finished. The check found **one page missing its
> entire reason for being, and one security behaviour that had never been tested**:
>
> 1. **`research` had no governed run at all.** It was a local CRUD list — `list_research` /
>    `create_research_item` / `delete_research_item` — with no receipt, no verified badge and no
>    `blocked` state, in the one page of this phase whose whole point is that it **crosses the
>    wall**. §D asks for *"run status (governed — with verified-receipt badge)"* and a
>    `blocked`(governed provider off / sidecar down → no result); the page had never gone near
>    the bridge.
> 2. **The files guard was implemented and untested.** `Files.tsx` renders `open`/`read`/`sealed`
>    honestly, and `Files.test.tsx` covered the listing mirror and *"no `read_file` while
>    browsing"* — both worth having, neither touching the guard. This phase's merge gate says
>    **files guard proven**, and nothing proved it. A guard nobody tests is a guard that has
>    never been shown to hold.
>
> Both closed. The rest was verified rather than rebuilt.

**Definition of Done.**
- [x] `memory`, `knowledge`, `research`, `files` pages to full §D incl. `blocked`. — `Memory.tsx` 815 · `Knowledge.tsx` 798 · `Research.tsx` 507 · `Files.tsx` 635, each with the real state set (`Skeleton`/`EmptyState`/`ErrorState`, `aria-live`) against the real IPC and no fixture layer. `research`'s `blocked` was **added this phase** and is the state the shipped app will actually be in.
- [x] Governed research produces verified receipts; results save to knowledge. — the run goes through **`stream_ask`**, the same governed path `chat` uses: buffered, verified desktop-side, and the answer **held server-side under a one-time id** rather than streamed into the window. Deltas are ignored deliberately — a governed ask is buffered by construction, and painting partial text would show what the verify step may still refuse. Saving is the new Rust command **`save_ask_to_knowledge`**, which takes the id and a title and **never a body**: composing it in the renderer would hand the window exactly the authority the held-answer design withholds (P1-6). A test asserts no call from the window carries the text.
- [x] Files honor engine guard states (open/read/sealed); no unlawful open. — **proven now, not asserted**: a refused open renders the guard reason verbatim in an `aria-live="assertive"` alert, leaves **no editable surface** behind (no textarea, no save), and an ordinary I/O failure is **not** dressed as a refusal — telling the owner the system is protecting them when it is merely broken is the fail-open direction here. `isGuardDenied` is tested in both directions, with a positive control so the suite cannot pass against a build that refuses everything.
- [x] Recall surfaced in `chat` context rail. — `Conversations.tsx` feeds `searchAll` results into the context rail (`ctx-rail`), covered by `Conversations.recall.test.tsx`.
- [x] Docs + `PROJECT_STATE.md` synced. — this note, the status board, `CLAUDE.md` (both languages) and the state anchor, in the same commit per the Continuous-Documentation Law.

**Task checklist.**
- [x] Desktop memory store + `memory` page (typed, linked, confidence) per §D. — `role=list`, `blocked`, and a write-record trail; three test files including `Memory.honesty.test.tsx`.
- [x] Knowledge store + `knowledge` page (collections/articles/citations) per §D. — `role=article`, `empty` vs filtered-empty, four test files.
- [x] `research` page wired to governed bridge run + verified badge, all §D states. — see DoD row 2; six new tests in `Research.governed.test.tsx`.
- [x] `files` page with guard states + preview/query per §D. — see DoD row 3; `role=grid`, guard state in the accessible name.
- [x] Retrieval/recall into `chat` context rail; search across stores. — `search_all` in Rust, `searchAll` in the service, consumed by the rail.
- [x] Tests: CRUD/search, governed research fail-closed, files guard. — the two that were missing are the two this phase added: **governed research fail-closed** (a refusal renders as a refusal, offers no save, and a failure is not dressed as one) and the **files guard** (six cases).

---
