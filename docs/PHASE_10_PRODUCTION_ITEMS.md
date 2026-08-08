# Phase 10 — Production items: the O-1 … O-5 inventory and the release-signing gate

> **Why this file exists.** `MASTER_EXECUTION_ROADMAP.md` §Phase-10 makes *"O-1..O-5 closed or
> owner-signed-deferred (each audited)"* an exit criterion, and `docs/SECURITY_MODEL.md` §5 makes it a
> precondition for flipping the production `trusted_verified` gate. Until now the five items existed only as
> one-line summaries repeated in four documents (`CLAUDE.md` §6, `docs/SECURITY_MODEL.md` §4,
> `MASTER_EXECUTION_ROADMAP.md` §K, `PROJECT_STATE.md`) — **no file said what any of them actually
> requires**, and nobody could answer "what is O-2?" without grepping the engine. One of them is an accepted
> **HIGH**. This is the single normative inventory: per item, the exact engine code, the exact reason it is
> open, and the exact work that closes it.
>
> **This file is machine-enforced.** `tools/check_residual_items.py` (CI job
> `Residual engine items O-1..O-5 · inventory gate`) requires every item to be present with a severity that
> matches what `CLAUDE.md` and `docs/SECURITY_MODEL.md` assert, requires every cited engine path to exist,
> and refuses to let a status move off `OPEN` without a named sign-off. Prose can no longer drift.

---

## 0. Summary

