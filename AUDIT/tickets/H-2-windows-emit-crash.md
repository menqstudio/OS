# H-2 — The fail-closed hook crashes while emitting its own verdict on non-UTF-8 stdout (Windows)

- **Severity:** High
- **Confidence:** High (2 auditors + **reproduced live — this bug wedged the audit session**)
- **Files:** `runtime/bro_hook.py:26` (`emit`), `188-214` (`fail_closed` / `__main__`)
- **Status:** Proposed patch (read-only audit)

## Problem
```python
def emit(obj): print(json.dumps(obj, ensure_ascii=False))
```
On Windows `sys.stdout` is the locale code page (cp1252), not UTF-8. Decision reasons embed attacker-influenced text — target paths, exception strings (`target outside task scope: {path}`), and at session-start the full `canonical_context()` file bodies. Any character outside cp1252 (em-dash, smart quote, accented filename, emoji) makes `print` raise `UnicodeEncodeError`. `fail_closed` calls the **same** `emit`, so it throws again *inside* the `except` block → uncaught → traceback, non-zero exit, **no verdict emitted**.

**Observed:** in this audit, a `UnicodeEncodeError` at position ~25971 (a canonical-doc body) fail-closed-cascaded at `session-start`, dropping the full-read receipt and canonical-context injection and wedging every subsequent tool until hooks were disabled out-of-band.

## Fix
1. Force UTF-8 at module import, independent of locale:
```python
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass
```
2. And/or emit machine-readable output ASCII-safe: `json.dumps(obj, ensure_ascii=True)`.
3. Make `fail_closed` build its reason with `errors="backslashreplace"` and use a last-resort writer that can never itself raise (e.g. `sys.stdout.buffer.write(data.encode("utf-8", "backslashreplace"))`).

## Acceptance criteria
- [ ] On a cp1252 console, a decision whose reason contains an em-dash / emoji / accented path emits valid JSON (no traceback, no empty output).
- [ ] `fail_closed` always emits a deny/block verdict even when the triggering exception's `str()` contains non-cp1252 characters.
- [ ] Session-start canonical-context injection succeeds with non-ASCII bytes in a canonical doc.
- [ ] A regression test feeds a non-encodable reason through `emit`/`fail_closed` and asserts a verdict is produced.
