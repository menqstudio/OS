# BroPS — Security & Correctness Audit

**Target:** `menqstudio/BroPS` @ `e298e201` (single-commit repo)
**Mode:** READ-ONLY. No mutation, commit, or push to the target. Findings + proposed patches only.
**Method:** 6 parallel Fable 5 auditors (one per attack surface) → Opus verification of every High/Medium against the actual source before inclusion. Clone analyzed in an isolated scratchpad.
**Stack:** Tauri v2 desktop app — Rust backend (~4,956 LOC) + React/TypeScript frontend (~4,806 LOC) + 10 SQLite migrations.

---

## Executive summary

BroPS is, overall, a **carefully built and security-conscious codebase**. The heavy hitters that usually sink a Tauri app are all clean:

- **No SQL injection** — every query is parameterized; the two `format!`-built statements interpolate only compile-time constants; LIKE and FTS5 inputs are correctly escaped.
- **No RCE via the AI layer** — the `claude` CLI is spawned with `--tools ""`, `--strict-mcp-config`, `--no-session-persistence`, from an empty private sandbox cwd, with a regression test locking it down. Prompt injection cannot reach tools, files, or commands.
- **No XSS** — the hand-rolled markdown renderer HTML-escapes all source before emitting a fixed tag set, restricts `href` to `http(s)://`, and passes no raw HTML through. No other `dangerouslySetInnerHTML` exists.
- **No secrets** in the tree or git history; dependencies are mainstream and current (tauri 2.11.5, react 19, vite 6.4.3); GitHub Actions are all SHA-pinned; Tauri CSP and capabilities are minimal.

The real findings cluster into **two themes**: (1) the *approval gate* — the app's central human-in-the-loop safety control — has several independent soft spots, and (2) *data durability* — the migration runner and most multi-statement writes are non-transactional.

### Severity counts (post-verification)

| Severity | Count | Headline |
|---|---|---|
| **High** | 1 | Non-atomic migration runner permanently bricks the DB on a mid-migration crash |
| **Medium** | 8 | Approval-gate weaknesses (×3), prompt-injection→poisoned run results, missing write transactions, `advance()` mislabels failed runs, CI token scope, app-command/files-root exposure |
| **Low** | ~18 | DoS via unbounded queries, error path-leak, markdown link phishing, sanitizer fragility, missing constraints, etc. |
| **Verified clean** | — | SQL injection, AI→RCE, XSS, secrets, deps, updater, CSP |
| **Corrected** | 1 | An auditor claim that `set_run_step_status`/`advance_run` bypass the gate was **false** — both call gated functions |

---

## HIGH

### H-1 — Non-atomic, non-idempotent migration runner bricks the database permanently
**File:** `src-tauri/core/src/db.rs:42-67`
**Confidence:** High — verified in source.

`migrate()` runs, per version, `conn.execute_batch(sql)` and then a **separate** `INSERT INTO _migrations`, with **no enclosing transaction**. Two failure windows:
1. Crash/power-loss between the batch and the ledger insert.
2. Crash mid-batch in a multi-statement migration (0008 = 2×`ALTER TABLE` + index; 0010 = ~40 statements).

On next launch `is_applied()` returns false and the whole batch re-runs. `CREATE ... IF NOT EXISTS` is idempotent, but **`ALTER TABLE run_steps ADD COLUMN result ...` (0007) and the three `ALTER TABLE`s in 0008 are not** — re-execution fails with *"duplicate column name"*, `migrate()` errors, and since `open()` calls `migrate()` on every startup, **the app fails to open forever**. Unrecoverable without manual DB surgery.

