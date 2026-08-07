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
| **O-1** | `L-6` / `H-6-protected-set-gaps` | HIGH | OPEN | no | `assert_no_bytecode_shadow` has **zero callers** and the wall is not run with `-B` |
| **O-2** | *(none — untracked engine-side)* | MEDIUM | OPEN | no | the signed audit-head anchor has **no producer**, and every production `verify()` is called without keys |
| **O-3** | `M-4` | MEDIUM | OPEN | **yes** (operator-signed session artifact) | conductor session token is implemented but `require_conductor_session_token` defaults to **false** and is absent from the shipped policy |
| **O-4** | `L-8` | LOW | OPEN | no | control-room command actor is a **string comparison on caller-supplied JSON** |
| **O-5** | `L-4` | LOW | OPEN | no | the evidence high-water mark lives on the filesystem and is **not bound into the signed completion manifest** |

**All five are engine-side code remediation, not credentials** — with the single exception of O-3, whose
*deployment* half needs the Owner to mint an operator-signed artifact. None of them is closeable by editing
CI, `tauri.conf.json` or `docs/`; each is an audited change under `engine/` (the golden rule: *deliberate,
tested, never rushed*), on its own branch/PR with Owner approval.

> **Provenance correction.** `CLAUDE.md` §6 and `docs/SECURITY_MODEL.md` §4 both state these items are
> *"tracked on Bro's `fix/audit-followups`"*. **That ref does not exist** — not locally and not on
> `origin` (~60 branches, none matching), and `grep -rn "O-1\|O-2\|O-3\|O-4\|O-5"` over `engine/` returns
> **zero** hits: the O-numbering exists only in this outer repository. The engine tracks four of the five
> under its own IDs in `engine/AUDIT/tickets/`; **O-2 has no engine-side ticket at all.** The tracking claim
> in those two documents is currently unbacked and should be corrected by whoever owns them
> (`CLAUDE.md`/`PROJECT_STATE.md` are Owner-synced files, so this note is the record, not an edit).

---

## 1. The items

### O-1 · bytecode-shadow

- **Severity:** HIGH
- **Status:** OPEN
- **Owner secret needed:** no
- **Engine ticket:** `engine/AUDIT/tickets/H-6-protected-set-gaps.md` (also `L-6`); independent audit `D-09`
- **Engine code:** `engine/runtime/bro_protected.py` — `assert_no_bytecode_shadow` (raises
  `ProtectedScopeError` for `__pycache__` / `.pyc` / `.pyo` under a digest root)
- **Closure requires:** (a) a fail-closed call to `assert_no_bytecode_shadow(ROOT, load_protected_manifest(ROOT))`
  on the wall's startup path in `engine/runtime/bro_hook.py`, alongside `_bind_workspace`; (b) the hook
  commands in `engine/.claude/settings.json` invoking `python -B …` (or exporting
  `PYTHONDONTWRITEBYTECODE=1` **plus** a `sys.dont_write_bytecode` self-check); (c) reordering/scoping the
  `python -m compileall -q runtime tools tests` step so it does not leave caches under a digest root before
  `tools/bro_live_validate.py` spawns the wall; (d) a regression test that drops a stray `.pyc` beside a
  control-plane module and asserts the wall refuses to start.

**The defect in full.** `is_digest_member` deliberately excludes `__pycache__`, `.pyc` and `.pyo` from the
control-plane digest, so a forged bytecode file changes nothing the digest can see. `assert_no_bytecode_shadow`
is the compensating control — and it is called from **nowhere**: a repo-wide grep finds only its own
definition and comments. The only mitigation in force is `sys.dont_write_bytecode = True` set at *import time*
inside `bro_protected.py`, i.e. after the interpreter has already been free to import (and mint bytecode for)
`bro_hook`, `bro_control_plane`, `bro_policy`, `bro_audit_log`, `bro_completion`, `bro_contracts` and
`bro_release_v3`. Not one hook command in `engine/.claude/settings.json` passes `-B`; neither does the
subprocess spawn in `engine/tools/bro_live_validate.py`. The digest is verified on every PreToolUse and
PostToolUse decision (`_bind_workspace` ← `authorize_tool` / `settle_execution_tool`), so a shadowed `.pyc`
subverts **every** gate decision while the digest still reports intact.

