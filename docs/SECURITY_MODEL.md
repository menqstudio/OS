# OS Security Model

Status: **pre-production. The shipped app is fail-closed and never renders production `trusted_verified`.**
This document is the single narrative for the trust boundary, the current posture, the audit findings, and
exactly what must land before the production "Verified" gate can flip. It is honest by construction: where a
guarantee is not yet real, it says so, and where it is real on one platform only, it names the platform.

## 1. The trust boundary

There are **two** chains, and conflating them is the mistake this section exists to prevent.

### 1.1 The receipt chain (a live AI turn)

A live AI turn is `trusted_verified` only when a full governed chain runs behind the wall and the desktop
independently verifies a signed receipt:

```
ROOT signing authority
  └─ signs the key manifest  ──▶ TCB-pinned ROOT PUBLIC key (compiled into the broker, tcb.rs)
        challenge-authority ─▶ governed-supervisor (lease + attest) ─▶ isolated-signer (Ed25519)
              └─ receipt {envelope_jcs_b64, signature_b64}  ──▶ DESKTOP verify_and_accept
                    (recompute JCS, verify_strict, bind request+output+attestation, one-time nonce)
                          └─ resolve_trust_state ─▶ trusted_verified  (production key, non-revoked, in-window)
```

Invariants that HOLD today (verified by the 2026-08-04 builder audit — `apps/desktop/src-tauri/win-live/proof/BUILDER_AUDIT_VERDICT_2026-08-04.md`):

- **No fresh production forgery without the root private half.** The production root pin is compiled in (never
  read from config); a demonstration-root-signed manifest is rejected; `verify_strict` rejects
  malleable/short signatures; the demo-pinning constructors are `pub(crate)`.
- **Output→receipt binding is airtight.** The bytes hashed == signed == committed == the executor's stdout.
- **The root private is never written to the serving box** (`config.json root_seed=""`).
- **The desktop is the verification authority** — the bridge/receipt carries signed material only; there is
  **no wire `verified` boolean** (`bridge/contracts/bridge-result.schema.json`).
- **Server-side peer-SID gate** on every named pipe is fail-closed and kernel-attested.

### 1.2 The governance chain (the engine's trust material) — provisioned at first launch, not by hand

This half **changed completely in PRs #78–#80** and the old description ("an offline root, held by the
operator, that never touches the serving box") no longer describes what the code does.

`apps/desktop/src-tauri/provision/` mints the engine's trust material **on the user's own machine, on first
launch**, in `run()`'s `setup` hook — after the app-data directory is made owner-only and **before the
database is opened**. A failure aborts startup; there is no degraded mode
(`apps/desktop/src-tauri/src/lib.rs`, `provision_local_trust`).

```
first launch (unprivileged app account)
  ├─ mint 9 Ed25519 keypairs        (MINTED_AUTHORITIES: builder, control-room, evidence-floor,
  │                                   evidence-recorder, issuer, operator-root, recovery, release, verifier)
  ├─ operator-root signs the trusted-key-registry and one conductor-session artifact
  ├─ operator-root's PRIVATE half is DESTROYED before mint() returns   (RETAINED_AUTHORITIES = the other 8)
  │
  ├─ <app data>/trust/              ← the app's own account writes all of it
  │     keys/          the 8 retained private halves
  │     artifacts/     conductor-session.json  (the O-3 credential)
  │     POSTURE.txt    the posture, for whoever finds the directory without the source
  │
  └─ <machine root>/trust-anchor/   ← the half the app CANNOT write, and the reason the rest means anything
        operator-root.pub   the out-of-registry pin
        registry-min        the anti-rollback floor
        registry/config/trusted-keys.json   the registry the engine reads
        PROVISIONING.json   sha256 of every app-side file (and the idempotency marker)
        CUSTODY.txt         the mechanism, stated
```

`<machine root>` is `%ProgramData%\BroPS` on Windows and `anchor::POSIX_MACHINE_ROOT` elsewhere
(`anchor::default_machine_root`). The anchor is sealed
by `anchor::seal`: a PROTECTED DACL whose **OWNER RIGHTS (`S-1-3-4`)** ACE grants read+execute *only* —
it **replaces** the owner's implicit `WRITE_DAC` rather than adding to it, so no elevation, service or
second login is needed — applied to the anchor's files, the anchor directory, and every ancestor up to the
machine root. `anchor::prove_unwritable` then asks the operating system whether the seal took, on **every**
launch, and refuses if it no longer holds. Sealing the leaf alone was not enough: the parent could be
renamed aside, which is why the walk goes to the volume root.

