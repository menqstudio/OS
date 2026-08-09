# Bro Operator Runbook

Operational procedures for running the Bro enforcement runtime: enforcement
modes and shadow rollout, the machine-local state it depends on, recovering a
failed or interrupted mutation, and backing up / restoring durable state.

This runbook describes behavior that is merged and covered by tests. It is
operator-facing: everything here is driven by environment variables the operator
controls (the same trust basis as `BRO_MODE`/`BRO_ROLE` — the hook reads the
harness process environment, which an agent's own tool subprocesses cannot
mutate) and by `tools/bro_backup.py`. See `docs/OPERATING_MODES.md` for the
review/work/release model and `docs/ARCHITECTURE.md` for the control plane.

## 0. First: where this deployment's trust material comes from

Answer this before anything else, because the preflight in §0.1 checks a configuration that two very
different deployments produce in two very different ways.

**A. The desktop product (BroPS).** `apps/desktop/src-tauri/provision/` mints the whole set on the
user's machine at first launch and there is **no operator ceremony at all** — no USB, no key to
carry, nothing to renew. It mints one keypair per authority, signs the `trusted-key-registry` and a
`conductor-session`, and then **destroys the operator-root private half before it returns**. The
pin (`operator-root.pub`), the anti-rollback floor (`registry-min`), the registry itself
(`registry/config/trusted-keys.json`) and the provisioning manifest live under a machine-wide
**trust anchor** the application's own account cannot write:

| | Windows | POSIX (specified, never executed) |
| --- | --- | --- |
| Trust anchor | `%ProgramData%\BroPS\trust-anchor\` | `<POSIX_MACHINE_ROOT>/trust-anchor/` (read `anchor::POSIX_MACHINE_ROOT`) |
| App-side store (private keys, artifacts) | `%APPDATA%\studio.menq.brops\trust\` | `~/.local/share/studio.menq.brops/trust/` |
| Audit signer, when installed | under `%ProgramData%\BroPS\` | a separate uid, provisioned by the installer |

Provisioning runs **before the database is opened and aborts startup if it fails**, so an install
that could not establish its anchor does not run at all. On Windows the anchor is sealed with a
PROTECTED DACL whose OWNER RIGHTS (`S-1-3-4`) ACE grants read+execute only, applied up to the
machine root and re-measured against the OS on every launch. **On POSIX `anchor::seal` returns
`Unsupported`** — an owner may always `chmod` a directory it owns — so a POSIX deployment must have
the anchor directory created by a **different uid** (root, or a dedicated `brops-anchor` account),
mode `0755`, ancestors likewise, with provisioning run once as that account by the installer. That
branch has never executed.

> **Install ordering, and it is not recoverable.** The registry seals when provisioning returns —
> the operator root is destroyed at that moment — so the audit signer's published key must be
> admitted *while the registry is being signed*. **Register the signer service before the app's
> first launch**, or that machine can never have an audit-head anchor without being re-provisioned.
> Nothing automates this today: the signer's binaries ship in no installer.

**B. An engine-only deployment.** You provide the environment yourself, per §0.1 — and note up
front that **nothing in this repository can mint a PRODUCTION trust root.** `tools/broctl.py
build-registry` hardcodes `"production": false`, `keygen --production` refuses by name, and
`bro_signature` refuses a non-production registry whenever the pin comes from the production `_FILE`
path. The ceremony runs honestly end to end and produces a **development** root: enough to exercise
every path, **not** enough to close residual items O-2, O-3 or O-5.

### 0.0 `BRO_TRUSTED_REGISTRY_ROOT` — where the registry is read from

`load_trusted_keys` reads `<root>/config/trusted-keys.json`. Every caller used to pass the engine's
own tree, so the **development** registry committed at `config/trusted-keys.json` answered for
everything and a deployment that provisioned its trust material elsewhere was invisible (residual
item O-3). `BRO_TRUSTED_REGISTRY_ROOT` names the deployment's real registry root.

- **Unset** — the default, and what CI does — behaviour is byte-for-byte what it was.
- **Set** — fail-closed, and checked at least as strictly as the pin: an absolute path, no symlink at
  **any** component, an existing directory that actually holds `config/trusted-keys.json` as a
  regular non-symlink file, a directory the reading account cannot rewrite, and containing
  **neither the operator pin nor the anti-rollback floor**. The anchor deliberately does **not**
  move with the redirect, so one variable can never hand over both the registry and the thing that
  authenticates it. While it is set, a caller that names some *third* root is refused by name rather
  than quietly served a different registry from the rest of the process.

See `runtime/bro_signature.resolve_registry_root` and `tests/test_provisioned_registry_root.py`
(all 23 call sites AST-enumerated and frozen, so a new caller cannot reintroduce a split brain).

> **Deployment A does not set it for you.** `Provisioned::engine_env()` returns
> `BRO_OPERATOR_ROOT_PUBKEY_FILE`, `BRO_OPERATOR_REGISTRY_MIN_FILE`, `BRO_CONDUCTOR_SESSION_TOKEN`
> and `BRO_SESSION_ID` — and the desktop startup path deliberately does **not** export them; the
> list does not even include `BRO_TRUSTED_REGISTRY_ROOT`. So on a stock desktop install the engine
> still reads the committed development registry. Wiring the two is a deployment decision.

> `BRO_OPERATOR_ROOT_PIN_SELF_OWNED=acknowledged` short-circuits **every** custody rule in the
> runtime at once, not just the pin's. It is no longer set anywhere, and the anchor now passes those
> rules on its merits. Do not reintroduce it to make a refusal go away — the refusal is the check.

### 0.1 Then: verify deployment posture

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
| `BRO_SHADOW_LEDGER` | shadow would-block records | append-only `*.jsonl` (+ `.head`, and `.head.sig` when anchor custody is configured) |

Trust configuration is not runtime state, but it decides whether any of the above verifies:

| Env var | Holds | Notes |
| --- | --- | --- |
| `BRO_OPERATOR_ROOT_PUBKEY_FILE` | the out-of-registry operator-root pin | the production form; `BRO_OPERATOR_ROOT_PUBKEY` is the CI form. If both are set they must match |
| `BRO_OPERATOR_REGISTRY_MIN_FILE` | the registry anti-rollback floor | what makes revocation stick against a replayed older registry |
| `BRO_TRUSTED_REGISTRY_ROOT` | where `config/trusted-keys.json` is read from | §0.0; unset means the engine's own tree |
| `BRO_CONDUCTOR_SESSION_TOKEN` / `BRO_SESSION_ID` | the operator-signed `conductor-session` and the session it binds | required: `require_conductor_session_token` is `true` in `.bro/policy.json`, and an absent key, a wrong type or an unreadable policy all mean REQUIRED |
| `BRO_AUDIT_ANCHOR_SIGNER` / `BRO_AUDIT_ANCHOR_KEY_ID` | the audit-head signing command and its key id | deliberately two variables: a half-configuration is refused loudly rather than degrading to an unanchored ledger |

The `*.jsonl` ledgers are append-only and hash-chained with a `.head` anchor, so
mid-chain tampering and tail truncation are both detectable
(`runtime/bro_audit_log.py`).

**The plain `.head` is not a defence against the ledger's own writer** — a writer that truncates the
chain can recompute it and rewrite the head. That is what the **signed** head anchor is for
(residual item O-2). When anchor custody is configured, `append()` assembles the anchor payload,
signs it through `BRO_AUDIT_ANCHOR_SIGNER` **inside the same exclusive append lock**, and installs
it, so a signed head can never describe a chain another writer has already extended; and it refuses
to append at all to a ledger that already carries an anchor when no custody is configured, rather
than stranding it. A keyed `verify(path, keys=...)` then **requires** an anchor and raises
`AuditAnchorMissing` when there is none — *unanchored* is reported as a different fact from
*tampered*, because only one of them is the operator's to fix. Without `keys` the check is
structural only: sufficient against corruption, not against the writer.

The anchor's authority is `audit-anchor`, and **nothing in this repository mints it**. That is the
point: `evidence-recorder` and `operator-root` used to be accepted there, and on a deployment that
mints its own trust material both private halves sat in the ledger writer's own store — so the
writer could truncate the chain, recompute it, sign a fresh anchor with a key it already held, and a
keyed `verify()` returned green. The signing principal must be one the writer cannot become (a
Windows service under its own virtual account, or a separate uid on POSIX), publishing only its
public half for registration. `head_anchor_payload` / `attach_head_anchor` are the out-of-band half
for an operator who signs heads on a separate machine; they have no in-repo caller **by design**.

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
   only when the live repository state matches the recorded before-state. Recovery
   now requires an **owner-signed `recovery-proof` artifact** (a document signed by
   the offline owner-held `recovery` authority, bound to the task/record/before-state/
   effect-class/state-version), not a bare hex string — obtain that document, then
   pass it in:
   ```
   python3 -c "import sys, json; sys.path.insert(0,'runtime'); import bro_recovery as r; \
     print(r.prove_recovery('<task_id>', json.load(open('<owner-signed-recovery-proof.json>'))))"
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
| Point the engine at a provisioned registry | `export BRO_TRUSTED_REGISTRY_ROOT=<absolute root holding config/trusted-keys.json>` (§0.0) |
| Know which registry answered | unset ⇒ the engine's own tree, i.e. the committed **development** registry; see `runtime/bro_signature.resolve_registry_root` |
| Enable shadow rollout | `export BRO_ENFORCEMENT=shadow BRO_SHADOW_LEDGER=<external .jsonl>` |
| Return to enforce | `unset BRO_ENFORCEMENT` (or set it to `enforce`) |
| Read shadow would-block records | `bro_audit_log.verify` + `read_all` on `BRO_SHADOW_LEDGER` |
| Back up state | `python3 tools/bro_backup.py backup --dest <dir> --source <name>=<path> ...` |
| Verify a backup | `python3 tools/bro_backup.py verify --archive <dir>` |
| Restore state | `python3 tools/bro_backup.py restore --archive <dir> --target <name>=<path> ...` |
| Prove a reversible recovery | `bro_recovery.prove_recovery(task_id, proof_document)` (owner-signed `recovery-proof`) |