| Item | Engine ticket | Severity | Status | Needs an Owner secret? | One-line defect |
|---|---|---|---|---|---|
| **O-1** | `L-6` / `H-6-protected-set-gaps` | HIGH | OPEN | no | the gate is now called on every digest-trusting path and the hook interpreters run `-B`; what stays open is the *read* half — CPython imports an existing `.pyc` before any Python check can run |
| **O-2** | `H-4-forgeable-audit-trail` (fix #1) | MEDIUM | OPEN | no | `append()` now attaches a signed head anchor and both production verifiers require one; OPEN until the Owner provides the signing custody — without it every ledger is honestly **UNANCHORED** and refused |
| **O-3** | `M-4` | MEDIUM | OPEN | **yes** (operator-signed session artifact) | code now fails closed and the shipped policy requires the token; OPEN until the Owner mints the `conductor-session` artifact and exports `BRO_CONDUCTOR_SESSION_TOKEN` |
| **O-4** | `L-8` | LOW | OPEN | yes | conductor actor is now signature-verified and an owner actor is refused by name; OPEN until an owner-authority artifact type + schema signature field exist |
| **O-5** | `L-4` | LOW | OPEN | **yes** (operator-signed `evidence-floor-anchor`) | the manifest binding is **now required and enforced**; the residual is a wiped-and-re-provisioned floor, which only an owner-signed anchor can distinguish from a first sighting |

**All five are engine-side code remediation, not credentials** — with the exception of O-3, whose
*deployment* half needs the Owner to mint an operator-signed artifact, and of the residual half of O-5,
whose "was this floor wiped or is this task new?" question no code can answer without an Owner-signed
`evidence-floor-anchor` (see §1 O-5; the code half of O-5 is built and enforced). None of them is closeable by editing
CI, `tauri.conf.json` or `docs/`; each is an audited change under `engine/` (the golden rule: *deliberate,
tested, never rushed*), on its own branch/PR with Owner approval.

> **Provenance correction.** `CLAUDE.md` §6 and `docs/SECURITY_MODEL.md` §4 both state these items are
> *"tracked on Bro's `fix/audit-followups`"*. **That ref does not exist** — not locally and not on
> `origin` (~60 branches, none matching), and `grep -rn "O-1\|O-2\|O-3\|O-4\|O-5"` over `engine/` returns
> **zero** hits: the O-numbering exists only in this outer repository. The engine tracks the items under
> its own IDs in `engine/AUDIT/tickets/`, and `SECURITY_MODEL.md` now points there instead of at the
> missing branch. `CLAUDE.md` is Owner-synced, so its line is left for the Owner and recorded here.
>
> **Correction to this correction (2026-08-07).** An earlier revision of this paragraph said *"O-2 has no
> engine-side ticket at all"*. It does: `engine/AUDIT/tickets/H-4-forgeable-audit-trail.md`, "The audit
> trail is forgeable by its own writer", whose fix #1 is verbatim this item and whose fixes #2 and #3 were
> already implemented. Only the `O-2` **label** is absent from `engine/`. The mistake came from grepping
> for the outer repo's numbering rather than reading the tickets, which is the same shape as the defects
> this inventory exists to catch — recorded rather than quietly edited away.

---

> ## ⛔ A blocker that applies to O-2, O-3 and O-5 together
>
> **Nothing in this repository can mint a PRODUCTION trust root.** `broctl build-registry`
> hardcodes `"production": false` and stamps *"DEVELOPMENT REGISTRY"*; `broctl keygen --production`
> refuses; and `bro_signature` refuses a non-production registry whenever the operator pin comes
> from the production file path (`BRO_OPERATOR_ROOT_PUBKEY_FILE`).
>
> So the ceremony in [`OWNER_CEREMONY.md`](./OWNER_CEREMONY.md) and
> [`DEBIAN_DEPLOYMENT.md`](./DEBIAN_DEPLOYMENT.md) runs honestly end to end and produces a
> **development** root. That is enough to exercise every path and watch each refusal become an
> acceptance. It is **not** enough to close these three items, and none of them may be recorded as
> closed on the strength of it.
>
> Found on 2026-08-08 by following the runbook rather than reading it — the first real attempt
> stopped at Step 0 and turned up four further defects in the document itself. Whoever closes this
> needs to decide how a production registry is minted, which is an Owner/architecture decision
> rather than a missing function.

## 1. The items

### O-1 · bytecode-shadow

- **Severity:** HIGH
- **Status:** OPEN
- **Owner secret needed:** no
- **Engine ticket:** `engine/AUDIT/tickets/H-6-protected-set-gaps.md` (also `L-6`); independent audit `D-09`
- **Engine code:** `engine/runtime/bro_protected.py` — `assert_no_bytecode_shadow` /
  `bytecode_shadow_offenders` (raise `ProtectedScopeError` for `__pycache__` / `.pyc` / `.pyo` under a
  digest root), called from `verify_control_plane_digest`; `engine/runtime/bro_control_plane.py` —
  `_bind_workspace` and `_settle_execution_tool`; `engine/.claude/settings.json` — the wired hook
  commands; `engine/tests/test_bytecode_shadow.py` — the regression tests
- **Closure requires:** (a) ✅ fail-closed calls to `assert_no_bytecode_shadow` on every path that
  trusts the control-plane digest; (b) ✅ the hook commands in `engine/.claude/settings.json` invoking
  `python -B` on **every** `||` interpreter alternative; (c) ◑ done: `compileall` now runs AFTER
  `engine/tools/bro_live_validate.py` in both `.github/workflows/ci.yml` and
  `engine/.github/workflows/verify.yml`, a cache-clearing step runs immediately before the probe,
  the validator is invoked as `python -B`, and both jobs carry `PYTHONDONTWRITEBYTECODE=1` — which
  `compileall` was NOT the only producer of: `engine/tools/bro_validate.py` calls `py_compile`,
  which writes caches even under that variable, and the probe planted a shadow on itself by
  importing `runtime/**` and by spawning `unittest` without `-B`. The probe now also names the
  refusal it wants;
  (d) ✅ regression tests that plant bytecode beside a control-plane module and assert the wall
  refuses; (e) ❌ the *read* half of the hole below, which is **not closeable from inside Python**
  and needs an owner decision on how the wall's interpreter is launched.

**The defect in full.** `is_digest_member` deliberately excludes `__pycache__`, `.pyc` and `.pyo` from the
control-plane digest, so a forged bytecode file changes nothing the digest can see.
`assert_no_bytecode_shadow` is the compensating control — and it used to be called from **nowhere**: a
repo-wide grep found only its own definition and comments. The only mitigation in force was
`sys.dont_write_bytecode = True` set at *import time* inside `bro_protected.py`, i.e. after the interpreter
had already been free to import (and mint bytecode for) `bro_hook`, `bro_control_plane`, `bro_policy`,
`bro_audit_log`, `bro_completion`, `bro_contracts` and `bro_release_v3`. Not one hook command in
`engine/.claude/settings.json` passed `-B`; neither does the subprocess spawn in
`engine/tools/bro_live_validate.py`.

**What this pass changed.**

1. `verify_control_plane_digest` now asserts no bytecode shadow **before** it compares digests. That is the
   one function every digest-trusting path goes through, so no caller — including one that does not exist
   yet — can trust a digest without the check.
2. `_bind_workspace` asserts it again, first, before a binding is loaded or any git subprocess is spawned,
   so the wall refuses on its own authority at its own entry point.
3. `_settle_execution_tool` asserts it too. PostToolUse settlement runs in a **second** process, never
   reaches `_bind_workspace`, and passes `control_plane_digest=None` to the lease — so it inherited no
   check from either. (Correction to the earlier text below and to the independent audit's wording: the
   digest is verified on PreToolUse only, **not** on PostToolUse.)
4. Every `||` alternative of every hook command in `engine/.claude/settings.json` now launches
   `python -B` / `python3 -B` / `py -3 -B`. The interpreter token stays first, so
   `engine/tools/bro_live_validate.py`'s `command.split()[0]` wiring probe is unaffected.
5. `engine/tests/test_bytecode_shadow.py` proves the premise (a hand-forged timestamp-valid `.pyc`
   really executes in place of its source **and** leaves the digest bit-identical), proves each of the
   three call sites and the `-B` wiring, and pins the import ordering: importing `bro_hook` without `-B`
   mints caches for 19 runtime modules **including `bro_protected` itself**, whose cache CPython writes
   before the module body sets `sys.dont_write_bytecode`.

**What is still open, precisely.** `-B` and `sys.dont_write_bytecode` stop bytecode being **written**.
Neither stops CPython **reading** an existing `.pyc`, and CPython has no flag that does. Imports happen
before any Python-level assertion can run, so a cache forged *before* the wall process starts shadows the
very module that would detect it — including `bro_protected` itself. The gate therefore raises the cost of
the attack (the shadow must be planted before the process starts, and any leftover cache is now a hard
refusal rather than silence) without eliminating it. Closing it needs something outside the interpreter:
launching the wall where no cache under a digest root can be read (e.g. `PYTHONPYCACHEPREFIX` pointed
outside the tree, or a read-only/freshly-cleaned control plane), or a pre-flight check in the launcher
before the interpreter starts. That is an owner/deployment decision, so the item stays **OPEN**.

**Item (c) is closed, and closing it found something worse than the masking it was about.** The
live-wall probe had **never once reached the check it is named for**, in either ordering:
`engine/tests/test_live_hook_deny.py` stripped `BRO_SESSION_STATE_DIR` as well as
`BRO_WORKSPACE_BINDING`, and the freeze gate is evaluated before the workspace gate — so the observed
refusal was always `freeze state gate RED`, both before O-1 and after. The probe and the test now run
the WIRED PreToolUse argv against a real temporary state dir and require the refusal to contain
`missing BRO_WORKSPACE_BINDING`; a bare `deny` no longer passes anything. Seven further negatives in
`engine/tests/test_hooks_subprocess.py` were asserting only that a call was denied and now each name
the gate they exercise — one of which turned out to refuse for `unknown tool/action` rather than the
review-mode rule in its own name, which is recorded in place rather than blessed.

The engine's standalone repository was not merely going to need this: it is **broken today on a clean
checkout**, verified in a standalone simulation — the unittest runner's own imports plant the shadow
and the wall refuses the real-root tests for it. Notably the suites that go red are the ones that name
their cause; the bare-deny ones keep passing on the shadow reason. The fix is already applied to
`verify.yml`. Flag retained: an accepted **HIGH** should not be carried to the end of Phase 10 —
the independent audit's `D-09` recommends pulling it forward.


**Read half hardened 2026-08-08.** `assert_control_plane_not_writable` refuses to trust a
control plane the running account can still write into, wired beside the shadow check at both
entry points. This does not detect a shadow — it removes the ability to plant one, which is the
only thing that reaches the case a detector cannot: a `.pyc` loaded during import, before any
check in the process exists.

It answers by ATTEMPTING a create, not by asking `os.access`. A test applies a deny ACE and
asserts `os.access` returns True while the real create is refused — the substitution would report
a genuinely protected deployment as writable. Five checks were deleted one at a time and every one
goes red; the pass also surfaced a real bug in the probe, where a leftover file made `O_EXCL`
raise and the directory read as unwritable, turning the gate green on exactly the stale state it
exists to catch.

`PYTHONPYCACHEPREFIX` was considered and rejected as the weakest option: it MOVES the caches, so
whoever can write the new location can still plant one.

**Still OPEN.** This closes the class on a deployment that can make the tree read-only — on Debian
a bind mount, see [`DEBIAN_DEPLOYMENT.md`](./DEBIAN_DEPLOYMENT.md) — and cannot close it on a box
that will not. Such a box may accept the residual risk by name:
`BRO_CONTROL_PLANE_WRITABLE_ACKNOWLEDGED=accepted-o1-residual-risk`.
### O-2 · audit-head anchor (was dead code; now produced and required)

- **Severity:** MEDIUM
- **Status:** OPEN
- **Owner secret needed:** yes
  Not a CI secret: a deploy-time signing custody. The anchor signer must run as a principal the
  ledger's own writer cannot reach, so it is provisioned where the engine is deployed rather than
  in a repository secret.
  (see *What the Owner must provide* below). Nothing here is closeable by inventing a key.
- **Engine ticket:** `engine/AUDIT/tickets/H-4-forgeable-audit-trail.md` — fix #1 (*"sign the audit head with
  a recorder/operator Ed25519 authority … and verify that signature inside `verify()`"*) is exactly this
  item. **Correction to §0's provenance note above:** O-2 is *not* untracked engine-side; only the outer
  repo's `O-2` label is absent from `engine/`. H-4 fixes #2 and #3 (ledger-ness from the `*.jsonl` suffix,
  signed backup manifest) were already implemented in `engine/tools/bro_backup.py`.
