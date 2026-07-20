# L-2 — Info disclosure / hardening (5 items)

- **Severity:** Low ×5
- **Confidence:** High / Medium
- **Type:** Information disclosure, hardening
- **Status:** Proposed patches (read-only audit)

## L-2a — Absolute paths & raw errors leaked to the frontend
**Files:** `src-tauri/src/files.rs:65,124,128,200,307,313`; `commands.rs` (`.map_err(|e| e.to_string())` throughout).
**Problem:** error strings embed canonical paths (`format!("{}: outside the allowed files root", canon.display())`) and raw `std::io` errors → a renderer can probe existence and read back username/home layout, distinguishing not-found vs permission-denied for arbitrary paths.
**Fix:** return generic messages ("path is outside the allowed workspace", "cannot read file"); log details server-side only.
**Accept:** [ ] no `canon.display()` / raw `{e}` in user-facing `Err` strings across the confine/FS boundary.

## L-2b — Markdown link phishing (visible text ≠ destination)
**Files:** `src/components/markdown.tsx:20-21` (rendered by `Conversations.tsx:183,195`, `Command.tsx:133`, `Home.tsx:89`).
**Problem:** model output like `[https://your-bank.com](https://evil.example/steal)` renders a link whose text misrepresents the destination → prompt-injected phishing.
**Fix:** disclose mismatched destinations (`text !== url` → append `(url)`), and/or intercept `.md a` clicks to confirm the full URL before opening; route opens through the Tauri opener plugin with an http/https allowlist.
**Accept:** [ ] a link whose text differs from its href visibly shows the real destination before navigation.

## L-2c — Fragile markdown sanitizer pipeline + `escapeHtml` misses `'`
**Files:** `src/components/markdown.tsx:8-14` (`escapeHtml`), `20-29` (`inline`).
**Problem:** inline regexes run over already-generated HTML (the bold rule can inject `<strong>` inside an `href` value); `escapeHtml` handles `& < > "` but not `'`. Not exploitable today (attributes are double-quoted; captures can't contain `"`), but the safety is accidental — any future rule emitting a `"` or unquoted attribute becomes attribute-breakout XSS in a `dangerouslySetInnerHTML` sink fed by model output.
**Fix:** extract links/code spans to placeholders before running other inline rules, then substitute back; add `.replace(/'/g, '&#39;')` to `escapeHtml`. Add unit tests for `<img src=x onerror=1>`, `[x](javascript:alert(1))`, `[x](https://a/**b**")`.
**Accept:** [ ] link/code content is tokenized before other inline rules; `'` is escaped; XSS payload tests pass (render as inert text).

## L-2d — Unix-only file/sandbox permissions on a Windows target
**Files:** `src-tauri/src/files.rs:270-300` (`write_text`, `#[cfg(unix)]`), `ai.rs:377-387,574-580`.
**Problem:** 0600/0700 modes + directory fsync are Unix-only; on Windows the atomic-write temp and sandbox rely on default `%TEMP%` ACLs (per-user by default, so no live breach) and durability isn't flushed.
**Fix:** on Windows create the temp/sandbox with a restrictive DACL (or under `%LOCALAPPDATA%`) and use the platform durability equivalent; at minimum document the reduced guarantee.
**Accept:** [ ] Windows atomic writes/sandbox use owner-restricted ACLs, or the reduced guarantee is documented.

## L-2e — Ollama URL validation permissive; Anthropic `ready` unprobed
**Files:** `src-tauri/src/ai.rs:70-97` (`validate_ollama_url`), `281-286` (`status`).
**Problem:** `validate_ollama_url` allows any loopback port/path (would POST the full conversation to a non-Ollama local service); remote opt-in ships the conversation to any HTTPS host. Both require env control (already local compromise). Separately, the Anthropic provider reports `ready:true` on mere key presence (no probe), so a revoked/typo'd key shows green until first send.
**Fix:** pin the default Ollama port (`11434`) unless overridden and require an empty base path; label Anthropic status "key present (unverified)" or issue a cheap authenticated probe with a short timeout.
**Accept:** [ ] non-default Ollama port/path requires explicit opt-in; Anthropic status reflects an actual probe or is labeled unverified.