**The authority split is the point.** `operator-root` no longer exists on the machine after install, so the
key that signs the registry is not a key the ledger's writer holds:

| Authority | Signs | Where the private half lives |
|---|---|---|
| `operator-root` | `trusted-key-registry`, `conductor-session`, `protected-authority`, `workspace-binding` | **nowhere** — generated in memory at install, destroyed before `mint()` returns |
| `audit-anchor` | the audit log's head anchor, and nothing else (`bro_audit_log.ANCHOR_AUTHORITIES`) | a **separate service principal** that mints its own seed and publishes only the public half. Nothing in this repository mints it. |
| `control-room` | `control-room-command` and nothing else (O-4) | retained by the app (`mint_control_room_command`) |
| `evidence-floor` | `evidence-floor-anchor` and nothing else (O-5) | retained by the app (`mint_floor_anchor`) |

`control-room` and `evidence-floor` are **delegated** authorities, split off the root deliberately: a machine
that is compromised can authorise its own control-room command and state its own evidence high-water mark
anyway, and neither key can sign a `trusted-key-registry`, a `conductor-session` or an `audit-head` —
`bro_signature.ARTIFACT_AUTHORITY` binds each to exactly one type and `_parse_key` refuses a registry entry
that tries to grant a second.

`BRO_TRUSTED_REGISTRY_ROOT` (`bro_signature.ENV_REGISTRY_ROOT`) is how the engine reads a *provisioned*
registry instead of the committed development one. Unset, behaviour is byte-for-byte what it was. Set, it
must be absolute, symlink-free at every component, hold `config/trusted-keys.json` as a regular file, be a
directory the reading account cannot rewrite, and contain **neither the pin nor the floor** — a redirect that
carried the anchor along would hand over the registry and the thing that authenticates it in one variable.
A caller that names a third root while the override is set is refused by name rather than served a different
registry from the rest of the process (`resolve_registry_root`).

**What this posture claims, and what it does not.** Locally-minted trust material defends against an attacker
who arrives **later**. It does not defend against one who already owned the machine at install time — that
attacker witnesses the mint or performs it. An SSH host key makes exactly the same trade. So the chain proves
*integrity over time on one machine*, not *provenance from a vendor*, and no claim of the second kind may be
made on the strength of it.

**Proofs you can run**, rather than claims to take on trust:

- `apps/desktop/src-tauri/provision/tests/python_verifier.rs` — runs the **real** `bro_signature`,
  `verify_conductor_session_token` and `bro_deploy_preflight` against the **real** Rust output (29 checks).
  It fails rather than skips when Python or `cryptography` is absent.
- `apps/desktop/src-tauri/audit-signer/tests/anchor_end_to_end.py` — makes the real
  `engine/runtime/bro_audit_log.py` judge the real signer over the real named pipe. Six cases, including
  `rollback`, `forgery` (the writer signs the truncated head with **every** private half it holds),
  `registry-resign` and `pin-rewrite` (the route that was open, run against the closure: the OS must refuse
  the write, the delete, the create and the rename of every directory on the path).
- `apps/desktop/src-tauri/provision/tests/anchor_custody.rs`, `engine/tests/test_provisioned_registry_root.py`
  (all 23 registry-root call sites AST-enumerated and frozen), `engine/tests/test_audit_head_anchor.py`,
  `engine/tests/test_bytecode_shadow.py`.

### 1.3 What is NOT true, stated as prominently as what is

- **This is Windows-only today.** `anchor::seal` returns `ProvisionError::Unsupported` on POSIX by
  construction — a POSIX owner may always `chmod` a directory it owns and there is no OWNER RIGHTS
  equivalent — so first-launch provisioning **aborts startup** there. The POSIX path is specified (the anchor
  created by a different uid at `<POSIX_MACHINE_ROOT>/trust-anchor` (`anchor::POSIX_MACHINE_ROOT`; the
  literal is being revised — read the constant, not a path copied out of a document), mode 0755,
  ancestors likewise, provisioning
  run once as that account by the installer) and **that branch has never executed**.
- **Nothing exports the provisioned environment into the engine.** `Provisioned::engine_env()` *returns*
  `BRO_OPERATOR_ROOT_PUBKEY_FILE`, `BRO_OPERATOR_REGISTRY_MIN_FILE`, `BRO_CONDUCTOR_SESSION_TOKEN` and
  `BRO_SESSION_ID`; `provision_local_trust` deliberately does not apply them, and the list does not include
  `BRO_TRUSTED_REGISTRY_ROOT` at all. So the engine still reads the committed development registry at
  `engine/config/trusted-keys.json` (`production: false`, with its DEVELOPMENT REGISTRY warning intact).
  Wiring it is one deployment decision, not a silent startup side effect.