- **Engine code:** `engine/runtime/bro_audit_log.py` — `append` (attaches the anchor),
  `anchor_custody` / `anchor_custody_configured` / `_signer_argv` (owner custody),
  `_sign_anchor` / `_install_anchor` / `_check_anchor_monotonic`, `head_anchor_payload`,
  `attach_head_anchor`, `_check_anchor_against_chain`, `verify(path, *, keys=None, now=None)`, and the
  refusal types `AuditAnchorMissing` / `AuditAnchorCustodyMissing`; the two production verifiers
  `engine/tools/bro_monitor.py` (`_anchor_state` → `verify_chain(ledger, keys=…)`) and
  `engine/tools/bro_backup.py` (`_anchor_keys` → `verify_audit_chain(path, keys=…)`)
- **Closure requires:** the Owner's signing custody in the deployment environment, and an operator
  procedure in `engine/docs/OPERATOR_RUNBOOK.md`. The code half is done; the custody half cannot be done by
  this repository and must not be faked.

**The defect, and what changed.** The append-only ledger's tamper-evidence terminated in a head pointer. The
signed anchor (`.head.sig`, artifact type `audit-head`) is what makes that pointer unforgeable — and nothing
ever wrote one: `head_anchor_payload` and `attach_head_anchor` had **zero callers** repo-wide. Meanwhile both
production verifiers — `bro_monitor.verify_chain(ledger)` and `bro_backup.verify_audit_chain(path)` — passed
no keys, so verification fell through to the **plaintext** `.head` branch, and that plaintext head is
rewritten by the ledger's own `append()`. A party who could write the ledger could drop records, recompute
the chain, rewrite the head, and `verify()` reported the chain intact.