**Why it is not closed here.** `engine/**` is a security perimeter and is read-only to this task; and (c)
interacts with two CI workflows (`.github/workflows/ci.yml` and `engine/.github/workflows/verify.yml`) that
currently run `compileall` immediately before the live-wall validation, so enabling the assertion without
reordering them turns CI red for the *right* reason in the *wrong* place. That coupling is exactly why the
ledger calls it "keystone-class". Flag: an accepted **HIGH** should not be carried to the end of Phase 10 —
the independent audit's `D-09` recommends pulling it forward.

### O-2 · audit-head anchor is dead code

- **Severity:** MEDIUM
- **Status:** OPEN
- **Owner secret needed:** no
- **Engine ticket:** *none — this item is untracked engine-side; it exists only in the outer repo's docs*
- **Engine code:** `engine/runtime/bro_audit_log.py` — `head_anchor_payload`, `attach_head_anchor`,
  `_check_anchor_against_chain`, and `verify(path, *, keys=None, now=None)` whose signed-anchor branch is
  guarded by `if keys is not None`
- **Closure requires:** a real producer — operator tooling (`engine/tools/broctl.py` is the natural home; it
  already documents `ANCHOR_AUTHORITIES`) that calls `head_anchor_payload`, signs it out-of-band with an
  `evidence-recorder` or `operator-root` Ed25519 key, and installs it via `attach_head_anchor` — **plus**
  every production verifier passing `keys=…` so the anchor branch actually executes:
  `engine/tools/bro_monitor.py` (`verify_chain(ledger)`), `engine/tools/bro_backup.py`
  (`verify_audit_chain(path)`), and the procedure in `engine/docs/OPERATOR_RUNBOOK.md`.

**The defect in full.** The append-only ledger's tamper-evidence terminates in a head pointer. The signed
anchor (`.head.sig`, artifact type `audit-head`) is the thing that makes that pointer unforgeable — and
nothing ever writes one: `head_anchor_payload` and `attach_head_anchor` have **zero callers** repo-wide.
Meanwhile every caller of `verify()` passes no keys, so verification falls through to the **plaintext**
`.head` branch — and that plaintext head is rewritten by the ledger's own `append()`. An attacker who can
write the ledger can rewrite the head to match, and `verify()` says the chain is intact. `.head` forgery is
open, and the code that would close it is inert. This is the one item with no engine-side ticket, so it is
also the one most likely to be lost.

### O-3 · conductor session token off by default

- **Severity:** MEDIUM
- **Status:** OPEN
- **Owner secret needed:** yes — an operator-root-signed `conductor-session` artifact (not a CI secret; an
  Owner deploy step)
- **Engine ticket:** `engine/AUDIT/tickets/MEDIUM-findings.md` § M-4
- **Engine code:** `engine/runtime/bro_policy.py` — `CONDUCTOR_SESSION_TOKEN_ENV =
  "BRO_CONDUCTOR_SESSION_TOKEN"` (a *path* to a signed artifact), `verify_conductor_session_token`, and the
  `require_conductor_session_token` flag read from `engine/.bro/policy.json` with default **`False`**;
  consumed by `authorize_conductor_stop` in `engine/runtime/bro_completion.py`
- **Closure requires:** setting `"require_conductor_session_token": true` in `engine/.bro/policy.json` (that
  file is inside the protected digest, so the requirement cannot be switched off by environment); an Owner
  deploy step that mints and rotates the operator-signed `conductor-session` artifact and exports
  `BRO_CONDUCTOR_SESSION_TOKEN` to the harness; and tests for the required-and-absent, mismatched-binding
  and expired branches — **there is currently no test in `engine/tests/` that references either symbol.**