- **The audit signer is in no installer.** The crate exists and builds two binaries
  (`brops-audit-signer`, `brops-anchor-relay`), and `audit-signer/src/register.rs` holds the elevated
  registration and prints the `sc.exe` plan — but `register::apply` has no binary entry point and no caller
  outside tests, `tauri.conf.json` declares no `externalBin` or extra resources, and there is no WiX/NSIS
  custom install step. Nothing ships or registers the second principal.
- **`broctl` cannot mint a production registry.** `broctl build-registry` hardcodes `"production": false` and
  stamps the DEVELOPMENT REGISTRY warning; `keygen --production` refuses by name; and `bro_signature` refuses
  a non-production registry whenever the pin comes from the production `_FILE` path. An engine-only
  deployment therefore has **no path** to a production registry. How one is minted is an Owner/architecture
  decision, not a missing function.
- **Windows key-material permissions are inherited, not set.** `secure_owner_only_file` has no non-unix
  branch, so the retained private halves carry the app-data directory's ACL (per-user, plus SYSTEM and
  Administrators). Recorded in `PROVISIONING.json`, in `POSTURE.txt` and on stderr at first launch rather
  than fixed.
- **The boundary is the app's unelevated token.** On a machine whose user is a local administrator one UAC
  consent gives full control. Provisioning fails closed if the token holds `SeTakeOwnership` or `SeRestore`,
  so an elevated run refuses rather than quietly proceeding — but that is the residual, and it is what having
  no second principal ultimately costs.

## 2. Current posture — FAIL-CLOSED (shipped)

Production `trusted_verified` is unreachable in the shipped application, by construction, in three
independent places:

1. `governed_verification_unconfigured()` (`apps/desktop/src-tauri/src/commands.rs`) returns
   `Some(GOVERNED_VERIFICATION_UNCONFIGURED)` **unconditionally**. It fires after the one-time challenge is
   issued and **before the model is called**, so no prompt is sent for a result that could only be discarded.
   The two policy digests are non-hex sentinels no wire-legal receipt can carry, and both the executor and
   builder rosters are empty.
2. `connect_broker()` (`apps/desktop/src-tauri/src/governed_turn.rs`) returns
   `BrokerAccessError::UnsupportedPlatform` on every host but Linux, so governed real-mode is unavailable
   rather than silently degraded.
3. The broker binary itself (`apps/desktop/src-tauri/broker/`) exits `EXIT_PLATFORM_UNSUPPORTED` off Linux,
   and on Linux `build_governed_executor` falls back to `UpstreamBlockedExecutor` unless a complete
   `BROPS_BROKER_CONFIG` parses — refusing every turn with `UpstreamBlocked` rather than fabricating an
   acceptance.

> **A naming correction.** The canonical documents describe this gate as
> "`platform_governed_execution_supported()` returns false". **No function of that name exists in the tree.**
> It is the *specification* symbol from `docs/design/WINDOWS_BROKER_DESIGN.md` §0.1/§7.1/§10 — a NORMATIVE,
> UNAUDITED target — and `config/spec-conformance.json` records §0.1 as `partial` for exactly that reason:
> *"the platform gate as specified; it is a hardcoded false."* The three refusals above are the hardcoded
> false. Cite them when you need to prove the gate is shut; cite the spec symbol only as a spec symbol.

**Two** paths in the shipped app run the real chain, and both run it under the **compiled-in
demonstration anchor**, so neither can render production `trusted_verified`:

1. the owner-visible self-test `governed_trust_selftest`, which reports `demonstration_custody: true`
   and never touches live turns; the UI shows a distinct "DEMONSTRATION CUSTODY" badge; and
2. `demonstration_verified_reply` (`src/commands.rs`), the chat "Demo-verify" button — a real chat
   reply produced *inside* the chain by `BROPS_SELFTEST_MODEL_CMD`, bound and verified, then posted
   with the derived `demonstration_verified` badge. Windows-only; fail-closed on every branch.

> This paragraph said *"the **only** wired chain path"* until 2026-08-09, and (2) had in fact never
> run: it accepted on `outcome.bound && outcome.production_verified`, and `production_verified` is
> `false` for every run the in-process proof can produce — the anchor is the demonstration root, which
> `win-live/src/proof.rs` both documents and asserts. A registered command, exported through
> `desktop.ts`, wired to a button, that could only ever return its error string. The acceptance
> condition now lives on `ProofOutcome::may_post_as_demonstration_verified` beside the fields it
> reads, with a test that runs on both CI platforms. The sentence and the defect had the same cause:
> nobody re-read either after the second path was added.

