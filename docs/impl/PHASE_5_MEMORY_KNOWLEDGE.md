# Phase 5 — Memory & Knowledge · Implementation Spec

> Execution blueprint for `MASTER_EXECUTION_ROADMAP.md` §"Phase 5 — Memory & Knowledge"
> (roadmap lines 808–891). Grounded in the code on `main`. Read with `docs/DESIGN_SYSTEM.md`
> (component/state rules) and `bridge/DESIGN.md` (governed transport) before starting. This is a
> build plan, not a §I change to the plan — it adds surfaces and local stores but never weakens
> the verified-receipt invariant.

## 1. Objective & current state

**Roadmap intent.** Give Bro durable, inspectable **memory** and a **knowledge** substrate, a
**files** plane with guard states, and **governed research runs** that produce verified receipts —
all local-first; retrieval (recall) surfaced in `chat`'s context rail. Ship four pages to full §D.

**What already exists (do NOT rebuild):**

- `memory` — `features/Memory.tsx` (real): lists/creates/pins/deletes `MemoryEntry` via
  `desktop.listMemory/createMemory/setMemoryPinned/deleteMemory` (`desktop.ts:102-106`). Store:
  `memory_entries` table (`schema/0004_knowledge_memory.sql:15-23`); kinds
  `fact|preference|note|reference` (`enums.ts:21-22`). FTS-indexed (`0010_search_fts.sql:104-113`).
- `knowledge` — `features/Knowledge.tsx` (real): collections-less notes with search, tags,
  source, delete; `desktop.listKnowledge/searchKnowledge/createKnowledge/deleteKnowledge`
  (`desktop.ts:96-99`). Store: `knowledge_notes` (`0004:5-13`), FTS-indexed (`0010:57-66`).
- `files` — `features/Files.tsx` (real): filesystem browser + text viewer/editor via
  `desktop.listDir/readFile/writeFile` (`desktop.ts:109-111`); `DirListing`/`FileContent`/
  `DirEntry` shapes (`entities.ts:253-273`); overwrite gated by `ConfirmDialog`. Backed by
  `src-tauri/src/files.rs`. **No guard/seal concept yet.**
- The **governed transport** the research run needs is built: `bridge/engine_adapter.py`
  (`run_governed_turn`, fail-closed + verified-receipt-mandatory, lines 53-135), the contracts
  `bridge/contracts/task-request.schema.json` + `bridge-result.schema.json`, the sidecar
  `bridge/engine_sidecar.py`, and the desktop provider `Provider::GovernedEngine` in
  `src-tauri/src/ai.rs:264, 312-324, 1039-1140+` (opt-in, default OFF; gated by
  `BROPS_AI_PROVIDER=governed-engine` **and** `BROPS_ALLOW_GOVERNED_ENGINE=1`). Its
  `interpret_bridge_result` (`ai.rs:1069-1090`) re-checks `ok && receipt.verified` on the desktop.
- Chat + context wiring: `features/Conversations.tsx` (thread, `@mention`, streaming, per-turn
  receipt badge `Conversations.tsx:182-186` reading `Message.receipt`). `Message.receipt` is a
  **frontend-only** field today (`entities.ts:104-115`) — the `messages` table
  (`0003_conversations.sql:14-21`) has **no receipt column**.

**What is missing / mock (the actual Phase-5 work):**

1. `features/Research.tsx` **does not exist** (not in `registry.tsx:1-48`); `research` route falls
   through to `<Generic>`. Must be created and wired to a **governed** bridge run.
2. No **`research_run` store** — no table, no Rust commands, no typed service. Governed research
   produces receipts that must be persisted and surfaced.