**The defect in full.** The verifier exists and is wired into `authorize_conductor_stop`, but it fails closed
only when a token is *presented and bad*. With the flag absent from the shipped policy (it is not merely
`false` — the key is not in the file), a caller presenting no token gets
`(True, "no conductor session token presented; identity rests on environment")`. Conductor identity therefore
rests on `CONDUCTOR_ROLE`/`CANONICAL_CONDUCTOR_ID` read from the environment: anything that can set two
environment variables can authorize a conductor stop. The `identity_basis` note is honestly recorded in the
audit log, which is what keeps this MEDIUM rather than HIGH.

### O-4 · control-room actor is self-asserted

- **Severity:** LOW
- **Status:** OPEN
- **Owner secret needed:** no
- **Engine ticket:** `engine/AUDIT/tickets/LOW-findings.md` § L-8
- **Engine code:** `engine/runtime/bro_control_room_api.py` — `validate_command_intent`, which reads
  `requested_by_type` / `requested_by` straight out of the caller's JSON and compares them against the
  literals `("owner", "owner-gev")` / `("bro", "bro-000")`; the same pattern in
  `engine/runtime/bro_orchestration_runtime.py` (`_validate_actor`); schema
  `engine/schemas/control-room-command.schema.json` carries **no signature or key field**
- **Closure requires:** promoting the control-room command to a signed artifact — register a
  `control-room-command` type in `engine/runtime/bro_signature.py`'s authority registry bound to the
  owner/bro authorities, extend `control-room-command.schema.json` with `artifact_type` / `key_id` and a
  detached signature, and verify it before `validate_command_intent` can stamp `"valid": true`.

**The defect in full.** The check is a string comparison on data the caller supplied. Anyone who can reach the
control-room API can claim to be `owner-gev`, and the API then echoes the claimed identity back inside a
`"valid": true` response — so the self-assertion is laundered into something downstream reads as verified.
The downstream policy check `validate_control_room_command` (`engine/runtime/bro_orchestration.py`) performs
no signature verification either. LOW because reaching the API already implies significant access; it is
nonetheless an unauthenticated identity claim inside the governance surface.

### O-5 · evidence high-water not bound into the signed manifest

- **Severity:** LOW
- **Status:** OPEN
- **Owner secret needed:** no
- **Engine ticket:** `engine/AUDIT/tickets/LOW-findings.md` § L-4
- **Engine code:** `engine/runtime/bro_evidence.py` (`min_head_sequence` / `EvidenceHead.head_sequence`,
  staleness rejection in `load_head`, propagation through `validate_chain`) versus
  `engine/runtime/bro_completion.py` — `_check_manifest`, whose strict required-field set contains **no**
  `evidence_head_sha256` and no `head_sequence`; mirrored in
  `engine/schemas/completion-manifest.schema.json`
- **Closure requires:** adding `evidence_head_sha256` and/or `head_sequence` to the builder-signed completion
  manifest (both the `_check_manifest` required set and the JSON schema — the shape is enforced strictly, so
  this is a deliberate schema-breaking change), feeding it as `min_head_sequence` into `_validate_evidence` /
  `validate_chain` instead of `None`, and mirroring the binding into the verifier receipt.

**The defect in full.** The anti-rollback property — "evidence cannot be replayed at an older head" — is
carried today by an on-disk floor directory (`engine/runtime/bro_completion.py`: `_head_floor_dir`,
`_load_head_floor`, `_advance_head_floor`, overridable by the `BRO_EVIDENCE_HEAD_FLOOR` environment
variable). Every production entry point passes `min_head_sequence=None`, so nothing about the high-water mark
is signed: it is filesystem state, and whoever can write the store can move it. Binding the mark into the
manifest the builder already signs makes the floor cryptographic rather than custodial. This is the same class
of finding as the desktop side's Windows anti-rollback work
(`apps/desktop/src-tauri/win-live/WINDOWS_ANTIROLLBACK_HARDENING.md`).

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
