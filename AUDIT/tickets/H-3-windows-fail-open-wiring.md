# H-3 — Enforcement wall is fail-OPEN on Windows when `python3` is unresolvable

- **Severity:** High
- **Confidence:** High (source-verified)
- **Files:** `.claude/settings.json` (all hook commands), `runtime/bro_hook.py:194` (deny delivered as exit-0 JSON), `.github/workflows/verify.yml` (live-wiring Linux-only)
- **Status:** Proposed patch (read-only audit)

## Problem
Every hook is wired as `python3 "$CLAUDE_PROJECT_DIR/runtime/bro_hook.py" …`. On Windows `python3` is frequently not on PATH (Windows uses `python` / the `py` launcher; `python3` is often a missing Store alias). A PreToolUse hook blocks only via exit 2 or a deny payload; a hook whose **interpreter fails to launch** (exit 9009/127) is a *non-blocking* error, so the tool call **proceeds**. CI concedes `python3` isn't on the Windows runner and runs the live-wiring assurance (`bro_live_validate.py`) **Linux-only**, so nothing detects dead wiring. Net: on a Windows host without a resolvable `python3`, review-mode read-only, protected-control-plane denial, scope gates, and the full-read wall are all silently absent.

> Corroborating: this session's local checkout had been hand-patched to `python` — evidence the canonical `python3` wiring doesn't resolve on Windows.

## Fix
1. Wire an interpreter resolvable on all supported OSes — a small launcher (resolve `py -3` → `python3` → `python`, first that exists) or an absolute interpreter path, instead of bare `python3`.
2. Add a **Windows** leg to CI (`verify.yml`) that runs the live-wiring assurance (`bro_live_validate.py`) so fail-open wiring produces a red build.
3. Consider a defense-in-depth self-check: on session-start, assert the hook interpreter resolves and fail closed (block) if not.

## Acceptance criteria
- [ ] Hooks fire on a Windows host where only `python`/`py` (not `python3`) exists.
- [ ] CI runs a live-wiring check on a Windows runner and fails if any hook is non-blocking.
- [ ] A deliberately-broken interpreter path is detected (red build), not silently fail-open.
