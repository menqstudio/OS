# Medium findings (9)

Read-only audit; each is a proposed patch and independently actionable.

---

## M-1 — Env-var operator anchor is always accepted
**File:** `runtime/bro_signature.py:254-268` (`resolve_operator_root_pin`), consumed at `294-305`.
**Problem:** `BRO_OPERATOR_ROOT_PUBKEY` (raw env) is co-equal to the file pin with no mode gate (the `_FILE` mismatch check only fires if both are set). An attacker controlling the verifier env + writing `trusted-keys.json` sets their own operator pubkey, writes a fully self-signed registry, and every downstream `verify_artifact` trusts attacker keys — the whole Ed25519 root swapped with no private key.
**Fix:** accept the env anchor only behind an externally-set CI flag (e.g. require `BRO_ENV=ci`), or drop the env path outside CI in favor of the file pin; ensure hook processes don't inherit an agent-writable environment.
**Accept:** [ ] outside CI, `BRO_OPERATOR_ROOT_PUBKEY` alone does not establish the trust root.

## M-2 — Pin-file tamper check is POSIX-only
**File:** `runtime/bro_signature.py:234`.
**Problem:** `if os.name == "posix" and (info.st_mode & (S_IWGRP|S_IWOTH))` — the group/other-writable guard is skipped entirely on Windows, so a pin file writable by the same principal as the repo is accepted (compounds M-1 on the Windows target).
**Fix:** verify owner-only ACL on Windows (`win32security`) or refuse the file pin on Windows and require an attested source; don't treat "not POSIX" as "no permission requirement".
**Accept:** [ ] a group/other/ACL-writable pin file is rejected on Windows.

## M-3 — STOP controller is POSIX-only → inert and silent on Windows
**File:** `runtime/bro_stop_controller.py:45,100,110,123`.
**Problem:** the mechanism is `os.killpg` + `/proc` scanning, neither of which exists on Windows. `terminate_group` raises `AttributeError` before `stop_all` reaches the `unstopped-process` audit branch — so the halt/freeze escape-hatch cannot stop a runaway builder subtree **and** records no incident, exactly when it matters.
**Fix:** on `os.name != "posix"`, use a Windows Job Object / `taskkill /T /F`; wrap `terminate_group` so any OS error still appends an `unstopped-process` incident. Document the runner-OS requirement if POSIX-only is intended.
**Accept:** [ ] on Windows, STOP either halts the tree or records an `unstopped-process` incident (never silently no-ops).

## M-4 — Conductor identity & stop-exemption rest on env vars only
**Files:** `runtime/bro_policy.py:98-105` (`is_conductor`), `runtime/bro_completion.py:440-474` (`authorize_conductor_stop`).
**Problem:** `is_conductor` = `BRO_ROLE == bro && BRO_AGENT_ID == bro-000` (both from `os.getenv`); the stop exemption additionally needs only a falsy `BRO_TASK_CONTRACT`. Anyone who can set the harness env becomes the conductor — read, delegate, and end a turn with zero completion evidence. Bounded (conductor mutation still denied) but the most privileged role is the only principal not cryptographically authenticated.
**Fix:** bind the conductor to a signed session grant (or a signed startup receipt), not plain env; at minimum log every conductor-exemption stop to the audit ledger.
**Accept:** [ ] setting `BRO_ROLE`/`BRO_AGENT_ID` alone does not grant the conductor exemption; every exemption stop is audit-logged.

## M-5 — Base orchestration runtime is the weaker path (no lease, double-claim)
**File:** `runtime/bro_orchestration_runtime.py:308-336,447-479`.
**Problem:** base `checkpoint/record_usage/submit_for_verification/complete_task/claim_next` only check "actor is the assignee" — no `_require_lease`, no `_claim_guard`. Only `…RuntimeV1` wraps the guards. The base class (public, importable, used at `tests/test_orchestration_runtime.py:128`) grants authority to an expired/released/revoked lease and permits two processes to double-claim. Safety is opt-in via subclass choice, not enforced.
**Fix:** fold the lease + `_claim_guard` requirement into the base mutation methods, or make the base class abstract for those entry points.
**Accept:** [ ] a mutation via the base class with an expired/released lease is denied; concurrent `claim_next` cannot double-claim.

## M-6 — Scope matcher is prefix-only: `*` over-permits, globs under-block
**Files:** `runtime/bro_security.py:225-230` (`path_allowed`), `runtime/bro_contracts.py:108-115` (`safe_repo_path`).
**Problem:** `match` treats bare `*`/`.` as match-all (so `scope:["*"]` disables confinement) and otherwise does literal-prefix matching — a glob prohibition like `["**/*.env"]` **never fires** against `src/.env`. The parallel `bro_workspace.matches_pattern` implements globs correctly, so the two enforcement layers disagree, and the `enforce_scope` layer is the one applied to shell-mutation targets.
**Fix:** share one glob implementation (`bro_workspace.matches_pattern`) across both layers, and/or have `safe_repo_path` reject glob metacharacters so scopes are provably literal; drop the `*`/`.` match-all shortcut.
**Accept:** [ ] `scope:["*"]` no longer disables confinement; a `["**/*.env"]` prohibition actually blocks `src/.env`; both layers agree on a shared test matrix.

## M-7 — `workspace.root` is never tied to `ROOT`
**File:** `runtime/bro_control_plane.py:66-76`.
**Problem:** the digest/repository gates verify against `ROOT`; `authorize_targets` resolves targets against the binding-supplied `workspace.root`, with no assertion they're equal — integrity can be verified on one tree while scope is checked against another (compounds H-1).
**Fix:** in `_bind_workspace`, require `_real(str(workspace.root)) == _real(str(ROOT))` (or drive all gates off one resolved root); fail closed on mismatch.
**Accept:** [ ] a binding whose `root` differs from `ROOT` is rejected.

## M-8 — Workspace binding expiry is never enforced
**File:** `runtime/bro_workspace.py:126-148`.
**Problem:** `expires_at_epoch` is stamped (8h TTL) by `bro_bind_workspace.py:72` but `load_workspace` never reads it (the field isn't even on the `Workspace` dataclass); a leaked/old binding never expires.
**Fix:** parse `expires_at_epoch`/`issued_at_epoch`, reject `now >= expires_at_epoch`, and fail closed if the field is missing/malformed. (Do this together with H-1's signature check.)
**Accept:** [ ] an expired binding is rejected at load.

## M-9 — `broctl` writes unencrypted private keys with default permissions
**File:** `tools/broctl.py:116-120` (`_write`, via `cmd_keygen`).
**Problem:** `cmd_keygen` writes `issuer.json`/`operator-root.json` (cleartext `private_key`) with umask perms (often other-readable), unlike the `0o600` used in `bro_security.py`/`bro_audit_log.py`. These are the signing keys for the whole lease/registry trust chain; on a shared host another local account reads the issuer key and mints valid leases.
**Fix:** create key files via `os.open(path, O_WRONLY|O_CREAT|O_EXCL, 0o600)` (and chmod existing); refuse to write into a world-writable/other-readable directory or a path inside the repo.
**Accept:** [ ] generated key files are owner-only (0600); writing to an unsafe/in-repo dir is refused.
