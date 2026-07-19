# Bro Operator Runbook

Operational procedures for running the Bro enforcement runtime: enforcement
modes and shadow rollout, the machine-local state it depends on, recovering a
failed or interrupted mutation, and backing up / restoring durable state.

This runbook describes behaviour that is merged and covered by tests. It is
operator-facing: everything here is driven by environment variables the operator
controls (the same trust basis as `BRO_MODE`/`BRO_ROLE` — the hook reads the
harness process environment, which an agent's own tool subprocesses cannot
mutate) and by `tools/bro_backup.py`. See `docs/OPERATING_MODES.md` for the
review/work/release model and `docs/ARCHITECTURE.md` for the control plane.

## 0. First: verify deployment posture

Before the runtime enforces anything, prove the environment it runs in is
hardened. `tools/bro_deploy_preflight.py` is a fail-closed check that turns the
configuration below from prose into a gate:

```
python3 tools/bro_deploy_preflight.py
```

It exits non-zero — printing each `RED:` reason — unless all of the following hold:

- **The operator-root pin comes from a file.** `BRO_OPERATOR_ROOT_PUBKEY_FILE` is
  set to an operator-controlled file, outside the repo, owner-only, resolving to the
  key that signed the registry. The raw `BRO_OPERATOR_ROOT_PUBKEY` env var is for CI
  only; a production deployment that relies on it is reported un-hardened.
- **The registry is hardened.** It authenticates against that pin, carries the
  owner-held `recovery` authority, and every `builder`/`verifier` key is bound to a
  `subject_agent_id`, so its signatures are tied to an agent identity.
- **Ledgers are external.** Every configured ledger/store
  (`BRO_EXECUTION_LEASE_LEDGER`, `BRO_RECOVERY_STORE`, `BRO_TASK_LOCK_LEDGER`,
  `BRO_EVIDENCE_STORE`, `BRO_RELEASE_LEDGER`, `BRO_SHADOW_LEDGER`) is an absolute
  path outside the checkout, and `BRO_ENFORCEMENT=shadow` is never left without its
  `BRO_SHADOW_LEDGER` (which would fail open).

This is a deployment check, not a CI step: CI legitimately pins via the env var,
which the preflight — correctly — reports as un-hardened for production.

Two owner responsibilities the preflight cannot check from inside the process, and
which remain yours: the `recovery` private key is held **offline** (the registry
ships only its public key), and the runner producing execution-receipt worktree
snapshots runs under an **OS identity distinct** from the builder, so the snapshot a
receipt attests cannot be mutated by the process it polices.

## 1. Machine-local state

Durable runtime state lives **outside** the repository by contract, on
operator-controlled paths supplied by environment variables. Each must be an
absolute path outside the checkout; the runtime refuses one that resolves inside
the repository.

| Env var | Holds | Shape |
| --- | --- | --- |
| `BRO_TASK_LOCK_LEDGER` | active worktree/task locks | directory of `<hash>.json` |
| `BRO_EXECUTION_LEASE_LEDGER` | lease reservations | directory of `<hash>.active` / `.used` / `.ambiguous` |
| `BRO_RECOVERY_STORE` | per-task transaction journals | directory of `<hash>.state.json` |
| `BRO_SESSION_STATE_DIR` | per-session freeze markers | directory |
| `BRO_SHADOW_LEDGER` | shadow would-block records | append-only `*.jsonl` (+ `.head`) |

The `*.jsonl` ledgers are append-only and hash-chained with a `.head` anchor, so
mid-chain tampering and tail truncation are both detectable
(`runtime/bro_audit_log.py`).

## 2. Enforcement modes

The wall runs in one of two enforcement modes, selected by `BRO_ENFORCEMENT`:

- **`enforce`** (default, and any value other than `shadow`): the PreToolUse /
  PostToolUse gate blocks what policy denies. This is the production posture.
- **`shadow`**: the gate **observes** instead of blocking. A decision it would
  have blocked is recorded to `BRO_SHADOW_LEDGER` and the action is allowed to
  proceed, so you can measure a candidate policy against real traffic before
  enforcing it.

### Fail-safe rules (important)

Shadow softens a block **only** when the decision was durably recorded:

- `BRO_ENFORCEMENT=shadow` **without** a usable `BRO_SHADOW_LEDGER` (missing,
  in-repo, or unwritable) falls back to **enforce**. A bypass that cannot be
  recorded is a bypass that is not granted.
- Shadow softens **policy verdicts only**. An unexpected hook fault still denies
  (`fail_closed`), because a malfunctioning gate is not a policy decision.
- The Stop / completion gate stays enforced in shadow (session-end evidence
  discipline is not real-traffic blocking).

### Shadow rollout procedure

