# C-1 — `find` (& read-only shell verbs) bypass scope/workspace gates → arbitrary read + RCE/delete

- **Severity:** Critical
- **Confidence:** High (2 auditors independently + source-verified)
- **Files:** `runtime/bro_security.py:38-41` (`READ_ONLY_SHELL`), `runtime/bro_authorization.py:161-162` (`_shell_capabilities`), scope enforcement `runtime/bro_policy.py:264-268`
- **Status:** ◑ remediated in code, **not independently re-audited** (verified against the tree at `0efa99e`, 2026-08-07; per-criterion evidence below). See the `◑` legend in [`../README.md`](../README.md) — this is not a closure mark.

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
- [x] `find . -delete` and `find . -exec … {} +` are classified mutating (or denied), not `READ_LOCAL`.
  `find` is no longer in `READ_ONLY_SHELL` (`runtime/bro_security.py:43-46`); `analyze_find`
  (`:229-265`) hard-denies `FIND_DENIED_ACTIONS` (`:62-65`) and treats any unrecognized flag as
  mutating. Observed: `analyze_command("find . -delete")` → `mutating=True recognized_read_only=False`;
  same for `find . -exec sh -c echo {} +`.
- [x] `cat`/`get-content`/`type` on a path outside the workspace scope is denied.
  `READ_TARGET_SHELL` (`runtime/bro_security.py:52-54`) populates targets for path-taking read verbs
  (`:285-291`), and `_bind_workspace` runs `authorize_targets` on `classification.targets`
  (`runtime/bro_control_plane.py:92-93`) for reads as well as mutations. Observed:
  `analyze_command("cat /etc/passwd")` → `targets=('/etc/passwd',)` (previously empty).
- [x] A benign `find`/`ls` within scope still succeeds.
  Observed: `find . -name *.py` → `mutating=False recognized_read_only=True targets=('.',)`;
  `ls runtime` → `targets=('runtime',)`.
- [ ] A regression test covers `find -delete`, `find -exec`, and an out-of-scope read; policy test suite stays green.
  **Partially met.** `tests/test_review_containment.py:32` covers `find . -delete`, `cat /etc/passwd`
  and `git -C /tmp status` — but only as *review-mode* denials, which would still pass if
  `analyze_find` were reverted. No test asserts `analyze_find`'s classification directly, and no test
  exercises `find -exec` at all (grep for `find ` across `tests/*.py` returns only
  `test_review_containment.py:32` and `test_hooks_subprocess.py:337`, both `find . -delete` in review).
  The suite is green (1196 tests, 53 skipped, 2026-08-07).