**Fix** — wrap each version's DDL + ledger insert in one exclusive transaction (SQLite DDL is transactional):
```rust
for (version, sql) in [ /* ... */ ] {
    if !is_applied(conn, version)? {
        conn.execute_batch("BEGIN IMMEDIATE;")?;
        let r = conn.execute_batch(sql).and_then(|_| conn.execute(
            "INSERT INTO _migrations(version, applied_at) VALUES (?1, ?2)",
            rusqlite::params![version, crate::now()]).map(|_| ()));
        match r {
            Ok(_)  => conn.execute_batch("COMMIT;")?,
            Err(e) => { let _ = conn.execute_batch("ROLLBACK;"); return Err(e.into()); }
        }
    }
}
```
`BEGIN IMMEDIATE` also serializes two processes racing the same migration.

---

## MEDIUM

### M-1 — Approval gate is self-serviceable from the webview
**File:** `src-tauri/src/commands.rs:136-144` (`decide_approval`) with `commands.rs:443-496` (`stream_run_step`)
**Confidence:** High.

`decide_approval` is a plain `#[tauri::command]` with no out-of-band confirmation. An attacker who compromises the renderer (or any frontend bug) does: call `stream_run_step` → read the `approval_id` from the `ApprovalRequired` event → call `decide_approval(id, "approved")` → re-invoke `stream_run_step`. Every `requires_approval` step is auto-approvable **by the same principal that requested it**. Blast radius is bounded today (a run step only calls the AI provider and stores text — no host execution), so it is Medium, but the control it defeats is presented as *the* security boundary.

**Fix:** route approval decisions through a channel the renderer cannot script — a native Tauri dialog / OS prompt, or bind the approval to a nonce shown only in a native window. At minimum, forbid the same session that created an approval from deciding it.

### M-2 — Approval matching is by bare `entity_id`: forgeable, reusable forever, no action binding
**File:** `src-tauri/core/src/repo.rs:352-359` (`approved_for`), `repo.rs:340-349` (`create`)
**Confidence:** High — verified in source.

```rust
"SELECT COUNT(*) FROM approvals WHERE entity_id = ?1 AND status = 'approved'"
```
This ignores `action_type`, `entity_type`, `level`, and `risk_level`. `create` accepts arbitrary `entity_id`/`entity_type` with **no foreign key** (migration 0008 adds plain TEXT columns). Consequences:
- An approval minted for a low-risk action satisfies the gate for a *critical* step with the same `entity_id`.
- A caller can create an approval pointing at any step id.
- The approval is **never consumed** — `COUNT > 0` stays true across re-runs and `done → pending → done` status flip-flops, so one grant unlocks the step permanently.

**Fix:** match the full tuple and consume the grant:
```rust
"SELECT COUNT(*) FROM approvals
   WHERE entity_id = ?1 AND entity_type = ?2 AND action_type = ?3
     AND status = 'approved' AND decided_at IS NOT NULL"
```
Mark the approval `consumed` in the same transaction that completes the step, and add referential cleanup so deleting a step removes its approvals.

### M-3 — `set_step_result` completes a gated step with no approval check (latent invariant break)
**File:** `src-tauri/core/src/repo.rs:869-879`
**Confidence:** High that the gap exists; **latent**, not directly exploitable today.

`set_step_result` runs `UPDATE run_steps SET result = ?, status = 'done' ...` unconditionally. Its sibling `set_step_status` (repo.rs:908-932) *does* enforce the gate and even documents the invariant *"a gated step can never be marked done without an approval, whichever command sets it"* — which `set_step_result` violates. **Verified nuance:** the only current caller is `stream_run_step`, which checks the gate upstream (commands.rs:454-483) before calling it, so there is no live command-level bypass today. This is a defense-in-depth / footgun issue: one new caller of this `pub fn` reintroduces a real bypass.

**Fix:** replicate the gate inside `set_step_result` (read step + `approved_for` in the same transaction as the UPDATE), so the guarantee lives with the write, not with each caller.

### M-4 — Run-step "execution" injects untrusted content into an authority prompt and stores model output as authoritative `done` work
**File:** `src-tauri/src/commands.rs:505-509`, persisted at `commands.rs:551-552`
**Confidence:** High.