**Production custody has been proven once, locally** (2026-08-04): the operator's real offline root signed a
manifest the TCB pin accepted, and a full `win_live_turn` over real named pipes reached
`trusted_verified … production_verified=true bound=true` under the real root. That is the honest graduation from
demonstration custody — but it is a local proof, **not** the shipped badge.

## 3. Builder audit (2026-08-04) — findings and disposition

Owner-designated builder-side adversarial audit, 5 independent reviewers. Verdict: **NOT GREEN, central
guarantee HOLDS.** This is builder evidence, **not** the independent Architect verdict (`CURRENT_CODE_AUDIT:
ARCHITECT_PENDING`).

- **P0-2 pipe squat + broker impersonation — FIXED.** Client connects with `SECURITY_SQOS_PRESENT |
  SECURITY_IDENTIFICATION`; server creates with `FILE_FLAG_FIRST_PIPE_INSTANCE`.
- **P0-1 anti-rollback floor — CORRECTED (honesty).** `FLOOR_SEED_HEX` is a public source constant, so the
  floor signature is a corruption check, **not** the anti-rollback boundary. The real boundary is the OS
  write-ACL on the deployment dir (broker-principal-only). Full closure (ACL enforcement + per-deploy sealed
  floor key + TPM monotonic counter) is specified in `win-live/WINDOWS_ANTIROLLBACK_HARDENING.md`.
- **demonstration_custody (UI) — FIXED.** The self-test can no longer be read as production trust.
- **Open, gated:** executor emits a placeholder (not a real model answer); containment (restricted token /
  image verify) is not wired to the live executor spawn; serving-seed plaintext TOFU window; receipt/attest
  `key_usage` not manifest-encoded.

## 4. Residual engine items (O-1 … O-5)

Tracked in `engine/AUDIT/tickets/` under the engine's own IDs — the `O-n` numbering is this
repository's, and does not appear in `engine/` at all. `docs/PHASE_10_PRODUCTION_ITEMS.md` is the
inventory and the **status of record**: what each item is, which engine path it lives in, and what closure
requires. All five are **OPEN** there. Each is its own audited engine task, never rushed.
(An earlier revision of this section said they were *"tracked on Bro's `fix/audit-followups`"*. That ref
exists neither locally nor on `origin`, so the claim was unbacked.)

The five bullets below described the **pre-remediation** defects, in the present tense, long after code
landed against every one of them. What each item is *now*:

- **O-1 (HIGH)** — bytecode-shadow: `assert_no_bytecode_shadow` **has real callers** — `bro_control_plane.py`
  lines 80 (in `_bind_workspace`, before any binding loads) and 271 (the settlement path), plus
  `bro_protected.verify_control_plane_digest` — and hook interpreters run `-B`. The reachability gate now
  defends those call sites (`must_have_caller`). **Still open, and not closeable from inside Python:** `-B`
  stops bytecode being *written*; nothing stops CPython *reading* a `.pyc` that is already there, and it
  reads it during import, before any check in the process exists. The compensating rule is that the engine
  refuses to trust a control plane the running account can write into. A packaged install (`Program Files`,
  `/opt`, `/Applications`) gives that for free — which needs verifying on a packaged build rather than
  asserting.
- **O-2 (MED)** — audit-head anchor: **no longer dead code.** `bro_audit_log.append()` is the in-band
  producer — it assembles the payload itself, signs it through the configured custody
  (`BRO_AUDIT_ANCHOR_SIGNER` / `BRO_AUDIT_ANCHOR_KEY_ID`) inside the same exclusive append lock, and installs
  it; a keyed `verify()` **requires** an anchor and raises `AuditAnchorMissing` on a ledger that has none.
  `head_anchor_payload`/`attach_head_anchor` remain caller-less **on purpose**: they are the owner-facing
  out-of-band half, and a signing key the ledger's own writer could reach would prove nothing. **Still open:**
  the anchor is worth its signature only under a principal the writer cannot become. On Windows that
  principal is designed and built as a service (`brops-audit-signer` under a virtual service account, reached
  over the peer-authenticated pipe by `brops-anchor-relay`) but is **in no installer**; on POSIX it is
  specified and has never run. **State the consequence, because the paragraph above states only the mechanism:** custody is configured by `BRO_AUDIT_ANCHOR_SIGNER`/`BRO_AUDIT_ANCHOR_KEY_ID`, **nothing in the shipped product sets either** (every occurrence in the tree is a test harness or a document; the startup path deliberately does not export `Provisioned::engine_env()`; `tauri.conf.json` declares no `externalBin`/`resources`, so neither signer binary is installed; `register::apply` has no caller outside tests). So on a shipped install `append()` takes its unconfigured path: it writes the record, rewrites the **plaintext** `.head` itself, and produces no `.head.sig`. **The audit ledger is therefore not tamper-evident against its own writer on any real deployment** — a party who can write it can drop records, recompute the chain and rewrite the head, and an unkeyed `verify()` reports it intact. A keyed `verify()` refuses, but with `AuditAnchorMissing`, which it raises for every ledger this deployment has ever written, so it cannot separate “never anchored” from “tampered”; `bro_monitor` asks for the keyed check and reports that as a blind spot. This is the property O-2 exists for and it has never run outside a test.