Now: `append()` assembles the anchor payload itself, hands it to the Owner's external signing command, and
installs the result only after verifying it against the operator-pinned trusted key registry **and** against
the chain on disk — refusing any document whose payload is not the one the ledger assembled. `verify()` with
keys REQUIRES that anchor, keyed on the existence of the ledger *file* (an emptied ledger with both sidecars
deleted used to return a clean `0`). Both production verifiers now pass keys, and neither has a keyless
mode: for `bro_backup` a key registry that will not load is a refusal, not a downgrade.

**Unanchored is not tampered.** They are separate refusal types — `AuditAnchorMissing` versus a plain
`AuditError` — because they call for different actions: provision custody versus incident response.
`bro_monitor` reports a three-valued `shadow.anchor.state` (`signed` / `unanchored` / `invalid` /
`keys-unavailable`); every non-`signed` state is ATTENTION, but the operator is told which.

**What the Owner must provide (deploy-time, not a CI secret).** No key is compiled in and none is invented;
an anchor signed with a key that lives in the repository would prove nothing, so a signing command resolving
inside `engine/` is refused by name. The Owner must export, from outside this repository:

| Variable | What it is |
|---|---|
| `BRO_AUDIT_ANCHOR_SIGNER` | Absolute path to a signing command (or a JSON argv array whose first element is that path). It reads one canonical `audit-head` payload as JSON on stdin and writes a `{payload, signature}` JSON document on stdout. It **must** run under a principal that cannot write the audit ledger, **must not** live inside `engine/`, and **must** refuse to sign an anchor whose `count` is below the last one it signed (anti-rollback; `previous_anchor_sha256` is carried in the payload so it can chain its own decisions). |
| `BRO_AUDIT_ANCHOR_KEY_ID` | The key id that command signs with, registered in the operator-pinned trusted-key registry under an `evidence-recorder` or `operator-root` authority. The private half never enters the engine process. |

Until both are set, ledgers are written **UNANCHORED** — the wall keeps running, but every keyed `verify()`
refuses them by name and prints exactly this list. That is deliberate: a silent green over an unanchored
ledger is the defect this item exists to remove.

**What this does NOT buy.** It does not defend against a party who can also make the Owner's signing command
sign arbitrary heads; that boundary is the signer's custody, which is why separate-principal execution and
signer-side anti-rollback are stated as requirements rather than assumed. The install-side monotonic check in
`_check_anchor_monotonic` is defence in depth only — a writer who drops a `.head.sig` in directly bypasses it.

**Status stays OPEN** because the Owner's custody is not provisioned, so no deployment is anchored yet.
Tests: `engine/tests/test_audit_head_anchor.py` (26 cases, including a ledger that is appended to, has its
plaintext head rewritten over dropped records, and must be REFUSED — the exact forgery that previously
verified green).

### O-3 · conductor session token off by default

- **Severity:** MEDIUM
- **Status:** OPEN
- **Owner secret needed:** yes
  an operator-root-signed `conductor-session` artifact (not a CI secret; an Owner deploy step)
- **Engine ticket:** `engine/AUDIT/tickets/MEDIUM-findings.md` § M-4
- **Engine code:** `engine/runtime/bro_policy.py` — `CONDUCTOR_SESSION_TOKEN_ENV =
  "BRO_CONDUCTOR_SESSION_TOKEN"` (a *path* to a signed artifact), `verify_conductor_session_token`, and the
  `require_conductor_session_token` flag read from `engine/.bro/policy.json` with default **`False`**;
  consumed by `authorize_conductor_stop` in `engine/runtime/bro_completion.py`
- **Closure requires:** ~~setting `"require_conductor_session_token": true` in `engine/.bro/policy.json`~~
  **(done)**; ~~tests for the required-and-absent, mismatched-binding and expired branches~~ **(done —
  `engine/tests/test_conductor_session_token.py`, 17 tests)**. What remains is the half only the Owner can
  do: a deploy step that mints and rotates the operator-root-signed `conductor-session` artifact and exports
  `BRO_CONDUCTOR_SESSION_TOKEN` to the harness. **Until then the conductor stop exemption is REFUSED, by
  design** — see "what the Owner must provide" below.

