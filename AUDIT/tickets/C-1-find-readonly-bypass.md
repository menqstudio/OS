# C-1 — `find` (& read-only shell verbs) bypass scope/workspace gates → arbitrary read + RCE/delete

- **Severity:** Critical
- **Confidence:** High (2 auditors independently + source-verified)
- **Files:** `runtime/bro_security.py:38-41` (`READ_ONLY_SHELL`), `runtime/bro_authorization.py:161-162` (`_shell_capabilities`), scope enforcement `runtime/bro_policy.py:264-268`
- **Status:** Proposed patch (read-only audit)

## Problem
`find` is on the read-only allowlist, so `analyze_command` marks any `find` invocation `mutating=False` / `recognized_read_only=True` and `_shell_capabilities` maps it to `("READ_LOCAL",)`. But `find` executes and mutates:
- `find . -delete` — arbitrary deletion
- `find . -exec sh -c '…' {} +` — arbitrary code execution
- `find / -fprintf out …`, `cat /etc/passwd`, `get-content <path>` — arbitrary host read

`-delete` and `+`-terminated `-exec` are a single shell segment (no redirection / `$()` / `;`), so `split_shell` never trips. Scope (`enforce_scope`) and the workspace gate only constrain **mutating** actions, and read-only verbs are emitted with **empty targets**, so the target is invisible to every gate — the command is authorized as a machine-local read regardless of mode.

## Fix
1. Remove `find` from `READ_ONLY_SHELL`.
2. If a read-only search primitive is needed, gate `find` behind an argument inspector that hard-denies `-exec -execdir -ok -okdir -delete -fprint -fprintf -fls`, and treats any unrecognized flag as mutating (fail-closed), mirroring the `git -c` `READ_SAFE_CONFIG` allowlist.
3. Populate `CommandInfo.targets` for read-only shell verbs, and enforce scope/workspace containment on **read** targets too — a read outside the workspace must be denied exactly like a direct `Read` of an absolute path.

## Acceptance criteria
- [ ] `find . -delete` and `find . -exec … {} +` are classified mutating (or denied), not `READ_LOCAL`.
- [ ] `cat`/`get-content`/`type` on a path outside the workspace scope is denied.
- [ ] A benign `find`/`ls` within scope still succeeds.
- [ ] A regression test covers `find -delete`, `find -exec`, and an out-of-scope read; policy test suite stays green.
