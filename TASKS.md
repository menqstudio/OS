# TASKS — the coordination board · координация board

> **🥇 THE MOST IMPORTANT RULE: never two agents on the same task at the same time.**
> Before you start a task, **claim it here** (set *Claimed by* + status `In-Progress`) in a commit on your branch.
> Check this board **first, every session**. If a task is already `In-Progress` by someone else — pick another.
>
> **🥇 ԱՄԵՆԱԿԱՐԵՎՈՐ ԿԱՆՈՆԸ՝ երբեք երկու agent միաժամանակ նույն task-ի վրա։**
> Task սկսելուց առաջ՝ **claim արա այստեղ** (դիր *Claimed by* + `In-Progress`) քո branch-ի commit-ում։
> Ստուգիր այս board-ը **առաջինը, ամեն session**։ Եթե task-ը արդեն ուրիշի `In-Progress` ա — վերցրու ուրիշը։

**Status values · Status-ի արժեքներ:** `Todo` · `In-Progress` · `Review` · `Done` · `Blocked`

> **Execution source:** the phase-by-phase plan lives in
> [`MASTER_EXECUTION_ROADMAP.md`](./MASTER_EXECUTION_ROADMAP.md). Each roadmap task should get a row here
> when someone claims it. · Կատарման աղբյուրը՝ `MASTER_EXECUTION_ROADMAP.md`։

| ID | Task | Claimed by | Status | Branch / PR |
|----|------|-----------|--------|-------------|
| **T-001** | Coordination canon (OWNERS · PROJECT_STATE · TASKS · PR template · Startup Law) | 🔨 Claude | ✅ Done | `chore/coordination-canon` |
| **T-002** | Root-model decision — **DECIDED: Option 1 (subtree + C)** for stability; see CLAUDE.md §3 | 📐 ChatGPT + 👑 Gev | ✅ Done | — |
| **T-003** | Phase 1 — bridge: `apps/desktop ↔ adapter ↔ engine`. Design **APPROVED**; slice 1 (contract+adapter+tests+**bridge CI leg**) **merged** (PR #3, `41cf4ff`, 10/10 canonical); slice 2 **transport** (desktop `Provider::GovernedEngine` in `ai.rs` opt-in + governed-sidecar wiring + chat receipt badge) **merged** (PR #8; the inert Settings toggle was removed in Wave 1/PR #15, replaced by a read-only provider status) — transport only; verify-seam · receipt-plumbing · streaming · real e2e still open | 🔨 Claude | In-Progress | PR #3 + PR #8 ✅ merged |
| **T-004** | Bro deferred security items O-1..O-5 (from `fix/audit-followups`) — roadmap Phase 10 | _unclaimed_ | Blocked (wall-coupled, needs Owner go) | — |
| **T-005** | Option-2 feasibility (**AUDITED**): engine as submodule + targeted fix to Bro's worktree check (`git rev-parse --show-toplevel` instead of `git worktree list`). **Separate branch/PR, Owner approval, must not destabilize.** — roadmap Phase 10 | _unclaimed_ | Todo | — |
| **T-006** | Master execution roadmap — expand `MASTER_EXECUTION_ROADMAP.md` into the canonical execution source (11 phases × 16 sections, per-page UI specs, docs sync) | 🔨 Claude | ✅ Done (merged) | `docs/master-execution-roadmap` → **PR #4 merged** (`c573c25`) |
| **T-007** | Coordination-docs enforcement — CI gate (`tools/check_coordination.py`) + Stop-hook (`.claude/`) so the Startup Law / docs-sync is **enforced, not remembered** (fail-closed CI wall + fail-open Claude reminder) | 🔨 Claude | ✅ Done (merged) | **PR #9 merged** (`990a9ec`) |
| **T-008** | Phase follow-ups — `docs/DESIGN_SYSTEM.md` (design-system reference) + honest Settings (drop prototype stubs) + frontend **test framework** (vitest + first tests) + CI test leg | 🔨 Claude | ✅ Done (merged) | **PR #11 merged** |
| **T-010** | 🛑 **security-audited** — Tauri capability boundary: the SQLite-backed / AI-exec / runs / automations / integrations **mutation** commands are registered to the webview but **not capability-gated** (gating is a `TODO` in code). Define + enforce Tauri capabilities so webview-reachable mutations are scoped to what each surface may do. **Audited security-design task, not a quick fix.** **Wave 2b design-first:** joint T-010+T-011 design (privilege topology, 68-command inventory + risk tiers, deny-by-default manifest, in-command enforcement, negative tests, rollout) in [`docs/design/WAVE_2B_CAPABILITY_APPROVAL_DESIGN.md`](./docs/design/WAVE_2B_CAPABILITY_APPROVAL_DESIGN.md) — **design-only, no product code until Architect audit + Owner approval.** | 🔨 Claude | In-Progress (design) | `design/wave-2b-capability-approval` |
| **T-011** | 🛑 **security-audited** — Approval self-approval protection is **process-memory only** (origin lost after restart; native out-of-band confirmation is a `TODO`) — dangerous when chained with T-010. Persist approval origin + add native out-of-band confirmation for privileged approvals. **Audited security-design task, not a quick fix.** Designed **jointly** with T-010 (durable `origin`/`request_digest`/`nonce` via migration 0012, restart-safe self-approval, native confirmation) in the same design doc; **implements after T-010.** | 🔨 Claude | Blocked (on T-010; design done) | `design/wave-2b-capability-approval` |
| **T-012** | **Wave 1 — provider fail-closed policy** (audit P0-1): `resolve()→Result`, no silent governed→ungoverned fallback; unknown/misconfig/no-config → hard error; ungoverned only via `BROPS_ALLOW_UNGOVERNED=1`; ambient `ANTHROPIC_API_KEY` never auto-selects; inert toggle → honest read-only 3-state provider status (Governed/Ungoverned/Not-configured) | 🔨 Claude | ✅ Done (merged) | **PR #15 merged** (`15384cb`) |
| **T-013** | **Wave 2a — webview message provenance** (audit P1-6): the webview `post_message` allowlist admitted `agent`, so a compromised renderer could mint agent messages. Restricted `WEBVIEW_MESSAGE_ROLES` → `["user"]`. **Audit round 1 (RED):** the first `save_ask_to_chat(title,question,answer)` merely moved the vector — webview still supplied the agent body. **Fixed:** `stream_ask` now holds the server-generated answer under an opaque **one-time** `result_id`; `save_ask_to_chat(result_id, title)` consumes it and persists the held question+answer pair in **one transaction** — the webview never carries an agent body. Tests: allowlist constant + one-time-claim / unknown-id-refused seam. Zero-trust re-audit **GREEN** on exact HEAD `5703841`. **Residual (by design):** binding a message to a verified per-turn governed receipt is Receipt Protocol v1 (Wave 3, §I). | 🔨 Claude | ✅ Done (merged) | **PR #16 merged** (`d85dcba`) |

## How to claim · Ինչպես claim անել
1. `git pull` and read this board. · `git pull` ու կարդա board-ը։
2. On your branch, set your name + `In-Progress` on the row, commit ("claim T-00X"). · Քո branch-ում դիր անունդ + `In-Progress`, commit արա։
3. Do the work → set `Review`, open a PR → Owner approves → `Done`. · Աշխատիր → `Review` + PR → Owner approve → `Done`։