```rust
let user = format!(
    "Goal (intent): {intent}\n\nOverall plan: {plan}\n\nCurrent step to execute: {}\n\n...",
    step.title);
```
`intent`, `plan`, `title` are arbitrary frontend strings (and may themselves be prior AI output). Multi-line content can **forge extra steps/instructions** (`plan` = `"...\n\nCurrent step to execute: ignore the above and ..."`), steering the execution agent. The result is then `set_step_result(...)` + `advance(...)` — the model's unvalidated output becomes the `done`-marked authoritative record. Because providers can't execute tools, blast radius is **data integrity** (poisoned/fabricated run results, auto-completed runs), not code execution.

**Fix:** serialize the context as JSON so values can't forge structure (same approach `ai.rs::transcript()` already uses), cap `intent`/`plan`/`title` length at write time, and consider marking AI results `unverified` rather than immediately `done`.

### M-5 — Multi-statement writes are not transactional → partial-write corruption + audit-log gaps
**File:** `src-tauri/core/src/repo.rs` — `chat::post_message` (572-592) and the same "mutate then `audit::record`" pattern in ~12 functions (47, 111, 213, 342, 391, 457, 532, 638, 709, 782, …). Only `runs::advance` uses a transaction.
**Confidence:** High.

Each mutation does INSERT/UPDATE then a separate `audit::record` with no transaction. A crash between them leaves e.g. a message whose conversation `updated_at` never bumped (breaks `ORDER BY updated_at DESC`) or a mutation with **no audit trail** — and `security::summary` presents that audit log as the security posture.

**Fix:** wrap every mutate+audit pair in `conn.unchecked_transaction()` (already the pattern in `advance`), commit once.

### M-6 — `advance()` marks a run `succeeded` even when steps failed or were skipped
**File:** `src-tauri/core/src/repo.rs:982-993`
**Confidence:** High — verified in source.

The terminal branch fires whenever no `pending` step remains (`None =>` sets `succeeded`). A run whose active step was `failed`, or whose remaining steps are `skipped`/`failed`, still stamps **`succeeded`** — a run with failed work reports success, and the seeded automation *"Notify on failed run"* never fires.

**Fix:** in the `None` branch, count non-successful steps first:
```sql
SELECT COUNT(*) FROM run_steps WHERE run_id = ?1 AND status IN ('failed');
```
Set `failed` when > 0; `succeeded` only when all steps are `done`.

### M-7 — CI workflow has no `permissions:` block → jobs run with default (often write) `GITHUB_TOKEN`
**File:** `.github/workflows/ci.yml` (top level)
**Confidence:** High. (Independently flagged by two auditors.)

