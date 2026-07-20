# Bro (harness) — Security Audit

**Target:** `menqstudio/Bro` @ `979e564`
**Mode:** READ-ONLY. No source changed; findings + proposed patches only.
**Method:** 7 parallel Fable 5 auditors (one per security subsystem) → Opus verification of every Critical/High against source, including reconciliation where two auditors disagreed on severity. Isolated clone.
**Scale:** ~17,900 LOC Python (runtime/ + tools/) + 21 JSON schemas + signed control-plane config.

---

## What this system is (and how to read this report)

Bro is a **security-governance harness**: it contains a coding agent (Claude) behind an enforcement wall — signed execution leases, an Ed25519 trust root, a completion gate, workspace-scope confinement, a protected control plane, and an append-only audit trail. So the audit question is not "is there a SQL injection" — it is **"can a contained, possibly-malicious specialist agent defeat one of these controls?"**

The headline: **the cryptographic core is genuinely strong and, where the Ed25519 discipline is applied, sound.** Leases, task contracts, protected-authority, verifier receipts and the evidence chain are correctly signed, type-bound, replay-bounded, and fail-closed. The real findings are the places where that same discipline was **defined but not applied**, where a control is **POSIX-only on a Windows host**, or where the **integrity-coverage set has gaps**.

### Severity counts (post-verification)

| Severity | Count | Headline |
|---|---|---|
| **Critical** | 1 | `find` (& read-only shell verbs) classified read-only → scope/workspace bypass → arbitrary read + RCE/delete |
| **High** | 6 | Unsigned workspace binding · Windows `emit` fail-closed crash · Windows fail-**open** wall · forgeable audit trail · defeatable key revocation · protected-set gaps |
| **Medium** | 9 | env trust-root swap, POSIX-only STOP, conductor-by-env, base-runtime lease gap, scope matcher, root binding, key file perms, … |
| **Low** | 13 | dead controls, replay-surface gaps, hygiene |
| **Verified clean** | — | lease binding/forgery/expiry, capability ceiling, shell-injection, deserialization, contract signing, CI content |

### Three cross-cutting themes

1. **Windows is a second-class platform** — multiple controls degrade or fail on the actual target OS: the hook crashes while emitting its own verdict (H-2), the wall is fail-**open** when `python3` is unresolvable (H-3), the STOP controller is inert (M-3), the pin-file tamper check is skipped (M-2), lease process-trees aren't reaped (L-9).
2. **Signed-vs-unsigned asymmetry** — Ed25519 is applied beautifully to leases/contracts/protected-authority/evidence, but a few load-bearing anchors rest on unsigned env/JSON: the workspace binding (H-1), the conductor identity (M-4), the audit-log head (H-4), and registry freshness (H-5).
3. **Integrity coverage gaps** — the protected/digest set misses trust-granting and CI-executed files: most of `tools/`, `tests/`, `requirements-ci.txt`, `.bro/policy.json` (H-6).

---

## CRITICAL

### C-1 — `find` (and other "read-only" shell verbs) bypass scope & workspace gates → arbitrary read + RCE/delete
**Files:** `runtime/bro_security.py:38-41` (`READ_ONLY_SHELL`), `runtime/bro_authorization.py:161-162` (`_shell_capabilities`)
**Confidence:** High — independently found by 2 auditors and verified in source.

`find` is on the read-only allowlist:
```python
READ_ONLY_SHELL = {"cat","echo","find","get-childitem","get-content","ls","pwd",
    "select-string","test-path","type","where","where-object","whoami"}
```
so `analyze_command` marks any `find` invocation `mutating=False`, `recognized_read_only=True`, and `_shell_capabilities` maps it to `("READ_LOCAL",)`. But `find` is a general executor/mutator: `find . -delete`, `find . -exec <cmd> {} +`, `find . -fprintf ...`. `-delete` and `+`-terminated `-exec` are a **single shell segment** — no redirection, no `$(...)`, no `;` — so `split_shell` (which blocks those) never trips, and the command sails through as `READ_LOCAL`. Because task-scope (`enforce_scope`) and the workspace gate only constrain **mutating** actions (and read-only verbs are emitted with **empty targets**), the target is invisible to every gate.