**The defect in full.** The verifier exists and is wired into `authorize_conductor_stop`, but it fails closed
only when a token is *presented and bad*. With the flag absent from the shipped policy (it is not merely
`false` — the key is not in the file), a caller presenting no token gets
`(True, "no conductor session token presented; identity rests on environment")`. Conductor identity therefore
rests on `CONDUCTOR_ROLE`/`CANONICAL_CONDUCTOR_ID` read from the environment: anything that can set two
environment variables can authorize a conductor stop. The `identity_basis` note is honestly recorded in the
audit log, which is what keeps this MEDIUM rather than HIGH.

**Verified (2026-08-07).** The diagnosis was confirmed exactly as written: the key was absent from
`engine/.bro/policy.json`, the read defaulted to `False`, and a repo-wide grep found no test in
`engine/tests/` referencing `require_conductor_session_token` or `verify_conductor_session_token`.

**What changed in this pass (code half).**

- `engine/.bro/policy.json` now declares `"require_conductor_session_token": true`. The file is inside the
  protected control-plane digest, so the requirement cannot be unset by an environment variable.
- `engine/runtime/bro_policy.py` gained `conductor_session_token_required(root)`. **An undeclared flag is now
  REQUIRED, not waived** — an absent key, a non-boolean value, or an unreadable policy all fail closed. Only
  an explicit boolean `false` waives it, and it is reported as an `EXPLICITLY waives` waiver so
  `authorize_conductor_stop` writes that word into the append-only ledger instead of a note about the
  environment.
- The refusal quotes `CONDUCTOR_SESSION_PROVISIONING` verbatim: the exact artifact payload shape, the
  registry entry, and the env var. Nothing here mints a token and no seed key is shipped — the check can only
  be satisfied by the Owner's offline operator-root key.
- The policy is now read from the `root` passed by the caller, not a module constant, so the requirement is
  testable against a fixture root.

**Consequence, deliberately accepted:** with the shipped policy fail-closed and no Owner artifact deployed,
`authorize_conductor_stop` refuses every conductor stop, naming what is missing. That is the honest state of
an unverifiable identity; it is not a regression to be "fixed" by re-defaulting the flag.

**Why it is still OPEN.** The credential half is the Owner's and is not in the repository. **This item is not
closeable by any agent.**

**Exactly what Gev must provide.** Mint, offline with the operator-root key, an artifact of the form

```json
{"payload": {"schema": 1, "artifact_type": "conductor-session", "key_id": "<operator-root key_id>",
             "session_id": "<the harness session id>", "agent_id": "bro-000", "role": "bro",
             "issued_at_epoch": 0, "expires_at_epoch": 0},
 "signature": "<ed25519 hex over the canonical payload>"}
```

with that `key_id` listed `active` in the operator-signed `engine/config/trusted-keys.json` (an
`operator-root` authority key is already allowed to sign `conductor-session`), then export
`BRO_CONDUCTOR_SESSION_TOKEN=<path to that file>` in the harness environment, and rotate it per session.

**Test evidence:** `engine/tests/test_conductor_session_token.py` — the shipped policy declares the flag;
absent / non-boolean / unreadable policy all require; only an explicit `false` waives; required-and-absent
refuses and names the env var, the artifact type and the registry; an operator-signed token bound to the
session verifies (real Ed25519 against an operator-signed registry); wrong-authority, tampered,
wrong-session/agent/role, expired, wrong-artifact-type and unreadable tokens all refuse; and a bad token
refuses even when the policy waives the requirement. `engine/tests/test_completion_gate.py` carries the
matching stop-gate refusal. Every one of these checks was deleted once and the matching test went red.

### O-4 · control-room actor is self-asserted

- **Severity:** LOW
- **Status:** OPEN
- **Owner secret needed:** yes
  A `control-room-command` artifact per owner command, signed by the offline operator root and
  bound to that command's `command_id`, `task_id` and `command`, with its key listed `active` in
  `config/trusted-keys.json`. See [`OWNER_CEREMONY.md`](./OWNER_CEREMONY.md).
- **Engine ticket:** `engine/AUDIT/tickets/LOW-findings.md` § L-8
- **Engine code:** `engine/runtime/bro_control_room_api.py` — `validate_command_intent`, which reads
  `requested_by_type` / `requested_by` straight out of the caller's JSON and compares them against the
  literals `("owner", "owner-gev")` / `("bro", "bro-000")`; the same pattern in
  `engine/runtime/bro_orchestration_runtime.py` (`_validate_actor`); schema
  `engine/schemas/control-room-command.schema.json` carries **no signature or key field**
- **Closure requires:** promoting the control-room command to a signed artifact — (a) ✅ register a
  `control-room-command` type in `engine/runtime/bro_signature.py`'s authority registry (**done** — bound to
  `operator-root` — which grants no key: see below); (b) ❌ extend `control-room-command.schema.json` with
  `artifact_type` / `key_id` and a detached signature; (c) ❌ verify it before `validate_command_intent` can
  stamp `"valid": true`. **The conductor half of this is done** (below); the owner half still needs (b) and
  (c), plus an operator key that is actually granted the new type.