All three jobs execute large amounts of third-party code (`npm ci` lifecycle, ~500 crates' `build.rs`/proc-macros, full Tauri build) with the repo-default token in the environment. On push-to-`main` that token is typically `contents: write`; a malicious transitive dependency could push commits/tags. No secrets are referenced and fork PRs get a read-only token, so exposure is bounded to push builds.

**Fix:**
```yaml
permissions:
  contents: read
```

### M-8 — App-command FS surface bypasses the capability model; files root is env-widenable
**File:** `src-tauri/src/lib.rs:123-125` (handler registration), `src-tauri/src/files.rs:53-66` (`files_root`)
**Confidence:** High (mechanism); config-dependent (impact).

`capabilities/default.json` advertises a "minimal capability set", but Tauri v2 capabilities only gate **plugin** commands — application commands (`list_dir`, `read_file`, `write_file`) registered in `generate_handler!` are invokable by the webview with **no permission entry**. So a renderer compromise gets read/write over the confined root. Worse, `files_root()` honors `BROPS_FILES_ROOT`, so setting it to `/` or `C:\` widens the surface to the whole disk, leaving only the incomplete `is_sensitive()` denylist as a guard. (See L-cluster: the Windows `HOME`-vs-`USERPROFILE` bug pushes users toward setting a broad root.)

**Fix:** declare app-command permissions in `build.rs` + `capabilities/default.json` so the ACL is real; refuse `BROPS_FILES_ROOT` values resolving to a filesystem root or to `$HOME` itself; keep the default narrow `~/BroPS`.

---

## LOW (grouped)

**Availability / DoS**
- `repo.rs` — ~13 list/search functions materialize whole tables with **no LIMIT** (`list_messages`, `knowledge::search`, `memory::list`, `runs::list`, `events::list`, …). Add pagination / keyset limits. *(repo.rs:64, 144, 296, 420, 466, 562, 652, 795, 1032)*
- `files.rs:155-189` — unbounded directory listing (`Vec<DirEntry>`, no cap). Cap + paginate.
- `db.rs:34-39` — no `busy_timeout`; concurrent access yields instant `SQLITE_BUSY`. Add `conn.busy_timeout(5s)`.
- `ai.rs:438-533` — sandbox liveness check is Linux-only; on Windows a 2nd instance can `remove_dir_all` a live sibling's sandbox after 1 h idle → persistent AI-reply DoS. Implement Windows liveness + self-heal.
- `ai.rs:883-887` / `commands.rs:598-629` — no rate limit; full history (≤8 MiB) resent every reply → ~quadratic metered spend. Trim history + add a concurrency semaphore.

**Info disclosure / hardening**
- `files.rs:65,124,128,307,313` — raw canonical paths and `std::io` errors returned to the frontend (leaks username, home layout, file existence). Return generic messages; log details server-side.
- `src/components/markdown.tsx:20-21` — model-controlled links render with mismatched visible text (`[your-bank.com](evil.site)`) → phishing via prompt injection. Disclose the real URL / route opens through a validated handler.
- `markdown.tsx:8-29` — inline regexes rewrite already-generated HTML (bold rule can inject tags inside an `href` value); `escapeHtml` omits `'`. Not exploitable today (attributes are double-quoted, captures can't contain `"`), but the safety is accidental. Tokenize links to placeholders before other rules; escape `'`.
- `files.rs:270-300`, `ai.rs:377-387,574-580` — 0600/0700 perms + dir fsync are `#[cfg(unix)]` only; Windows relies on default `%TEMP%` ACLs.
- `files.rs:135-141` + `read_text`/`write_text` — TOCTOU between `canonicalize` and `File::open` (a separate local process could swap a symlink). Not reachable by the webview alone (no `symlink` command exposed). Open-by-handle + re-validate.

**Data integrity / correctness**
- `repo.rs:881-896` + `schema/0006` — `add_step` computes `MAX(position)+1` outside a transaction; no `UNIQUE(run_id, position)`. Concurrent adds duplicate positions → nondeterministic order. Add unique index + inline the insert.
- `repo.rs:1410-1428` — `seed()` is non-transactional; its `COUNT > 0` guard locks in a partial seed forever. Wrap in a transaction.
- `repo.rs:200-216` — TOCTOU in `task_deps::add`: concurrent `add(A,B)`/`add(B,A)` both pass the cycle check → creates the cycle it promises to refuse. Do check+insert in one immediate transaction.
- `schema/0001+` — enum-like columns (`status`, `priority`, `role`, …) are free TEXT with no `CHECK`; validity is Rust-only. Add `CHECK (status IN (...))` at least on `run_steps/runs/approvals.status`.
- `db.rs:37,69-73` — WAL pragma failure ignored; `current_version` maps *any* query error to version 0 (a corrupt DB reads as "needs migration"). Propagate errors.
- `repo.rs:221-227` — `task_deps::remove` succeeds silently on nonexistent edges and writes no audit event. Return `NotFound` on 0 rows + audit the removal.