**Impact:** a contained specialist runs `find . -exec sh -c '…' {} +` (arbitrary code execution) or `find / -delete` (arbitrary deletion), or `cat /etc/passwd` / `get-content <anything>` (read any host file) — all authorized as a machine-local read. This is the single most severe defeat of the command classifier; it collapses the confinement kernel.

**Fix:** remove `find` from `READ_ONLY_SHELL`; if a read-only search primitive is needed, hard-deny `-exec -execdir -ok -okdir -delete -fprint* -fls` and treat any unrecognized flag as mutating (fail-closed, matching the `git -c` allowlist philosophy). Populate `targets` for read-only verbs too, and enforce scope/workspace containment on **read** targets, not only mutations.

---

## HIGH

### H-1 — Workspace binding is declared operator-signed but loaded as unauthenticated JSON
**Files:** `runtime/bro_workspace.py:114-148` (`load_workspace`); contrast `runtime/bro_control_plane.py:138-145`
**Confidence:** High — found by 3 auditors; **severity reconciled from a Critical claim to High after source verification** (see note).

`bro_signature.py:85` classifies `"workspace-binding": OPERATOR` (an Ed25519-signable type), yet `load_workspace` reads it as raw JSON from an agent-reachable env var and verifies **no signature**:
```python
raw = os.getenv("BRO_WORKSPACE_BINDING")
value = json.loads(binding_path.read_text(encoding="utf-8"))   # no verify_artifact
```
The binding supplies `allowed_paths`, `prohibited_paths`, `allowed_remote_repository`, `root`, `control_plane_digest`. The codebase's own threat model defends the identical exposure for `BRO_PROTECTED_AUTHORITY` (Ed25519-verified "because a builder can point the var at a file it wrote") — the workspace binding is the one local-authority artifact that received no such protection.

**Verification note (Critical → High):** one auditor rated this Critical, arguing a forged binding lets an attacker set `control_plane_digest` to a tampered tree and defeat control-plane integrity entirely. I read `verify_control_plane_digest` (`bro_protected.py`): it **computes** `current = compute_control_plane_digest(root, manifest)` and rejects on mismatch — the bound digest must equal ROOT's real digest, and writing protected files is independently gated by the **signed** protected-authority. So control-plane integrity is **not** defeated. The real, confirmed impact is: a forged binding sets `allowed_paths:["**"]`/`prohibited_paths:[]`, defeating operator-defined **workspace scope for reads** (reads have no second scope gate → exfiltrate operator-restricted files inside the worktree, incl. `.git`/secrets), bypassing workspace-level write prohibitions for paths still inside the signed contract scope, and neutralizing `verify_workspace_remote`. That is a High, not a full break.

**Fix:** in `load_workspace`, require and `verify_artifact(document, "workspace-binding", load_trusted_keys(root))` before trusting any field, and jointly enforce the payload's `control_plane_digest`/`workspace_id` against the signed lease's.

### H-2 — The fail-closed hook crashes while emitting its own verdict on non-UTF-8 stdout (Windows)
**Files:** `runtime/bro_hook.py:26` (`emit`), `188-214` (`fail_closed`/`__main__`)
**Confidence:** High — found by 2 auditors **and reproduced live: this is the exact bug that wedged this very session.**

```python
def emit(obj): print(json.dumps(obj, ensure_ascii=False))
```
On Windows `sys.stdout` is the locale code page (cp1252), not UTF-8. Decision reasons embed attacker-influenced text — target paths, exception strings (`target outside task scope: {path}`), and at session-start the full `canonical_context()` file bodies. Any character outside cp1252 (em-dash, smart quote, accented filename, emoji) makes `print` raise `UnicodeEncodeError`. The recovery path `fail_closed` calls the **same** `emit`, so it throws again *inside* the `except` block → uncaught → traceback, non-zero exit, **no verdict emitted**. As the docstring concedes, "the enforcement point simply disappears."