3. **Memory/knowledge lack the roadmap's richer model:** memory has no typed link graph
   (`[[name]]`), no confidence field (roadmap line 824-827; `MemoryEntry` has only
   scope/kind/content/pinned). Knowledge has no **collections/articles/citations** structure
   (roadmap line 828-830; today it's flat notes).
4. **Files have no guard state.** Roadmap requires open/read/**sealed** with a `blocked` state
   showing the engine guard reason (lines 836-840, 855-856). `files.rs` today has no seal concept.
5. **No retrieval into `chat`'s context rail.** Roadmap wants recalls surfaced (`ctxRecalls`/
   `crCount`, lines 843, 890). `Conversations.tsx` has no context rail / recall panel yet.
6. **Receipt persistence gap.** For a governed research run (and governed chat), the
   `receipt_id`/`verified` must be stored alongside the product row; the `messages` and new
   `research_runs` tables need columns for it.

## 2. Phase 5 specifics

### 2a. Desktop stores (SQLite tables + Rust commands + typed services)

Follow the established pattern exactly: forward-only migration → bump `SCHEMA_VERSION`
(`core/src/db.rs:18`) and add to the `migrate` array (`db.rs:65-77`) → repo functions in
`core/src/repo.rs` → `#[tauri::command]` in `src-tauri/src/commands.rs` → register in
`src-tauri/src/lib.rs:63` `generate_handler!` → typed method in `services/desktop.ts` → TS shape
in `domain/entities.ts` (camelCase, mirroring the Rust struct — `entities.ts:1-3`).

**New migration `0012_memory_knowledge_research.sql`** (coordinate the integer with Phase 4 via
`TASKS.md` — Phase 4 also claims `0012`; the second one becomes `0013`):

```sql
-- Memory: add confidence + typed links (links stored as JSON array of target ids/names).
ALTER TABLE memory_entries ADD COLUMN confidence REAL NOT NULL DEFAULT 1.0;
ALTER TABLE memory_entries ADD COLUMN links TEXT NOT NULL DEFAULT '[]';

-- Knowledge collections/articles/citations (keep knowledge_notes for back-compat / migrate).
CREATE TABLE IF NOT EXISTS knowledge_collections (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS knowledge_articles (
    id TEXT PRIMARY KEY,
    collection_id TEXT REFERENCES knowledge_collections(id) ON DELETE SET NULL,
    title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
    citations TEXT NOT NULL DEFAULT '[]',              -- JSON: [{source, url, quote}]
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);

-- Governed research runs: the receipt is the security truth; we store its id + verified flag.
CREATE TABLE IF NOT EXISTS research_runs (
    id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',            -- pending|running|completed|failed|blocked
    receipt_id TEXT,                                   -- engine receipt id (null until verified)
    verified INTEGER NOT NULL DEFAULT 0,               -- 1 only when receipt.verified == true
    sources TEXT NOT NULL DEFAULT '[]',                -- JSON: [{title, url}]
    synthesis TEXT NOT NULL DEFAULT '',
    error TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
```

Add FTS triggers for `knowledge_articles` mirroring `knowledge_notes`
(`0010_search_fts.sql:57-66`) so search/`search_all` cover articles.

**New Rust commands** (`commands.rs` + `repo.rs`, register in `lib.rs:63`):

- Memory: extend `create_memory`/`list_memory` for `confidence` + `links`; add
  `update_memory`, `set_memory_confidence`, `link_memory(id, targetId)`.
- Knowledge: `list_collections`, `create_collection`, `list_articles(collectionId?)`,
  `create_article`, `update_article`, `delete_article` (keep existing note commands for now).
- Research: `list_research_runs`, `get_research_run(id)`, `create_research_run(query)`,
  `save_research_to_knowledge(runId, collectionId?)`. The **run execution** is the governed path
  (2c) — it does not run in-process; it dispatches through the bridge.

**Typed services** (`desktop.ts`): add the above; mirror the `Channel` streaming pattern
(`desktop.ts:124-128, 162-167`) if the research run streams progress.

### 2b. Retrieval into chat context

Add a **context rail** to `features/Conversations.tsx` (roadmap `ctxRecalls`/`crCount`, line 843).
On each user turn, run a local retrieval across `memory_entries` + `knowledge_articles` (+ notes)
using the existing FTS `search_index` (`0010_search_fts.sql`) — a new command
`recall(query, limit) -> Recall[]` returning `{kind, id, title, snippet, score}`. Surface the top
recalls in a rail beside the thread; count badge = `crCount`. **Local-only** — recall never leaves
the machine. When a governed chat turn runs, the recalls that were in context can be passed inside
the governed task's `rationale` (same channel `ai.rs:governed_request` at `ai.rs:1039-1050` already
uses) — no new contract.

### 2c. Governed research run (bridge task → verified receipt)

This is the security-critical piece. A research run is **an AI turn like any other** — it goes
through the exact governed path already built, and obeys verified-receipt-mandatory.

Flow (reuse, do not re-implement):
1. `Research.tsx` calls `desktop.runResearch(query, onEvent)` (new command).
2. The Rust command builds a `bridge.task-request` — reuse `governed_request`
   (`ai.rs:1039-1050`) shape, with a research **task_class** (e.g. `standard-builder` as today,
   or a dedicated research class if the engine defines one — a new class is an engine-side change,
   §G.2 audited; do **not** invent one here). `protected_scope` carries only exact paths if a file
   is handed in (roadmap line 847-848).
3. It routes through `Provider::GovernedEngine` → `bridge/engine_sidecar.py` →
   `engine_adapter.run_governed_turn` (`engine_adapter.py:53-135`): supervisor issues a lease into
   a **separate builder**, runs behind the wall, returns a `bridge.result`.
4. The desktop re-checks `ok && receipt.verified` via `interpret_bridge_result`
   (`ai.rs:1069-1090`). **No verified receipt ⇒ no result** — the run row is marked `failed`/
   `blocked` with the engine reason; the synthesis/sources are **never** shown.
5. On verified success: persist `receipt_id`, `verified=1`, `sources`, `synthesis` into
   `research_runs`; the UI shows the verified-receipt badge (reuse the chat badge pattern
   `Conversations.tsx:182-186`); "save to knowledge" writes a `knowledge_article` with citations.

The desktop holds **no lease/key/env** at any step — those live in the operator-provisioned
sidecar (`engine_adapter.py:1-15`, `ai.rs:33-38, 432-439`). The provider stays opt-in + default
OFF; a research run when the governed provider is off/sidecar-down renders `blocked` (fail-closed,
no result) — roadmap line 834, 855.

## 3. Data models / contracts

- **No new cross-boundary contract** for storage (all local) — roadmap line 845. Research reuses
  the existing `bridge.task-request` / `bridge.result` (contracts already in
  `bridge/contracts/`). A result is non-null **iff** `ok && receipt.verified` (bridge-result
  schema, `bridge-result.schema.json:4`).
- New TS shapes (`entities.ts`): `ResearchRun`, `ResearchSource`, `Recall`, `KnowledgeCollection`,
  `KnowledgeArticle`, `Citation`; extend `MemoryEntry` with `confidence: number`, `links: string[]`
  (note: `entities.ts:141-149` today lacks these). Matching Rust structs in `core/src/domain.rs`.
- **Receipt persistence:** `research_runs.receipt_id`/`verified` (above). For governed **chat**,
  add the same to `messages` in a small migration so `Message.receipt` (`entities.ts:104-115`,
  currently frontend-only) is backed by real columns — this closes the "populated once
  receipt-plumbing lands" note. Keep it minimal; the receipt/evidence themselves stay in the
  engine ledger (roadmap Phase-1 data-model rule, lines 476-478).

## 4. UI wiring & states (§D per page)

**`memory` ❖ Հիշողություն** (`features/Memory.tsx` — extend). Add typed filter (user/feedback/
project/reference — reconcile with `MEMORY_KINDS` `enums.ts:22`), confidence display, `[[name]]`
link rendering with a **text-list fallback** for the link graph (roadmap line 827). States:
existing `Async` (loading/error/empty via `ui.tsx:108-134`) + `blocked`(memory referencing sealed
evidence → `BlockedState`). Keyboard: `/` search, `n` new (wire to existing `NewEntryForm`),
`Enter` open, `e` edit. A11y: list `role=list`; graph has a list fallback.

**`knowledge` ⁂ Գիտելիք** (`features/Knowledge.tsx` — extend into collections/articles). Components:
collection sidebar, article list, article editor, citation view, search (keep `searchKnowledge`
path `Knowledge.tsx:64`). States: `empty` **vs** filtered-empty (distinct copy — roadmap line
828), `error`. A11y: article `role=article`, structured headings.

**`research` ⌖ Հետազոտում** (`features/Research.tsx` — **create**; register in `registry.tsx`
under `research:`). Components: query input, run status with **verified-receipt badge**, sources
list, synthesis, save-to-knowledge. States: `default`, `loading`(run in progress — pulse, reuse
motion tokens), `empty`(no runs), `error`(run failed), `blocked`(governed provider off / sidecar
down → fail-closed reason from `interpret_bridge_result`, **no result shown**). Keyboard: `Enter`
run, `Esc` cancel, arrow-navigate sources. A11y: run status `aria-live` region; each source
labeled + linked.

**`files` ▤ Ֆայլեր** (`features/Files.tsx` — extend with guard states). Add per-file guard
(open/read/**sealed**); a sealed file cannot be opened and shows the engine guard reason via
`BlockedState` (roadmap line 838-840, 855). Components: file index, query/chips, preview plane,
per-file guard badge. States: existing loading/error/empty (`Files.tsx:121-123`) + `blocked`
(sealed). Keyboard: `/` query, arrows, `Enter` preview, `Space` select. A11y: index `role=grid`
or `list`; guard state in the accessible name. **Guard enforcement lives at the wall, not in the
desktop** (stop-condition, roadmap line 876) — the desktop reads guard state and refuses; it never
implements the seal.

Depends on Phase 4's `BlockedState`/`Rail`/motion primitives where noted — if Phase 4 lands
first, reuse; if parallel, coordinate the shared `ui.tsx` additions (roadmap §E).

## 5. Exact files to touch

Create:
- `apps/desktop/src/features/Research.tsx`
- `apps/desktop/src-tauri/core/schema/0012_memory_knowledge_research.sql` (or `0013` if Phase 4
  claims `0012` first — coordinate via `TASKS.md`)
- tests (see §6)

Edit:
- `apps/desktop/src/features/Memory.tsx`, `Knowledge.tsx`, `Files.tsx`
- `apps/desktop/src/features/Conversations.tsx` (context rail + recall)
- `apps/desktop/src/features/registry.tsx` (add `research`)
- `apps/desktop/src/services/desktop.ts` (research/collections/articles/recall + extended memory)
- `apps/desktop/src/domain/entities.ts` (new shapes; extend `MemoryEntry`)
- `apps/desktop/src/domain/enums.ts` (reconcile memory kinds if the roadmap's typed set differs)
- `apps/desktop/src-tauri/src/commands.rs` + `src-tauri/src/lib.rs:63` (register commands)
- `apps/desktop/src-tauri/core/src/repo.rs` (research/collections/articles/recall/memory) +
  `core/src/domain.rs` (structs) + `core/src/db.rs:18,65-77` (bump `SCHEMA_VERSION`, add migration)
- `apps/desktop/src-tauri/src/files.rs` (guard/seal read model)
- optionally a `messages` receipt-column migration + `commands.rs` post_message/reply path
- `docs/ARCHITECTURE.md` (memory/knowledge/files + retrieval + governed research), `PROJECT_STATE.md`

**Do NOT touch** `engine/` security code or `bridge/engine_adapter.py`'s invariants. If research
needs a new engine task class or a file-seal primitive, **stop** and raise a separate audited
engine task (§G.2, roadmap stop-conditions 875-876).

## 6. Tests & acceptance

- **Store CRUD + search** (`cargo test -p brops-core`): memory (confidence/links), collections/
  articles, research_runs, recall over FTS; the `0012`/`0013` migration applies cleanly (mirror
  existing repo/migration tests; keep 29+ green).
- **Governed research fail-closed** (the security test — roadmap line 859): assert a run with
  `ok=false` or `receipt.verified=false` yields **no** synthesis/sources and marks the row
  `failed`/`blocked` (extend the existing `bridge/tests/test_engine_adapter.py` fail-closed cases
  and add a desktop-side `interpret_bridge_result` test in the Rust `ai` module tests). A
  verifier-negative run **never** persists a result.
- **Files guard:** a sealed file → `blocked`, cannot open (no `read_file` call succeeds on it).
- **Recall-into-chat wiring:** a user turn produces recalls from memory/knowledge; recalls are
  local-only (assert no network).
- **Frontend:** `Research`/extended `Memory`/`Knowledge`/`Files` render all §D states incl.
  `blocked`; `research` shows the verified badge only when `verified`.
- **Acceptance (roadmap 868–872, DoD 878–883):** owner can create/curate memory + knowledge, run
  a **governed** research yielding a verified result and save it to knowledge, browse files with
  guard states honored, and see recalls in `chat`. Governed research proven verified + fail-closed;
  files guard proven; local-first upheld. Verify: `cd apps/desktop && npm ci && npm run build`,
  the Rust legs, and `cd bridge && BRO_ENV=ci python -m unittest discover -s tests` (§B.4). No
  `git push`/merge — hand Gev the commands (§B.5).

## 7. Security notes

- **Governed research is verified-receipt-mandatory** (the phase's central invariant). The result
  (synthesis + sources) is shown **only** when `ok=true` and `receipt.verified=true`
  (`bridge-result.schema.json:4`, `engine_adapter.py:112-135`, `ai.rs:1069-1090`). No verified
  receipt ⇒ no result — enforced twice (Python adapter + desktop re-check) and asserted by test.
- **Desktop holds no lease/key/env.** The research task-request carries none (task-request schema
  forbids extra props, `task-request.schema.json:6`); leases are issued into a separate builder in
  the operator-provisioned sidecar. Never cache or relay a lease/key.
- **Provider opt-in + default OFF, fail-closed.** `governed-engine` requires both
  `BROPS_AI_PROVIDER=governed-engine` and `BROPS_ALLOW_GOVERNED_ENGINE=1` (`ai.rs:312-324`); the
  desktop strips `BRIDGE_SIDECAR_FAKE` before spawning (`ai.rs:1108-1110`) so a fabricated
  verifier can't be env-injected. Do not add a bypass for "faster" research (stop-condition,
  roadmap line 875).
- **Local-first.** Memory, knowledge, recall, and file content stay on-device; file content
  crosses the wall **only** inside a governed task's declared `protected_scope` (exact paths,
  roadmap line 847-848, 857). Sealed files cannot be opened or handed to a turn.
- **File seal is a wall property, not a desktop check.** The desktop reads and honors guard state;
  it must not be circumventable from the desktop. If it is, that's a wall/engine issue → audited
  engine task, not a desktop patch (roadmap line 876).

## 8. Dependencies / open questions

- **Depends on Phase 3** (shell + governed chat + the context rail seam). Phase 3 is not yet
  merged (phase board: P3 ⏳). The bridge governed path exists (Phase 1 slice-1 merged), but a
  **real** governed round-trip needs an operator-provisioned supervisor sidecar; until then the
  sidecar fails closed (`ai.rs:432-439`). A **mock supervisor** is acceptable for CI, documented
  (roadmap line 862-863). Flag if the real round-trip provisioning is unresolved (escalate to
  Owner/Architect — do not hardcode keys).
- **Runs parallel to Phase 4** (roadmap §E). Coordinate the shared `#nav` seam and the
  `SCHEMA_VERSION`/migration integer (both phases want `0012`) via `TASKS.md` claim (§B.2).
- **Open:** does the engine define a dedicated **research task class**, or is `standard-builder`
  (`ai.rs:37`) correct for research? A new class is an engine change (§G.2 audited) — default to
  the existing class and confirm with Architect.
- **Open:** knowledge migration path — keep flat `knowledge_notes` alongside new
  collections/articles, or migrate notes into an "Inbox" collection? Recommend keeping notes and
  adding collections/articles additively (no data loss), decide in review.
- **Open:** where does the engine expose **file guard/seal** state to the desktop? If no such
  read exists, `files` ships open/read only and `sealed`/`blocked` is deferred behind an
  engine-read task (do not fake a seal).
- **Open:** persisting governed-chat receipts on `messages` (§3) — include in this phase or split
  into a small Phase-1 slice-2 follow-up? It's the natural home for the receipt columns; confirm
  ownership with the Phase-1 builder to avoid a double migration.