**The defect in full.** The check is a string comparison on data the caller supplied. Anyone who can reach the
control-room API can claim to be `owner-gev`, and the API then echoes the claimed identity back inside a
`"valid": true` response — so the self-assertion is laundered into something downstream reads as verified.
The downstream policy check `validate_control_room_command` (`engine/runtime/bro_orchestration.py`) performs
no signature verification either. LOW because reaching the API already implies significant access; it is
nonetheless an unauthenticated identity claim inside the governance surface.

**Verified (2026-08-07).** Confirmed as written, including the downstream half: `validate_control_room_command`
checks the registry, the state and the expiry, and verifies no signature. `bro_orchestration_runtime._validate_actor`
carries the same self-assertion pattern (out of this pass's scope).

**What changed in this pass.** `validate_command_intent` no longer compares the claim; it demands proof, via
a new `_prove_command_actor`. There is no return path for an unproven actor — every branch raises, so
`"valid": true` is unreachable without a verified signature.

- A command claiming `bro`/`bro-000` must present the operator-root-signed `conductor-session` artifact of
  O-3/M-4 as the new `actor_attestation` argument. It is verified with `verify_artifact` against the
  runtime's trusted-key registry (authority binding, key status, key validity window, Ed25519 signature) and
  must bind `role` and `agent_id` to the claimed actor with an unexpired integer `expires_at_epoch`. Reusing
  the artifact the Owner already has to mint for O-3 means no new artifact type is invented by the code that
  consumes it.
- The attestation is judged against the **wall clock**, not the caller-supplied `now_epoch` every other view in that module takes: whether a key and a session credential are live right now is not the caller's question to ask, and a backdated clock would otherwise revive an expired identity.
- A runtime constructed without trusted keys refuses rather than accepting the claim unverified.
- The reply now carries `actor_identity` (`operator-signed-conductor-session`), `actor_key_id`,
  `actor_session_id` and `actor_attestation_sha256` — what verified the identity, not what was claimed. No
  value exists meaning "the caller said so".
- A command claiming `owner`/`owner-gev` is **refused by name**, and the refusal states the three changes
  that would close it. It is not validated on its say-so.

**Known, documented limit.** A `conductor-session` artifact proves the caller holds an operator-issued
session credential; it is not bound to the individual command, so within its validity window it authorises
any command that caller could already reach. That is a session credential's semantics and a strictly smaller
claim than "anyone who can spell `bro-000`". Per-command non-repudiation needs the signed
`control-room-command` artifact type.

**The registration blocker is removed (2026-08-07).** `_parse_key` rejects any registry entry naming an
artifact type absent from `ARTIFACT_AUTHORITY`, so while `control-room-command` was unregistered the closure
could not be provisioned from configuration *at all* — an operator-signed registry granting it would not even
load. `engine/runtime/bro_signature.py` now registers `control-room-command` against the `operator-root`
authority. **Registering a type provisions no key and weakens nothing:** `verify_artifact` still requires the
presenting key to carry the type in its own `allowed_artifact_types`, the committed
`engine/config/trusted-keys.json` grants it to no key, no key material is compiled in or generated, and
nothing consumes a `control-room-command` document yet — so `validate_command_intent` is exactly as strict as
before.

**Why it is still OPEN.** The owner actor still cannot be verified:
`engine/schemas/control-room-command.schema.json` has no `artifact_type` / `key_id` / signature field, no
trusted key is granted the type, and `validate_command_intent` verifies no command signature — an
owner-issued command is still **refused by name**, exactly as before.
`bro_orchestration_runtime._validate_actor` is also untouched. Proven in
`engine/tests/test_owner_artifact_registration.py`: an owner command carrying a flawless, operator-signed,
registry-granted `control-room-command` artifact is *still* refused by name, and the committed registry
grants the type to nobody.

**Test evidence:** `engine/tests/test_control_room_api.py` (`ControlRoomActorProofTests`, real Ed25519
against an operator-signed registry) — a signed session proves the conductor actor; missing attestation,
owner actor, wrong authority, tampered payload, wrong agent/role, expired, wrong artifact type, malformed
document, and a keyless runtime all refuse; and a proven actor does not soften the state or scope gates.
`engine/tests/test_owner_artifact_registration.py` covers the registration: the type is bound to
`operator-root` and to no other authority, a registry entry may now name it, a still-unregistered type is
refused exactly as before, the committed registry grants it to no key, and an owner command is refused by
name even with a valid signed `control-room-command` presented. Every one of these checks was deleted once
and the matching test went red.


**Closed in code 2026-08-08.** `_prove_command_actor` now routes by actor: the conductor keeps
its `conductor-session` credential, and the OWNER must present a `control-room-command` artifact
bound to this exact command. The difference is deliberate — a session authorises any command in a
window, and `owner-gev` is the identity that can cancel, recover and retry, so a window is the
wrong shape for it. A stolen owner artifact replays exactly the command that was already signed.
The schema carries `artifact_type`/`key_id`/`signature`, optional because a conductor command is
proven by a separate credential and carries none.

Four checks were deleted one at a time to confirm their tests go red. One — the guard that
refuses to prove an owner without the command to bind to — **stayed green**, because every caller
passes the command and nothing reached it directly. It was untested, not merely redundant, and it
has its own test now. **Status stays OPEN:** the shipped registry pins no key for the type, and a
test holds that even a flawless artifact signed by an ungranted key still refuses.
### O-5 · evidence high-water not bound into the signed manifest

- **Severity:** LOW
- **Status:** OPEN
- **Progress:** the manifest-binding half is built and enforced; what remains needs an Owner key (below)
- **Owner secret needed:** yes
  an operator-root-signed `evidence-floor-anchor` artifact (an Owner deploy step, not a CI secret). This corrects the earlier "no": the binding half needed no secret, the floor-reset half cannot be closed without one.
- **Engine ticket:** `engine/AUDIT/tickets/LOW-findings.md` § L-4
- **Engine code:** `engine/runtime/bro_evidence.py` (`min_head_sequence` / `EvidenceHead.head_sequence`,
  staleness rejection in `load_head`, propagation through `validate_chain`) and
  `engine/runtime/bro_completion.py` — `_check_manifest` (strict required-field set),
  `validate_evidence_chain`, `_head_document_digest`, `_require_store_agrees_with_head`,
  `_require_establishable_mark`, `_signed_floor_anchor`, `_head_floor_dir` / `_load_head_floor` /
  `_advance_head_floor`; the manifest shape is mirrored in
  `engine/schemas/completion-manifest.schema.json`
- **Closure requires:** *(done)* `evidence_head_sha256` + `head_sequence` in the strict `_check_manifest`
  required set, fed through to `validate_chain` instead of `None`, checked for exact equality against the
  store's signed head, mirrored onto the verifier-receipt chain check and into the persisted completion
  proof. *(done, 2026-08-07)* the `evidence-floor-anchor` → `operator-root` entry in
  `engine/runtime/bro_signature.py`'s `ARTIFACT_AUTHORITY`, and the same two fields added to
  `engine/schemas/completion-manifest.schema.json` (`required` + `properties`, since
  `additionalProperties` is `false`) — the schema no longer under-describes the enforced shape, and
  `engine/tests/test_manifest_schema_agreement.py` turns RED if the schema and the runtime required-set
  disagree in either direction. *(remaining, Owner)* an operator-root-signed `evidence-floor-anchor`,
  minted offline and granted to a key in the operator-signed registry, presented at
  `BRO_EVIDENCE_FLOOR_ANCHOR`.

**The defect in full.** The anti-rollback property — "evidence cannot be replayed at an older head" — was
carried entirely by an on-disk floor directory (`engine/runtime/bro_completion.py`: `_head_floor_dir`,
`_load_head_floor`, `_advance_head_floor`, overridable by the `BRO_EVIDENCE_HEAD_FLOOR` environment
variable). Every production entry point passed `min_head_sequence=None`, so nothing about the high-water mark
was signed: it was filesystem state, and whoever could write the store could move it. This is the same class
of finding as the desktop side's Windows anti-rollback work
(`apps/desktop/src-tauri/win-live/WINDOWS_ANTIROLLBACK_HARDENING.md`).

**What is now enforced.** The builder-signed manifest must name exactly one evidence head — its monotonic
`head_sequence` and the sha256 of the signed head *document* — and the store must hold that head and no
other, so the mark is carried in signed bytes rather than only in a directory. The binding is mirrored onto
the verifier receipt (which is already hash-bound to the manifest) and persisted into the hash-chained
transition record, which lives in a different store from the evidence it polices: a later completion naming
a lower `head_sequence` than one already recorded there is a rollback an auditor can see. Independently of
any bookkeeping file, the store's own recorder-signed events must not reach past the presented chain, so the
classic truncation rollback is refused even with the floor directory deleted — the surplus events are signed
by an authority the builder does not hold and cannot be re-minted. Each floor mark now records the digest of
the head it was taken against, and two different signed heads sharing one sequence is a refusal.

**What is NOT closed, and why.** A floor that is deleted **and re-provisioned** reads exactly like a task
being seen for the first time. Nothing the runtime can reach distinguishes them, so a manifest binding a
re-anchored head (`head_sequence` > 1) with no durable mark behind it is **refused by name** rather than
defaulted to zero, and the refusal states what the Owner must provide.

`evidence-floor-anchor` is now **registered** in the signature module's authority registry against
`operator-root` (2026-08-07). That was a hard blocker, not a formality: `_parse_key` refuses any registry
entry naming an unregistered artifact type, so the Owner could not have been given a key for it even
offline — the registry would not load. **Registering the type provisioned nothing and weakened nothing.**
Authority to sign comes from the per-key `allowed_artifact_types` grant in the operator-signed registry, and
no key holds it: the committed `engine/config/trusted-keys.json` grants the type to nobody, so presenting
`BRO_EVIDENCE_FLOOR_ANCHOR` today still **fails closed by name** — including when the document is genuinely
signed by the deployment's own registry-signing operator key, which is the "type registered, key not pinned"
case pinned by `test_registered_but_unpinned_the_anchor_is_still_refused` in
`engine/tests/test_owner_artifact_registration.py`. No key is compiled in, none is generated, and no seed is
shipped. What remains is the Owner's: mint the anchor offline, grant the type to that key in the
operator-signed registry, and present the file under a principal the policed account cannot write. The item
therefore stays **OPEN**.

---

## 2. Release signing, the updater, and what the Owner must provide

The other half of Phase 10 — *"signed/updatable build"*. The **checks** are now closed and enforced; the
**credentials** are, by definition, the Owner's.

### 2.1 Closed in this pass (no Owner secret required)

| What | Where |
|---|---|
| The release workflow refuses, loudly and by name, when signing material is absent | `.github/workflows/release.yml` job `preflight` → `tools/check_release_signing.py --require-release-ready`; `build` declares `needs: preflight` |
| The previous "build unsigned, skip signing, still publish a draft release" path is **removed** | `.github/workflows/release.yml` |
| Updater configuration can only be fully wired or fully absent — never half-wired | `tools/check_release_signing.py`, CI job `Release signing + updater` |
| A placeholder or non-minisign updater `pubkey` is RED (it would mean verifying against a key nobody controls) | `tools/check_release_signing.py` `pubkey_problem()` |
| Committed private key material in the Tauri config is RED | same |
| Authenticode settings that need no secret are configured: `digestAlgorithm: sha256` + RFC-3161 `timestampUrl` | `apps/desktop/src-tauri/tauri.conf.json` `bundle.windows` |
| Post-build proof from the produced bytes: every updater payload has a non-empty `.sig`; Windows installers return `Valid` from `Get-AuthenticodeSignature`; the macOS `.app` passes `codesign --verify` and `spctl --assess` | `.github/workflows/release.yml`, `tools/check_release_signing.py --verify-updater-signatures` |
| The Owner-secret list cannot drift between code, workflow and docs | `tools/check_release_signing.py` cross-checks `release.yml` and `docs/RELEASE_SETUP.md` |

**Deliberately NOT done:** `plugins.updater.pubkey`, `bundle.createUpdaterArtifacts: true`, the
`tauri-plugin-updater` dependency and its Rust initialisation are **not** added. The pubkey is the public half
of a key the Owner does not yet hold; inventing one would be a placeholder that silently disables update
verification, and enabling `createUpdaterArtifacts` without it breaks the bundle for the wrong reason. The
config is therefore held in a coherent **UNPROVISIONED** state, and the gate refuses any mixture. (The Rust
plugin init also lives in `apps/desktop/src-tauri/src/**`, which is outside this task's scope.)

### 2.2 Owner-gated — exactly what Gev must provide

| Secret | What it is / where it comes from |
|---|---|
| `TAURI_SIGNING_PRIVATE_KEY` | `cd apps/desktop && npm run tauri signer generate -- -w ~/.tauri/brops.key`. The printed **public** key then goes into `tauri.conf.json` `plugins.updater.pubkey`. |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | Password for that key. Generate it **with** a password — an empty one is refused. |
| `WINDOWS_CERTIFICATE` | Base64 of an Authenticode code-signing `.pfx` (OV or EV) from a CA. **Purchase required.** |
| `WINDOWS_CERTIFICATE_PASSWORD` | Password for that `.pfx`. |
| `APPLE_CERTIFICATE` | Base64 of a *Developer ID Application* `.p12`. **Paid Apple Developer Program membership required.** |
| `APPLE_CERTIFICATE_PASSWORD` | Password for that `.p12`. |
| `APPLE_SIGNING_IDENTITY` | e.g. `Developer ID Application: menq studio (TEAMID)`. |
| `APPLE_ID` | Apple ID used for notarization. |
| `APPLE_PASSWORD` | App-specific password for that Apple ID (`notarytool`). |
| `APPLE_TEAM_ID` | Apple Developer team id. |

Plus one **non-secret** Owner action: paste the updater **public** key into
`apps/desktop/src-tauri/tauri.conf.json`, set `bundle.createUpdaterArtifacts: true` and an `https://`
`plugins.updater.endpoints` entry, and add the `tauri-plugin-updater` dependency + init. The gate requires
those four to land together. Step-by-step: `docs/RELEASE_SETUP.md` §3.

And one Owner action for **O-3**: mint an operator-root-signed `conductor-session` artifact and export
`BRO_CONDUCTOR_SESSION_TOKEN` in the deployment environment (see §1 above). This is a deploy-time step, not a
CI secret.

---

## 3. What still blocks Phase 10 after this pass

1. **O-1 … O-5** — all five OPEN; all five are `engine/` changes (§1). O-1 is a HIGH.
2. **T-005** — the root-model native fix that retires the option-C CI skips.
3. **`contracts/` dedupe** — `contracts/` is still a placeholder README.
4. **The updater's provisioned half** — the Owner's keypair and the four config/dependency changes (§2.2).
5. **The `docs/RELEASE_SETUP.md` §5 release gate** — Architect CODE-audit GREEN, the governed chain wired
   into the shipped runtime, and 3b-2/3b-3, before any `v*` tag is created.