**Impact (observed):** at `session-start` the mandatory full-read receipt + canonical-context injection are silently dropped (startup contract broken); at `pre-tool` the gate collapses to blanket denial or, worse, disappears. In this session a `UnicodeEncodeError` at position ~25971 (a canonical-doc body) fail-closed-cascaded and wedged every tool until hooks were disabled out-of-band. One non-ASCII byte degrades or halts enforcement for the whole session.

**Fix:** force UTF-8 at import (`sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")`) and/or `ensure_ascii=True` for the machine-readable output; give `fail_closed` a last-resort writer built with `errors="backslashreplace"` that can never itself raise.

### H-3 — Enforcement wall is fail-OPEN on Windows when `python3` is unresolvable
**Files:** `.claude/settings.json` (all hook commands wire `python3 …`), `runtime/bro_hook.py:194` (deny delivered as exit-0 JSON), `.github/workflows/verify.yml` (live-wiring assured Linux-only)
**Confidence:** High — verified in source.

Every hook is wired as `python3 "$CLAUDE_PROJECT_DIR/runtime/bro_hook.py" …`. On Windows `python3` is frequently **not on PATH** (Windows uses `python`/the `py` launcher; `python3` is often a Store alias or absent). A PreToolUse hook blocks only via exit 2 / a deny payload; a hook whose **interpreter fails to launch** (exit 9009/127) is a non-blocking error, so the tool call **proceeds**. CI itself concedes `python3` isn't on the Windows runner and runs the live-wiring assurance (`bro_live_validate.py`) **Linux-only**, so no check ever detects dead wiring. Net: on a Windows host without a resolvable `python3`, review-mode read-only, protected-control-plane denial, scope gates and the full-read wall are all silently absent.
> Corroborating signal: this session's *local* checkout had been hand-patched to `python` (not `python3`) — evidence the canonical wiring doesn't resolve on Windows.

**Fix:** wire an interpreter resolvable on all supported OSes (a wrapper that resolves `py -3`/`python`/`python3`, or an absolute path), and add a **Windows** live-wiring assurance leg to CI so fail-open wiring trips a red build.

### H-4 — The audit trail is forgeable by its own writer (unkeyed self-anchored chain + manifest-gated restore)
**Files:** `runtime/bro_audit_log.py:115-172` (`append`/`verify`), `tools/bro_backup.py:212-215` (`verify_archive`/`restore`)
**Confidence:** High.

The audit ledger is a plain **unkeyed** SHA-256 hash chain plus a co-located plaintext `.head` sidecar written by the same unprivileged writer. `verify()` recomputes from `GENESIS` and checks the head — but an attacker who can write the ledger (it lives beside the recovery store / session state the agent already writes) drops records, recomputes the chain, and rewrites `.head`; `verify()` returns green. `laws/registry.json` advertises `integrity_level: "Hash-Chained"` but the real property is `trust_source: "Self"`. The **evidence chain** (`bro_evidence.py`) does this correctly with an Ed25519 `evidence-head`; the audit ledger never adopted the same anchor. Compounding it, backup **restore** decides whether to chain-verify a file from the **attacker-supplied manifest** (`if entry.get("audit_chain") is not None`) and the SHA-256 it checks is also attacker-chosen — a crafted archive with `"audit_chain": null` restores a forged ledger while the tool prints `GREEN: archive verified`.

**Fix:** sign the audit head with a recorder/operator Ed25519 authority (mirror `evidence-head`) and verify that signature in `verify()`; derive "is a ledger" from the `*.jsonl` suffix on the archived file (not the manifest), and sign the backup manifest.

### H-5 — Key revocation is defeatable: the trusted-key registry has no anti-rollback binding
**Files:** `runtime/bro_signature.py:271-319` (`load_trusted_keys`), `242-268` (pin resolution)
**Confidence:** High.