1. Choose an external ledger path and export it:
   ```
   export BRO_SHADOW_LEDGER=/var/lib/bro/shadow-ledger.jsonl
   export BRO_ENFORCEMENT=shadow
   ```
2. Run representative traffic.
3. Review what enforcement *would* have blocked:
   ```
   python3 -c "import sys; sys.path.insert(0,'runtime'); import bro_audit_log as a; \
     print('records=', a.verify('$BRO_SHADOW_LEDGER')); \
     [print(r['payload']['kind'], r['payload']['reason']) for r in a.read_all('$BRO_SHADOW_LEDGER')]"
   ```
   Each record's `payload.kind` is `pre-tool-deny`, `execution-settlement-block`,
   or `release-settlement-block`, with the denial `reason`.
4. When the would-block set is understood and acceptable, flip to enforce:
   ```
   export BRO_ENFORCEMENT=enforce   # or unset it
   ```

## 3. Recovering a failed or interrupted mutation

Every governed mutation opens a transaction: a `PREPARED` recovery journal is
written and an execution lease is reserved before the tool runs. Settlement moves
the journal to a terminal or recovery phase:

| Outcome | Recovery phase | Lease |
| --- | --- | --- |
| success | `MUTATION_RECORDED` | consumed (`.used`) |
| failure, reversible/compensatable | `RECOVERY_REQUIRED` | quarantined (`.ambiguous`) |
| failure, unknown effect | `QUARANTINED` | quarantined |
| failure, irreversible effect | `FAILED_WITH_IRREVERSIBLE_EFFECT` | quarantined |

A journal in any blocking phase **fences further mutation on that task**: a new
mutation attempt is denied at the transaction gate until the journal is cleared.
This is deliberate — an interrupted transaction must be reconciled, not raced.

### Procedure for `RECOVERY_REQUIRED`

1. Inspect the journal: `BRO_RECOVERY_STORE/<sha256(task_id)>.state.json`. The
   `before_head` / `before_tree` / `before_status_hash` fields record the repo
   state before the mutation.
2. Restore the worktree to that before-state (e.g. discard the partial change).
3. Prove recovery — only valid for `REVERSIBLE` / `COMPENSATABLE` effects, and
   only when the live repository state matches the recorded before-state:
   ```
   python3 -c "import sys; sys.path.insert(0,'runtime'); import bro_recovery as r; \
     print(r.prove_recovery('<task_id>', '<64-hex-proof-hash>'))"
   ```
   On success the journal advances to `REWORK_REQUIRED` and the task can be
   re-attempted. An `IRREVERSIBLE` or `UNKNOWN` effect cannot be proven recovered
   and requires manual operator adjudication.

## 4. Backup and restore

`tools/bro_backup.py` snapshots the machine-local state with a per-file SHA-256
manifest and restores it with the manifest re-verified. Append-only ledgers are
chain-verified at both backup and restore; a broken or truncated ledger is never
archived and never restored.

Back up (names are arbitrary labels; each source is a file or directory):
```
python3 tools/bro_backup.py backup --dest /backups/bro-2026-07-19 \
  --source shadow=$BRO_SHADOW_LEDGER \
  --source recovery=$BRO_RECOVERY_STORE \
  --source leases=$BRO_EXECUTION_LEASE_LEDGER \
  --source locks=$BRO_TASK_LOCK_LEDGER
```

Verify an archive without restoring:
```
python3 tools/bro_backup.py verify --archive /backups/bro-2026-07-19
```

Restore named sources into target directories (refuses to overwrite existing
files unless `--force`):
```
python3 tools/bro_backup.py restore --archive /backups/bro-2026-07-19 \
  --target recovery=$BRO_RECOVERY_STORE \
  --target shadow=$BRO_SHADOW_LEDGER
```

Integrity note: the append-only ledgers carry cryptographic anti-rewrite
protection via their hash chain; ordinary state files are checksummed against the
manifest, which detects corruption and truncation but is not a defence against an
adversary who rewrites both a file and its manifest entry.

## 5. Quick reference

| Task | Command |
| --- | --- |
| Verify deployment posture | `python3 tools/bro_deploy_preflight.py` |
| Enable shadow rollout | `export BRO_ENFORCEMENT=shadow BRO_SHADOW_LEDGER=<external .jsonl>` |
| Return to enforce | `unset BRO_ENFORCEMENT` (or set it to `enforce`) |
| Read shadow would-block records | `bro_audit_log.verify` + `read_all` on `BRO_SHADOW_LEDGER` |
| Back up state | `python3 tools/bro_backup.py backup --dest <dir> --source <name>=<path> ...` |
| Verify a backup | `python3 tools/bro_backup.py verify --archive <dir>` |
| Restore state | `python3 tools/bro_backup.py restore --archive <dir> --target <name>=<path> ...` |
| Prove a reversible recovery | `bro_recovery.prove_recovery(task_id, proof_hash)` |