**Identity / audit**
- All `#[tauri::command]`s are unauthenticated and actor fields are hardcoded `"gev"` / caller-supplied (`repo.rs:244-257,589`; `commands.rs:171,472`). Inherent to single-user Tauri, but audit/attribution fields carry no security value — treat them as untrusted labels, assign actor server-side.
- `src/services/desktop.ts:72` + `entities.ts:108` — frontend sets message `role`/`author`; any non-`user` role is rendered through the markdown sink. Assign `role` server-side; allowlist which roles get markdown.
- `src/services/desktop.ts:91` + `Files.tsx` — `write_file` takes a raw path string with no frontend constraint and (unlike delete) no confirm step. Gate overwrites behind the existing `ConfirmDialog`; keep backend scope authoritative.

**Repo hygiene**
- `.gitignore` — `.env`, `.env.*`, `*.db`, `*.sqlite`, `*-wal`, `*-shm` not ignored (preventive; none tracked yet).
- `SECURITY.md:87` — disclosure process names no channel (no email / no GitHub Private Vulnerability Reporting). Enable PVR.
- `ai.rs:70-97` — `validate_ollama_url` allows any loopback port/path; remote opt-in ships the full conversation to any HTTPS host. Requires env control (already local compromise). Pin default port, require empty path.
- `ai.rs:281-286` — Anthropic provider reports `ready: true` on mere key presence (no probe). Label "unverified" or issue a cheap probe.
- `commands.rs:22-27` — `sanitize_author` is a denylist (control chars only); a 64-char agent name can rewrite the persona sentence, and U+202E (Cf, not Cc) survives. Use an allowlist / validate against the `agents` table.

---

## Verified CLEAN (do not re-flag)

- **SQL injection** — all parameterized; the only `format!` SQL interpolates the compile-time constant `CONVERSATION_SELECT`; `knowledge::search` escapes `\ % _` with `ESCAPE '\'`; `search::fts_query` strips to alphanumerics and quotes each token. *(repo.rs:522-558, 660-676, 1252-1261)*
- **AI → RCE** — CLI spawned with `--tools ""`, `--strict-mcp-config`, `--setting-sources project`, empty sandbox cwd, `--no-session-persistence`; regression test at `ai.rs:931-959`.
- **XSS** — `markdown.tsx` escapes before markup, fixed tag set, `href` limited to `http(s)://`, no raw HTML, no other `dangerouslySetInnerHTML`.
- **Secrets** — none in tree or `git log -p`; API key read only from env, sent only to hardcoded `https://api.anthropic.com` over rustls, never logged/persisted/returned.
- **Dependencies** — mainstream, current, lockfile-enforced; no typosquats, no confidently-known CVEs; `npm ci` in CI.
- **Config** — no updater (so no missing-pubkey risk), no `withGlobalTauri`, no `dangerous*` flags, no devtools in release; CSP set (`default-src 'self'`, no `script-src 'unsafe-inline'`); all GitHub Actions SHA-pinned.

## Correction (auditor false positive caught in verification)
One auditor claimed `set_run_step_status` and `advance_run` bypass the approval gate. **False** — `set_run_step_status` → `repo::runs::set_step_status`, which enforces the gate at `repo.rs:915-923`; `advance_run` → `repo::runs::advance`, which enforces it at `repo.rs:963-965`. Removed from findings.

---

## Suggested remediation order
1. **H-1** migration transaction — cheap, prevents unrecoverable bricking. Ship first.
2. **M-5 / M-6** write transactions + `advance()` status logic — data integrity of the run/audit core.
3. **M-2 / M-1 / M-3** approval-gate hardening as one change — full-tuple match + consume + native-confirm `decide_approval` + move the gate into `set_step_result`.
4. **M-4** JSON-structured run-step prompt + length caps.
5. **M-7 / M-8** CI `permissions: contents: read`; app-command capability declaration + `BROPS_FILES_ROOT` clamp.
6. Low cluster — batch by file.