The external pin (`BRO_OPERATOR_ROOT_PUBKEY[_FILE]`) fixes the operator-root **identity** but not **which registry version** is current. `load_trusted_keys` verifies the operator signature and the key's presence, but never compares `issued_at_epoch` (or a monotonic counter) to a trusted floor. Revocation works by publishing a new registry marking a leaked key `revoked` — but an attacker simply **restores an earlier, still-operator-signed registry** in which that key is `active`, and every signature (including one from the leaked key) verifies again. In-repo revocation is inert without an external monotonic reference.

**Fix:** pin a monotonic `registry_version` (or minimum `issued_at_epoch`, or the sha256 of the authorized registry) in the operator-controlled out-of-repo anchor, and reject any registry below it in `load_trusted_keys`.

### H-6 — Integrity-coverage gaps: trust-granting & CI-executed files sit outside the protected/digest set
**Files:** `config/protected-control-plane.json` (`protected_roots`/`digest_roots`)
**Confidence:** High.

The protected set covers `config/**`, `runtime/**`, `schemas/**`, `laws/**`, `.github/workflows/**` — but misses files that grant or gate trust:
- **`tools/`**: only 3 of 14 protected. Unprotected: `bro_traceability.py` (the **registered validator** for `meta-layer`/`runtime-dependencies` in `sst-registry.json`), `bro_live_validate.py` (CI's enforcement-liveness gate), `bro_supervisor.py` (issues leases), `broctl.py` (builds `trusted-keys.json`), `bro_authorize_specialist.py`, `bro_run_receipt.py`. Editing `bro_live_validate`/`bro_traceability` to always-pass neuters validation without tripping access denial or lease digest mismatch.
- **`requirements-ci.txt`**: the sole CI supply-chain input (installed `--require-hashes`), editable by a standard builder with self-supplied matching hashes; not in `digest_roots`, so it doesn't perturb the lease-bound `control_plane_digest`.
- **`tests/**`**: CI gates on `unittest discover -s tests`; a builder can weaken policy tests in the same change that weakens the runtime and stay green.
- **`.bro/policy.json`**: selects the operating mode (`default_mode`); unprotected → flip `review` → `work`, removing the default-deny posture.

**Fix:** add `tools/**`, `tests/**` (at least `tests/catalog.json` + policy suites), `requirements-ci.txt`, and `.bro/policy.json` to both `protected_roots` and `digest_roots`.

---

## MEDIUM

- **M-1 — Env-var operator anchor is always accepted** (`bro_signature.py:254-268`). `BRO_OPERATOR_ROOT_PUBKEY` (raw env) is co-equal to the file pin with no mode gate; an attacker controlling the verifier env + writing `trusted-keys.json` swaps the entire Ed25519 root by self-signing a registry. **Fix:** gate the env anchor behind an externally-set CI flag, or drop it outside CI.
- **M-2 — Pin-file tamper check is POSIX-only** (`bro_signature.py:234`). The group/other-writable guard is skipped on Windows, so a user-writable pin file is accepted. **Fix:** verify owner-only ACL on Windows or refuse the file pin there.
- **M-3 — STOP controller is POSIX-only** (`bro_stop_controller.py:45,100,110,123`). `os.killpg`/`/proc` don't exist on Windows → `terminate_group` raises before the `unstopped-process` incident is appended → the halt escape-hatch is inert **and** silent on the Windows target. **Fix:** Windows Job Object / `taskkill /T /F`, and always append the incident on any teardown error.
- **M-4 — Conductor identity & stop-exemption rest on env vars only** (`bro_policy.py:98-105`, `bro_completion.py:440-474`). `is_conductor` = `BRO_ROLE == bro && BRO_AGENT_ID == bro-000`, and the stop exemption additionally needs only an empty `BRO_TASK_CONTRACT`. Anyone who can set the harness env is the conductor (read + delegate + zero-evidence turn-end). Bounded (conductor mutation still denied), but the most privileged role is the only principal not cryptographically authenticated. **Fix:** bind the conductor to a signed session grant; log every exemption stop.
- **M-5 — Base orchestration runtime is the weaker path** (`bro_orchestration_runtime.py:308-336,447-479`). The base class checks only "actor is assignee" — no `_require_lease`, no `_claim_guard` — so it grants authority to an expired/released/revoked lease and allows double-claims; only `…RuntimeV1` wraps the guards. Enforcement depends on V1 always being the class in use, which isn't enforced in code. **Fix:** fold the lease/claim guard into the base methods (or make them abstract).
- **M-6 — Scope matcher is prefix-only: `*` over-permits, globs under-block** (`bro_security.py:225-230`, `bro_contracts.py:108-115`). `path_allowed` treats bare `*`/`.` as match-all (so `scope:["*"]` disables confinement) and does literal-prefix matching, so a glob prohibition like `["**/*.env"]` **never fires** — while the parallel `bro_workspace.matches_pattern` implements globs correctly, so the two enforcement layers disagree. **Fix:** share one glob implementation; reject glob metacharacters in `safe_repo_path`; drop the `*`/`.` match-all shortcut.
- **M-7 — `workspace.root` is never tied to `ROOT`** (`bro_control_plane.py:66-76`). Digest/repository gates verify against `ROOT`; the workspace-scope gate resolves targets against the binding-supplied `workspace.root`, with no assertion they're equal. **Fix:** require `_real(workspace.root) == _real(ROOT)`, fail closed on mismatch.
- **M-8 — Workspace binding expiry is never enforced** (`bro_workspace.py:126-148`). `expires_at_epoch` is stamped (8h TTL) but never read; a leaked/old binding never expires. **Fix:** parse and reject `now >= expires_at_epoch`, fail closed if missing.
- **M-9 — `broctl` writes unencrypted private keys with default permissions** (`tools/broctl.py:116-120`). `cmd_keygen` writes `issuer.json`/`operator-root.json` (cleartext `private_key`) with umask perms, unlike the `0o600` used elsewhere — on a shared host another local account reads the issuer key and mints valid leases. **Fix:** `os.open(..., O_CREAT|O_EXCL, 0o600)`; refuse world-readable/writable out-dirs.

---

## LOW

- **L-1** — Mode-grant `nonce` is validated but never consumed (no single-use). `bro_contracts.py:346`. Bound by session/head/tree so replay is inert today; consume it or remove it.
- **L-2** — Identity PreToolUse hook trusts an unsigned env-referenced profile (canonical-form check, not signature). `bro_identity_hook.py:57`. Verify via the signed mode-grant binding.
- **L-3** — `max_tool_calls` is dead code — never counted; the ledger enforces single-use instead. `bro_execution_lease.py:130`. Enforce it or remove the misleading field.
- **L-4** — Evidence head fetched by `task_id` with no monotonicity binding; a retained older signed head enables a self-consistent truncated chain if the store path is influenced. `bro_evidence.py:71`. Bind `evidence_head_sha256` into the signed manifest.
- **L-5** — Completion manifest carries `issued_at_epoch` but the gate never checks freshness/expiry (unlike the verifier receipt), so a stale GREEN manifest replays if the repo is rolled back to the candidate. `bro_completion.py:221`. Add a freshness window + per-turn nonce.
- **L-6** — Control-plane digest excludes `.pyc`/`__pycache__`, leaving a bytecode-shadowing gap. `bro_protected.py:72`. Run with `-B`/`sys.dont_write_bytecode` and assert no `__pycache__` under digest roots.
- **L-7** — Hook authorize/settle decisions are not written to the audit ledger (only supervisor lease issuance is). `bro_control_plane.py:100`. Emit an audit record per authorize/settle verdict.
- **L-8** — Control-room-API actor identity is self-asserted string-matching, not authenticated. `bro_control_room_api.py:328`. Read-only, so no direct mutation; bind command authority to a signed artifact before any consumer trusts `valid:true`.
- **L-9** — On Windows the supervisor doesn't group-reap the builder's lease-bearing process tree; a grandchild orphan retains lease context. `tools/bro_supervisor.py:307`. Use a Windows Job Object (kill-on-close).
- **L-10** — `.gitignore` has no key-material patterns and `broctl` writes cleartext keys to an arbitrary dir; a keydir inside the repo commits cleanly. Add `*.key`/`keys/` patterns; make broctl refuse in-repo out-dirs.
- **L-11** — `production:false` dev registry is accepted on the production pin path (`production` flag never checked). `bro_signature.py`. Refuse `production:false` when the pin is the production file path.
- **L-12** — Secret scanner is precision-over-recall by design; untagged high-entropy secrets pass into recovery/quarantine records. `bro_secrets.py`. Add an entropy heuristic for known credential-carrying fields if stronger DLP is wanted.
- **L-13** — Schema replay-surface gaps: completion-manifest has no `expires_at_epoch`/`nonce`; mode-grant leaves `grant_id`/`session_id`/`agent_id`/`role` as unconstrained strings. Tighten to match the execution-lease schema.

---

## Verified CLEAN (do not re-investigate)

- **Lease binding/reuse/forgery/expiry** — `validate_execution_lease` cross-checks task/agent/session/repo/branch/worktree/head/tree/digest/workspace against live values; Ed25519-verified against the externally-pinned root; atomic `O_EXCL` reservation; single-use ledger; bounded 60s skew. A lease for X cannot be replayed for Y, and a builder cannot mint one.
- **Capability ceiling** — `allowed_capabilities ⊆ CLASS_CAPABILITIES`; neither class has `DELETE`/`WRITE_EXTERNAL`/`USE_CREDENTIAL`/`PUBLISH`, so `rm`, `gh`, and push can never be leased.
- **Shell/deserialization injection** — no `shell=True`, `os.system`, `eval`, `exec`, `pickle`, or `yaml.load` anywhere; every subprocess uses list-argv; `split_shell` blocks `$()`, backticks, and redirection; `git -c`/config uses an allowlist; `_exe` normalizes case/`.exe`.
- **Contract & artifact signing** — task contract is Ed25519-bound (pointing `BRO_TASK_CONTRACT` at an attacker file breaks the signature); builder ≠ verifier is cryptographically enforced; `_require_signer_identity` stops identity theft; artifact-type→authority binding holds at load and verify; no private keys committed (238-commit history verified).
- **Mode elevation** — `enforce_grant_bindings` requires `grant.mode == task.mode == runtime mode` over a signed grant; review mode denies all mutation/orchestration.
- **CI content** — `pull_request` (not `pull_request_target`); no `${{ github.event.* }}` in `run:` steps; explicit `permissions: contents: read`; actions SHA-pinned; `--require-hashes`; deps are legitimate exact-pinned packages (no typosquats).

## Reconciliations & corrections (from the verification pass)
- **Workspace binding rated Critical by one auditor → downgraded to High (H-1):** `verify_control_plane_digest` computes ROOT's real digest and protected writes need signed authority, so control-plane integrity is not defeated — the impact is workspace-scope/remote, not arbitrary control-plane writes.
- The two "read-only shell" auditors independently converged on **C-1** (find); kept as the sole Critical after source confirmation.

---

## Suggested remediation order
1. **C-1** `find`/read-only-shell classifier — the confinement kernel is bypassed; fix first.
2. **H-2 / H-3** Windows enforcement (emit UTF-8 + fail-closed writer; resolvable interpreter + Windows CI leg) — the wall is currently degradable/absent on the target OS.
3. **H-1** sign & verify the workspace binding.
4. **H-4 / H-5** anchor the audit head + registry freshness to Ed25519/monotonic references.
5. **H-6** extend `protected_roots`/`digest_roots` to `tools/**`, `tests/**`, `requirements-ci.txt`, `.bro/policy.json`.
6. **M-1..M-9**, then the **L** cluster.