- **O-3 (MED)** — conductor session token: **fail-closed and set.** `require_conductor_session_token` is
  `true` in `engine/.bro/policy.json`, `bro_policy` treats an absent key, a wrong type or an unreadable
  policy as REQUIRED, and `verify_conductor_session_token` is called from `bro_completion`. First-launch
  provisioning mints the `conductor-session` artifact, so **no Owner-minted artifact is needed**, and
  `BRO_TRUSTED_REGISTRY_ROOT` lets the engine read the registry that admits its key. **Still open:** one line
  in the app's startup — exporting the four variables `engine_env()` computes **plus
  `BRO_TRUSTED_REGISTRY_ROOT`, which it does not**. §1.3 above says so explicitly ("the list does not
  include `BRO_TRUSTED_REGISTRY_ROOT` at all") and §5.5 below says so too; this bullet used to say
  "the variables `engine_env()` already computes", which contradicted both and understated the work by
  the one variable that decides which registry the engine trusts.
- **O-4 (LOW)** — control-room actor: **no longer self-asserted.** `_prove_command_actor` routes by actor: a
  conductor command must present the operator-signed `conductor-session`; an **owner** command must present a
  `control-room-command` artifact bound to this exact `command_id`, `task_id` and `command`, so a stolen
  artifact replays only the command that was already signed. The artifact type is registered in
  `ARTIFACT_AUTHORITY` against the delegated `control-room` authority, and
  `schemas/control-room-command.schema.json` **does** carry `artifact_type` / `key_id` / `signature`.
  Provisioning retains the `control-room` key and `mint_control_room_command` signs one, so **no
  Owner-minted artifact is needed**. **Still open:** the *committed* registry pins no key for the type, and a
  flawless artifact signed by an ungranted key still refuses — pointing the engine at the provisioned
  registry is what closes it, and that is the same unexported-environment decision as O-3.
- **O-5 (LOW)** — evidence high-water: the head digest and sequence are **required** and travel into a
  hash-chained record in a different store, so a rollback is visible from signed bytes after the evidence
  store is wiped. `mint_floor_anchor` signs the `evidence-floor-anchor` with the retained delegated
  `evidence-floor` key, so **no Owner-minted artifact is needed**. **Still open, deliberately:** it is not
  minted at install and must not be minted automatically. At install no task exists, and an anchor the app
  produced by reading the very store the check polices would restate that store's own claim under a
  signature — worse than no anchor, because it reads as corroboration. *When* it is called is a design
  question.

## 5. What must land before the production "Verified" gate flips

All of the following, then an **independent** audit, then **Owner** approval:

1. **Executor → real model** — the contained executor invokes the model and emits its exact output (today a
   placeholder), then re-provision the pinned executor SHA.
2. **Wire the live chain into the shipped runtime** — route through the broker/manifest; make
   `governed_verification_unconfigured()` a real provisioning probe instead of a hardcoded `Some`; retire
   `UpstreamBlockedExecutor`; select `GovernedEngine` with a real `ManifestReceiptKeyAuthority`.
3. **Session-0 isolation** — broker as its own dedicated service account, `CreateProcessAsUser` under a
   restricted token + `STARTUPINFOEX` handle list wired to the output-producing spawn, CNG key custody.
4. **Anti-rollback real closure** — provisioning-enforced deploy-dir ACL + per-deploy sealed floor key + TPM
   monotonic counter.
5. **The provisioned trust actually reaching the engine** — export `engine_env()` plus
   `BRO_TRUSTED_REGISTRY_ROOT` from a deployment that has decided where the registry lives; ship and register
   the audit signer; and answer how a **production** registry is minted at all, since `broctl` cannot.
6. **O-1 … O-5** closed or owner-signed-deferred, per `docs/PHASE_10_PRODUCTION_ITEMS.md`.
7. **Independent Architect CODE-audit** on the exact head + **Owner approval**.

Until every item above is real, the gate stays false and the app fails closed. **The badge is never faked.**
