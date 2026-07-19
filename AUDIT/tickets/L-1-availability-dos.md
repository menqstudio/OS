# L-1 — Availability / DoS (5 items)

- **Severity:** Low ×5
- **Confidence:** High / Medium
- **Type:** Availability, resource use
- **Status:** Proposed patches (read-only audit)

Each item is independent; fix any subset.

## L-1a — Unbounded list/search queries
**Files:** `src-tauri/core/src/repo.rs:64,144,296,420,466,562,652,795,1032` (~13 functions: `projects::list`, `tasks::list_all`, `approvals::list`, `notifications::list`, `decisions::list`, `chat::list_conversations`, `chat::list_messages`, `knowledge::list`/`search`, `memory::list`, `runs::list`, `events::list`, `automations::list`).
**Problem:** each materializes the entire table into a `Vec` with no `LIMIT`; a long chat or busy agent grows unbounded, and every screen load deserializes the full set across IPC → freezes. Only `activity::list` (LIMIT 200) and `security::summary` (LIMIT 25) are capped.
**Fix:** add `LIMIT ?/OFFSET ?` or keyset pagination on `(created_at, rowid)`; start with `list_messages` and the audit-adjacent lists.
**Accept:** [ ] `list_messages` returns a bounded page; UI can request further pages.

## L-1b — Unbounded directory listing
**Files:** `src-tauri/src/files.rs:155-189` (`read_listing`), `191-213` (`list_dir`).
**Problem:** collects every child into `Vec<DirEntry>` then sorts — a huge directory allocates proportional memory and blocks.
**Fix:** cap entries (e.g. 10k), paginate or stream, signal truncation to the UI.
**Accept:** [ ] listing a directory with >cap entries returns cap + a truncation flag, bounded memory.

## L-1c — No `busy_timeout`
**Files:** `src-tauri/core/src/db.rs:34-39` (`configure`).
**Problem:** WAL allows one writer; with no busy handler a second connection gets an instant `SQLITE_BUSY` surfacing mid-operation.
**Fix:** `conn.busy_timeout(std::time::Duration::from_secs(5))?;` and prefer `BEGIN IMMEDIATE` for write transactions.
**Accept:** [ ] concurrent writers retry within the timeout instead of failing immediately.

## L-1d — Sandbox liveness check is Linux-only → Windows DoS
**Files:** `src-tauri/src/ai.rs:438-448` (`pid_liveness`), `500-533` (`cleanup_stale_sandboxes_in`).
**Problem:** `pid_liveness` returns `None` off-Linux, so cleanup falls back to a 1-hour age rule. On Windows a second instance can `remove_dir_all` a live sibling's sandbox after >1h idle → the victim's `write_system_prompt_file` then fails (missing dir) → persistent denial of all AI replies until restart.
**Fix:** implement Windows liveness (`OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,...)` via `windows`/`sysinfo`, or `tasklist`); make `write_system_prompt_file` self-heal by recreating the sandbox dir when the cached path vanished.
**Accept:** [ ] on Windows, a running instance's sandbox is not deleted by a sibling; a vanished sandbox is recreated on next reply.

## L-1e — No rate limit / history trimming → metered spend growth
**Files:** `src-tauri/src/ai.rs:883-887`, `src-tauri/src/commands.rs:598-629` (`reply_in_conversation`/`stream_reply`).
**Problem:** `max_tokens:1024` caps output, but full history (up to `MAX_CONVERSATION_BYTES` = 8 MiB) is resent every reply and nothing rate-limits invocation → ~quadratic metered cost over a conversation's life; a looping frontend spends continuously.
**Fix:** trim history to a token/byte budget before dispatch (keep system + last N messages under ~200 KB); add a `tokio::sync::Semaphore` (1–2 concurrent generations) + a minimum inter-request interval.
**Accept:** [ ] a long conversation sends a bounded history; concurrent generations are limited.
