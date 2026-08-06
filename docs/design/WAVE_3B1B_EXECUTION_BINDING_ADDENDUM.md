# Wave 3b-1B — authoritative execution→receipt binding · ARCHITECT ADDENDUM (design-lock, rev 30 — closes the rev-29 Architect design RED: 1 P0 + 3 P1)

> **STATUS: ❌ DESIGN RED. Last reviewed candidate = rev-29 = Architect design RED (1 P0 + 3 P1 at exact
> HEAD `1a79bc28ba89d78fc547b9f17b4fb94cdea81abe`; CI run 30297820594 9/9 GREEN — CI ≠ design GREEN).
> CURRENT candidate = rev-30 = PENDING re-audit (the remediation below; it does NOT inherit the rev-29
> verdict). No Architect-approved or merged 3b-1B implementation exists; PR #32 holds UNAPPROVED
> Draft/WIP code with no authority over the design (adapt only after design-GREEN). rev-26/rev-27/rev-28 were also RED.**
>
>
> **rev-30 closes the rev-29 Architect design RED (1 P0 + 3 P1 @ `1a79bc2`).** **P0 — exact broker-committed output delivery path (§4.10(g)):** the renderer↔broker reply frame `brops.renderer-governed-turn-result.v1` now returns the broker-produced immutable UI projection `message{message_id, role:"assistant", author, body, created_at_ms, trust_state:"trusted_verified"}` on commit (and NO `message` on `blocked`, with a CLOSED `reason` enum); the returned `body` is the exact strict-UTF8 bytes whose length+SHA-256 matched the signed envelope; `message_id/body/trust_state` equal the row the broker verification tx committed (in-tx re-read; any mismatch ⇒ fail-closed `commit_readback_mismatch`); only the broker tx creates the verified message/trust state; no renderer command (incl. generic chat writes) can create/mutate/mark it; output-bytes == persisted body == returned body is equality-tested; forged renderer events can never render Verified; +positive/negative E2E delivery tests. **P1-1 — request correlation + payload-aware idempotency:** a NON-authoritative `client_request_id: UUIDv4` on the request (grants no signing/verification authority); the broker mints its OWN `broker_turn_id` + `request_nonce`; idempotency keyed on the exact `{client_request_id, conversation_id, agent}` (live-duplicate reattach; same id + different conversation/agent ⇒ `retry_conflict`; a different request while the conversation has a live turn ⇒ explicit `turn_in_progress`, NOT silent reattach — replaces the old 'idempotent on conversation_id' rule); every reply echoes both IDs; a late reply from a timed-out request cannot satisfy a newer one; +disconnect/reconnect/duplicate/conflicting-agent/late-reply tests. **P1-2 — complete the 0/1/2 stdio lifecycle (§2.7):** the recorder OPENS controlled inert endpoints for FDs 0/1/2; the launcher verifies 0/1/2 are exactly the approved inert endpoints, rejects interactive/inherited/unexpected stdio, closes 0/1/2 or sets `FD_CLOEXEC` before `fexecve`, and confirms ONLY 3–6 survive into the executor; +a real `/proc/self/fd` enumeration test proving only 3–6 are inherited. **P1-3 —** canonical state synchronized (rev-29 reviewed = RED, rev-30 = PENDING_REAUDIT, blockers = this 1 P0 + 3 P1) across `config/current_state.json`, `NEXT_CHAT.md`, `PROJECT_STATE.md`, `TASKS.md`, this banner, and the PR #31 body. A fresh adversarial red-team over the package caught 2 residual gaps (bracketing 'carry ONLY' prose vs the new `client_request_id`; an undeclared closed `reason` enum) — both fixed before commit.**
> **rev-29 closes the rev-28 Architect design RED (3 P0 + 1 P1 @ `c9680f5`).** **P0-1 (§0, §2.1, §4.10(g), §6.1, §7.1) — propagate the renderer → trusted verifier/BROKER service → challenge-authority split through the ENTIRE normative contract** (rev-28 declared the nine-role table but the topology diagram + §2.1 peer/nonce/return-path + §4.10(g) `governed_turn_execute` + §6.1/§7.1 still named ONE in-process desktop/Tauri principal): a global terminology binding resolves every *trusted-actor* "desktop"/"backend" reference to the broker service (never the renderer); the topology diagram is now three-tier; the challenge-authority IPC allowlists **only the broker UID** and **DENIES the renderer/login UID**; **only the broker** supplies create-pending facts/`request_nonce`/issue and receives the signed challenge; `PreparedGovernedTurnV1B` + receipt DB + pinned manifest + final verification + accepted-output persistence live **only** in the broker; `governed_turn_execute` is a **broker-service operation** and the Tauri command a **THIN proxy** carrying only `{conversation_id, agent?}`; a NORMATIVE renderer↔broker IPC schema (peer auth, frame limits, timeout, replay/idempotency, errors) is defined; **only the broker emits the committed UI-safe result**. **P0-2 (§2.5) — TCB integrity floor** expanded so `TCB_ARTIFACTS` includes the broker + challenge-authority executables/config/policy/unit-files/IPC-policy/manifest-config/loaded-libs; both services require root/TCB ownership + non-writability + start-time SHA-256 pin + fail-closed `verify_tcb_integrity()` + UID/SID + peer-auth verification (7 negative tests: login-writable/modified broker or authority binary/config, writable ancestor, wrong owner/SID, fake broker cannot forge Verified ⇒ governed mode DISABLED). **P0-3 (§2.7, §4.7) — FD survival across BOTH exec boundaries:** the RECORDER (before `execve(launcher)`) maps the 3 inputs + output to FDs 3–6, `dup2/dup3`s, CLEARS `FD_CLOEXEC` on 3–6, redirects 0/1/2 to inert, `close_range(7,…)`, `execve`s with empty env; the LAUNCHER (before `fexecve(executor)`) verifies exactly 3–6 (mode/inode/offset/store-binding), re-clears CLOEXEC, rejects any unexpected FD, opens the executor image `O_NOFOLLOW|O_RDONLY|O_CLOEXEC`, runs the locked privilege drop, `fexecve`s with **only** 3–6 surviving (7 integration/negative tests). **P1-1 —** canonical state synchronized (rev-28 reviewed = RED, rev-29 = PENDING_REAUDIT, blockers = these 3 P0 + 1 P1) across `config/current_state.json`, `NEXT_CHAT.md`, `PROJECT_STATE.md`, `TASKS.md`, this banner, and the PR #31 body. A fresh adversarial red-team over the remediation package caught 3 residual gaps (a mismatched retitle anchor + two un-rebound references at §4.10(g)/§2.1) — all fixed before commit.**
> The consolidated closure history (rev 25 → rev 26) follows; the rev-27 → rev-28 closure is summarized in
> the rev-28 banner block further below and in Appendix A. rev 25 was Architect-reviewed at exact HEAD
> `bcd24fe0d5af0a33fc72ca7eaee35b8f1f12be1a` (exact-head CI **#132** 8/8 SUCCESS incl. both mandatory
> Wave-3b gates — **CI GREEN ≠ design GREEN**); the Architect **CONFIRMED CLOSED** the rev-24 model-identity
> P0 + issued-row-cleanup P1, and returned the **FINAL CONSOLIDATED remediation, 2 P0 · 3 P1**, mandating a
> **parallel fan-out (Tracks A–F) → one integrator → a fresh independent red-team over the ENTIRE §0–§9 +
> real code.** rev 26 closes all five in place:
> **P0-1 — pre-result refusal plumbing was not constructible.** Internal a0/a/b/c/d + authority refusal
> codes are absent from `GOVERNED_REFUSAL_REASONS` and the sidecar may originate no verdict, yet must reach
> the desktop as a Block. **rev 26 (§4.10(h)):** a NEW `bridge.governed-turn-diagnostic.v1{stage,
> upstream_reason}` (≤ `MAX_DIAGNOSTIC_BYTES = 256`, no signature, distinct discriminator) carries internal
> refusals; `governed_turn_execute` classifies by top-level `protocol` into 3 disjoint bounded-reason
> prefixes (`governed_verdict_refused:` / `governed_internal_refusal:` / `governed_transport_failure:`),
> each → exactly one `record_pre_verification_block` Block, never confusable with a signed verdict; a
> complete routing table maps every internal reason; explicit `refused` is terminal, only transport
> failures retry.
> **P0-2 — model identity must be immutable + historically verifiable.** The rev-25 mutable registry could
> let a later update reinterpret a past execution. **rev 26 (§2/§4.3/§7):** identity is a pure formula
> `model_profile_id = "cfg-sha256:" + generation_config_sha256` (no lookup); the former registry survives
> only as a non-identity `GOVERNED_EXECUTION_ALLOWLIST` (execution-permission gate, consulted once at
> acceptance, never by §7); the 5-field resolver is frozen to exact literals (model `"claude-sonnet-5"`,
> max_output_tokens `"4096"`, temperature `"0.00"`, top_p `"1.00"`, engine_id the frozen id) with an exact
> `BROPS_GOVERNED_*` override contract; `validate_governed_turn_lease` + `LiveRunStateProvider` recompute
> the formula from signed bytes, so an allowlist change after signing cannot reinterpret a record.
> **P1-1 — challenge-authority exact constants + ordering + frame-fit.** **rev 26 (§2.1.1):** a canonical
> constants table (all literal — `PENDING_TTL_MS 30000`, `MAX_AUTHORITY_ATTEMPTS 3`,
> `AUTHORITY_ATTEMPT_TIMEOUT_MS 2000`, `AUTHORITY_RETRY_BACKOFF_MS 1000`, `AUTHORITY_REPLAY_WINDOW_MS 30000`,
> `ISSUED_RETENTION_MS 60000`, `MAX_ISSUED_ROWS_PER_INSTALL 8`, `MAX_ISSUED_BYTES_PER_INSTALL 65536`,
> `AUTHORITY_CHANNEL_FRAME_BYTES 8192`, …); idempotent-lookup-before-quota; synchronous logical expiry
> (expired-not-swept never live, never counted); `pending_expired` (present+expired) vs `no_pending_row`
> (absent); the issue reply raised to `challenge_document_b64` in an 8192 frame (the old 4 KiB could not
> hold a 4096-byte doc + base64 + envelope).
> **P1-2 — output-stream expiry/retention/cleanup complete.** **rev 26 (§4.10(f)):** three-phase lifecycle
> (LIVE / tombstone `stream_expired` / swept `stream_unknown`) on a synchronous verdict; `OUTPUT_STREAM_TTL_MS
> 360000` + `OUTPUT_STREAM_RETENTION_MS 360000` + `OUTPUT_STREAM_SWEEP_INTERVAL_MS 60000` + per-install
> quota + FIFO-evict; the token is minted once (no re-mint post-expiry); the sweep never unlinks the
> content-addressed output (pinned by the terminal record + receipt).
> **P1-3 — expired challenges could pin staging quota.** **rev 26 (§4.10(a0)/§2.4):** a resource-admission
> expiry gate refuses `challenge_expired` iff `now_ms > challenge_expires_at_ms` (before any publish/CAS,
> no nonce consume, no acceptance stamp), and the staging quota counts only LIVE rows — so an expired/
> replayed challenge occupies zero slots.
> *(rev-18 → … → rev-25 findings remain closed; see the non-normative Appendix A. Track F swept the whole
> doc for undefined constants / `e.g.` / prose-only reasons: all governed constants now literal; the
> `EXECUTION_STARTING→EXECUTING` trigger + the `challenge_replay`/`acceptance_conflict`/`lease_not_ready`
> producing gates are pinned.)*
> **All contracts below are OPEN until the Architect returns design-GREEN at the exact pushed HEAD.**
> STOP gates: `NoTrustedManifest` unchanged, no production "Verified", 3b-2/3b-3 not started, PR #31
> not merged.
>
> **rev-28 closes the rev-27 Architect design RED (2 P0 + 4 P1 @ `0e41ef6`).** **P0-1 (§0, §2.1, §2.6):**
> rev-27 wrongly folded the **trusted Rust/Tauri backend** (the final cryptographic verifier + persistence
> authority) into the "untrusted client" — impossible, since a compromised renderer and a compromised
> final verifier cannot be the same principal. rev-28 defines **nine roles** and splits three identities:
> **Renderer/session UI** (interactive login identity, fully untrusted, owns no key/DB/manifest/trust-state,
> reaches only the broker via a closed `{conversation_id, agent?}` command); **Trusted desktop
> verifier/broker** (dedicated service UID/SID, separate process from the renderer, owns the receipt DB +
> pinned manifest + orchestration + final verification, resolves system/history/config/IDs itself, never
> accepts renderer-supplied hashes/objects/verdicts/receipt fields); **`desktop-challenge-authority`**
> (separate dedicated UID/SID, owns the challenge key/store, accepts create-pending/issue **only from the
> broker UID**). Broker-compromise is stated **out of scope** (it is the TCB final authority). The **seven
> runtime service UIDs** `verify_distinct_principals()` checks are broker/authority/sidecar/supervisor/
> recorder/executor/signer; the renderer is the login role and the launcher is a root/TCB helper. Renderer
> denial tests added (§9). **P0-2 (§2.7/§4.7):** the launcher is made **executable + privilege-safe** —
> the data **FDs 3–6 have `FD_CLOEXEC` explicitly CLEARED** so they survive both exec boundaries (rev-27
> wrongly set `O_CLOEXEC`, which would have closed the executor's I/O); the **exact privilege-drop syscall
> sequence** is locked (verify → root cgroup setup → `setgroups([])` → `setresgid` → drop bounding/ambient
> caps via **`CAP_SETPCAP`** → `setresuid` → clear all cap sets → verify unprivileged → `PR_SET_NO_NEW_PRIVS`
> → `fexecve`); a setuid-root helper is acknowledged to **start fully privileged** (not "only CAP_SETUID/
> CAP_SETGID"); a **real executable integration test** + full negative matrix are required.
> **P1-1** the obsolete "same-login-user sidecar" wording is removed from the normative §2.1/§2.5 (3-actor
> model). **P1-2** canonical state uses separate `last_reviewed_candidate`/`last_architect_verdict`/
> `current_candidate`/`current_candidate_gate` fields (rev-28 does not inherit the rev-27 verdict). **P1-3**
> this banner + top STATUS identify rev-28. **P1-4** PR #31 gains a `carrier_transition` (OPEN ⇒ design/
> impl/code-audit gate; MERGED ⇒ verify main + rebase PR #32) + a main-push anti-self-stale check (checker
> generalized to snapshot-declared gate names). **NOT Architect-GREEN; re-audit pending.**
>
> **Preparation-P0 closure (independent prep review, NOT the Architect verdict — closed in rev-26 on the
> prior HEAD; PR #31 rebased onto the repaired `main` `b6c6712`):**
> **P0-a TCB code-integrity floor (§2.5, §4.3, §4.7):** the lease now pins `executor_executable_sha256`
> as well as the launcher; the launcher re-hashes the executor image and `fexecve`s the exact verified
> `fd`; **all** TCB binaries + config must be TCB-owned and non-writable by any runtime/login UID,
> verified fail-closed at start (`verify_tcb_integrity()`) — so a same-login-user sidecar can no longer
> swap a TCB binary and obtain a genuinely-signed `trusted_verified` (`tcb_integrity_violation`).
> **P0-b distinct-principal linchpin (§2.6):** the **sidecar's own** dedicated UID is now a checked
> requirement; `verify_distinct_principals()` refuses (fail-closed) unless all seven runtime UIDs are
> set, pairwise-distinct, and ≠ the login UID — no single-UID collapse.
> **P0-c enforced platform gate + Windows normative (§0.1, §0.W):** `platform_governed_execution_supported()`
> is a tested runtime gate (not prose); Windows real-mode is DISABLED (gate false) until a Windows broker
> is separately Architect-audited, with the broker's required primitives specified. New refusal reasons
> `tcb_integrity_violation` + `platform_unsupported`; new §9 test matrix.

> **DESIGN-ONLY.** No 3b-1B code ships until this addendum is Architect-GREEN. It reuses the
> existing lease / containment / receipt / evidence authorities — **no parallel executor**.
> **This document is the single normative source for the 3b-1B contracts; where any other
> file (including the 3b-1 map) and this document disagree, THIS document wins and the other
> is a bug to fix.**

---

## 0. Scope & topology

The governed AI turn (desktop `system`/`history` → model reply) becomes a
**`bro_supervisor`-owned supervised execution** that **atomically emits a signed terminal
record**. No unsigned run-state JSON is ever signing authority. The model executor is the
`builder_command` for this run — spawned + contained exactly as any builder, but under the
recorder (below), holding **no signing key**.

```
untrusted RENDERER / LOGIN PROCESS (webview + message handlers; interactive login identity; NO
      key/store/DB/manifest/trust-state; sends the broker ONLY a closed {conversation_id, agent?})
  → TRUSTED DESKTOP VERIFIER / BROKER SERVICE (dedicated service UID/SID; SEPARATE process from the
      renderer; owns receipt DB + pinned manifest + PreparedGovernedTurnV1B + final verification +
      accepted-output persistence; resolves system/history/config/IDs itself; the ONLY caller of the
      authority and the ONLY emitter of the committed UI-safe result, §4.10(g))
    → desktop-challenge-authority (dedicated UID; owns challenge key + pending store; allowlists ONLY
          the broker UID, DENIES the renderer/login UID, §2.1) ── issues signed challenge BACK TO THE
          BROKER (never the renderer); the broker then drives the governed submit ──┐
                                                        ▼
supervisor (owns the acceptance ledger §5 + the governed-turn lease issuer + the
            governed-turn-recorder key; signs the TERMINAL RECORD only)
  → EVIDENCE-RECORDER RUNNER  (dedicated recorder UID; holds the evidence-recorder key;
        signs the governed-turn execution RECEIPT + evidence chain/head; owns the
        executor pidfd/cgroup + output pipe + teardown measurement; the ONLY caller of the launcher)
      → NARROW PRIVILEGED LAUNCHER  (P0-2 Model A: ROOT/TCB-OWNED setuid helper, NOT a runtime UID;
            effective identity root/TCB; validates peer/lease/hashes/FDs/target-UID/cgroup, then
            drops to executor + fexecve's the verified image; holds NO key)
          → CONTAINED MODEL EXECUTOR  (executor UID; NO key/store access; reads 3 read-only
                input FDs, writes 1 output FD — nothing else, §2)
[peer of supervisor only] ISOLATED RECEIPT SIGNER (dedicated signer UID; holds the receipt key)
```

**Principal topology (rev-28, P0-1 — split the RENDERER from the trusted desktop VERIFIER/BROKER).**
rev-27 wrongly folded the trusted Rust/Tauri backend (the final cryptographic verifier + persistence
authority) into the "untrusted client." That is impossible: a compromised renderer and a compromised
final verifier cannot be the same threat principal — if the final verifier is compromised it can just
bypass verification and display/persist a fake `Verified`. rev-28 defines **nine roles**; the trusted
verifier/broker is a distinct principal from the renderer.

1. **Renderer / session UI** — the webview + its message handlers. Runs under the **interactive login
   identity** (Actors A/B). **Fully untrusted:** owns **no** key, receipt DB, pinned manifest, trust
   state or authority store; **cannot directly reach** the challenge authority, sidecar, supervisor or
   signer. It may send the broker only a **closed command** (e.g. `{conversation_id, agent?}`) — never
   `system`/`history`/`config`/hashes/nonces/prepared objects/verdicts/receipt fields.
2. **Trusted desktop verifier / BROKER** — a **dedicated service UID/SID**, a **separate process from
   the renderer** (the Tauri app is split: the webview is the renderer; the broker is a separate local
   service). This is the one trusted Rust orchestration + **final verification** path: it owns the
   local `receipt_challenges` / `receipt_verification_attempts` / `receipt_ids_seen` DB + the pinned
   manifest state; **resolves `system`/`history`/`generation_config`/workspace/install/run/task IDs
   itself from trusted backend state** given only the closed renderer command; builds the immutable
   `PreparedGovernedTurnV1B`; issues the challenge (via the authority); verifies the isolated-signer
   envelope + supervisor attestation; consumes the nonce; enforces receipt-id uniqueness + freshness;
   **persists accepted output; and permits rendering only after the verification transaction commits.**
   It **never** accepts renderer-supplied hashes, prepared objects, verdicts or receipt fields.
3. **`desktop-challenge-authority`** — a **separate dedicated UID/SID**. Owns the challenge signing key
   + the pending-challenge store; both **unreadable/unlistable/unwritable** by the renderer/login user,
   the broker's *data* is separate, the sidecar, and every other principal. Accepts **create-pending /
   issue only from the trusted verifier/broker UID** (never the renderer/login UID), over an
   authenticated local IPC that verifies the exact broker principal (§2.1).
4. **`sidecar`** — the `engine_sidecar` service under its **own dedicated service UID** (NOT login, NOT
   renderer, NOT broker). RCE here is threat actor C.
5. **`supervisor`** — acceptance ledger §5 + governed-turn lease issuer + governed-turn-recorder key;
   signs the TERMINAL RECORD only.
6. **evidence-recorder runner** (`brops-recorder`) — dedicated recorder UID; evidence-recorder key;
   owns the executor pidfd/cgroup + output pipe + teardown; the **only** caller of the launcher.
7. **privileged launcher** — **NOT a service UID** (P0-2, Model A): a **root/TCB-owned setuid helper**,
   invoked only by the recorder; effective identity root/TCB; drops to the executor and `fexecve`s the
   verified image (§2.5, §2.7, §4.7).
8. **contained model executor** — dedicated executor UID; NO key/store access; 3 read-only input FDs +
   1 write-only output FD, nothing else (§2).
9. **isolated receipt signer** — dedicated signer UID; receipt-signing key; only peer is the supervisor.

**The SEVEN runtime service UIDs** that `verify_distinct_principals()` (§2.6) requires pairwise-distinct
and **≠ the interactive login UID** are: **verifier/broker (#2), challenge-authority (#3), sidecar (#4),
supervisor (#5), recorder (#6), executor (#8), signer (#9)**. The **renderer (#1) is the interactive
login role**, not a service UID (it is *supposed* to be the low-trust identity). The **launcher (#7) is
a root/TCB-owned setuid file** (§2.5), not a service UID. The `governed-turn-recorder` remains a
supervisor-held key class, not an OS principal (§8).

**Normative terminology binding (rev-28 P0-1 — LOCKED; resolves the whole contract to ONE topology).**
Throughout the CURRENT normative body of this addendum (§1–§9), wherever the text says **"the desktop"**,
**"the desktop backend"**, **"desktop-UI"**, or **"backend"/"backend execution"** as the *trusted* actor
that owns the `receipt_challenges`/receipt DB, mints or pre-stores the `request_nonce`, calls the
challenge authority, builds the `PreparedGovernedTurnV1B`, runs final verification/acceptance, or emits
the committed result, it **DENOTES the trusted desktop verifier/BROKER service (role #2 — a dedicated
service UID/SID in its OWN process, separate from the renderer)**, and **NEVER** the renderer/login/webview
process. The renderer/login process (role #1) is a **thin proxy** that may send the broker **only** a
closed `{conversation_id, agent?}` command and render the broker's committed reply; it owns/accesses **no**
key, receipt DB, pinned manifest, prepared object, hash, nonce, challenge authority, sidecar/supervisor/
signer socket, or verification verdict (§4.10(g)). The authenticated challenge-authority IPC allowlists
**only the broker UID** and **DENIES** the renderer/login UID (§2.1); the signed challenge returns to the
**broker**, never to the renderer. This single topology —
`renderer/login → (narrow authenticated IPC) → broker → (authenticated IPC) → challenge-authority →
sidecar/supervisor/signer governed chain` — is authoritative wherever any older in-process desktop/Tauri
phrasing survives; such phrasing is a wording residue, not a second architecture. (Historical Appendix A
is non-normative and may keep the old model.)

**Trusted-verifier/broker compromise is OUT of scope (it is the TCB final authority).** The `Verified`
UI/persistence guarantee is *defined by* the broker; if the broker itself is compromised the guarantee
is void — therefore the broker is **inside the TCB**, protected by the same distinct-UID + TCB-binary
+ ACL controls as the signer/supervisor, and its compromise is out of scope exactly as `root`/kernel
is. What IS in scope is a **compromised renderer** (Actor B) trying to reach *past* the broker: it
cannot, because the broker is a separate service principal the renderer can only address through the
closed command, and the renderer holds no key/DB/authority handle.

**Threat model (rev-28 — three DISTINCT actors):**
- **Actor A — malicious interactive login user:** holds the login UID. OUT of the TCB; DENIED
  read/list/write to every authority/key/store/TCB asset (POSIX/NTFS ownership + ACL, §2.5).
- **Actor B — compromised renderer / session UI:** holds the login identity via the renderer process.
  Owns no key/DB/manifest/trust-state; can send the broker only the closed command; cannot reach the
  challenge authority / sidecar / supervisor / signer, cannot supply any authoritative input, cannot
  forge a `Verified` message (only the broker's committed verification transaction creates one).
- **Actor C — RCE inside the dedicated `sidecar` SERVICE UID:** holds the **sidecar service UID**,
  **NOT** the login UID and **NOT** the broker. It can trigger a run + relay the final receipt
  (transport only), but cannot connect the signer socket, read any key/store, or make any authority
  sign caller-supplied evidence.
admin / root / kernel — and the trusted verifier/broker, challenge authority, supervisor and signer
identities — are OUT of scope. A sidecar-SERVICE-UID compromise (Actor C) is **not** "same-login-user
RCE" (separate identity; separate denial-matrix rows, §9). Where a platform cannot provide these
distinct principals + peer auth + ACL isolation, governed real-mode is **FAIL-CLOSED** (Windows is
fail-closed until its broker (§0.W) is separately audited).

### 0.1 Platform capability gate (P0 — ENFORCED + TESTED, not prose, fail-closed)

"Fail-closed on unsupported platforms" is only real if it is a **runtime gate with a test**, not a
sentence. The supervisor evaluates a single normative predicate
**`platform_governed_execution_supported()`** at start and **enables governed real-mode only if it
returns true**. It returns true **iff ALL** of the following primitives are present *and verified*:

1. **Distinct OS principals** — `verify_distinct_principals()` passes (§2.6): all seven runtime UIDs
   set, pairwise-distinct, and ≠ the interactive login UID.
2. **Local-IPC peer authentication** — an `SO_PEERCRED`-equivalent that authenticates the connecting
   process's UID against an exact allowlist on the authority + supervisor sockets (§2.1, §2.3).
3. **File-ownership / ACL isolation** — the receipt-key store (§2.3 `store/keys/`) and the protected
   evidence store are enforceable owner-only / owner-write-shared-read against the in-scope login/
   sidecar UIDs.
4. **Privilege-dropping verified exec** — a `setuid(executor)+fexecve` (drop-caps, run-the-exact-
   verified-`fd`) primitive for the launcher (§4.7).
5. **TCB code integrity** — `verify_tcb_integrity()` passes (§2.5): every TCB binary/config is
   TCB-owned and non-writable by any runtime/login UID, and matches its start-time pin.

If **any** primitive is absent or unverified, `platform_governed_execution_supported()` returns
**false** ⇒ the supervisor issues **NO governed-turn lease**, every governed turn resolves to
**Blocked** (dev/blocked only, `NoTrustedManifest`-equivalent), and the desktop **never** renders
`trusted_verified`. There is no partial/degraded governed mode. **Test (normative, §9):** a platform
shim that reports any single primitive missing ⇒ the gate returns false ⇒ a governed turn Blocks with
no lease; the all-present Linux fixture ⇒ the gate returns true and the §2.1 isolation proofs run.

### 0.W Windows (primary platform) — normative stance + broker target

**Linux is the currently-audited platform** (dedicated UIDs, `AF_UNIX` + `SO_PEERCRED`, setuid
launcher + `fexecve`, POSIX ownership/ACL, `engine/ci/isolation_proof.sh`). **Windows real-mode is
DISABLED by the §0.1 gate today** — `platform_governed_execution_supported()` returns **false** on
Windows, so governed turns are fail-closed (dev/blocked, never Verified) until a Windows broker is
designed **and passes its own Architect audit**. This is not a TODO gap in the trust chain: it is an
explicit, tested refusal.

A future **Windows governed-execution broker** MUST provide equivalents for each §0.1 primitive
(normative target, audited separately before it may flip the gate true on Windows):
- **Distinct principals** — a dedicated **service account / SID per principal** (or an isolated
  service with a per-principal **restricted token / AppContainer**); none may be the interactive user.
- **Peer authentication** — named-pipe peer identity via `GetNamedPipeClientProcessId` →
  `OpenProcessToken` → **token-SID allowlist** (the `SO_PEERCRED` equivalent); reject any other SID.
- **Ownership / ACL isolation** — **NTFS ACLs** that DENY write to the interactive user (and every
  non-owning runtime SID) on the key store, the protected store, **and all TCB binaries/config**;
  owner = a TCB principal (TrustedInstaller-class / `brops-admin`).
- **Privilege-separated verified exec** — `CreateProcessAsUser` under the executor's **restricted
  token**, launching an image whose **hash + Authenticode + ACL** are verified before launch and which
  is **not writable by the login user** (the `fexecve`/TCB-integrity equivalent).
- **TCB code integrity** — **WDAC/AppLocker** (or signature + ACL) so the login user cannot substitute
  any TCB binary.

Until that broker exists and is Architect-audited, the gate stays **false** on Windows.

**Machine-proof status (PR #53, crate `brops-win-live`, `apps/desktop/src-tauri/win-live`).** The Windows
governed turn is now **machine-proven to production `trusted_verified`** end-to-end: (1) an **in-process,
host-independent** full crypto chain (challenge → lease → attest → sign → `verify_and_accept` →
`production_verified=true bound=true`) that runs on the Linux CI runner too (`cargo test -p
brops-win-live`), so the one cross-implementation boundary — the signer's `JCS(payload)` vs
`brops-core`'s `ReceiptEnvelope::payload_jcs` — is byte-exact; (2) the **same `GovernedChain` over real
`\\.\pipe\` named pipes** across three separate Windows processes (same-account); (3) the **peer-SID gate
fail-closed both directions** (correct broker SID → verified, wrong → blocked); (4) **cross-account** —
challenge-authority / supervisor / isolated-signer each as a **DISTINCT dedicated Windows service account**
(session-0, batch logon), peer-SID authed across real account boundaries → `trusted_verified`
(`win-live/proof/CROSS_ACCOUNT_PROOF.md`). This proves the peer-authentication + distinct-principal +
verified-exec-binding primitives above over the real syscalls. It does **NOT** flip the §0.1 gate: the
remaining primitives (broker as its **own** dedicated service account — currently blocked by a session-0
console-launch `STATUS_DLL_INIT_FAILED` 0xC0000142 limitation, an environment issue orthogonal to the
chain; `CreateProcessAsUser` under a restricted token + STARTUPINFOEX handle list; **CNG key custody**;
WDAC/AppLocker TCB integrity) and a **separate Architect audit of the Windows broker** are still required.
`platform_governed_execution_supported()` stays **false** on Windows until then.

---

## 1. Canonical time model (P0-1) — ONE unit, explicit names

**Every governed-turn artifact uses integer epoch MILLISECONDS**, and **every field name
ends in `_ms`** so the unit is visible at the call site. The ratified base `execution-lease`
(`issued_at_epoch`/`expires_at_epoch`, epoch **seconds** via `int(time.time())`) is **left
unchanged and is NOT reused** by the governed-turn chain — the governed-turn lease is a
**separate artifact** with its own `_ms` fields (§4.3), never the base `*_epoch` names with
silently changed units.

- **LEGACY epoch-seconds reused artifacts (P1-4, LOCKED — do NOT mutate).** The reused
  **`bro_evidence` event/head** (`issued_at_epoch`) is epoch **seconds** (minted by `broctl`
  as `int(time.time())`; `EVENT_FIELDS`/`HEAD_FIELDS` are exact-set-matched + Ed25519-signed,
  so changing the unit is a breaking re-sign of every stored chain). It stays epoch-seconds
  and is a **legacy exception** to the `_ms` rule: its `issued_at_epoch` is **NEVER** compared
  against any governed-turn ms window. Only the evidence chain's **structural** bindings
  (`event_hash`, `sequence`, `final_event_hash`, `head_sequence`) cross into the governed-turn
  record — no time comparison — so the seconds field never touches the ms logic. The desktop's
  own receipt-freshness window is ms (`FreshnessWindow{future_skew_ms, max_age_ms}` vs
  `now_ms`) and applies only to governed-turn `_ms` fields, never to the evidence seconds.

- Canonical fields: `requested_at_ms`, `challenge_issued_at_ms`, `challenge_expires_at_ms`,
  `challenge_accepted_at_ms`, `lease_issued_at_ms`, `lease_expires_at_ms`, `started_at_ms`,
  `finished_at_ms`, `completed_at_ms`, `measured_at_ms`, `registry_issued_at_ms`,
  key `valid_from_ms` / `valid_to_ms` / `revoked_at_ms`.
- Type: JSON **integer**, `1 ≤ v ≤ 2^53-1` (fits an f64/i64 both sides; overflow/negative
  rejected). The desktop's Wave-3a `requested_at` is normalized to `requested_at_ms` (ms)
  **when the challenge authority builds the challenge** (§4.1); the whole chain is ms after
  that point.
- **`challenge_accepted_at_ms` is produced by exactly one supervisor clock read** (§5 step
  2) and is the **only** field the validity/expiry/revocation window is checked against.
- **Boundaries are inclusive on both ends:** a time `t` is in a window iff
  `lo_ms ≤ t ≤ hi_ms`. The acceptance predicate (§5, §7) is
  `requested_at_ms ≤ challenge_accepted_at_ms` **and**
  `challenge_issued_at_ms ≤ challenge_accepted_at_ms ≤ challenge_expires_at_ms`.
- **Freshness + window nesting (P1-6, LOCKED).** The desktop freshness window is the real
  `FreshnessWindow{future_skew_ms: 60000, max_age_ms: 300000}` (`receipt_store.rs`). Every
  engine-side governed-turn window MUST nest inside `max_age_ms = 300000` so a legitimately
  executed turn is never refused as stale: governed **challenge TTL** `≤ 30000 ms`;
  **`EXECUTION_TIMEOUT_MS = 120000`** (§4.7); governed **lease window** `≥ EXECUTION_TIMEOUT_MS`
  + teardown; and engine↔desktop wall-clock skew bounded `≤ 60000 ms` (shared NTP) because the
  desktop stale check has **no** skew allowance on the old side. Elapsed timeouts use a MONOTONIC
  clock; only signed `_ms` fields use the wall clock (§4.7).
- **Negative tests (normative):** a value that is plausibly seconds not ms (≈10 digits vs
  ≈13) is rejected by range/consistency; overflow, negative, zero, far-future-skew, and each
  inclusive boundary (`== lo_ms`, `== hi_ms`, `lo-1`, `hi+1`) are covered. Cross-language
  (Python engine ↔ Rust desktop) parity asserts identical ms integers.

---

## 2. Principals & capabilities (P0-3) — the executor inherits NO builder authority

The base lease task classes (`STANDARD_BUILDER`, `SECURITY_MAINTENANCE`) each grant
`{EXECUTE_CODE, WRITE_FILESYSTEM, WRITE_REPOSITORY}` and are built around repos/worktrees.
The governed model executor's locked topology gives it **only three read-only input FDs and
one write-only output FD** (§4.7). It therefore uses a **dedicated, closed capability
profile — NOT a base-lease superset**:

- **task class `governed-model-turn-v1`** with a **CLOSED** capability set
  `["INVOKE_GOVERNED_MODEL"]` — the single narrow capability "run the pinned model executor
  once, read the three input FDs, write the one output FD". It **MUST NOT** include
  `EXECUTE_CODE`, `WRITE_FILESYSTEM`, `WRITE_REPOSITORY`, arbitrary path access, arbitrary
  executable selection, or arbitrary tool invocation. `validate_governed_turn_lease` (§4.3)
  rejects any lease whose `allowed_capabilities` is not exactly `["INVOKE_GOVERNED_MODEL"]`.
- **`max_tool_calls = 0`** — tool use is out of 3b-1B scope and **fails closed**. (If tool
  execution is ever added, it needs a separately-mediated, exactly-scoped tool-broker
  contract; builder capabilities are never inherited implicitly.)
- The **pinned launcher executable digest** (`launcher_executable_sha256`) and the **model
  profile** (`model_profile_id`) are explicit lease fields with real verifiers (§4.3): the
  launcher refuses any other executable/target UID (§4.7), and the recorder refuses a
  `model_profile_id` not in its allow-set.
- **ONE model authority (P0-2 LOCKED — identity is a DETERMINISTIC FUNCTION of the config, not a
  lookup).** `model_profile_id` is **NOT** a free lease field and is **NOT** resolved through any
  mutable map. The executor reads the actual `engine_id`/`model`/`max_output_tokens`/`temperature`/
  `top_p` from the `generation_config` FD (§4.7); the model identity is therefore **defined** as a
  pure, total function of the config's canonical hash — **no registry, no historical lookup, no
  supervisor-owned mapping table**:
  ```
  model_profile_id = "cfg-sha256:" + generation_config_sha256
  ```
  where `generation_config_sha256 = SHA256(JCS(generation_config))` (the §4.10(g) flat string→string
  object form). The result is `"cfg-sha256:"` (11 chars) + 64 lowercase-hex = **exactly 75 chars**,
  within the `≤128` bound; `model_profile_id` MUST match `^cfg-sha256:[0-9a-f]{64}$`. Because identity
  is a deterministic function of the signed config hash alone, it is **immutable and historically
  verifiable forever from the signed lease/record bytes** — no external state can reinterpret or
  invalidate a past execution's identity.
- **Execution allowlist (an EXECUTION GATE, NOT an identity source — P0-2 LOCKED).** Whether a config
  is *permitted to execute* is a **separate** supervisor decision from what its identity *is*. The
  supervisor owns a **`GOVERNED_EXECUTION_ALLOWLIST`**: a set of `generation_config_sha256` values
  (each `^[0-9a-f]{64}$`) it will launch, computed deterministically at supervisor start by
  canonicalizing (JCS) + hashing every governed config it is configured to permit — at minimum the
  frozen-default config, hash `732b58634d0a83e9b7fdf1ca69db78df145bd9dd79ac8922fed3e79cf5faab22`,
  plus the hash of each config a valid trusted-host override combination its environment resolves to
  (§4.10(g)). It is frozen for the process lifetime (a change is a restart). **The allowlist decides
  ONLY whether a config MAY execute; it MUST NOT map a hash to an identity, MUST NOT redefine the
  identity formula, and MUST NOT be consulted by any identity derivation or by historical
  verification (§7).**
- **Before acceptance** the supervisor parses+validates the **staged** `generation_config` bytes
  (§2.4), recomputes `generation_config_sha256`, asserts it equals the challenge's committed value (a
  mismatch is `handle_not_challenge`, §2.4), **requires it ∈ `GOVERNED_EXECUTION_ALLOWLIST`** (a hash
  not in the allowlist ⇒ `model_profile_unknown` Block, no lease, no launch — §4.5), and **derives
  `model_profile_id = "cfg-sha256:" + generation_config_sha256`** by the formula only.
  `issue_governed_turn_lease` (§4.3) sets the lease `model_profile_id` to exactly that derived value
  and binds `generation_config_sha256` as a signed field. `validate_governed_turn_lease` (§4.3) and
  `LiveRunStateProvider` (§7) **each independently recompute the formula + equality chain** and refuse
  unless `lease.model_profile_id == "cfg-sha256:" + lease.generation_config_sha256` **and**
  `lease.generation_config_sha256 == challenge.generation_config_sha256 == the executed config's
  re-hashed bytes` — neither verifier consults the allowlist (§7 verifies identity, not
  execution-permission), so a later allowlist change never touches a past record. Any
  model/engine/parameter mismatch Blocks **before launch**.
- The governed-turn lease **omits** the builder-only fields `repository`, `branch`,
  `worktree`, `head_sha`, `tree_identity`, and `protected_scope` — none has a verifier for a
  model turn. (If a future justified use reintroduces `protected_scope`, its type is an
  **array of exact non-pattern paths**, never a string.)

### 2.5 TCB binary & config integrity (P0 — code-integrity floor, NORMATIVE)

A pinned digest in the lease only proves *which* image the launcher is *told* to run — it does
**nothing** if the sidecar (compromised — the **dedicated sidecar SERVICE UID**, Actor C, NOT the login
user) can **overwrite that image on disk**.
Pinning `launcher_executable_sha256` while leaving the **executor** image unpinned and any TCB
binary **login-user-writable** is a forge path: the sidecar swaps the executor (or launcher, signer,
supervisor) binary and obtains a **genuinely-signed** `trusted_verified` for attacker-chosen output.
This section closes it.

- **TCB binary set (LOCKED).** The trusted-computing-base executables are: the **supervisor**, the
  **evidence-recorder runner**, the **privileged setuid launcher**, the **contained model executor**,
  the **isolated receipt signer**, the **trusted desktop verifier/broker service** executable, and the
  **`desktop-challenge-authority`** executable — plus every file that steers them: their **config /
  policy bundles** (**including both the broker's and the challenge-authority's config / policy**), the
  **broker IPC / peer-auth policy**, the **`desktop-challenge-authority` IPC / peer-auth policy**, the
  **broker pinned-manifest configuration**, **every library / plugin loaded into either trusted process**
  (the broker or the challenge-authority), the **`GOVERNED_EXECUTION_ALLOWLIST`** source, the
  key-manifest/root-anchor, and the systemd/service unit files (**including both services' unit files**).
  Call this set `TCB_ARTIFACTS`.
- **Ownership + non-writability floor (NORMATIVE).** Every path in `TCB_ARTIFACTS`, **and every
  ancestor directory up to `/`**, MUST be **owned by a dedicated TCB principal** (`root` or a
  dedicated `brops-admin` that is NOT any runtime principal) and **MUST NOT be writable** — by mode
  bits **or** POSIX ACL **or** group membership — by the interactive login user or by the
  `verifier/broker` / `challenge-authority` / `sidecar` / `desktop-UI` / `supervisor` / `recorder` /
  `executor` / `signer` runtime UIDs. (The
  runtime principals get **read/execute only**; the private-key store keeps its existing owner-only
  ACL, §2.3.) A writable ancestor directory is treated as writable (a rename/replace vector).
- **Start-time verification `verify_tcb_integrity()` (fail-closed).** At supervisor start (before it
  will issue **any** governed-turn lease) the supervisor, from a **root-owned pin manifest**, holds
  the expected `sha256` of **every** `TCB_ARTIFACT` and: (a) `fstat`s each opened `fd` (`O_NOFOLLOW`,
  never a path re-lookup) and refuses unless owner ∈ TCB principals and no write bit/ACL for any
  runtime/login UID; (b) re-hashes each binary/config and refuses on any mismatch; (c) verifies the
  **trusted verifier/broker** and **`desktop-challenge-authority`** executables, their config/policy,
  their IPC/peer-auth policy, and (for the broker) the **pinned-manifest configuration** are each
  **present**, **TCB-owned**, **non-writable** (by mode/ACL/group/writable-ancestor for any runtime or
  login UID) and **hash-matched to the exact start-time SHA-256 pin**, and confirms **each of the two
  services runs under its own expected service UID/SID** (Windows: SID; POSIX: UID) with the expected
  **peer-auth policy** in force. Failure of **any** clause — including either service's binary, config,
  or policy being **missing**, **writable**, or **hash-mismatched**, a **wrong service UID/SID**, or a
  **peer-auth-policy mismatch** ⇒ governed real-mode is **DISABLED** (the platform gate §0.1 reports
  unsupported; every governed turn Blocks) — never a partial/degraded launch.
- **Lease-time + exec-time re-binding.** `issue_governed_turn_lease` sets `launcher_executable_sha256`
  **and** `executor_executable_sha256` to the start-time TCB pins; `validate_governed_turn_lease` (§4.3)
  refuses a lease naming any other digest; and the launcher **re-hashes the executor image it is about
  to run and `fexecve`s the exact verified `fd`** (§4.7) so the bytes hashed are the bytes executed
  (no path-relookup TOCTOU). The recorder binds both digests into the signed execution receipt (§4.7).
- **Negative tests (normative, §9).** login-user-writable executor image ⇒ start refused; executor
  bytes swapped after pinning (hash mismatch at `fexecve`) ⇒ `tcb_integrity_violation` Block, no
  receipt; wrong-owner launcher / signer / config ⇒ start refused; a writable **ancestor directory**
  of any TCB path ⇒ start refused; a lease naming an unpinned `executor_executable_sha256` ⇒ Block;
  **login-writable trusted verifier/broker binary ⇒ governed mode DISABLED**; **modified
  (hash-mismatched) broker binary ⇒ governed mode DISABLED**; **login-writable
  `desktop-challenge-authority` binary or config ⇒ governed mode DISABLED**; **modified (hash-mismatched)
  challenge-authority binary or config ⇒ governed mode DISABLED**; **a writable ancestor directory of
  either service's binary/config ⇒ governed mode DISABLED**; **a wrong service owner / SID / UID for the
  broker or challenge-authority ⇒ governed mode DISABLED**; **a fake broker (not the pinned, TCB-owned
  binary running under the expected service UID/SID) cannot create, persist, or display a `Verified`
  result.**

### 2.6 Distinct-principal provisioning linchpin (P0 — no single-UID collapse, NORMATIVE)

Every ACL, `SO_PEERCRED` allowlist, and file-ownership boundary in this design assumes the runtime
principals are **different OS UIDs**. If provisioning quietly lands two of them on the **same UID**
— most dangerously the **renderer/login** identity sharing the **trusted verifier/broker** UID, the
**broker** sharing the **`desktop-challenge-authority`** UID, or the **`sidecar`** sharing any of them
— the entire separation model silently collapses (the attacker *is* the final verifier / *is* the
authority / *owns* the store). rev-28 splits the renderer from the trusted verifier/broker (P0-1) and
keeps the sidecar's own distinct UID a **checked** linchpin.

- **The SEVEN runtime service UIDs (NORMATIVE, P0-1, rev-28).** `trusted desktop verifier/broker`,
  `desktop-challenge-authority`, `sidecar`, `supervisor`, `evidence-recorder runner`,
  `contained executor`, and `isolated signer` MUST each run as a **dedicated OS UID**, **pairwise
  distinct**, and **all ≠ the interactive login UID**. The **renderer/session UI is NOT a service UID**
  — it *is* the interactive login role (the low-trust identity, Actor B); it must therefore be **≠ every
  one of the seven** (the check enforces `login UID ∉ {the seven}`, which is exactly the renderer
  being distinct from the broker/authority/etc.). The **privileged launcher is NOT in this set** —
  under Model A (P0-2/§2.7) it is a **root/TCB-owned setuid file**, verified by `verify_tcb_integrity()`
  (§2.5). In particular: the **trusted verifier/broker** (#2) runs as its own service UID and is
  **never** the login/renderer UID (a compromised renderer can never *become* the final verifier) nor
  the challenge-authority UID; the **challenge authority** (#3) is its own UID and accepts IPC only from
  the broker UID; the **sidecar** (Actor C) runs as its own UID — never login/renderer/broker/authority,
  never a UID sharing the authority socket ACL or the `store/` ACL — and a process it spawns MUST NOT
  inherit a UID carrying any of those grants.
- **Provisioning (operator/installer, NORMATIVE).** Installation MUST create these dedicated service
  accounts (e.g. `brops-verifier`, `brops-challenge`, `brops-sidecar`, `brops-supervisor`,
  `brops-recorder`, `brops-executor`, `brops-signer`), run the **renderer under the interactive login
  identity** (never a service account), start each service component under its own account, and install
  the launcher as a **root/TCB-owned** setuid binary. It MUST NOT run any of the seven services as the
  login user, and MUST NOT run the broker in-process with the renderer.
- **Start-time verification `verify_distinct_principals()` (fail-closed).** At start the supervisor
  resolves the effective UID configured for the **seven runtime service principals** and refuses to
  enable governed real-mode unless **all are present, pairwise-distinct, and ≠ the interactive login
  UID** (so the renderer/login identity equals none of them; the launcher's root/TCB ownership is
  checked by `verify_tcb_integrity()`, §2.5). On a single-UID host (a developer laptop or a
  mis-provisioned install) the check fails ⇒ the platform gate (§0.1) reports **unsupported** ⇒ every
  governed turn is **FAIL-CLOSED** (no lease, `NoTrustedManifest`-equivalent).
- **Negative tests (normative, §9).** any two of the seven service principals sharing a UID ⇒ Block;
  `verifier/broker` UID == login/renderer UID ⇒ Block; `broker` UID == `challenge-authority` UID ⇒
  Block; `sidecar` UID == login UID ⇒ Block; any of the seven unset/defaulted to login ⇒ Block;
  **renderer-isolation:** the renderer (login UID) cannot read/write/list the verifier DB or manifest,
  cannot call the challenge-authority IPC, cannot reach the sidecar/supervisor/signer IPC, cannot supply
  `system`/`history`/`config`/hashes/nonces/receipt fields, and a forged renderer "Verified" event
  cannot create a verified message (only the broker's committed verification tx does); the broker
  accepts only the closed renderer command and resolves all authoritative inputs itself. A passing
  7-distinct-service-UID fixture (+ a distinct login/renderer identity + a root/TCB launcher) ⇒ these
  proofs all hold.

### 2.7 Privileged launcher — LOCKED to Model A (P0-2, NORMATIVE)

rev-26 was un-implementable: it required TCB binaries owned by `root`/`brops-admin` (not a runtime
principal) **and** a dedicated launcher runtime UID among the pairwise-distinct principals **and** a
setuid launcher — three mutually contradictory statements. rev-27 locks exactly **Model A: a
root/TCB-owned setuid helper, not a persistent runtime UID**. Every field is fixed:

- **Binary owner / file owner:** `root` (or the dedicated `brops-admin` TCB principal). The file has
  mode `4750` (setuid, owner `root`/TCB, group = the recorder group, **no** world/other bits), and
  its parent directories up to `/` are TCB-owned + non-writable by any runtime/login UID (§2.5).
- **Invoking principal:** **only** the `evidence-recorder runner` (#5) may `exec` it; the launcher
  checks its real UID/gid on entry (`getresuid`) and refuses (`tcb_integrity_violation`) unless the
  caller is exactly the recorder. No other principal — sidecar, desktop-UI, supervisor, signer, login
  user — may invoke it (mode `0` for other; group-exec limited to the recorder group).
- **Bootstrap privilege (P0-2 correction).** A setuid-root helper starts **fully privileged** (effective
  UID root, a full effective/permitted capability set). It is therefore **wrong** to claim it "has only
  `{CAP_SETUID, CAP_SETGID}`"; it must *reduce to* those and then to zero. The exact reduction is the
  locked sequence below. Removing the **bounding** set requires **`CAP_SETPCAP`** (held at entry as
  root); the final state is **zero capabilities in every set**.
- **Exact privilege-drop syscall sequence (LOCKED, P0-2 — order is load-bearing).** GID/groups MUST be
  changed **before** the UID drop (after dropping to the executor UID the process can no longer change
  its groups/GID). The sequence:
  1. **Entry:** real UID = recorder, effective/saved UID = root (setuid); verify `getresuid`/`getresgid`
     ⇒ caller is exactly the recorder; verify immutable argv, empty environment, the exact FD set (below),
     the lease, all hashes, the cgroup path, and the target executor UID/GID. Any mismatch ⇒ refuse
     (`tcb_integrity_violation`), **no exec, no receipt**.
  2. Perform all **root-required** cgroup / process-group / rlimit setup.
  3. `setgroups([])` — clear **all** supplementary groups.
  4. `setresgid(exec_gid, exec_gid, exec_gid)` — real/effective/saved GID = executor GID.
  5. Drop the **capability bounding set** (and ambient set) to empty using **`CAP_SETPCAP`**
     (`prctl(PR_CAPBSET_DROP, …)` for every cap; clear `PR_CAP_AMBIENT`), while still UID-root so the op
     is permitted.
  6. `setresuid(exec_uid, exec_uid, exec_uid)` — real/effective/saved UID = executor UID (drops the
     effective/permitted caps that root implied).
  7. `capset()` the effective/permitted/inheritable sets to **zero** (belt-and-suspenders; bounding +
     ambient already empty).
  8. **Verify** (fail-closed) `getresuid`/`getresgid` == (exec, exec, exec), `getgroups()` == empty, and
     **all five capability sets (eff/perm/inh/bounding/ambient) == 0**; any residual ⇒ abort, no exec.
  9. `prctl(PR_SET_NO_NEW_PRIVS, 1)`.
  10. Normalize signal dispositions/mask, `umask`, and resource limits as required.
  11. `fexecve(executor_fd, fixed_argv, empty_env)` with **only FDs 3–6** open.
  A failure at **any** step ⇒ abort before exec; the recorder tears down the cgroup (SIGKILL) and
  produces **no** receipt/evidence/record.
- **Capabilities / privileges (final):** **zero** in every set after step 8; `no_new_privs` set;
  bounding + ambient empty. During the sequence only `{CAP_SETPCAP, CAP_SETUID, CAP_SETGID}` (+ the
  root privilege for cgroup setup) are actually used; no `CAP_DAC_OVERRIDE`, `CAP_SYS_ADMIN`, or network.
- **IPC / direct-exec boundary:** **direct exec**, not an IPC service. The recorder `fork`s and the
  child `execve`s the launcher with a fixed argv/FD set — no launcher socket, no request parsing, no
  confused-deputy service surface.
- **Allowed argv / env:** a **fixed, closed** argv (lease handle + the pinned executor index + the
  cgroup path); **environment fully cleared** (no inheritance) so no `LD_PRELOAD`/`PATH`/`BROPS_*`
  influence. Any extra/unknown argv or a non-empty env ⇒ refuse.
- **Inherited FDs — SURVIVAL across BOTH exec boundaries (P0-3 correction, NORMATIVE).** The executor's
  I/O channel is FDs **3/4/5/6** (three read-only inputs + the write-only output, §4.7). They MUST
  **survive both** exec boundaries — recorder-child → `execve(launcher)` **and** launcher →
  `fexecve(executor)` — and FD survival is prepared by the **recorder BEFORE it launches the setuid
  helper**. The rev-27 text was un-implementable: it described only the launcher acting (a setuid helper
  can only clear `FD_CLOEXEC` on descriptors it *already* inherited, so nothing survives the *first*
  boundary unless the recorder prepares it), and it wrongly set `O_CLOEXEC` on the data FDs, which would
  have closed the executor's only I/O at exec. The two-sided contract is LOCKED:
  - **RECORDER — before `execve(launcher)` (the first boundary):**
    1. **Map** the three read-only input descriptors and the write-only output descriptor onto the
       **exact numbers 3, 4, 5 and 6** (`system`→3, `history`→4, `generation_config`→5, output-pipe→6);
       never assume an inherited number.
    2. Perform the renumber with **`dup2`/`dup3`** (or an equivalent atomic descriptor move).
    3. **Explicitly CLEAR `FD_CLOEXEC`** on each of FDs **3–6** (`fcntl(fd, F_SETFD, flags & ~FD_CLOEXEC)`)
       so they cross `execve(launcher)` instead of being closed at exec.
    4. **Open controlled INERT endpoints and MAP them onto FDs 0/1/2** (symmetric with the 3–6 map
       above — a defined inert state, never "just closed" and never interactive). `open("/dev/null",
       O_RDONLY)` for FD 0 and `/dev/null` (or a controlled append-only log sink) `O_WRONLY` for FDs 1
       and 2; `dup2`/`dup3` those inert endpoints onto the **exact numbers 0, 1 and 2** (**replacing**
       any inherited interactive/ambient stdio), and **explicitly CLEAR `FD_CLOEXEC`** on 0/1/2 so the
       launcher **inherits the known-inert stdio and can verify it** at the second boundary — the child
       never sees interactive, inherited, or absent stdio.
    5. **Close every FD ≥ 7** (`close_range(7, ~0U, 0)`), **except** an explicitly defined
       executor-image / launcher-bootstrap handle **where the platform requires the recorder to pass
       one** — on Linux Model A none is required (the launcher opens the executor image itself, below),
       so nothing above FD 6 survives.
    6. **`execve` the launcher with the fixed, closed argv and a fully EMPTY environment** (§ "Allowed
       argv / env") — no inherited `LD_PRELOAD`/`PATH`/`BROPS_*`.
  - **LAUNCHER — before `fexecve(executor)` (the second boundary):**
    1. **Verify EXACTLY FDs 3–6 exist** with the correct access mode, inode/type, offset and store
       binding: FDs 3/4/5 each `O_RDONLY` + `S_ISREG` + offset 0 + backed by a `brops-store` store inode
       (size ≤ its per-artifact ceiling, §4.7), and FD 6 the write-only output pipe.
    2. **Explicitly confirm — and, if needed, re-clear — `FD_CLOEXEC`** on each of FDs 3–6 so they also
       cross `fexecve`; a data FD 3–6 that arrives marked `FD_CLOEXEC` and cannot be cleared ⇒ refuse.
    3. **Verify and NEUTRALIZE stdio — FDs 0/1/2 (symmetric with the 3–6 verification).** Confirm 0, 1
       and 2 are **EXACTLY** the approved inert endpoints the recorder mapped — FD 0 `O_RDONLY`, FDs 1/2
       `O_WRONLY`, each backed by `/dev/null` (or the controlled log-sink inode) and **never** a
       tty/pty, socket, pipe, or any interactive/inherited/ambient stdio; interactive, inherited,
       missing, or otherwise-unexpected stdio ⇒ refuse. Then, **BEFORE `fexecve`, CLOSE FDs 0/1/2 (or
       set `FD_CLOEXEC` on each)** so the inert stdio does **NOT** cross the second boundary into the
       executor. **Reject** any FD ≥ 7, or anything outside the exact set {0,1,2,3,4,5,6} ⇒ refuse —
       after this step **only FDs 3–6** survive into the executor.
    4. **Open the executor image separately** with **`O_NOFOLLOW|O_RDONLY|O_CLOEXEC`** (it is NOT one of
       FDs 3–6, is used **only** by `fexecve`, and is closed by a successful exec).
    5. Perform the **locked privilege-drop sequence** (steps 2–10 of the sequence above).
    6. **`fexecve` the verified executor image with ONLY the approved data descriptors (3–6) surviving**
       — every other descriptor already closed or close-on-exec.
  Any failure on either side — a data FD 3–6 arriving `FD_CLOEXEC` that cannot be cleared, a missing /
  wrong-mode / wrong-inode/type / wrong-offset / wrong-store-binding data FD, a non-inert / interactive
  / inherited FD 0/1/2 (not the approved inert endpoints), stdio that cannot be neutralized before the
  second boundary, or any unexpected extra FD ⇒ **refuse before signing any receipt**: no exec, and **no**
  receipt/evidence/terminal record.
- **Real executable integration test (NORMATIVE, §9).** A tiny **pinned** test executor that (a) on
  entry **enumerates `/proc/self/fd` and asserts the open descriptor set is EXACTLY {3,4,5,6}** —
  proving FDs 0/1/2 were neutralized and every FD ≥ 7 closed before `fexecve`, i.e. **only** the four
  data descriptors were inherited — and (b) reads all three input FDs to EOF and writes a known output
  through FD 6 MUST run successfully through the real recorder → launcher → `fexecve` path (proving FD
  survival + stdio neutralization + the privilege drop actually work), and the full negative matrix
  below MUST fail closed.
- **Target executable + UID:** the **pinned** `executor_executable_sha256` image (from the lease,
  §4.3) run as the fixed **executor UID**. No arbitrary target executable, target UID, or argument
  selection — both are validated against the lease before any privilege use.
- **Start-time + exec-time integrity:** start-time — `verify_tcb_integrity()` confirms the launcher
  binary is root/TCB-owned + non-writable + matches its pin (§2.5). Exec-time — the launcher opens the
  executor image `O_NOFOLLOW`, `fstat`s the `fd` (owner/mode), **re-hashes it and compares to the
  lease `executor_executable_sha256`**, then `fexecve`s **that exact fd** (bytes hashed == bytes
  executed, no path-relookup TOCTOU). Any mismatch ⇒ `tcb_integrity_violation`, no exec, no receipt.
- **Failure + teardown:** any check failure ⇒ **no exec**, non-zero exit, the recorder tears down the
  cgroup/process-group (SIGKILL) and produces **no** receipt/evidence/record (`tcb_integrity_violation`
  or `platform_unsupported`). A crash mid-drop cannot leave a root-privileged process (drop precedes
  exec; the helper is short-lived and holds no key/store handle).
- **Windows equivalent (§0.W):** there is no setuid; the recorder-equivalent service calls
  `CreateProcessAsUser` with the **executor's restricted token**, having verified the executor image's
  **hash + Authenticode + NTFS ACL (non-writable by login/runtime SIDs)** before launch; the launcher
  helper binary is ACL'd non-writable + WDAC/AppLocker-pinned. Same closed argv / cleared env / fixed
  FD (via explicit `STARTUPINFOEX` handle list) / pinned-image / restricted-token rules.
- **Confused-deputy / oracle negative matrix (normative, §9):** wrong caller UID (≠ recorder) ⇒ refuse;
  extra group / residual supplementary groups after the drop ⇒ refuse; extra argv / non-empty env /
  extra inherited FD ⇒ refuse; interactive / inherited / non-inert stdio on FDs 0/1/2 (a tty/pty,
  socket, pipe, or anything that is NOT the approved inert `/dev/null`/log-sink endpoint) ⇒ refuse; any
  0/1/2 (or other non-{3,4,5,6}) descriptor left surviving into the executor ⇒ refuse; a data FD 3–6
  arriving `FD_CLOEXEC` (would close the executor I/O) ⇒
  refuse; wrong executor UID **or** GID ⇒ refuse; target executable ≠ pinned `executor_executable_sha256`
  ⇒ refuse; writable/login-owned executor image ⇒ refuse; residual **effective/permitted/inheritable/
  ambient/bounding** capability after the drop ⇒ refuse; a failed `setgroups`/`setresgid`/`setresuid`/
  `prctl`/`capset` ⇒ refuse; image hash/owner/mode/path swap ⇒ refuse; cgroup mismatch ⇒ refuse;
  `fexecve` failure ⇒ refuse. **Every** failure yields **no receipt/evidence/terminal record**. The
  launcher can be coerced into **no** action other than "run this exact pinned image as the executor,
  with these exact FDs, fully unprivileged, or refuse." (§4.7 mirrors the exec-boundary FD rules.)

### 2.1 Challenge-authority trust boundary + creation channel (P0-2, NORMATIVE — no oracle)

The sidecar is compromised-in-scope as a **dedicated sidecar SERVICE UID** (Actor C — **NOT** the login
user), and the renderer (Actor B, login identity) is separately untrusted. The desktop signed challenge
(artifact #1) is minted by a **dedicated `desktop-challenge-authority`** whose create-pending/issue IPC
is accepted **only from the trusted desktop verifier/broker UID** (never the renderer/login UID, never
the sidecar) and which is neither a `sign(payload)` oracle nor a `create_pending(arbitrary_bytes) →
sign(id)` two-step oracle (the mandated create-pending/issue split below is **not** such an oracle:
create-pending stores only strictly-validated fixed-shape hashes/ids — never arbitrary bytes — and issue
signs only what the authority itself assembles from its own row).
The exact current contract (not history):

- **Store ownership:** the **pending-challenge store** (the trusted rows the authority builds
  challenges from) and the authority private key are owned by the authority's **own dedicated
  OS principal (UID/SID)**, mode owner-only (`0700`). **The sidecar UID can neither read, nor
  write, nor list** it — so it can neither exfiltrate the key nor tamper a row directly.
- **Distinct principals:** the **trusted verifier/broker principal MUST be a UID distinct from the
  renderer/login identity AND from the sidecar** principal — the authority's only accepted peer is the
  broker UID (§0). Where a platform cannot provide that separation, governed real-mode is
  **FAIL-CLOSED** on that platform (mirrors the Windows-broker stance, §0).
- **Creation channel (TWO explicit messages, ONE canonical trust model — P1-2 LOCKED):**
  pending-challenge rows are created and challenges are issued **only** through the
  **authority-owned `AF_UNIX` channel**; on Linux the authority authenticates the peer with
  **`SO_PEERCRED`, allowlisting the exact trusted verifier/broker UID** — the **renderer/login UID and
  the sidecar UID are DENIED** on both messages. The channel carries exactly two request/reply protocols, and **neither ever carries
  challenge bytes or a caller-chosen canonical payload** (this replaces the rev-18 "facts **or**
  row-id" disjunction, which left the implementer a choice between two trust models):
  - **(A) `brops.governed-challenge-create-pending.v1`** (create-pending / propose — **does NOT
    sign**). The **broker** supplies the **BROKER-minted `request_nonce`** (the ratified Wave-3a
    nonce — `prepare_governed_turn_v1b` → `brops_core::id()` UUIDv4; see §4.10(g)) **plus the structured
    authoritative turn facts** (`run_id`/`task_id` + `workspace_id`/`install_id` context +
    `system_sha256`/`history_sha256`/`generation_config_sha256`/`requested_at_ms`). It does **NOT**
    supply `request_sha256`. The authority **validates** them (rules below), **recomputes
    `request_sha256` itself** from the supplied `request_nonce` + normalized context + the three
    hashes via the **merged canonical request-envelope formula** (`receipt.rs::request_envelope_sha256:245-264`
    ↔ `brops_canonical.request_sha256:157-179` — `protocol="brops.request.v1"`, an 8-field JCS
    envelope with `request_nonce` **inside** the hashed bytes), and **stores the supplied nonce + the
    recomputed `request_sha256` + facts verbatim in its OWN protected pending-challenge row**, minting
    **only** a **fresh opaque `pending_challenge_id`** (it NEVER mints the `request_nonce` — that is the
    broker's, already pre-stored by the broker in `receipt_challenges`, see the pre-store bullet
    below); it returns that `pending_challenge_id`. No signature is produced and no
    `brops.governed-turn-challenge.v1` payload exists yet. Reply
    `brops.governed-challenge-create-pending-result.v1`. **Frame ≤ `AUTHORITY_CHANNEL_FRAME_BYTES`
    (8192, §2.1.1)** each way (the same authority-reply cap as the (B) issue reply).
  - **(B) `brops.governed-challenge-issue.v1`** (issue / sign — **signs exactly once**). The
    **broker** supplies **ONLY the `pending_challenge_id`** (never facts, never bytes). The authority
    **resolves the row from its OWN protected store**, **constructs the exact
    `brops.governed-turn-challenge.v1` payload (§4.1) itself** — selecting `challenge_key_id` from its
    active registry key, filling `workspace_id`/`install_id`/`supervisor_id` from its own trusted
    config, copying the stored `*_sha256`/`requested_at_ms`/`run_id`/`task_id`/`request_nonce`, and
    stamping `challenge_issued_at_ms`/`challenge_expires_at_ms` from its own clock — **signs once**,
    **one-time-consumes** the pending row (`PENDING → ISSUED`, non-reusable), and returns the signed
    `{payload,sig}` document. Reply `brops.governed-challenge-issue-result.v1`, carrying
    `challenge_document_b64` (decoded ≤ `CHALLENGE_DOCUMENT_MAX_BYTES = 4096`); **reply frame ≤
    `AUTHORITY_CHANNEL_FRAME_BYTES = 8192`** (worst case 5563 B, §2.1.1(g) — the old "≤ 4 KiB" could not
    hold a 4096-byte document + base64 + envelope); **request frame ≤ `AUTHORITY_REQUEST_FRAME_BYTES =
    4096`**. The same 8192 reply cap applies to `create-pending-result` (§2.1.1).
- **Single trust invariant (LOCKED):** the caller **NEVER** supplies challenge bytes or a
  caller-chosen canonical payload; the authority **ALWAYS** builds the signed
  `brops.governed-turn-challenge.v1` payload from its **own stored row**. Turn facts enter the system
  **only** at create-pending (A), where they are validated and stored; at issue (B) they are
  re-derived from the authority's own store and **never re-accepted from, or signed verbatim as,
  caller-controlled bytes.** There is no path by which supplied facts and a signature occur in the
  same message. (This closes the `create_pending(arbitrary_bytes) → sign(id)` oracle: (A) stores only
  strictly-validated fixed-shape hashes/ids — never free bytes — and (B) signs only what the authority
  itself assembled.)
- **Broker nonce authority + `receipt_challenges` pre-store (P0-1 LOCKED — "desktop" in this subsection DENOTES the trusted verifier/BROKER service, which owns `receipt_challenges`; NEVER the renderer/login process — preserves the ratified
  Wave-3a contract).** The `request_nonce` is minted by the **desktop**, and `request_sha256` is the
  SHA-256 of the canonical request **envelope that CONTAINS that nonce** — so the two are, by
  construction, ONE pair from ONE request. This is the already-merged Wave-3a model and MUST NOT be
  changed: (1) the desktop mints `request_nonce = brops_core::id()` (UUIDv4) inside the **NEW 3b-1B
  preparation function `prepare_governed_turn_v1b`** (§4.10(g) — the object-JCS-hash single source; NOT
  the frozen raw-string `prepare_governed_turn(&str)`, which produces a different
  `generation_config_sha256` and would split-authority the hash, P0-1); (2) **before** submitting the
  governed turn the desktop **atomically pre-stores** `(nonce, request_sha256, conversation_id)` in its
  own `receipt_challenges` table via `issue_challenge` (`receipt_store.rs:109-126`; ordering
  `commands.rs:866-878` runs BEFORE `governed_turn` at `commands.rs:883`), where
  `request_sha256 = IssuedRequest::request_sha256()` over the exact same fields — **including the
  object-JCS `generation_config_sha256` from `prepare_governed_turn_v1b`**, so the pre-stored hash and
  the authority/staging hash are one value, not two; (3) the desktop carries that SAME `request_nonce` + envelope fields into
  create-pending (A); (4) the authority **recomputes** `request_sha256` from those inputs with the
  byte-identical formula (`receipt.rs::request_envelope_sha256:245-264` ↔
  `brops_canonical.request_sha256:157-179`) and stores the desktop nonce + its recomputed hash; (5) at
  §4.10(a0) open-time the supervisor **recomputes** `request_sha256` the same way and requires equality;
  (6) at desktop final acceptance (§6.1 step 14) the one-time consume is keyed by
  `expected.request.request_nonce` against `receipt_challenges` (`receipt_store.rs:256-271`) and
  additionally requires the stored `request_sha256` to equal the expected envelope's
  (`receipt_store.rs:322-327`). Because every hop derives `request_sha256` from the SAME desktop nonce +
  context + hashes, the happy path is constructible end-to-end: authority recompute == supervisor
  recompute == the desktop's pre-stored row, and the desktop always finds its own issued nonce to
  consume. **The authority NEVER mints the nonce** (that would decouple it from `request_sha256` and
  from the desktop's pre-stored `receipt_challenges` row, forcing a supervisor `request_sha256`
  mismatch or a desktop "nonce not found" Block — the rev-19 defect this closes). A future
  authority-minted-nonce variant would require a separate ratified redesign (authority returns the
  nonce/hash pair; desktop atomically records them in `receipt_challenges` before submit) and is NOT in
  scope here.
- **Mandatory E2E test (P0-1):** one governed turn proves the single-envelope chain end-to-end — the
  desktop mints + pre-stores the nonce in `receipt_challenges`; create-pending (A) carries it; the
  authority-recomputed `request_sha256` equals the desktop's pre-stored value; issue (B) signs the §4.1
  challenge carrying that exact `(request_nonce, request_sha256)`; the supervisor open-time recompute
  (§4.10(a0)) matches; and desktop final acceptance consumes the **same** `receipt_challenges` row
  (nonce match + stored `request_sha256` == expected). Negatives: an authority that re-mints the nonce ⇒
  desktop consume fails / supervisor mismatch (both Block); a create-pending carrying a `request_sha256`
  field ⇒ `malformed`.

Creation-channel schemas (both on the authority-owned `AF_UNIX` + `SO_PEERCRED` **broker-UID**
channel — the renderer/login UID is denied; `additionalProperties:false`, unknown-field + duplicate-key rejection, schema-validated
before any side effect):
```jsonc
// (A) request:  (carries the DESKTOP-minted request_nonce + envelope fields; NO caller request_sha256 — the authority recomputes it)
{ "protocol": "brops.governed-challenge-create-pending.v1",
  "run_id": "<string ≤128>", "task_id": "<string ≤128>",
  "workspace_id": "<string ≤128>", "install_id": "<string ≤128>",   // context; the authority MAY substitute its own trusted install/workspace, but for the SAME install these MUST equal the desktop's values (they are inputs to request_sha256 — a divergence makes the authority-recomputed hash ≠ the desktop's pre-stored receipt_challenges.request_sha256 and every turn Blocks at receipt_store.rs:322-327)
  "request_nonce": "<string ≤128 — the desktop-minted brops_core::id() UUIDv4, already pre-stored in receipt_challenges>",
  "system_sha256": "<64hex>", "history_sha256": "<64hex>",
  "generation_config_sha256": "<64hex>",
  "requested_at_ms": <int> }        // the authority forms the envelope `requested_at` = decimal-ms string of this, matching ai.rs:1233
// (A) reply (created):  { "protocol": "brops.governed-challenge-create-pending-result.v1", "status": "created",
//   "pending_challenge_id": "<opaque string ≤128>", "pending_expires_at_ms": <int> }
// (A) reply (refused):  { "protocol": "brops.governed-challenge-create-pending-result.v1", "status": "refused",
//   "reason": "peer_denied"|"malformed"|"field_invalid"|"timestamp_invalid"|"oversize"|"retry_conflict"|"quota_pending" }
// (B) request:  { "protocol": "brops.governed-challenge-issue.v1", "pending_challenge_id": "<opaque string ≤128>" }
// (B) reply (issued):   { "protocol": "brops.governed-challenge-issue-result.v1", "status": "issued",
//   "challenge_document_b64": "<base64url of the EXACT signed {payload,sig} JCS bytes, decoded ≤ CHALLENGE_DOCUMENT_MAX_BYTES = 4096>" }
//   (P1-1: base64url carriage — the BROKER places it directly into challenge_doc_b64 at §4.10(a0)/(g) with NO re-canonicalization; an inline object would risk a non-canonical re-serialization the §4.10(a0) canonicality gate rejects.)
// (B) reply (refused):  { "protocol": "brops.governed-challenge-issue-result.v1", "status": "refused",
//   "reason": "peer_denied"|"no_pending_row"|"pending_expired"|"key_unavailable"|"malformed" }
//   (NOTE: an already-ISSUED row is NOT a refusal — it takes the idempotent replay path below and re-returns the stored `issued`.)
```
The authority's **protected pending-challenge store** (owner-only `0700`, §2.3) row:
```sql
CREATE TABLE governed_pending_challenge (
  pending_challenge_id     TEXT PRIMARY KEY,          -- opaque, authority-minted (≥128-bit random)
  request_nonce            TEXT NOT NULL,             -- BROKER-minted (brops_core::id() UUIDv4, prepare_governed_turn_v1b §4.10(g)); pre-stored by the BROKER in receipt_challenges BEFORE (A); the authority stores it verbatim, NEVER mints it (feeds §4.1 request_nonce)
  run_id TEXT NOT NULL, task_id TEXT NOT NULL, workspace_id TEXT NOT NULL, install_id TEXT NOT NULL,
  supervisor_id            TEXT NOT NULL,             -- authority's OWN config, never caller-supplied
  system_sha256 TEXT NOT NULL, history_sha256 TEXT NOT NULL,
  generation_config_sha256 TEXT NOT NULL,
  request_sha256           TEXT NOT NULL,             -- authority-RECOMPUTED via receipt.rs::request_envelope_sha256:245-264 / brops_canonical.request_sha256:157-179 from request_nonce+context+hashes (protocol brops.request.v1); NOT caller-supplied
  requested_at_ms          INTEGER NOT NULL,
  created_at_ms            INTEGER NOT NULL,          -- authority clock at create-pending
  pending_expires_at_ms    INTEGER NOT NULL,          -- created_at_ms + PENDING_TTL_MS
  state                    TEXT NOT NULL,             -- 'PENDING' → 'ISSUED' (one-time-consume); terminal
  issued_at_ms             INTEGER,                    -- authority clock stamped in the CAS PENDING→ISSUED tx; NULL while PENDING; the ISSUED retention/sweep key (issued_at_ms + ISSUED_RETENTION_MS)
  issued_challenge_document TEXT,                     -- the EXACT signed {payload,sig} JCS document (base64url), stored verbatim at issue so a lost-reply retry replays byte-identical bytes (a hash cannot reproduce its preimage)
  issued_challenge_handle  TEXT,                      -- SHA256(decode(issued_challenge_document)) — integrity only, NOT the replay source
  UNIQUE(install_id, request_nonce),                  -- nonce one-time per install (mirrors §4.10(a0))
  UNIQUE(install_id, request_sha256) );               -- idempotency key: one pending row per identical request
```
- **Validation (A):** peer UID == allowlisted **trusted verifier/broker UID** (a renderer/login UID ⇒ `peer_denied`) else `peer_denied`; strict UTF-8 JSON +
  `additionalProperties:false` + duplicate-key rejection + exact required set
  `[protocol,run_id,task_id,workspace_id,install_id,request_nonce,system_sha256,history_sha256,generation_config_sha256,requested_at_ms]`
  else `malformed` (a caller-supplied `request_sha256` is an unknown field ⇒ `malformed`, since the
  authority recomputes it); every `*_sha256` matches `^[0-9a-f]{64}$`, `request_nonce` non-empty and
  all ids ≤128 else `field_invalid`; `requested_at_ms` an integer in the §1 canonical-ms range and not
  future-beyond-skew else `timestamp_invalid`; serialized frame ≤ 4096 else `oversize`; a 3rd live
  `PENDING` row for the `install_id` ⇒ `quota_pending` (mirrors `MAX_CONCURRENT_GOVERNED_TURNS = 2`).
  The authority sets `supervisor_id`, `created_at_ms`, `pending_expires_at_ms` (and later
  `challenge_key_id`) from its **own** state, and **recomputes `request_sha256`** from the supplied
  `request_nonce` + normalized context + hashes — it takes `request_nonce` verbatim from the request
  (the desktop's) but never re-mints it and never accepts a caller `request_sha256`.
- **One-time consume + idempotency (P1-6):** a repeat (A) with the same `(install_id, request_nonce)`
  AND identical stored facts re-returns the SAME `pending_challenge_id`/`pending_expires_at_ms`
  (lost-reply safe retry; the recomputed `request_sha256` is deterministic in the same inputs, so it is
  identical too); a repeat with the same `(install_id, request_nonce)` but any differing fact (or a
  differing recomputed `request_sha256`) ⇒ `retry_conflict`. Issue (B) atomically CAS
  `PENDING → ISSUED` before returning; the first success **signs once and stores the exact signed
  `{payload,sig}` document bytes** verbatim in `issued_challenge_document` (+ its `issued_challenge_handle`
  for integrity, + stamps `issued_at_ms` from the authority clock — the retention/sweep key, §2.1),
  inside the same commit that flips the state; a repeat (B) on an already-`ISSUED` row
  **re-returns that stored document byte-for-byte** — it never re-signs, never re-stamps
  `challenge_issued_at_ms`/`challenge_expires_at_ms`, never re-selects `challenge_key_id`, and never
  alters the stored desktop `request_nonce` (a one-way handle could not reproduce the bytes, so the
  exact document MUST be persisted, not just its hash); a concurrent-CAS loser observes `ISSUED` and
  takes that same replay path; an unknown id ⇒ `no_pending_row`, an expired row ⇒ `pending_expired`.
- **Pending/issued store retention + sweep (P1 LOCKED — PENDING and ISSUED are cleaned DIFFERENTLY).**
  A `PENDING` row (never issued) expires at `pending_expires_at_ms = created_at_ms + PENDING_TTL_MS`
  and is swept then. An `ISSUED` row is **terminal** and MUST **retain** its exact signed
  `issued_challenge_document` for byte-identical replay (the lost-`issue`-reply idempotency above) —
  so it is **NOT** governed by `PENDING_TTL`; it is retained for
  **`ISSUED_RETENTION_MS = 60000`** (`= CHALLENGE_TTL_MS 30000 + AUTHORITY_REPLAY_WINDOW_MS 30000`,
  §2.1.1), measured from the row's **`issued_at_ms`** (the queryable
  column stamped in the CAS `PENDING → ISSUED` tx — NOT `created_at_ms`, since create-pending (A)
  precedes issue (B)), so replay is available for exactly as long as the challenge could still be
  legitimately submitted. **After `issued_at_ms + ISSUED_RETENTION_MS` the row + its stored document are
  swept**; a replay `issue(pending_challenge_id)` after that ⇒ `no_pending_row`
  (the desktop's `request_nonce` is by then either consumed (terminal turn) or its own challenge expired,
  so no turn is lost). **Deterministic sweep:** a `PENDING_SWEEP_INTERVAL_MS = 60000` background pass
  (+ startup pass) deletes every `PENDING` row past `pending_expires_at_ms` and every `ISSUED` row past
  `issued_at_ms + ISSUED_RETENTION_MS` (an indexed column), within `2 × PENDING_SWEEP_INTERVAL_MS` of
  eligibility (one missed-sweep tolerance). **Quotas (fail-closed):** at most `MAX_CONCURRENT_GOVERNED_TURNS = 2` live
  `PENDING` rows per `install_id` (existing `quota_pending`), and at most `MAX_ISSUED_ROWS_PER_INSTALL`
  live `ISSUED` rows / `MAX_ISSUED_BYTES_PER_INSTALL` total stored `issued_challenge_document` bytes per
  `install_id` (a new create-pending refuses `quota_pending` when the sum of live PENDING+ISSUED would
  exceed the bound — a defense-in-depth resource floor bounding issued-document accumulation independent of caller trust; the only create-pending caller is the broker, whose compromise is out of scope, §0). A left-behind
  `ISSUED` row binds **no execution right** (it is not an acceptance-ledger row, §5) and cannot become a
  reusable turn, so this retention is safe.

#### 2.1.1 Challenge-authority lifecycle constants + ordering (P1-1, LOCKED — literal values)

All elapsed/timeout durations are MONOTONIC (§1); all `*_at_ms` are wall-clock. Every value nests inside
the desktop `max_age_ms = 300000` (§1).

| Constant | Literal | Meaning / counting |
|---|---|---|
| `CHALLENGE_TTL_MS` | `30000` | `challenge_expires_at_ms == challenge_issued_at_ms + CHALLENGE_TTL_MS` (§1 pins the "≤30000" bound to this literal) |
| `PENDING_TTL_MS` | `30000` | PENDING-row life: `pending_expires_at_ms == created_at_ms + PENDING_TTL_MS` |
| `MAX_AUTHORITY_ATTEMPTS` | `3` | total tries per authority message (**counts the first**); `MAX_AUTHORITY_RETRIES = 2` (retries only) |
| `AUTHORITY_ATTEMPT_TIMEOUT_MS` | `2000` | per-attempt monotonic deadline for one authority reply |
| `AUTHORITY_RETRY_BACKOFF_MS` | `1000` | **fixed** delay between attempts |
| `AUTHORITY_REPLAY_WINDOW_MS` | `30000` | lost-reply byte-identical `issue` replay window after `issued_at_ms` |
| `ISSUED_RETENTION_MS` | `60000` | `= CHALLENGE_TTL_MS + AUTHORITY_REPLAY_WINDOW_MS = 30000 + 30000`; ISSUED-row+document retention from `issued_at_ms` |
| `MAX_ISSUED_ROWS_PER_INSTALL` | `8` | max logically-live ISSUED rows / install |
| `MAX_ISSUED_BYTES_PER_INSTALL` | `65536` | max total stored `issued_challenge_document` bytes / install |
| `PENDING_SWEEP_INTERVAL_MS` | `60000` | background + startup sweep cadence (physical delete within `2×` = 120000) |
| `AUTHORITY_CHANNEL_FRAME_BYTES` | `8192` | max authority **reply** frame (issue-result / create-pending-result) |
| `AUTHORITY_REQUEST_FRAME_BYTES` | `4096` | max authority **request** frame (untrusted-side oversize guard) |
| `CHALLENGE_DOCUMENT_MAX_BYTES` | `4096` | decoded ceiling on the signed `{payload,sig}` document (= §4.10(a0)/(g) `decoded ≤ 4096`) |

**Attempt budget:** `3×2000 + 2×1000 = 8000 ms`/hop; worst create→issue span `2×8000 = 16000 < PENDING_TTL_MS 30000`. ✔

**(a) Idempotent-before-quota (LOCKED).** At create-pending (A): peer-auth+validate → **idempotent
lookup FIRST** (resolve `UNIQUE(install_id,request_nonce)`, apply §2.1.1(b) logical-expiry): a
logically-live identical row re-returns the SAME `pending_challenge_id` **with no quota check**; a live
row with any differing fact ⇒ `retry_conflict`; a logically-expired-not-swept row for that nonce ⇒
`retry_conflict` → **only when no row exists** does the quota check run (live-PENDING ≤ 2, live-(PENDING+ISSUED)
≤ 8, stored bytes ≤ 65536, else `quota_pending`). A full quota can never break recovery of an existing
identical request.

**(b) Synchronous logical expiry (LOCKED).** On **every** create-pending lookup and **every** issue
resolution, evaluate a fresh `now_ms` synchronously **before acting**: a PENDING row with `now_ms >
pending_expires_at_ms` is logically expired (never issued/replayed as live); an ISSUED row with `now_ms >
issued_at_ms + ISSUED_RETENTION_MS` is retention-expired (never replays its stored document) — even if
the background sweep has not yet deleted it. Physical presence is never sufficient for liveness.

**(c) Expired-not-swept excluded from live quotas (LOCKED).** The live-quota counts in (a) count only
rows passing (b); sweep latency can never cause a spurious `quota_pending`.

**(d) `pending_expired` vs `no_pending_row` (LOCKED — replaces the earlier line-337 wording).** At issue
(B): a row **physically present but failing its logical-expiry predicate** (expired PENDING, OR
retention-expired ISSUED) ⇒ `pending_expired`; **no row physically present** (never created, or swept) ⇒
`no_pending_row`; a live PENDING ⇒ CAS→ISSUED + stamp `issued_at_ms` + sign once + store; a live ISSUED ⇒
byte-identical replay.

**(e) Physical cleanup is separate.** A `PENDING_SWEEP_INTERVAL_MS = 60000` sweep (+ startup pass)
deletes PENDING rows past `pending_expires_at_ms` and ISSUED rows past `issued_at_ms + ISSUED_RETENTION_MS`
within `2×PENDING_SWEEP_INTERVAL_MS = 120000` of eligibility. Logical expiry (b) governs correctness; the
sweep only reclaims storage.

**(f) `refused` terminal; only transport failures retryable (LOCKED — refines §4.10(g), cross-ref §4.10(h)).**
Retryable (⇒ bounded idempotent retry, `MAX_AUTHORITY_ATTEMPTS = 3`): socket-unavailable / lost reply /
transport-malformed (unparseable/oversize) frame. Terminal (⇒ `record_pre_verification_block`, never
retried): any well-formed `status:"refused"` verdict (incl. `reason:"malformed"` — the authority telling
us OUR request was malformed, distinct from a transport-malformed reply).

**(g) Frame-fit byte math.** Real §4.1 payload worst case (all `≤128` strings at max, `*_sha256`=64hex,
`_ms`=16 digits, `sig`=88 b64url) = **1634 B**, so `CHALLENGE_DOCUMENT_MAX_BYTES = 4096` keeps 2.5×
headroom. The (B) issued reply must hold a document up to the 4096 ceiling: base64url(4096)=5464 chars +
envelope (`{"protocol":…,"status":"issued","challenge_document_b64":"…"}` ≈99 B) ⇒ **≤ 5565 B**, which
fits `AUTHORITY_CHANNEL_FRAME_BYTES = 8192` (headroom 2627 B). The old 4 KiB cap could not.

**(h) Tests:** generated max-size issued frame (≤8192, >4096, proving the raise is necessary+sufficient);
frame-cap boundaries (8192 accept / 8193 oversize; request 4096/4097; doc 4096/4097); every constant
boundary (`pending_expires` +0/+1; `issued_at+ISSUED_RETENTION` +0/+1; quotas at 8/9, 65536/+1, 2/3);
retry-cut (≤3 tries, 4th ⇒ terminal); quota-order (idempotent-before-quota at full quota); logical-expiry
vs delayed sweep (expired ⇒ `pending_expired`, present); physically-swept ⇒ `no_pending_row`; lost-reply/
transport-malformed ⇒ retry recovers, well-formed `refused` ⇒ terminal Block; byte-identical issue replay.
- **Authority builds the payload itself:** at issue (B), from its protected row the authority
  **constructs** the exact `brops.governed-turn-challenge.v1` payload (§4.1), stamps
  `challenge_issued_at_ms`/`challenge_expires_at_ms`, and signs once (consuming the pending id). It
  never signs caller-supplied bytes/fields.
- **Return path (P0-1, closes the "by-assumption" document carriage):** the authority returns the
  **exact signed `{payload,sig}` document bytes** to the **trusted verifier/broker** **in the reply on the same
  authenticated `AF_UNIX` channel** — the **broker** is the only `SO_PEERCRED`-allowlisted peer (the
  renderer/login UID is denied), so **the signed challenge NEVER reaches the renderer** and no other
  principal receives it. The **broker** (which now holds the document bytes) base64url-
  encodes them into `challenge_doc_b64` and passes them to the sidecar **only** via the
  `bridge.governed-turn-submit.v1` ingress frame (§4.10(g), §6.1 step 0). The sidecar first sees the
  document here; it can neither mint nor alter it (the canonicality gate + `challenge_handle` re-hash
  at §4.10(a0) bind the exact bytes). No step delivers the document "by assumption".
- **How broker facts cross the boundary without giving the sidecar the same capability:** the
  **trusted verifier/broker** principal (a **distinct UID**, never the renderer/login UID) is the only
  peer the `SO_PEERCRED` allowlist admits; it hands the structured facts over the authenticated channel
  **at create-pending (A)**,
  and at issue (B) supplies only the `pending_challenge_id`, while the authority
  writes its **own** store. The sidecar (a different UID) is denied the channel by
  `SO_PEERCRED` **and** the store by file ownership — so it can present neither facts the
  authority will trust nor bytes the authority will sign.
- **Mandatory Linux isolation tests:** the sidecar principal cannot (a) read/list the
  authority key dir, (b) `ptrace` the authority, (c) call **either** creation-channel message
  (`create-pending` **or** `issue`) — peer-UID denied on both, (d) directly read/write/list/mutate
  the pending store file(s)/DB, (e) obtain a signature over caller-chosen bytes, or (f) issue a
  challenge by presenting a forged/guessed `pending_challenge_id` (refused `no_pending_row`) — all
  machine-proven, alongside the 3b-1A denials.

Full principal/ACL matrix in Appendix B. The acceptance ledger + protected content-addressed
store: **acceptance ledger** is supervisor-only `0700`; the **published content-addressed
store** is the group-shared model of §2.3 (NOT a literal `0700` — see §2.3); executor/sidecar
have no store or key access.

### 2.2 Protocol versioning (P0-1) — NEVER mutate the GREEN 3b-1A v1 protocols

The governed turn introduces new fields (integer `_ms` timestamps, no `builder_id`, new
echoes, new refusal reasons) that the **already-GREEN 3b-1A** strict `additionalProperties:
false` v1 schemas would reject. The ratified protocols — **`brops.sign-request.v1`**
(requires `builder_id` + string `requested_at`/`completed_at`), **`brops.sign-result.v1`**
(closed 12-value `reason` enum), **`brops.evidence-request.v1`**, **`brops.governed-result.v1`**
(the EXISTING supervisor→sidecar shape already shipped in 3b-1A: `{protocol, status, output
(top-level string), receipt:{envelope_jcs_b64, signature_b64, containment_evidence_b64,
attestation_*, run_id, execution_attempt_id, lease_id}}` for `signed` and `{protocol, status,
reason}` for `refused` — the constant `GOVERNED_RESULT_PROTOCOL` + emitter in
`brops_supervisor_service.py` + the `engine_sidecar.py` consumer), the **`bridge.result`**
receipt (whose `receipt` object **already REQUIRES `envelope_jcs_b64`** — `bridge-result.schema.json`),
and the **`bridge.task-request`** — are all **frozen byte-for-byte** and MUST NOT be
redefined; the 3b-1A signer-isolation positive control (`brops_isolation_prover.py` +
`test_brops_services.py` + `test_brops_isolation.py`) + the shipped governed-result emitter
depend on them exactly. **The 3b-1B result therefore uses a NEW name (`brops.governed-turn-result.v1`),
NOT the taken `brops.governed-result.v1` (P0-1).**

The governed turn therefore uses a **separate `brops.governed-*` / `bridge.governed-*`
protocol family, in its own schema files**, selected by a **positive `protocol` const in both
directions** (the one canonical bridge rule, P0-1: the FROZEN `bridge.result` has **NO** top-level
`protocol` key and is `additionalProperties:false`, so it rejects any governed frame (unknown
top-level key); every NEW `bridge.governed-*` schema **REQUIRES** its explicit top-level `protocol`
const, so it rejects any `bridge.result` (missing const) — do NOT discriminate on
`receipt.envelope_jcs_b64`, which is required in both):
- **`bridge.governed-turn-submit.v1`** (+ `bridge.governed-turn-result.v1` reply) — the
  **desktop→sidecar governed INGRESS frame (P0-1)**: the ONLY protocol that carries the signed
  challenge document + the raw `system`/`history`/`generation_config` bytes from the desktop into
  the one-shot sidecar, which then originates §2.4 staging and §4.10(a0) open. The frozen
  `bridge.task-request` (`additionalProperties:false`, `required:[task_id,task_class,rationale,system,history,request]`, no
  `challenge_doc_b64`, no bytes-carrying `generation_config`, no `protocol` discriminator —
  `bridge/contracts/task-request.schema.json`) **cannot** carry it and is NOT reused. COMPLETE in
  §4.10(g); built by the internal `governed_turn_submit_prepared` helper inside the one backend
  `governed_turn_execute` command from the in-process `PreparedGovernedTurnV1B` (§4.10(g), §6.1 step 0).
- **`brops.governed-turn-open.v1`** (+ `-result`) — the signed-challenge submission (P0-2),
  COMPLETE in §4.10(a0)
- **`brops.governed-sign-request.v1`** — `engine/contracts/brops-governed-sign-request.v1.schema.json`
- **`brops.governed-sign-result.v1`** — `engine/contracts/brops-governed-sign-result.v1.schema.json`
- **`brops.governed-evidence-request.v1`** — the sidecar→supervisor execute/finalize trigger,
  COMPLETE in §4.10(d) (the governed path uses THIS, never the v1 `brops.evidence-request.v1`)
- **`brops.governed-turn-result.v1`** — `engine/contracts/brops-governed-turn-result.v1.schema.json`
  (the supervisor→sidecar tagged union, COMPLETE in §4.10(e); a **NEW name distinct from the
  frozen `brops.governed-result.v1`** shipped in 3b-1A, P0-1). **KEEP + ADD, never rename (P0-1,
  LOCKED):** the shipped `GOVERNED_RESULT_PROTOCOL = "brops.governed-result.v1"` constant, its
  emitter (`brops_supervisor_service.py`), its `engine_sidecar.py` consumer, its schema and its
  positive-control tests stay **byte-for-byte unchanged**; 3b-1B **ADDS in parallel** a new
  `GOVERNED_TURN_RESULT_PROTOCOL = "brops.governed-turn-result.v1"` constant, a **new emitter
  branch**, a **new consumer branch**, a new schema and new tests. **Nothing old is renamed or
  repurposed** — the two coexist, selected by the `protocol` const.
- **`brops.governed-staging-open/-chunk/-final.v1`** (+ their `-result` replies) — the bounded
  ingress control plane, COMPLETE in §4.10(a–c) (§2.4)
- **`brops.governed-turn-output-read.v1`** (+ `-result`, supervisor hop) **and
  `bridge.governed-turn-output-read.v1`** (+ `-result`, desktop→sidecar hop) — the **pull-based**
  result-return (P0-2/P0-3), COMPLETE in §4.10(f): one idempotent request/response per chunk on
  each hop (the real `brops_socket` is one-request/one-response and the sidecar is a one-shot
  subprocess, so NO push stream); the desktop re-invokes the sidecar per chunk, the sidecar proxies
  one supervisor read. Backed by the durable supervisor `governed_output_streams` table (§4.10(f)).
- **`brops.governed-challenge-create-pending.v1`** and **`brops.governed-challenge-issue.v1`** (+
  their `-result` replies) — the desktop-UI↔`desktop-challenge-authority` **challenge creation
  channel** (the single two-message protected-row-ID trust model, COMPLETE in §2.1, P1-2)
- **`brops.governed-receipt-envelope.v1`** — the isolated-signer receipt envelope (§4.9)
- **`bridge.governed-turn-result.v1`** — `bridge/contracts/bridge-governed-turn-result.schema.json`
  (the COMPLETE parent, §4.6; a distinct schema + a distinct sidecar emit branch). **Discriminator
  (P0-1, CORRECTED):** it carries an explicit **top-level `"protocol": "bridge.governed-turn-result.v1"`
  const** in its `required` set. The frozen `bridge.result` (`additionalProperties:false`, no
  `protocol` key) therefore **rejects** any governed document (unknown top-level `protocol` key),
  and the new schema **rejects** any `bridge.result` (missing required `protocol` const) — true
  bidirectional disjointness via a positive discriminator. (The earlier claim that
  `receipt.envelope_jcs_b64` is "absent from `bridge.result`" was FALSE — it is a REQUIRED key of
  `bridge.result.receipt` — and MUST NOT be used to discriminate.) `bridge.result` stays untouched.

**Compatibility rule (LOCKED + tested):** the old/frozen path accepts ONLY its own documents and
**refuses** any new governed document; the new governed path accepts ONLY new-governed documents
(routed by `protocol` const) and **refuses** any frozen document. No shared file, enum, or
required-key list. The frozen v1/`bridge.result`/`brops.governed-result.v1` schema files, parser
functions, and tests are unchanged, and their positive-control round-trip runs identically.
**Compatibility tests (LOCKED):** (1) old `brops.governed-result.v1` (`signed`+`refused`) emitted
+ consumed by the shipped path with its exact shipped shape (golden/regression); (2) new
`brops.governed-turn-result.v1` emitted + consumed by the new branch; (3) an old doc fed to the new
consumer/schema → refuse; (4) a new doc fed to the old `brops.governed-result.v1` consumer/schema →
refuse; (5) `bridge-result.schema.json` rejects a `bridge.governed-turn-result.v1` doc (unknown
top-level `protocol`) and `bridge-governed-turn-result.schema.json` rejects a `bridge.result`
(missing required `protocol`), asserting discrimination is NOT via `envelope_jcs_b64`; (6) the
frozen positive-control (`brops_isolation_prover.py` + `test_brops_services.py` +
`test_brops_isolation.py`) still passes byte-for-byte after the ADD.

### 2.3 Protected-store namespaces + ACL (P0-1, LOCKED) — enforceable owner-write / shared-read

A single `0700` dir cannot be written by two distinct principals (supervisor + recorder) and
read by a third (signer) — so the store is **group-shared for READ**. But a `2770` (group-
write) dir is **also wrong**: under real POSIX, directory create/rename/unlink needs **`w`+`x`
on the dir**, so `2770` would let *every* `brops-store` member (incl. the signer and the other
namespace's owner) create/rename/unlink — breaking "signer read-only", "recorder cannot write
`sup/`", and "supervisor cannot write `rec/`". The 3b-1A CI today provisions `store` at `2770`
with the signer in the group (`isolation_proof.sh`), so that write leak is real and its
isolation prover (which runs only as the login user) does **not** currently prove the
recorder/signer write-denials. The corrected, enforceable model is **`2750` owner-write /
group read-traverse**:
- **Shared READ group `brops-store`** = `brops-supervisor`, **`brops-recorder`** (a dedicated
  recorder OS principal — NEW for 3b-1B; the 3b-1A key `evidence-recorder` is a signing-key
  authority, not this OS principal), and `brops-signer` (**read-only** member).
- **Store root** and both namespaces at mode **`2750`** (owner `rwx`, group `r-x` **— NO group
  `w`**, other `---`): `store/sup/` owner `brops-supervisor:brops-store` (supervisor writes:
  challenge doc, registry snapshot, inputs, self-resolved policy bundle, lease, terminal
  record) and `store/rec/` owner `brops-recorder:brops-store` (recorder writes: output,
  containment, execution-receipt). **Only the namespace owner may create/rename/unlink** in its
  own dir; the other owner and the signer get group `r-x` = **read + traverse only, no write**.
- **`setgid` bit stays set** on the dirs **only** to make new files inherit group `brops-store`
  (so the signer can read them); it does **not** grant directory write. Artifacts are **`0640`**
  (owner rw, group r, no world) — so a non-owner group member cannot even overwrite an existing
  artifact (needs `w` on the file), and `chmod`/symlink-swap needs file/dir ownership it lacks.
- **`umask 0027`** for every service process (new files ≤ `0640`, new dirs ≤ `0750`).
- **Runtime enforcement:** `brops_evidence_store._harden_dir` (which today refuses only world-
  write `S_IRWXO`) MUST additionally **refuse `S_IWGRP`** on the store dirs, so a re-introduced
  `2770` fails closed at load, not just in CI.
- **Private-key dirs stay strictly `0700`** owner-only (`signerkeys`→`brops-signer`,
  attestation keys→`brops-supervisor`, evidence-recorder key→`brops-recorder`, **governed-turn-
  recorder key→`brops-supervisor`** — an owner-only `0700` dir held by the supervisor principal,
  NOT a separate principal, P1-5). The **evidence-head floor DB** (§7 P1-7) is `brops-signer`-owned, dir `0700`/
  file `0600`. The **acceptance ledger + `governed_turn_staging` store** (§2.4/§5) are
  supervisor-only `0700`.
- **`sidecar`, `executor`, and `desktop` are in NEITHER `brops-store` nor any owner** ⇒ no
  read/write/list of the published store or any key.
- IPC stays `AF_UNIX` + `SO_PEERCRED` allow-lists (unchanged).
- **Machine tests (run AS each OS principal — the 3b-1A login-user prover does NOT cover
  these):** for supervisor, recorder, signer, sidecar, executor, attempt
  create/overwrite/rename/unlink/chmod/symlink-attack + list + read in **both** `sup/` and
  `rec/`, asserting exactly: signer = **DENY all writes** (incl. chmod/symlink) in both, ALLOW
  list+read; recorder = ALLOW writes in `rec/`, **DENY all writes in `sup/`**, ALLOW read/list
  `sup/`; supervisor = ALLOW writes `sup/`, **DENY all writes in `rec/`**, ALLOW read/list
  `rec/`; sidecar+executor = DENY every op incl. list/read. Plus a **mode-regression guard**:
  `stat` store root/`sup/`/`rec/` MUST equal `2750` (setgid set, **group-write bit clear**) —
  fail closed if anyone re-introduces `2770`.

### 2.4 Bounded input ingress (P0-2, LOCKED) — a PRE-ACCEPT chunked upload to supervisor staging

The signed challenge carries only input **hashes**; before execution the exact **raw**
system/history/generation_config bytes must reach the supervisor's protected store. **The
sidecar is compromised-in-scope, so it uploads ONLY the three desktop-originated artifacts and
NEVER `policy_bundle`** (policy is a supervisor authority — see the policy note below). ONE
frozen Linux mechanism (Windows real-mode stays fail-closed): an **authenticated chunked upload
to a supervisor-owned staging store**, over a supervisor-owned `AF_UNIX` + `SO_PEERCRED`
channel (the sidecar is the untrusted sender; it can never *read* staging). Reuses
`brops_evidence_store.publish` (temp→fsync→verify size+sha256→`os.link`/`O_EXCL` create-if-
absent→`_verify_idempotent` divergent-refuse→fsync dir) for the final publish.

**No staging↔acceptance deadlock (P0-2):** staging is gated by the **verified signed
challenge**, NOT by an acceptance-ledger row (a row that, by §5, does not yet exist). The
supervisor keeps a durable, supervisor-only **`governed_turn_staging`** row (`0700`), distinct
from the acceptance ledger and carrying **no `execution_attempt_id` and no execution right**:
```sql
CREATE TABLE governed_turn_staging (
  install_id TEXT NOT NULL, request_nonce TEXT NOT NULL, challenge_handle TEXT NOT NULL, -- 64hex
  run_id TEXT NOT NULL, task_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
  system_sha256 TEXT NOT NULL, history_sha256 TEXT NOT NULL, generation_config_sha256 TEXT NOT NULL,
  system_handle TEXT, history_handle TEXT, generation_config_handle TEXT,   -- set as each publishes
  state TEXT NOT NULL CHECK (state IN ('VERIFYING','UPLOADING','INPUTS_READY')),  -- P1-4 CHECK; VERIFYING(transient)→UPLOADING→INPUTS_READY
  challenge_expires_at_ms INTEGER NOT NULL, created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL,
  UNIQUE (install_id, request_nonce), UNIQUE (challenge_handle) );
-- Per-artifact upload session (durable — P0-1 crash-consistency + P1-6 idempotency):
CREATE TABLE governed_turn_staging_session (
  staging_session_id TEXT PRIMARY KEY,   -- opaque
  challenge_handle TEXT NOT NULL,
  artifact TEXT NOT NULL CHECK (artifact IN ('system','history','generation_config')),  -- P1-4: closed; policy_bundle REFUSED
  declared_len INTEGER NOT NULL CHECK (declared_len >= 0 AND declared_len <= 8388608), declared_sha256 TEXT NOT NULL,  -- P1-4: <= absolute max ceiling (history 8 MiB); the tighter per-artifact ceiling (system 262144 / generation_config 65536) is enforced at staging-open (§4.10(a))
  next_seq INTEGER NOT NULL CHECK (next_seq >= 0 AND next_seq <= 46),   -- 46 = MAX_STAGING_CHUNKS (P1-3/P1-4)
  byte_count INTEGER NOT NULL CHECK (byte_count >= 0 AND byte_count <= declared_len),   -- P1-4: never exceeds declared; NO running_sha256 (not a resumable hash state, P0-1)
  session_dir TEXT NOT NULL,             -- 0700 dir holding the IMMUTABLE <seq>.chunk files
  state TEXT NOT NULL CHECK (state IN ('UPLOADING','ARTIFACT_READY','SESSION_CORRUPT')),  -- P1-4: renamed (was INPUTS_ARTIFACT_READY, collided with the row's INPUTS_READY / FAILED)
  published_handle TEXT,                  -- set on final publish
  UNIQUE (challenge_handle, artifact) );
-- Per-chunk digest of the IMMUTABLE <seq>.chunk file (durable; the source of truth for resume/idempotency):
CREATE TABLE governed_turn_staging_chunk (
  staging_session_id TEXT NOT NULL, seq INTEGER NOT NULL,
  chunk_sha256 TEXT NOT NULL, chunk_len INTEGER NOT NULL,
  PRIMARY KEY (staging_session_id, seq) );
```
**Crash-consistent immutable per-chunk storage (P0-1, LOCKED — no mutable append file, no
resumable-hash assumption).** Each staging session owns a supervisor-only `0700` `session_dir`;
each accepted chunk is an **immutable** `<session_id>/<seq>.chunk` file, and the DB records only
`next_seq`/`byte_count` + per-chunk `(sha256,len)`. **`running_sha256` is removed** — a finalized
SHA-256 digest is NOT a resumable internal hash state; the final hash is recomputed from byte zero.
- **Accept `seq == next_seq` (exact order, reusing `brops_evidence_store` mechanics):** (1) strict-
  decode + validate the chunk; (2) compute `chunk_sha256`, `chunk_len`; (3) write bytes to an
  `O_CREAT|O_EXCL` temp in `session_dir`; (4) `fsync` the temp; (5) **`os.link(temp, <seq>.chunk)`**
  (P1-4, LOCKED — the exact frozen `brops_evidence_store.py:157` `os.link` create-if-absent no-overwrite
  primitive, with the `O_EXCL` fallback `:171`; **NOT `rename` and NOT `renameat2`**, which are used
  nowhere in the store) to the immutable `<seq>.chunk` (EEXIST ⇒ verify byte-identical = idempotent
  replay, else `retry_conflict`); (6) `fsync(session_dir)`; (7) `BEGIN IMMEDIATE`; (8) re-check
  `next_seq == seq`; (9) `INSERT governed_turn_staging_chunk(seq, chunk_sha256, chunk_len)`; (10)
  `UPDATE next_seq=seq+1, byte_count+=chunk_len`; (11) `COMMIT`; (12) **ACK only after commit.**
- **Restart-recovery reconciliation (per seq):** (a) durable `<seq>.chunk` exists but NO DB row
  (crash between step 6 and step 11) → verify its digest; the byte-identical retry **adopts** it
  (re-runs the tx then ACKs), a conflicting re-send ⇒ `retry_conflict`; (b) DB row exists but the
  `<seq>.chunk` is missing/unreadable/`sha ≠ chunk_sha256` → session `state = SESSION_CORRUPT`
  (terminal), never ACK/finalize; (c) both present + sha matches → consistent
  (idempotent ACK, current `next_seq`, no re-append). **No mutable incremental-hash state is
  trusted across restart.**
- **`SESSION_CORRUPT` terminal contract (P1-4, LOCKED):** once a session is `SESSION_CORRUPT`, EVERY
  later `governed-staging-open` (reopen), `-chunk`, and `-final` for that `staging_session_id` (or
  its `(challenge_handle, artifact)`) returns **`session_corrupt`** and the supervisor **never**
  finalizes, publishes, advances the `governed_turn_staging` row to `INPUTS_READY`, or silently
  re-creates/reuses the session. Recovery is **operator-swept only** (the §2.4 sweep unlinks the
  `session_dir` + deletes the row **without consuming the challenge nonce**); the desktop then
  re-issues a fresh staging session against the still-valid signed challenge (new `request_nonce`
  if the whole turn is abandoned). A `SESSION_CORRUPT` artifact can never contribute to an accepted
  turn — it fails closed, not open.
- **Final assembly (§4.10(c)):** read `<seq>.chunk` in strict `seq` order `0..next_seq-1`, assert
  no gap + `Σ chunk_len == declared_len`, stream into one `O_EXCL` final temp while **recomputing
  SHA-256 + length from byte zero**, assert `== declared_sha256 == the challenge's committed
  *_sha256` (else `sha_mismatch`/`handle_not_challenge`), `fsync`, publish via the idempotent
  `EvidenceStore.publish` (`os.link`/`O_EXCL` create-if-absent, divergent ⇒ `publish_divergent`),
  `fsync(dir)`, then persist `published_handle` + advance in one tx; identical final retry re-returns
  the same handle.
- **Idempotency + restart survival:** a `governed-turn-open` re-open with the byte-identical
  canonical challenge doc returns the existing `challenge_handle` + current state; a differing doc
  under the same `(install_id,request_nonce)` ⇒ `retry_conflict`. An abandoned session's
  `session_dir` is swept **without consuming the challenge nonce**.
- **Crash tests (each = crash injected at the cut, then restart + recover):** after chunk-file
  fsync + dir-fsync **before** the DB commit (rule a: adopt-if-identical / else `retry_conflict`);
  after the DB row commits (rule c: idempotent re-ACK, `byte_count`/`next_seq` unchanged); mid-final-
  concat (orphan final temp swept, final re-driven from the immutable chunks); after final-temp fsync
  **before** publish (retry re-links identical bytes → same handle); after publish **before** the
  `published_handle`/advance commit (idempotent publish → re-record handle + advance).
Staging states: **`VERIFYING`** (uncommitted — happens inside **`brops.governed-turn-open.v1`**
(§4.10(a0)), where the sidecar delivers the EXACT signed challenge document bytes and the
supervisor decodes them, computes the handle, verifies the `sig`+registry+context, publishes the
challenge doc, and CAS-creates the row; **do NOT read the acceptance clock, do NOT consume the
challenge nonce**) → **`UPLOADING`** (the three `*_sha256` copied from the *verified*
challenge) → **`INPUTS_READY`** (all three published + re-hashed). Because the supervisor only
holds a `challenge_handle` after `governed-turn-open`, the challenge document **must** arrive over
the wire there (P0-2) — a handle alone can neither be re-hashed nor signature-verified. Frozen
protocol:
- **`brops.governed-staging-open.v1`** `{install_id, challenge_handle, request_nonce, artifact
  ∈ {system,history,generation_config}, declared_len, declared_sha256}` — sent **only after a
  successful `governed-turn-open.v1`**; the supervisor authenticates the peer UID, **requires an
  existing `UPLOADING` `governed_turn_staging` row** for `(install_id, request_nonce,
  challenge_handle)` (it does NOT create one — that was `governed-turn-open`; a missing row ⇒
  `no_staging_row`), requires `declared_sha256 == the verified challenge's committed *_sha256` for
  that artifact, rejects `declared_len` over the per-artifact ceiling, and returns an opaque
  `staging_session_id` bound to exactly `(challenge_handle, request_nonce, install_id,
  artifact)`; one in-flight session per (tuple, artifact) — a **byte-identical re-open returns the
  SAME session_id + current `next_seq`** (idempotent, P1-6), a conflicting re-open ⇒ `retry_conflict`.
  `policy_bundle` is **not** an accepted `artifact` value (refused).
- **`brops.governed-staging-chunk.v1`** `{staging_session_id, seq, bytes_b64}` — each chunk ≤
  **`MAX_STAGING_CHUNK_BYTES = 184320` decoded bytes (180 KiB, P1-4)**. **Deterministic chunk length
  — bounds cardinality (P1-3, LOCKED, closes the tiny-chunk amplification Track E flagged):** the
  chunk length is **not sender-chosen**; every chunk MUST be exactly
  `expected_chunk_len = min(MAX_STAGING_CHUNK_BYTES, declared_len − byte_count)` (i.e. all chunks are
  a full `184320` except the final remainder), else ⇒ **`nondeterministic_chunk`**. This makes the
  chunk count a deterministic function of `declared_len`: `n_chunks = ceil(declared_len / 184320)`
  (so `n_chunks == 0` for the zero-byte case below — no chunk is sent), `seq` runs `0..n_chunks−1`,
  and a session is hard-capped at
  **`MAX_STAGING_CHUNKS = 46`** (= `ceil(8 MiB / 184320)`, the worst case = the `history ≤ 8 MiB`
  ceiling); any `seq ≥ 46` or a `next_seq` that would exceed 46 ⇒ **`too_many_chunks`**. A compromised
  sidecar therefore cannot mount a 1-byte-chunk flood — the min-size is enforced per chunk and the
  count is bounded. **Zero-byte artifact (`declared_len == 0`):** send **NO** chunk messages; go
  straight to `governed-staging-final` with `seq == next_seq == 0`, which publishes the empty artifact
  and asserts `SHA256("") == declared_sha256`. **Single canonical order predicate
  (P1-2, LOCKED — replaces the old collapsed `seq != next_seq ⇒ refuse`):** `seq == next_seq` ⇒
  validate `chunk_len == expected_chunk_len` then persist the immutable `<seq>.chunk` + advance + ACK
  (P0-1 order above); `seq < next_seq` **and** the bytes are byte-identical to the durable
  `<seq>.chunk`/recorded `chunk_sha256` ⇒ idempotent ACK with the current `next_seq` (no re-append);
  `seq < next_seq` **and** different ⇒ `retry_conflict`; `seq > next_seq` ⇒ `seq_mismatch`.
  `byte_count+chunk_len > declared_len` (or > ceiling) ⇒ `over_declared`/`oversize_chunk`.
- **`brops.governed-staging-final.v1`** `{staging_session_id, seq==next_seq}` — assemble the
  immutable `<seq>.chunk` files in order **recomputing SHA-256 + length from byte zero** (P0-1 — no
  stored `running_sha256`), assert `total == declared_len` and `recomputed_sha == declared_sha256`,
  and **require `handle == the challenge's committed *_sha256`** for that artifact (else refuse —
  never publish bytes the challenge did not authorize); then idempotent atomic create-if-absent
  publish into `store/sup/` (divergent existing handle ⇒ `publish_divergent`); record the handle on
  the staging row. When all three input handles are set, the row advances to `INPUTS_READY`.
- **Frame sizing proof (P1-4, LOCKED):** the IPC frame body cap is `MAX_FRAME_BYTES = 262144`
  (`brops_protocol.py`, body-only, compact JSON, base64url **no padding**). A `184320`-byte
  decoded chunk base64url-encodes to `4·⌈184320/3⌉ = 245760` bytes; plus the chunk-frame JSON
  envelope (`{"protocol":"brops.governed-staging-chunk.v1","staging_session_id":"…",
  "seq":<int>,"bytes_b64":"…"}`, ≤ ~203 bytes with a ≤128-char session id + **≤2-digit seq** (P1-3:
  `seq` ∈ `0..45`)) = **≤ 245963 ≤ 262144** (≥ 16 KiB headroom). A 256 KiB decoded chunk would encode to `4·⌈262144/3⌉ = 349528` +
  envelope > 262144 — **rejected**. The validator MUST check **BOTH** caps independently and
  fail-closed: (1) `decoded_len ≤ 184320`, **and** (2) the serialized frame ≤ `262144` (reuse
  `encode_frame`/`read_frame`). Tests: exact-max (184320 → accept), max+1 (184321 → refuse on
  the DECODED cap even though its frame still fits), oversized-serialized-frame (refuse on the
  FRAME cap before decode), and a `256 KiB`-decoded regression (refused by both).
- **Per-artifact ceilings (LOCKED):** `system ≤ 256 KiB` and `history ≤ 8 MiB` match the desktop's
  real `ai.rs` caps (`MAX_SYSTEM_BYTES = 262144` `:71`, `MAX_CONVERSATION_BYTES = 8388608` `:73`);
  `generation_config ≤ 64 KiB` = `MAX_GENERATION_CONFIG_BYTES = 65536`, the governed-family ceiling on
  `JCS(generation_config_object)` (NOT an `ai.rs` cap — the frozen 3b-1A path carries only a fixed
  arbitrary config string, so this ceiling is new to the 3b-1B object form, §4.10(g)); `policy_bundle ≤ 64 KiB`
  applies only to the **supervisor-self-published** bundle (below), never to a sidecar upload.
  Total sidecar-uploaded request `≤ 8.5 MiB`.
- **Policy authority (P0-2, LOCKED — sidecar NEVER supplies policy):** the signed challenge
  commits `system_sha256`/`history_sha256`/`generation_config_sha256`/`request_sha256` and has
  **no** `policy_bundle_sha256` (§4.1) — so there is nothing to bind a sidecar-uploaded policy
  against, and policy must not traverse the untrusted sidecar. Instead the **supervisor
  self-resolves** `policy_id`/`policy_version`/`policy_bundle` bytes from **its own authoritative
  policy registry/config** (the real `brops_supervisor_attest.RunState.policy_bundle`, published
  via `store.publish`), binds `policy_bundle_sha256 = SHA256(raw bundle)` itself, and the
  isolated signer independently re-checks it against the operator-provisioned
  `BROPS_EXPECTED_POLICY_BUNDLE_SHA256` (`brops_receipt_signer` authorization policy). The
  desktop ships only a placeholder policy hash (used only on the never-active Trusted path).
- **Quota / expiry / crash (P1-3, LOCKED — exact numeric caps, no prose-only quota):** per
  `install_id` the supervisor enforces, fail-closed:
  - **`MAX_CONCURRENT_GOVERNED_TURNS = 2`** **LIVE** `governed_turn_staging` rows per install (matches the
    desktop `MAX_CONCURRENT_GENERATIONS = 2`, `ai.rs:212`); a 3rd concurrent **live** row on
    `governed-turn-open` ⇒ `quota_turns`. **Live-count rule (P1-3, rev 26, LOCKED):** the count includes
    only rows with `challenge_expires_at_ms ≥ now_ms` (the same resource-admission `now_ms` of §4.10(a0));
    an expired row (`challenge_expires_at_ms < now_ms`) is **NOT counted**, whether or not the sweep has
    unlinked it. Together with the §4.10(a0) expiry gate (which never *creates* an expired row), an expired
    challenge can never occupy a slot even during the `≤ STAGING_CLEANUP_DEADLINE_MS` window before a
    lagging sweep runs — closing the "expired challenge pins a staging slot" vector (P1-3).
  - **`MAX_STAGING_SESSIONS_PER_INSTALL = 6`** concurrent `governed_turn_staging_session` rows
    (= 2 turns × 3 artifacts); over ⇒ `quota_sessions`.
  - **`MAX_STAGING_CHUNKS = 46`** per session (above) ⇒ **`MAX_STAGING_FILES_PER_TURN = 49`** immutable
    `<seq>.chunk` files per turn (`history` 46 + `system` 2 + `generation_config` 1) and
    **`MAX_STAGING_FILES_PER_INSTALL = 98`** (= 2 turns × 49) files on disk; over ⇒ `too_many_chunks`.
  - **`MAX_STAGING_BYTES_PER_INSTALL = 17825792`** (= 17 MiB = 2 × the 8.5 MiB per-turn request
    ceiling) total decoded staging bytes; over ⇒ `quota_bytes`.
  - A session/row **TTL bound to the signed challenge's own `challenge_expires_at_ms`** (NOT an
    acceptance window — none exists yet). Two literal cleanup bounds (P1-3, no implicit latency):
    **`EXPIRED_SESSION_RETENTION_MS = 0`** — an expired staging row/`session_dir` (now past
    `challenge_expires_at_ms`) has **zero** retention: it is eligible for unlink the instant it
    expires, never preserved (staging holds no post-expiry value; the nonce is not consumed on sweep,
    so nothing is lost). **`STAGING_CLEANUP_DEADLINE_MS = 120000`** — an expired session MUST be fully
    unlinked (row + `session_dir` + temps) within `2 × STAGING_SWEEP_INTERVAL_MS` of its expiry (one
    missed-sweep tolerance), a provable completion SLA so the per-install byte/file quotas can rely on
    expired rows being gone (a slow sweep can never silently exceed `MAX_STAGING_BYTES/FILES_PER_INSTALL`).
    A **`STAGING_SWEEP_INTERVAL_MS = 60000`** background sweep (plus a startup pass) unlinks orphan
    `.tmp-*.part` + the whole `session_dir` and deletes expired/abandoned staging rows **WITHOUT
    consuming the challenge nonce** — the desktop may re-issue against the same signed challenge until
    the challenge itself expires (this denies the sidecar a nonce-burning DoS). A partial temp is never
    linked to a handle; `read(handle)` re-verifies sha.
- **Isolation:** `governed_turn_staging` + staging blob root are `0700` supervisor-only;
  sidecar/executor have **no read**; the executor receives only post-publish read-only FDs (§4.7).
- **Ordering:** acceptance/lease/execution (§5) may proceed **only after** the staging row is
  `INPUTS_READY` (every declared input exists in the store and re-hashes to the challenge's
  committed digest) **and** the supervisor has self-published+bound the policy bundle.

---

## 3. THE ARTIFACT MATRIX (single normative source)

Every 3b-1B artifact, locked. A **handle** is always `SHA256(exact stored bytes)`, but "the
bytes" differ by kind: **signed-document** handles hash `JCS(exact signed document)`
(`{payload, sig}`), **raw-artifact** handles (system/history/generation_config/output/
policy) hash the exact **raw** bytes (see Appendix B). "Signed bytes" = detached Ed25519 over
`JCS(payload)` unless noted. A field has **one name, one type, one unit, one authority**
everywhere; §4 gives the exact key sets.

| # | Artifact / protocol | Producer | Signer / authority | Verifier / consumer | Time unit | Handle formula | Durable owner | Replay/idempotency key | Key cross-bindings |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `brops.governed-turn-challenge.v1` | broker → **challenge-authority** | `desktop-challenge-authority` key (`challenge_key_id`) | supervisor §5; `LiveRunStateProvider` §7 | ms | `challenge_handle = SHA256(JCS({payload,sig}))` | supervisor store (published §6) | `request_nonce` (one-time) | binds `run_id`/`task_id`/context + `*_sha256` |
| 2 | `brops.challenge-key-registry.v1` | operator (root-signed) | challenge-**root** anchor (`root_key_id`) | supervisor §5; provider §7 | ms | `challenge_registry_handle = SHA256(JCS({payload,root_sig}))` | supervisor store | `registry_epoch` + `registry_hash` (anti-rollback) | `registry_hash = SHA256(JCS(payload))` (identity, ≠ handle) |
| 3 | acceptance-ledger row (§5) | supervisor | — (durable DB, not signed) | supervisor (recovery); provider (indirect) | ms | — | supervisor acceptance DB (`0700`) | `UNIQUE(install_id,request_nonce)`, `UNIQUE(challenge_handle)`, `UNIQUE(execution_attempt_id)` | holds lease_payload bytes + state |
| 4 | `brops.governed-turn-lease.v1` | supervisor **governed-turn lease issuer** | lease-issuer key | recorder; supervisor; provider §7 | ms | `lease_handle = SHA256(JCS({payload,signature}))` | supervisor store | `nonce` (lease) + `execution_attempt_id` | binds challenge #1 via `challenge_handle`/`challenge_key_id` + registry #2 + `challenge_accepted_at_ms` |
| 5 | `brops.governed-sign-request.v1` (attested evidence) | supervisor | **supervisor attestation** key (`supervisor_attestation_key_id`) over `JCS(evidence)` | isolated signer §6.1; desktop re-verifies the attestation bytes | ms | (transported, not stored) | — | `request_nonce` + `execution_attempt_id` | echoes #4/#6 handles; every `*_sha256` DERIVED by signer |
| 6 | `brops.governed-turn-execution-receipt.v1` | recorder runner | **evidence-recorder** key | isolated signer's `LiveRunStateProvider` §7; `verify_governed_turn_receipt` | ms | `execution_receipt_handle = SHA256(JCS({payload,signature}))` | recorder store namespace (§2.3) | `receipt_id` (global unique) | `output_handle == output_sha256`; binds attempt/lease |
| 7 | `brops.governed-turn-containment.v1` | recorder runner | evidence event (evidence-recorder) | provider §7 | ms | `containment_evidence_sha256 = SHA256(JCS(artifact))` | recorder store namespace | attempt+lease | `contained==true`, closed `teardown_outcome` enum |
| 8 | evidence event / head (`bro_evidence`, REUSED) | recorder runner | **evidence-recorder** key | isolated signer's `LiveRunStateProvider` §7 | **legacy epoch-seconds (never compared to ms)** | `event_hash` chain | evidence chain + **signer-owned `governed_evidence_head_floor`** (§7 P1-7/P0-2) | signer-owned floor keyed on `head_sequence` monotonicity + chain-content `(event_count, last_sequence, final_event_hash)` via BEGIN IMMEDIATE CAS A–E matrix (case A lower head → `stale_evidence`; B/D/E → `evidence_fork`; C unchanged re-anchor advances head only; D prefix-extend) | head monotone + chain content prefix-extends (structural) |
| 9 | `brops.governed-sign-result.v1` | isolated signer | signer key (the receipt envelope #12) | supervisor → bridge → desktop | ms | (transported) | — | `receipt_id` | tagged union `signed`/`refused`; echoes TRANSPORT-ONLY |
| 10 | `bridge.governed-turn-result.v1` (metadata-only, top-level `protocol` discriminator) + `brops.governed-turn-output-read.v1` pull | sidecar (transport/proxy) | — (carries #9/#12 signed bytes; output pulled) | **desktop verifies signatures + whole-output SHA256, NO store access** | ms | (transported; output via §4.10(f) pull) | — | `receipt_id` + `execution_attempt_id` + `output_stream_id` (read 3-tuple, P1-3) | echoes TRANSPORT-ONLY; desktop equality-checks vs the verified signed envelope #12; output digest vs #12 |
| 11 | `brops.governed-turn-record.v1` | supervisor | **`governed-turn-recorder`** key (dedicated) | isolated signer's `LiveRunStateProvider` §7 | ms | `record_handle = SHA256(JCS({payload,signature}))` (also create-if-absent at `<run_id>__<execution_attempt_id>.json`) | supervisor store namespace | `(run_id, execution_attempt_id)` | binds ALL of #1,#2,#4 (via `lease_handle`),#6 (via `execution_receipt_handle`),#7,#8 + `challenge_accepted_at_ms` |
| 12 | governed **receipt envelope** (`brops.governed-receipt-envelope.v1`) | isolated signer | **isolated-signer** key (pinned by desktop) | **desktop** (§6.1 step 14) | ms | (inside `envelope_jcs_b64`) | — | `receipt_id` | binds `record_handle`/`lease_handle`/`execution_receipt_handle`/`request_nonce`/`execution_attempt_id`/head fields/attestation digest/`output_sha256`/`output_bytes` |

**Refusal is fail-closed everywhere:** any missing/extra key, wrong type/unit, handle
mismatch, signature failure, cross-binding inequality, or ledger conflict Blocks; nothing
renders.

---

## 4. Exact schemas (backing the matrix)

Strict decode for **every** artifact: exact required-key set, **unknown-field rejection**,
**duplicate-key rejection**, UTF-8, integers for `_ms`/epoch/counts, lowercase-64-hex for
`*_handle`/`*_hash`/`*_sha256`. `artifact_type`/`key_id` are injected by the signer and
echoed. Signed bytes = detached Ed25519 over `JCS(payload)` unless noted.

### 4.1 `brops.governed-turn-challenge.v1` (artifact #1)
```jsonc
{ "payload": {
    "protocol": "brops.governed-turn-challenge.v1",
    "challenge_key_id": "<string ≤128>",
    "run_id": "<string ≤128>", "task_id": "<string ≤128>",
    "workspace_id": "<string ≤128>", "install_id": "<string ≤128>",
    "supervisor_id": "<string ≤128>",
    "request_nonce": "<string ≤128>",                         // one-time (Wave-3a nonce)
    "system_sha256": "<64hex>", "history_sha256": "<64hex>",
    "generation_config_sha256": "<64hex>",
    "request_sha256": "<64hex>",                              // == sha256(JCS(request envelope))
    "requested_at_ms": <int>, "challenge_issued_at_ms": <int>,
    "challenge_expires_at_ms": <int> },
  "sig": "<b64url Ed25519 over JCS(payload), by the desktop-challenge-authority key>" }
```
The authority **builds** this from its own protected pending-challenge row (the caller supplies only
a protected `pending_challenge_id` via `brops.governed-challenge-issue.v1`; the turn facts were entered
earlier and validated at `brops.governed-challenge-create-pending.v1` — the single two-message trust
model, §2.1); it does **not** carry
`challenge_accepted_at_ms` (the supervisor stamps that later — §1/§5).

### 4.2 `brops.challenge-key-registry.v1` (artifact #2)
```jsonc
{ "payload": {
    "artifact_type": "brops.challenge-key-registry.v1",
    "root_key_id": "<string ≤128>", "registry_epoch": <int>, "registry_issued_at_ms": <int>,
    "keys": [ { "challenge_key_id": "<string ≤128>", "public_key": "<b64url 32B→43 chars>",
                "valid_from_ms": <int>, "valid_to_ms": <int>, "key_epoch": <int>,
                "revoked": <bool>, "revoked_at_ms": <int epoch-ms> | null } ] },
  "root_sig": "<b64url Ed25519 over JCS(payload), by the pinned challenge-root>" }
```
**Key-entry revocation invariant (P1-3, LOCKED — the schema must be able to REPRESENT a
revoked key, not hardcode `false`/`null`):**
- `revoked` is a boolean; `revoked_at_ms` is an integer epoch-ms **or** `null`, discriminated:
  `revoked == false` ⇒ `revoked_at_ms` **MUST be `null`**; `revoked == true` ⇒ `revoked_at_ms`
  **MUST be an integer within the canonical ms range (§1)** and **`>= valid_from_ms`**.
- **Acceptance (§5)** refuses a key with `revoked == true && revoked_at_ms <=
  challenge_accepted_at_ms`.
- **Historical verification (§7)** accepts a record only when the bound key's
  `revoked_at_ms IS NULL OR revoked_at_ms > challenge_accepted_at_ms` (as-of-run).
- **Uniqueness + bounds:** duplicate `challenge_key_id` entries are **refused**; `keys` length
  ≤ **256**; the full registry document ≤ **256 KiB**.
- **Negative tests:** `revoked==true` with `null` time; `revoked==false` with a non-null
  time; `revoked_at_ms < valid_from_ms`; a seconds-not-ms value; duplicate key ids; and the
  boundary `revoked_at_ms == challenge_accepted_at_ms` (refused at acceptance).

Two distinct digests (protected-store law): `registry_hash = SHA256(JCS(payload))`
(fork/epoch identity, anti-rollback) vs `challenge_registry_handle = SHA256(JCS({payload,
root_sig}))` (exact stored document bytes, store lookup + record binding). `root_key_id`
selects a **binary-pinned challenge-root anchor baked into the supervisor config**
(root-owned; separate root + registry from the receipt keys); an unknown root is refused.

### 4.3 `brops.governed-turn-lease.v1` (artifact #4) — dedicated, closed
```jsonc
{ "payload": {
    "artifact_type": "brops.governed-turn-lease.v1",   // injected + echoed
    "key_id": "<lease-issuer key id>",                  // injected + echoed
    "schema": 1,
    "lease_id": "<string ≤128>", "nonce": "<string 16..128>",   // LEASE nonce (not lease_nonce)
    "run_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>",
    "task_id": "<string ≤128>", "agent_id": "<string ≤128>", "session_id": "<string ≤128>",
    "workspace_id": "<string ≤128>", "install_id": "<string ≤128>", "supervisor_id": "<string ≤128>",
    "task_class": "governed-model-turn-v1",
    "allowed_capabilities": ["INVOKE_GOVERNED_MODEL"],  // CLOSED; exactly this
    "max_tool_calls": 0,
    "launcher_executable_sha256": "<64hex>",            // pinned setuid launcher digest
    "executor_executable_sha256": "<64hex>",            // pinned CONTAINED MODEL EXECUTOR digest (P0 — TCB code-integrity floor, §2.5); the launcher re-hashes the executor image and refuses to setuid+exec on any mismatch (§4.7)
    "model_profile_id": "cfg-sha256:<64hex>",          // == "cfg-sha256:" + generation_config_sha256 (deterministic formula, §2 P0-2); ^cfg-sha256:[0-9a-f]{64}$; NOT a free field, NOT a registry lookup
    "generation_config_sha256": "<64hex>",             // == challenge #1 generation_config_sha256 == the executed config's hash; the SOLE input to the model_profile_id formula
    "lease_issued_at_ms": <int>, "lease_expires_at_ms": <int>,
    "challenge_accepted_at_ms": <int>,                  // supervisor-stamped (§5)
    "request_nonce": "<string ≤128>",                   // == challenge #1 request_nonce
    "challenge_handle": "<64hex>", "challenge_key_id": "<string ≤128>",
    "challenge_registry_handle": "<64hex>", "challenge_registry_hash": "<64hex>",
    "challenge_registry_epoch": <int>, "challenge_registry_root_key_id": "<string ≤128>"
  },
  "signature": "<detached Ed25519 over JCS(payload)>" }
```
- **Authority:** `ARTIFACT_AUTHORITY["brops.governed-turn-lease.v1"] = the governed-turn
  lease issuer` (the supervisor's lease-issuing authority; signs **leases only**, never
  receipts/records/evidence). `verify_artifact` refuses any other signer.
- **`issue_governed_turn_lease`:** the sole issuer; called **inside §5 step 4/6** with the
  accepted challenge, reserved `execution_attempt_id`, stamped `challenge_accepted_at_ms`, and
  resolved registry bindings. **Model-profile derivation (P0-2 LOCKED — formula only):** it sets
  `generation_config_sha256 = the accepted challenge's committed generation_config_sha256` (§5 step 4
  has already re-verified this equals the INPUTS_READY staged config re-hash) and
  `model_profile_id = "cfg-sha256:" + generation_config_sha256` — **never** a free/caller-chosen value
  and **never** a lookup. **Execution-permission gate (separate from identity):** before deriving,
  acceptance requires `generation_config_sha256 ∈ GOVERNED_EXECUTION_ALLOWLIST` (§2); a hash not in
  the allowlist ⇒ the acceptance Blocks (`model_profile_unknown`, §4.5) and no lease is issued. The
  allowlist gates launch; it does **not** feed the `model_profile_id` value. **Lease time is frozen,
  not issuer-chosen (P0-4, LOCKED):**
  `lease_issued_at_ms == challenge_accepted_at_ms` (equality — the exact lease payload bytes are
  persisted in the same acceptance tx, §5 step 4) and `lease_expires_at_ms == lease_issued_at_ms
  + LEASE_DURATION_MS` where **`LEASE_DURATION_MS = 210000` (210 s)** — one locked constant, not
  a signed input degree of freedom. `LEASE_DURATION_MS` covers the whole lease-scoped critical
  path: `~30000` post-acceptance pre-launch + `MIN_LAUNCH_REMAINING_MS 180000` (= `EXECUTION_TIMEOUT_MS`
  120000 + grace 5000 + teardown 10000 + post-exec signing to `completed_at_ms` 40000 = 175000
  worst-case + 5000 launch/scheduling slack) = **210000** exactly (§4.7 additive budget, §5 step 8a).
  It still nests inside the desktop `max_age_ms = 300000` freshness window (challenge TTL ≤30000 +
  210000 = 240000 < 300000, §1). It also enforces `requested_at_ms ≤ challenge_accepted_at_ms`; signs.
- **`validate_governed_turn_lease`:** `verify_artifact` (issuer) → strict-decode the exact
  key set → return fields. Refuses a missing/extra key, non-int `_ms`, `schema != 1`,
  `nonce` length ∉ [16,128], `allowed_capabilities != ["INVOKE_GOVERNED_MODEL"]`,
  `max_tool_calls != 0`, `generation_config_sha256` not `^[0-9a-f]{64}$`,
  `launcher_executable_sha256` or `executor_executable_sha256` not `^[0-9a-f]{64}$` **or not equal to the
  supervisor's start-time TCB pin for that binary** (§2.5 — a lease may only name the exact audited
  launcher + executor images), `model_profile_id` not
  `^cfg-sha256:[0-9a-f]{64}$`, and — the P0-2 binding, **recomputed independently by this validator** —
  `model_profile_id != "cfg-sha256:" + generation_config_sha256` **or**
  `generation_config_sha256 != the bound challenge's generation_config_sha256`. It does **NOT** consult
  `GOVERNED_EXECUTION_ALLOWLIST` (execution-permission is an acceptance-time gate, not a lease-validity
  or historical property). **Separate** from the base `validate_execution_lease` (which would
  reject the governed-turn keys as unexpected — a governed-turn lease presented to the base
  validator MUST be refused, tested).

### 4.4 `brops.governed-sign-request.v1` — attested evidence (artifact #5), COMPLETE schema
**NEW governed protocol (§2.2) — the ratified `brops.sign-request.v1` is untouched.**
`additionalProperties:false` on both objects; unknown-field + duplicate-key rejection;
`_ms` are integers; `*_handle`/`*_hash` lowercase-64-hex; frame ≤ 256 KiB; large inputs are
handles, never inline. There is **no `builder_id`** on the governed-model path (no builder
authority) — only `executor_id` + `runner_id`.
```jsonc
{ "protocol": "brops.governed-sign-request.v1",
  "attestation": {
    "attestation_protocol": "brops.run-attestation.v1",
    "supervisor_key_id": "<string ≤128>",
    "sig": "<b64url no-pad, 86 chars: Ed25519 over JCS(evidence)>" },
  "evidence": {
    "run_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>", "lease_id": "<string ≤128>",
    "task_id": "<string ≤128>", "request_nonce": "<string ≤128>", "receipt_id": "<string ≤128>",
    "decision": "completed",
    "workspace_id": "<string ≤128>", "install_id": "<string ≤128>", "supervisor_id": "<string ≤128>",
    "executor_id": "<string ≤128>", "runner_id": "<string ≤128>",
    "policy_id": "<string ≤128>", "policy_version": "<string ≤128>",
    "requested_at_ms": <int>, "completed_at_ms": <int>, "challenge_accepted_at_ms": <int>,
    "system_handle": "<64hex>", "history_handle": "<64hex>", "generation_config_handle": "<64hex>",
    "output_handle": "<64hex>", "containment_evidence_handle": "<64hex>", "policy_bundle_handle": "<64hex>",
    "lease_handle": "<64hex>", "execution_receipt_handle": "<64hex>",
    "challenge_handle": "<64hex>", "challenge_key_id": "<string ≤128>",
    "challenge_registry_handle": "<64hex>", "challenge_registry_hash": "<64hex>",
    "challenge_registry_epoch": <int>, "challenge_registry_root_key_id": "<string ≤128>",
    "evidence_event_count": <int ≥ 1>, "evidence_last_sequence": <int ≥ 0>, "evidence_head_sequence": <int>, "evidence_final_event_hash": "<64hex>" } }
```
`evidence` is authoritative ONLY because `attestation.sig` covers `JCS(evidence)`; every
`*_handle`/`*_sha256` is **DERIVED by the signer** from the store bytes, never trusted from
the wire. Malformed/oversize ⇒ `refused` (§4.5).

### 4.5 `brops.governed-sign-result.v1` — (artifact #9), COMPLETE tagged union
**NEW governed protocol (§2.2) — the ratified `brops.sign-result.v1` is untouched.**
`additionalProperties:false` per member; unknown/duplicate-key rejection; frame ≤ 64 KiB
(**machine-checked, P1-6:** worst-case signed body = `envelope_jcs_b64 ≤ 2848` +
`attestation_evidence_jcs_b64 ≤ 4664` + two 86-char sigs + echoes ≈ **9865 ≤ 65536** — cannot
exceed 64 KiB at full schema max).
```jsonc
// status == "signed":
{ "protocol": "brops.governed-sign-result.v1", "status": "signed",
  "receipt_id": "<string ≤128>",
  "envelope_jcs_b64": "<b64url ≤ 2848 bytes>", "signature_b64": "<b64url 86>", "key_id": "<string ≤128>",
  "attestation_evidence_jcs_b64": "<b64url ≤ 4664 bytes>", "attestation_signature_b64": "<b64url 86>",
  "supervisor_attestation_key_id": "<string ≤128>",
  "run_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>", "lease_id": "<string ≤128>",
  // ── TRANSPORT-ONLY echoes (desktop equality-checks against verified authority) ──
  "task_id": "<string ≤128>", "challenge_accepted_at_ms": <int>,
  "challenge_handle": "<64hex>", "challenge_key_id": "<string ≤128>",
  "challenge_registry_handle": "<64hex>", "challenge_registry_hash": "<64hex>",
  "challenge_registry_epoch": <int>, "challenge_registry_root_key_id": "<string ≤128>",
  "lease_handle": "<64hex>", "execution_receipt_handle": "<64hex>",
  "evidence_event_count": <int ≥ 1>, "evidence_last_sequence": <int ≥ 0>, "evidence_head_sequence": <int>, "evidence_final_event_hash": "<64hex>" }
// status == "refused":
{ "protocol": "brops.governed-sign-result.v1", "status": "refused",
  "receipt_id": "<string ≤128>" | null, "reason": "<one literal member of GOVERNED_REFUSAL_REASONS (defined next)>" }
```
**The CLOSED governed refusal-reason enum `GOVERNED_REFUSAL_REASONS` (P1-4, LOCKED — the single
union; SEPARATE from the frozen 12-value `brops.sign-result.v1` enum, which is untouched):** the
ratified 12 (`attestation_invalid, not_completed, run_binding_invalid, nonce_mismatch,
handle_missing, hash_mismatch, policy_mismatch, containment_missing, identity_denied,
timestamp_invalid, oversize, malformed`) + the governed additions (`challenge_replay,
acceptance_conflict, lease_not_ready, output_oversize, output_timeout, evidence_fork, stale_evidence,
lease_expired, challenge_invalidated, retry_conflict, stream_unknown, stream_expired,
stream_binding_mismatch, seq_out_of_range, model_profile_unknown, tcb_integrity_violation,
platform_unsupported`). **`tcb_integrity_violation`** (P0 — the launcher's exec-time executor re-hash /
owner / non-writable check failed, §2.5, §4.7) and **`platform_unsupported`** (P0 — the §0.1 platform
gate / `verify_distinct_principals()` / `verify_tcb_integrity()` refused at start, §0.1, §2.5, §2.6) are
both **pre-record Blocks**: no lease is issued (or no exec occurs), no receipt/evidence/terminal record
is produced, and the desktop renders dev/blocked, never `trusted_verified`. `model_profile_unknown` (P0-2 — a
staged `generation_config` whose `generation_config_sha256` is **not a member of
`GOVERNED_EXECUTION_ALLOWLIST`** (a config the supervisor is not configured to execute), §2) is a
**pre-launch acceptance Block** (`BLOCKED`; no lease is issued, no launch) — not an identity failure
(the identity `"cfg-sha256:"+generation_config_sha256` is always well-defined; already-signed historical
records for a since-removed config stay verifiable, §7). `stale_evidence` (P0-2, §7 case A — a lower-`head_sequence`
rolled-back/truncated head) is **distinct** from `evidence_fork` (a divergent-content fork, §7 cases
B/D/E). The previously-prose-only reasons (`evidence_fork`/`stale_evidence` from §7, `lease_expired`/
`EXPIRED` from the §7 lease-time invariants, acceptance-time `challenge_invalidated`, idempotency
`retry_conflict`, output-stream `stream_expired`/`stream_binding_mismatch`) are now closed members —
no reason is prose-only. **Producing gates for the acceptance-time members (LOCKED):**
`challenge_replay` = §5 acceptance CAS finds the `request_nonce` already ACCEPTED for a different
`challenge_handle` (a supervisor-side replay); `acceptance_conflict` = the §5 `absent → ACCEPTED_PREPARED`
CAS loses to a conflicting existing binding; `lease_not_ready` = the execute trigger (§4.10(d)) arrives
before the row reaches `LEASE_READY`; `timestamp_invalid` additionally covers an **acceptance-time
challenge-window expiry** — the §5/§7 predicate `challenge_issued_at_ms ≤ challenge_accepted_at_ms ≤
challenge_expires_at_ms` failing at acceptance (distinct from the §4.10(a0) resource-admission
`challenge_expired`, which is pre-row and internal). Each is produced at exactly one §5/§7 gate. (The §4.10(a0/a/b/c/d) and §2.1(A/B) internal producer codes —
`peer_denied`, `noncanonical`, `session_unknown`, `seq_mismatch`, `oversize_chunk`, `no_staging_row`,
`session_corrupt`, `challenge_expired`, `no_inputs_ready`, `field_invalid`, `pending_expired`,
`key_unavailable`, `quota_*`, … — are a **DISJOINT namespace** from `GOVERNED_REFUSAL_REASONS` and are
**never** added to it. They reach the desktop as a single durable Block via the §4.10(h) NON-SUCCESS
DIAGNOSTIC (sidecar-driven hops) or the §4.10(g) backend-direct authority reply (authority hops), each
mapped to a `governed_internal_refusal:{stage}:{upstream_reason}` bounded reason — **never** relayed as
a `GOVERNED_REFUSAL_REASONS` verdict. Only a `signed` result or a `GOVERNED_REFUSAL_REASONS` `refused`
verdict is relayed verbatim per the rule below.) A `signed` result REQUIRES both `envelope_jcs_b64` and
`signature_b64`; anything else ⇒ the desktop Blocks.

**Relay literal-embed rule (P1-4, LOCKED):** the two metadata-result relay reason enums — §4.6
`bridge.governed-turn-result.v1.error.reason` and §4.10(e) `brops.governed-turn-result.v1.reason` —
embed the **exact literal `GOVERNED_REFUSAL_REASONS` array VERBATIM** (a `$ref`/copy of the single
list above), **never** an inferred "mirrors §4.5" and **never** an open "superset". The bridge
output-read reason (§4.10(f)) is instead the **literal 5-member output-read set IDENTICAL to its
supervisor hop** (the sidecar is a transport proxy that originates **no supervisor or signature
verdict** — it never mints a refusal reason or a signed result, NOT a superset). **Precise scope
(P1-5):** "originates no reasons" means the sidecar cannot author a *governed decision* (accept,
refuse-with-reason, sign); it says nothing about **local transport failures** on the one-shot
subprocess/socket. A spawn/connect/timeout/oversize-or-malformed-reply/unexpected-exit is NOT a
supervisor reason at all — it surfaces as an **out-of-band Tauri command error ⇒ the desktop Blocks
with no result** (§6.1 step 14, §7.1). Every governed refusal thus has a representable literal code,
and every non-verdict transport failure is an explicit out-of-band Block; no prose-only or placeholder
reason exists in any normative schema.

### 4.6 `bridge.governed-turn-result.v1` — COMPLETE metadata-only parent (artifact #10)
**NEW bridge protocol (§2.2, renamed from the P0-1-collided `bridge.governed-result.v1`) — the
ratified `bridge.result` is untouched.** This is the **full outer object**, NOT the inner receipt
alone. **Discriminator (P0-1, CORRECTED):** it carries an explicit **top-level `"protocol"`
const** in its `required` set; the frozen `bridge.result` (`additionalProperties:false`, no
`protocol` key) rejects it (unknown top-level key) and this schema rejects a `bridge.result`
(missing required `protocol`). Do **not** use `receipt.envelope_jcs_b64` to discriminate — it is a
REQUIRED key of `bridge.result.receipt` too. `additionalProperties:false` on both objects;
`receipt` non-null iff `ok==true`; `error` non-null iff `ok==false`.

**ALWAYS-STREAM output (P0-3 + P1-6, LOCKED) — output is NEVER inlined in this frame.** The
governed reply text does **not** ride an unauthenticated `bridge.result.result` string, and it is
**not** carried inline here (a full-schema inline frame provably OVERFLOWS `262144` — output_b64
at even 128 KiB plus the co-resident `containment_evidence_b64 ≤ 65536` + `evidence[]` +
envelope/attestation reaches ~266707 > 262144). Instead the summary is **metadata-only** and the
exact bytes are pulled via the §4.10(f) `brops.governed-turn-output-read.v1` request/response loop.
Removing inline output drops this frame's worst case to **≈9.9 KiB** (§4.10 frame-fit proof).
```jsonc
{ "protocol": "bridge.governed-turn-result.v1",   // REQUIRED top-level discriminator (P0-1)
  "ok": <bool>,
  "output_stream_id": "<43-char base64url capability §4.10(f)> | null",     // non-null iff ok==true; drives the §4.10(f) pull
  "receipt": {                                     // non-null iff ok==true; ALL fields TRANSPORT-ONLY
    "task_id": "<string ≤128>", "status": "<string ≤64>", "exit_code": <int> | null,
    "evidence": ["<string ≤256>", ...],           // ≤ 64 entries (maxItems 64, each maxLength 256)
    "envelope_jcs_b64": "<b64url, ≤ 2848 bytes>", "signature_b64": "<b64url 86>",
    "containment_evidence_b64": "<b64url ≤ 65536 bytes>" | null,
    "attestation_evidence_jcs_b64": "<b64url, ≤ 4664 bytes>", "attestation_signature_b64": "<b64url 86>",
    "supervisor_attestation_key_id": "<string ≤128>",
    "run_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>", "lease_id": "<string ≤128>",
    "challenge_accepted_at_ms": <int>,
    "challenge_handle": "<64hex>", "challenge_key_id": "<string ≤128>",
    "challenge_registry_handle": "<64hex>", "challenge_registry_hash": "<64hex>",
    "challenge_registry_epoch": <int>, "challenge_registry_root_key_id": "<string ≤128>",
    "lease_handle": "<64hex>", "execution_receipt_handle": "<64hex>",
    "output_sha256": "<64hex>", "output_bytes": <int 0..8388608>,
    "evidence_event_count": <int ≥ 1>, "evidence_last_sequence": <int ≥ 0>, "evidence_head_sequence": <int>, "evidence_final_event_hash": "<64hex>" } | null,
  "error": { "reason": "<the literal GOVERNED_REFUSAL_REASONS array (§4.5), embedded verbatim>", "receipt_id": "<string ≤128>" | null } | null }
```
**Exact frame-fit (P1-6, machine-checked):** every b64 field has a frozen **encoded-byte**
`maxLength` — `envelope_jcs_b64 ≤ 2848` (= `4·⌈2135/3⌉`, the §4.9 payload at schema max),
`attestation_evidence_jcs_b64 ≤ 4664` (= `4·⌈3498/3⌉`, the §4.4 evidence at schema max),
`containment_evidence_b64 ≤ 65536`, `evidence[]` `maxItems 64 × maxLength 256`. A generated
maximum-size compact-JSON instance MUST assert `len(encoded_frame_body) ≤ MAX_FRAME_BYTES =
262144` in CI (worst case ≈ 92 KiB with containment+evidence at max; ≈ 9.9 KiB typical). No
approximate "≈" proof; the test constructs the literal maximum.

**Output binding (P0-3, LOCKED).** The desktop obtains the exact output bytes by driving the
§4.10(f) pull loop **through the sidecar** and reassembling into a bounded ≤ 8 MiB buffer, then —
**before any normalization/render and OUTSIDE any DB transaction** — asserts `len(bytes) ==
envelope.output_bytes` (length gate) and `SHA256(bytes) == envelope.output_sha256` (digest gate,
raw bytes — **no trim/NFC/NFKC/CRLF/lossy decode**); only then strict-UTF8 decode for UI display
(invalid UTF-8 ⇒ Block, unless the product explicitly supports binary output); render only after
the `BEGIN IMMEDIATE` tx commits (§6.1 step 14). Negative tests: substitution, one-byte mutation,
truncation, appended byte, Unicode-normalization (NFC/NFKC), CRLF conversion, invalid-UTF8→U+FFFD,
wrong-length, and a tampered/mis-ordered/short/replayed-stream chunk (each MUST Block).

**Authority rule (LOCKED, P0-3) — the BROKER verifies SIGNATURES, it does NOT read the
protected store.** The protected store is on the engine host, group-`brops-store`, and is
**not readable by the broker principal** (§2.3); the broker may also be a different runtime/
host. So the **deep protected-store verification** (fetch record/lease/receipt/challenge/
registry/containment/head **by handle**, re-hash, re-verify each signature, cross-check
bindings) is performed by the **isolated signer's `LiveRunStateProvider`** (§6.1 step 11, §7),
**not** by the desktop. The isolated signer then emits a **signed receipt envelope** (#12,
§4.9) that binds `record_handle`/`lease_handle`/`execution_receipt_handle`/`request_nonce`/
`execution_attempt_id`/head fields/attestation digest. The **desktop** takes authority ONLY
from: (a) the **isolated-signer receipt-envelope signature** (Ed25519 over `envelope_jcs_b64`,
pinned key); (b) the **supervisor-attestation signature** over `attestation_evidence_jcs_b64`
(re-verified against the manifest `supervisor_attestation` key) and its equality to the
envelope; (c) `request_nonce` one-time consume; (d) `receipt_id` global uniqueness; (e)
receipt-freshness (`_ms`); then it **equality-checks** every bridge/sign-result echo against
the verified envelope. **A bare bridge/sign-result echo never authorizes anything; the
desktop never dereferences a store handle;** a mismatch Blocks.

### 4.7 `brops.governed-turn-execution-receipt.v1` (artifact #6) — COMPLETE schema
Recorder-runner signed (**evidence-recorder** key); `additionalProperties:false`; unknown/
duplicate-key rejection; verified by **`verify_governed_turn_receipt`** (NOT
`verify_passing_receipt` — that CRLF-normalizes). Signed bytes = detached Ed25519 over
`JCS(payload)`; `execution_receipt_handle = SHA256(JCS({payload,signature}))`.
```jsonc
{ "payload": {
    "artifact_type": "brops.governed-turn-execution-receipt.v1",   // injected + echoed
    "key_id": "<evidence-recorder key id>",                         // injected + echoed
    "receipt_id": "<string ≤128>",
    "run_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>", "lease_id": "<string ≤128>",
    "runner_id": "<string ≤128>", "executor_id": "<string ≤128>",
    "exit_code": 0,                                                 // MUST be integer 0
    "contained": true,                                             // MUST be true
    "output_handle": "<64hex>",                                    // == output_sha256
    "output_sha256": "<64hex>",                                    // SHA256(exact binary reply bytes)
    "output_bytes": <int>,                                        // 0 ≤ n ≤ 8388608 (8 MiB, P1-6)
    "started_at_ms": <int>, "finished_at_ms": <int> },            // started ≤ finished
  "signature": "<detached Ed25519 over JCS(payload)>" }
```
- `output_handle == output_sha256 == SHA256(exact binary reply bytes)` (**no decode/trim/CRLF
  normalization**); `output_bytes` equals the accepted byte count; `started_at_ms ≤
  finished_at_ms`. Authority: `ARTIFACT_AUTHORITY[...] = evidence-recorder`; any other signer
  refused.

**Input FDs + OUTPUT BOUND (P1-6, canonical):** FDs `3`/`4`/`5` are **read-only regular-file
descriptors** to the exact content-addressed `system`/`history`/`generation_config` bytes (no
length prefix); FD `6` is the write-only output pipe. **These four descriptors MUST survive BOTH exec
boundaries: the recorder maps them onto the exact numbers 3/4/5/6 (`dup2`/`dup3`), clears `FD_CLOEXEC`
on each, redirects 0/1/2 to inert endpoints, and closes every FD ≥ 7 BEFORE `execve`ing the launcher
(§2.7 "Inherited FDs — SURVIVAL across BOTH exec boundaries"); the launcher then re-confirms/clears
`FD_CLOEXEC` on 3–6 before `fexecve`.** The launcher validates each input FD is
`O_RDONLY`, `S_ISREG`, offset 0, size ≤ the per-artifact ceiling (system ≤256 KiB, history
≤8 MiB, generation_config ≤64 KiB), backed by a `brops-store` store inode; it closes every
other FD, validates the pinned `launcher_executable_sha256` + fixed caller/target UID, drops
caps, then **(P0 — TCB code-integrity floor, §2.5) re-hashes the on-disk executor image it is
about to run and refuses unless it equals the lease's `executor_executable_sha256`**, verifies the
executor image is owned by the TCB principal + not writable by the in-scope login/sidecar UID
(`O_NOFOLLOW`, `fstat` the opened `fd` — never a path re-lookup), and only then
`setuid(executor)+exec`s that same verified `fd` (via `fexecve`, so the bytes hashed are the bytes
executed — no TOCTOU). Any mismatch/writable-image/owner check ⇒ **no exec, no receipt**, refused
reason **`tcb_integrity_violation`** (§4.5). The executor reads each input to EOF and writes only its
reply. **The output channel is BOUNDED:**
- **`MAX_OUTPUT_BYTES = 8 MiB`** (8388608; matches the desktop's real `MAX_ASSISTANT_OUTPUT`/
  `MAX_HTTP_BODY`, `ai.rs`). The recorder reads FD 6 into a **bounded** buffer with a hard
  ceiling; on the (`MAX_OUTPUT_BYTES + 1`)-th byte it **stops reading, terminates the executor
  (SIGKILL) + tears down its cgroup/process-group**, produces **no** receipt/evidence/terminal
  record, and returns refused reason **`output_oversize`** (§4.5).
- **`EXECUTION_TIMEOUT_MS = 120000` (120 s, LOCKED, P1-6).** Chosen so the **entire** pipeline
  nests inside the desktop freshness window `max_age_ms = 300000` (`receipt_store.rs`): worst
  case cross-host skew 60000 + pre-execution (challenge/ingress/acceptance/lease) 30000 +
  execution 120000 + post-execution signing (recorder receipt + record + isolated-signer deep
  verify + envelope + bridge + desktop tx) 40000 = 250000 < 300000 (50000 ms slack). It matches
  the desktop's shipping per-model-call bound (120 s, `ai.rs`); the 180 s streaming deadline is
  **NOT** reused (180000 + skew + pre + post would breach 300000). **Clock discipline:** the
  elapsed timeout is measured with a **MONOTONIC** clock (immune to NTP steps); **only** signed
  `_ms` fields use the wall clock. **Window nesting (LOCKED):** the governed challenge TTL
  `challenge_expires_at_ms − challenge_issued_at_ms ≤ 30000`; the governed lease window
  `lease_expires_at_ms − lease_issued_at_ms ≥ EXECUTION_TIMEOUT_MS + teardown`; and engine↔desktop
  wall-clock skew MUST be bounded ≤ 60000 (shared NTP) since the desktop stale check has no skew
  allowance on the old side. On timeout the recorder discards the buffer, produces no
  receipt/record, and returns **`output_timeout`**.
- **Termination + teardown (LOCKED, recorder-owned):** on `elapsed_monotonic ≥ EXECUTION_TIMEOUT_MS`
  (or the oversize path), **immediate `SIGKILL`** to the whole process-group / `cgroup.kill` (NOT
  SIGTERM→SIGKILL — the executor holds no key/store and only the FD-6 pipe already being
  discarded, and is treated as potentially hostile); **termination grace = 5000 ms** for the
  kernel to reap the process group; **cgroup teardown deadline = 10000 ms** to confirm
  `cgroup.procs` empty and `rmdir` the leaf cgroup. Success ⇒ `teardown_outcome = "contained"`
  (only this + `contained:true` yields a record, §4.7b); not-empty by the deadline ⇒
  `orphan-quarantined`/`timed-out` ⇒ **no accepted record**. **Budget model (P1-5, canonical —
  ADDITIVE):** the launch-gate remaining requirement is `EXECUTION_TIMEOUT_MS(120000) +
  grace(5000) + teardown(10000) + post_exec_signing_reserve(40000) = 175000` worst-case critical
  path (grace + teardown are **added to**, NOT absorbed by, the 40000 signing reserve); the gate
  threshold `MIN_LAUNCH_REMAINING_MS = 180000` adds 5000 launch/scheduling slack, and
  `LEASE_DURATION_MS = 210000 = ~30000 pre-launch + 180000` (§4.3, §5 step 8a).
- **Backpressure:** the recorder reads the pipe continuously into the bounded buffer so a slow
  reader cannot be exploited; a full buffer triggers the `output_oversize` path (never
  unbounded growth).
- **`output_handle`/`output_sha256` are computed ONLY over a COMPLETE, accepted byte stream**
  (executor exited `0`, within `MAX_OUTPUT_BYTES`, before timeout, `contained==true`). A
  truncated/partial output (crash/timeout/oversize) yields **no** published output artifact and
  **no** signed receipt — fail-closed.
- **Partial-output cleanup:** the recorder's bounded buffer/temp is discarded (never published)
  on any oversize/timeout/crash; a partial temp is never linked to a handle.
- **Negative tests:** `output_bytes` at `MAX-1` (accept), `MAX` (accept), `MAX+1`
  (`output_oversize`, no receipt), timeout mid-stream (`output_timeout`, no receipt), and a
  partial-write crash (no receipt, ledger → `RECOVERY_REQUIRED`).

### 4.7b `brops.governed-turn-containment.v1` (artifact #7) — COMPLETE schema
Recorder-measured firsthand; `additionalProperties:false`; recorded as a containment-confirmed
`bro_evidence` event whose `payload_hash == containment_evidence_sha256`.
```jsonc
{ "artifact_type": "brops.governed-turn-containment.v1",
  "run_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>", "lease_id": "<string ≤128>",
  "runner_id": "<string ≤128>", "executor_id": "<string ≤128>",
  "cgroup_id": "<string ≤256>", "process_group_id": "<string ≤64>",   // both always present
  "contained": true,                                                  // MUST be true for an accepted record
  "teardown_outcome": "contained",                                    // closed enum ↓
  "measured_at_ms": <int> }
```
`teardown_outcome` closed enum = `contained | orphan-quarantined | timed-out | failed`; only
`contained` (with `contained: true`) yields an accepted record. Canonical bytes = `JCS(artifact)`;
**`containment_evidence_sha256 = SHA256(JCS(artifact))`** (a JCS-document digest — the `_sha256`
suffix is retained for continuity but it hashes the JCS artifact, not raw bytes; see Appendix B).

### 4.8 `brops.governed-turn-record.v1` (artifact #11) — the ONLY terminal authority, COMPLETE schema
Signed by the dedicated **`governed-turn-recorder`** key; `additionalProperties:false`;
unknown/duplicate-key rejection; written atomically (create-if-absent, §6) into `store/sup/`
and also mirrored at `<run_id>__<execution_attempt_id>.json`. Signed bytes = detached Ed25519
over `JCS(payload)`; **`record_handle = SHA256(JCS({payload,signature}))`**.
```jsonc
{ "payload": {
    "artifact_type": "brops.governed-turn-record.v1",   // injected + echoed
    "key_id": "<governed-turn-recorder key id>",         // injected + echoed
    "run_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>",
    "task_id": "<string ≤128>", "agent_id": "<string ≤128>", "session_id": "<string ≤128>",
    "workspace_id": "<string ≤128>", "install_id": "<string ≤128>", "supervisor_id": "<string ≤128>",
    "executor_id": "<string ≤128>", "runner_id": "<string ≤128>",
    // lease binding
    "lease_id": "<string ≤128>", "lease_nonce": "<string 16..128>",   // == the lease's `nonce`
    "lease_issued_at_ms": <int>, "lease_expires_at_ms": <int>, "lease_handle": "<64hex>",
    // request binding
    "request_nonce": "<string ≤128>",
    "system_sha256": "<64hex>", "history_sha256": "<64hex>", "generation_config_sha256": "<64hex>",
    "requested_at_ms": <int>, "request_sha256": "<64hex>",
    // challenge binding (challenge_accepted_at_ms is SUPERVISOR-stamped, not in the challenge)
    "challenge_handle": "<64hex>", "challenge_key_id": "<string ≤128>",
    "challenge_issued_at_ms": <int>, "challenge_expires_at_ms": <int>, "challenge_accepted_at_ms": <int>,
    // registry snapshot binding
    "challenge_registry_handle": "<64hex>", "challenge_registry_hash": "<64hex>",
    "challenge_registry_epoch": <int>, "challenge_registry_root_key_id": "<string ≤128>",
    // output / policy / containment / receipt
    "output_sha256": "<64hex>", "output_bytes": <int>,
    "policy_id": "<string ≤128>", "policy_version": "<string ≤128>", "policy_bundle_sha256": "<64hex>",
    "containment_evidence_sha256": "<64hex>", "containment_event_id": "<string ≤128>",
    "receipt_id": "<string ≤128>", "execution_receipt_handle": "<64hex>",
    // evidence head (bro_evidence is LEGACY epoch-seconds; only these structural fields cross in)
    "evidence_final_event_hash": "<64hex>", "evidence_event_count": <int ≥ 1>, "evidence_last_sequence": <int ≥ 0>, "evidence_head_sequence": <int>,
    "completed_at_ms": <int> },
  "signature": "<detached Ed25519 over JCS(payload)>" }
```
Authority: `ARTIFACT_AUTHORITY[...] = governed-turn-recorder` (§8); any other signer refused.
`lease_handle`/`execution_receipt_handle` are the exact signed-document handles (§4.3/§4.7) so
the verifier fetches + re-verifies the exact lease/receipt documents (§7). `evidence_*` are the
**structural** bindings of the legacy epoch-seconds `bro_evidence` head (§1) — never compared
to an ms window.

### 4.9 `brops.governed-receipt-envelope.v1` (artifact #12) — the isolated-signer's signed envelope, COMPLETE schema
The isolated signer, **after** its `LiveRunStateProvider` deep-verifies the protected chain
(§7), constructs + signs this envelope; it is the ONLY thing the desktop trusts (the desktop
has no store access, §4.6/§2.3). `additionalProperties:false`; signed bytes = detached Ed25519
over `JCS(payload)` under the **isolated-signer key pinned by the desktop manifest**;
`envelope_jcs_b64 = base64url(JCS(payload))`, `signature_b64 = base64url(signature)` (both ride
`brops.governed-sign-result.v1` §4.5 + `bridge.governed-turn-result.v1` §4.6).
```jsonc
{ "payload": {
    "artifact_type": "brops.governed-receipt-envelope.v1",
    "key_id": "<isolated-signer key id, pinned by the desktop manifest>",
    "receipt_id": "<string ≤128>",
    "run_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>",
    "task_id": "<string ≤128>", "workspace_id": "<string ≤128>", "install_id": "<string ≤128>",
    "request_nonce": "<string ≤128>", "request_sha256": "<64hex>",
    "record_handle": "<64hex>", "lease_handle": "<64hex>", "execution_receipt_handle": "<64hex>",
    "output_sha256": "<64hex>", "output_bytes": <int>,
    "challenge_accepted_at_ms": <int>, "completed_at_ms": <int>,
    "evidence_final_event_hash": "<64hex>", "evidence_event_count": <int ≥ 1>, "evidence_last_sequence": <int ≥ 0>, "evidence_head_sequence": <int>,
    "supervisor_attestation_key_id": "<string ≤128>",
    "attestation_evidence_sha256": "<64hex>" },   // SHA256(the JCS(governed-sign-request evidence) the supervisor attested
  "signature": "<detached Ed25519 over JCS(payload), isolated-signer key>" }
```
The desktop (§6.1 step 14) verifies this signature under the pinned isolated-signer key, then
verifies the supervisor attestation and confirms `attestation_evidence_sha256` matches, then
consumes `request_nonce` + checks `receipt_id` uniqueness + freshness, then equality-checks the
bridge echoes — all without any protected-store access.

### 4.10 Control-plane protocols (P1-5) — staging, execute-trigger, supervisor→sidecar result

Every named governed protocol has ONE complete normative schema, a `protocol` const
discriminator, a producer, a consumer, and strict rejection of any v1 document (and vice
versa). `additionalProperties:false` + unknown/duplicate-key rejection everywhere; requests are
schema-validated **before** any side effect. These complete the challenge-submission open (P0-2), the two names that previously had no
§4 schema (`brops.governed-turn-result.v1`, `brops.governed-evidence-request.v1`), the three
staging messages, and the pull-based output read (P0-3) that were field-lists only.

**(a0) `brops.governed-turn-open.v1`** — sidecar→supervisor, the **signed-challenge submission
(P0-2)**. Reply `brops.governed-turn-open-result.v1`. Frame ≤ **8 KiB** (the challenge document
JCS is small — ≤ ~2.3 KiB base64url, far under this). This is the FIRST governed message; without
it the supervisor has only a `challenge_handle` and cannot verify a signature or recompute the
handle (verify-by-handle-before-possession is impossible).
```jsonc
// request:
{ "protocol": "brops.governed-turn-open.v1", "install_id": "<string ≤128>",
  "request_nonce": "<string ≤128>",
  "challenge_doc_b64": "<b64url of the EXACT signed challenge document JCS({payload,sig}), decoded ≤ 4096>" }
// reply (opened): { "protocol": "brops.governed-turn-open-result.v1", "status": "opened", "challenge_handle": "<64hex>" }
// reply (refused): { "protocol": "brops.governed-turn-open-result.v1", "status": "refused",
//   "reason": "peer_denied"|"doc_oversize"|"malformed"|"noncanonical"|"handle_mismatch"|"registry_unknown"|"key_invalid"|"sig_invalid"|"context_mismatch"|"challenge_expired"|"retry_conflict" }
```
**OPEN-TIME PRELIMINARY verification (P0-3, LOCKED — this is NOT the final §7 predicate; the
authoritative as-of-acceptance predicate runs at §5/§7 because `challenge_accepted_at_ms` does not
exist yet at open).** The supervisor MUST, in order: authenticate the peer UID; base64url-decode
`challenge_doc_b64`; strict UTF-8 JSON decode of the §4.1 `{payload,sig}` (unknown-field +
**duplicate-key** rejection; `decoded ≤ 4096`); **canonicality gate (P0-3, LOCKED):** require
`decoded_document_bytes == canonical_bytes({payload, sig})` (`bro_signature.canonical_bytes` — JCS)
else refuse `noncanonical` — so the transported bytes, the computed handle, and the stored document
can never diverge; `challenge_handle = SHA256(decoded_document_bytes)` (now identical to
`SHA256(JCS({payload,sig}))`); resolve the current accepted root-signed
`brops.challenge-key-registry.v1` **from its own supervisor state** (§4.2 pinned root anchor +
registry floor — the registry is NEVER supplied by the sidecar); verify `root_sig`, key presence,
and the challenge `sig` under the resolved snapshot key, with key validity **as of
`challenge_issued_at_ms`** (`valid_from_ms ≤ challenge_issued_at_ms ≤ valid_to_ms`, `revoked_at_ms
IS NULL OR revoked_at_ms > challenge_issued_at_ms`); verify `run_id`/`task_id`/`install_id`/window
context + recompute `request_sha256`; **RESOURCE-ADMISSION EXPIRY GATE (P1-3, rev 26, LOCKED — a
resource gate, NOT the binding acceptance predicate):** *after* the challenge `sig` is verified (so
`challenge_expires_at_ms`, a signed §4.1 field, is authenticated) and *before* any publish or CAS, read
the supervisor **wall clock once → `now_ms`** and refuse **`challenge_expired`** iff **`now_ms >
challenge_expires_at_ms`** (**inclusive boundary:** `now_ms == challenge_expires_at_ms` ADMITTED,
`+1` REFUSED). This `now_ms` is a **resource-admission read only**: it is **NOT** persisted, is **NOT**
`challenge_accepted_at_ms`, does **NOT** consume the nonce, does **NOT** create a row or execution right,
and does **NOT** replace the §5/§7 as-of-acceptance predicate (which still independently re-reads the
single §5 acceptance clock and re-checks the FULL validity/revocation window as-of
`challenge_accepted_at_ms`). A `challenge_expired` refusal creates **NO staging row**, publishes nothing,
consumes no nonce ⇒ an expired (or replayed-expired) challenge occupies **zero** staging quota.
`challenge_expired` is an **§4.10(a0)-internal producer code**, **NOT** a `GOVERNED_REFUSAL_REASONS`
member — routed to a terminal durable Block via the §4.10(h) diagnostic. Only if the gate passes:
**atomically create-if-absent publish the EXACT
`decoded_document_bytes`** into `store/sup/` (the §6 step-1 publish); CAS-create the
`governed_turn_staging` row `absent→VERIFYING→UPLOADING` keyed
`UNIQUE(install_id,request_nonce)`+`UNIQUE(challenge_handle)`; return `challenge_handle`. **No ACCEPTANCE
clock read (`challenge_accepted_at_ms` is NOT produced here — only the resource-admission `now_ms` above,
which is discarded), no nonce consume, no execution right — this only *admits* the turn to upload; the
binding authority is the acceptance-time re-verification (§5).** The gate is evaluated on **every** open
(first AND idempotent re-open, P1-6). Refused reasons: `peer_denied, doc_oversize,
malformed, noncanonical, handle_mismatch, registry_unknown, key_invalid, sig_invalid,
context_mismatch, challenge_expired, retry_conflict` (idempotent re-open, P1-6), plus `quota_turns` (P1-3: a 3rd
concurrent **LIVE** `governed_turn_staging` row for the `install_id` — `MAX_CONCURRENT_GOVERNED_TURNS = 2`;
expired rows excluded, §2.4 live-count rule). The untrusted sidecar transports bytes
only; the challenge signature + supervisor-resolved registry are the authority.

**(a) `brops.governed-staging-open.v1`** — sidecar→supervisor (§2.4), **only after a successful
`governed-turn-open.v1`** (requires the `UPLOADING` `governed_turn_staging` row). Reply
`brops.governed-staging-open-result.v1`. Frame ≤ 4 KiB.
```jsonc
// request:
{ "protocol": "brops.governed-staging-open.v1",
  "install_id": "<string ≤128>", "challenge_handle": "<64hex>", "request_nonce": "<string ≤128>",
  "artifact": "system" | "history" | "generation_config",     // policy_bundle REFUSED
  "declared_len": <int 0..8388608>, "declared_sha256": "<64hex>" }
// reply (opened):
{ "protocol": "brops.governed-staging-open-result.v1", "status": "opened",
  "staging_session_id": "<opaque string ≤128>", "next_seq": <int ≥ 0> }   // first open 0; idempotent reopen = current cursor (may be ≥ 1)
// reply (refused): { "protocol": "brops.governed-staging-open-result.v1", "status": "refused",
//   "reason": "peer_denied"|"no_staging_row"|"artifact_invalid"|"digest_mismatch"|"oversize"|"retry_conflict"
//            |"quota_sessions"|"quota_bytes"|"session_corrupt"|"malformed" }   // P1-3 quotas, P1-4 session_corrupt
```
`declared_sha256` MUST equal the verified challenge's committed
`*_sha256` for `artifact`; `declared_len` ≤ that artifact's ceiling (§2.4). **Idempotent re-open
(P1-6, LOCKED):** a re-open with the SAME `(challenge_handle, request_nonce, install_id, artifact,
declared_len, declared_sha256)` returns the **SAME** `staging_session_id` + the current `next_seq`
(re-emitting the original `opened` reply — a lost reply is safely retried); a re-open of the same
`(tuple, artifact)` with any differing `declared_len`/`declared_sha256` ⇒ `retry_conflict`.

**(b) `brops.governed-staging-chunk.v1`** — sidecar→supervisor. Reply
`brops.governed-staging-chunk-result.v1`. Frame ≤ `MAX_FRAME_BYTES = 262144`.
```jsonc
// request:
{ "protocol": "brops.governed-staging-chunk.v1", "staging_session_id": "<string ≤128>",
  "seq": <int ≥0>, "bytes_b64": "<b64url, decoded ≤ 184320 (P1-4)>" }
// reply (ack):     { "protocol": "brops.governed-staging-chunk-result.v1", "status": "ack", "next_seq": <int ≥ 0>, "reason": null }
// reply (refused): { "protocol": "brops.governed-staging-chunk-result.v1", "status": "refused", "next_seq": <int ≥ 0>,
//   "reason": "session_unknown"|"seq_mismatch"|"retry_conflict"|"oversize_chunk"|"oversize_frame"|"over_declared"
//            |"nondeterministic_chunk"|"too_many_chunks"|"session_corrupt"|"malformed" }   // P1-3 length/count, P1-4 session_corrupt
```
**Discriminated union (P1-2, LOCKED):** `status:"ack"` ⇒ `reason == null`; `status:"refused"` ⇒
`reason` a non-null literal from the closed set above; `next_seq` (the current durable cursor) is
present in both. Validator enforces `len(decode(bytes_b64)) ≤ 184320`, the serialized
frame ≤ 262144 (§2.4 P1-4), **and (P1-3) the deterministic length `chunk_len == min(184320,
declared_len − byte_count)`** (else `nondeterministic_chunk`) plus the cardinality cap `seq ≤ 45`
/ `next_seq ≤ 46 = MAX_STAGING_CHUNKS` (else `too_many_chunks`); a `SESSION_CORRUPT` session ⇒
`session_corrupt` (P1-4). **Idempotent chunk (P1-2/P1-6, LOCKED — the old collapsed `seq !=
next_seq ⇒ refuse` is DELETED; the single canonical rule is the four-way split):** `seq ==
next_seq` ⇒ persist the immutable `<seq>.chunk` + advance + ACK **only after the DB commit** (§2.4
P0-1 order); `seq < next_seq` **and** byte-identical to the durable `<seq>.chunk`/recorded
`chunk_sha256` ⇒ idempotent ACK + current `next_seq` (NO re-append, `byte_count` unchanged — a lost
ACK is safely retried); `seq < next_seq` **and** different ⇒ `retry_conflict`; `seq > next_seq` ⇒
`seq_mismatch` (a true gap).

**(c) `brops.governed-staging-final.v1`** — sidecar→supervisor. Reply
`brops.governed-staging-final-result.v1`. Frame ≤ 4 KiB.
```jsonc
// request: { "protocol": "brops.governed-staging-final.v1", "staging_session_id": "<string ≤128>", "seq": <int ≥0> }
// reply (published):
{ "protocol": "brops.governed-staging-final-result.v1", "status": "published",
  "artifact": "system" | "history" | "generation_config", "handle": "<64hex>",
  "inputs_ready": <bool> }          // true once all three inputs are published + re-hashed
// reply (refused): { "protocol": "brops.governed-staging-final-result.v1", "status": "refused",
//   "reason": "session_unknown"|"seq_mismatch"|"len_mismatch"|"sha_mismatch"|"handle_not_challenge"|"publish_divergent"|"retry_conflict"|"session_corrupt"|"malformed" }
```
Refused reasons: `session_unknown, seq_mismatch, len_mismatch, sha_mismatch, handle_not_challenge,
publish_divergent, retry_conflict, session_corrupt, malformed` (`session_corrupt` = P1-4). Requires `handle == the challenge's committed
*_sha256`. **Idempotent final (P1-6, LOCKED):** the first valid final publishes (reusing the
already-idempotent `os.link`/`O_EXCL` create-if-absent, `brops_evidence_store.publish`) and records
the `*_handle` + advances `inputs_ready`; an identical retry re-returns the SAME
`{status:"published", artifact, handle, inputs_ready}` from the recorded `*_handle` (a lost reply is
safe); a conflicting retry (session diverged / different declared digest) ⇒ `retry_conflict` /
`publish_divergent`.

**(d) `brops.governed-evidence-request.v1`** — sidecar→supervisor **execute/finalize trigger**
(the message that, once the staging row is `INPUTS_READY`, asks the supervisor to run the
governed turn and produce the signed result). Replaces the mis-named use of the v1
`brops.evidence-request.v1` const on the governed path. **Reply is a tagged union (P0-1):** once a
`governed_turn_acceptance` row exists, the acceptance/signer verdict is `brops.governed-turn-result.v1`
(e — `signed` or a `GOVERNED_REFUSAL_REASONS` `refused`); a **pre-acceptance** gate failure (no
`INPUTS_READY` staging row / peer / corrupt session) returns the internal
`brops.governed-evidence-request-result.v1 {status:"refused", reason:
"peer_denied"|"no_inputs_ready"|"session_corrupt"|"retry_conflict"|"malformed"}` — a **disjoint**
namespace from `GOVERNED_REFUSAL_REASONS`, carried to the desktop as the §4.10(h) NON-SUCCESS DIAGNOSTIC
(stage `evidence-request`) ⇒ one `governed_internal_refusal:*` Block; it creates **NO** acceptance row.
Both replies use its `protocol` const discriminator. Frame ≤ 4 KiB.
```jsonc
{ "protocol": "brops.governed-evidence-request.v1",
  "install_id": "<string ≤128>", "challenge_handle": "<64hex>", "request_nonce": "<string ≤128>" }
```
The supervisor authenticates the peer UID, requires the `INPUTS_READY` staging row for
`(install_id, request_nonce, challenge_handle)`, then drives §5 acceptance→lease→execution→
record and the isolated-signer flow (§6.1). It carries **no** `execution_attempt_id` (the
supervisor reserves it, §5) and grants no authority by itself.

**(e) `brops.governed-turn-result.v1`** — supervisor→sidecar **COMPLETE metadata-only tagged
union** (a NEW name; the existing `GOVERNED_RESULT_PROTOCOL = "brops.governed-result.v1"` in
`brops_supervisor_service.py` is FROZEN with its shipped shape — §2.2 P0-1). The sidecar re-frames
it into `bridge.governed-turn-result.v1` (§4.6). Frame ≤ `MAX_FRAME_BYTES = 262144`; **the output
is NEVER inlined** — the summary carries only `output_bytes`/`output_sha256`/`output_stream_id` and
the output is pulled via §4.10(f). All non-signature fields TRANSPORT-ONLY.
```jsonc
// status == "signed":
{ "protocol": "brops.governed-turn-result.v1", "status": "signed", "receipt_id": "<string ≤128>",
  "output_stream_id": "<43-char base64url capability, §4.10(f)>", "output_bytes": <int 0..8388608>, "output_sha256": "<64hex>",
  "envelope_jcs_b64": "<b64url ≤ 2848 bytes>", "signature_b64": "<b64url 86>", "key_id": "<string ≤128>",
  "attestation_evidence_jcs_b64": "<b64url ≤ 4664 bytes>", "attestation_signature_b64": "<b64url 86>",
  "supervisor_attestation_key_id": "<string ≤128>",
  "containment_evidence_b64": "<b64url ≤ 65536 bytes>" | null,
  "run_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>", "lease_id": "<string ≤128>" }
// status == "refused":
{ "protocol": "brops.governed-turn-result.v1", "status": "refused",
  "receipt_id": "<string ≤128>" | null, "reason": "<the literal GOVERNED_REFUSAL_REASONS array (§4.5), embedded verbatim>" }
```
A `signed` result REQUIRES `envelope_jcs_b64` + `signature_b64` + `output_stream_id`; anything
else ⇒ Block. The desktop's authority for the output is always the signed envelope's
`output_sha256`/`output_bytes`, applied to the §4.10(f)-reassembled bytes (§4.6/§7.1).

**(f) Output-read PULL (P0-2/P0-3) — the ONLY egress path, complete on BOTH hops.** The output is
NEVER pushed (the real `brops_socket` is one-request/one-response and the supervisor is a pure
responder; the real `engine_sidecar` reads ONE stdin request, writes ONE stdout result, exits).
The desktop therefore **drives a pull loop by re-invoking the sidecar once per chunk** (a fresh
one-shot subprocess each read); the sidecar is a **stateless proxy** that forwards exactly one
supervisor read and reframes the reply.

**Capability token + binding (P0-2/P1-3, LOCKED).** `output_stream_id` = **32 cryptographically-
random bytes, base64url no-pad, EXACTLY 43 chars** (256-bit) — an unguessable, non-enumerable
capability generated server-side and bound in the durable `governed_output_streams` table (below)
to `(receipt_id, execution_attempt_id, output_handle, output_bytes, output_sha256)`. **The
supervisor requires the client to present `receipt_id` + `execution_attempt_id` alongside the token
(P1-3)** and compares all three against the row before serving — so a *valid* token from a different
receipt/attempt is caught **server-side** (`stream_binding_mismatch`), not merely by the desktop's
final digest.

**Honest threat scope (P1-3, LOCKED — no false confidentiality claim):** the 256-bit token prevents
**blind guessing and unauthorized *unrelated* callers**; it does **NOT** provide confidentiality
against the compromised sidecar, which — being the transport proxy for **all** turns — necessarily
observes the token and every chunk's bytes. 3b-1B guarantees output **authenticity/integrity** via
the isolated-signer envelope's `output_sha256`/`output_bytes` (the desktop's sole authority);
**confidentiality of the output from the sidecar is NOT provided in 3b-1B** — end-to-end output
encryption would require a separate future contract.

**Durable mapping (P0-2, LOCKED — supervisor-owned `0700` DB, survives restart):**
```sql
-- INSERT-ONCE (immutable after commit; never UPDATEd; only the sweep DELETEs). Logical state is DERIVED, not stored.
CREATE TABLE governed_output_streams (
  output_stream_id     TEXT PRIMARY KEY,          -- 43-char base64url, 256-bit
  install_id           TEXT NOT NULL,             -- (NEW P1-2) per-install quota + sweep grouping
  receipt_id           TEXT NOT NULL UNIQUE,
  execution_attempt_id TEXT NOT NULL UNIQUE,
  output_handle        TEXT NOT NULL,             -- content-addressed store/rec handle; a REFERENCE, NOT the retention owner (§2.3)
  output_bytes         INTEGER NOT NULL,          -- 0..8388608
  output_sha256        TEXT NOT NULL,
  created_at_ms        INTEGER NOT NULL,          -- ≥ completed_at_ms
  expires_at_ms        INTEGER NOT NULL,          -- created_at_ms + OUTPUT_STREAM_TTL_MS   (LOGICAL-expiry key: reads past this ⇒ stream_expired)
  retained_until_ms    INTEGER NOT NULL );        -- (NEW P1-2) created_at_ms + OUTPUT_STREAM_TTL_MS + OUTPUT_STREAM_RETENTION_MS (PHYSICAL-sweep key)
CREATE INDEX ix_gos_install ON governed_output_streams (install_id);
CREATE INDEX ix_gos_retained ON governed_output_streams (retained_until_ms);
```
The row is **durably committed BEFORE** the §4.10(e) result summary is returned; a supervisor restart
preserves it. `output_stream_id` is minted **exactly once** (create-if-absent on `UNIQUE(receipt_id)`/
`UNIQUE(execution_attempt_id)`), recorded in the §4.10(e) summary + terminal record, and a `COMPLETED`
retry **re-reads, never re-mints** it. **Output-stream lifecycle (P1-2, LOCKED — three phases; the read/
retry verdict is SYNCHRONOUS on every read, never dependent on the async sweep):** constants
`OUTPUT_STREAM_TTL_MS = 360000` (logical), `OUTPUT_STREAM_RETENTION_MS = 360000` (tombstone window),
`OUTPUT_STREAM_SWEEP_INTERVAL_MS = 60000`, `MAX_OUTPUT_STREAMS_PER_INSTALL = 64`,
`MAX_OUTPUT_STREAM_BYTES_PER_INSTALL = 536870912` (= 512 MiB = 64×8 MiB). TTL proof: `now_sup ≤
completed_at + max_age_ms(300000) + skew(60000) ≤ created_at + 360000`, nesting inside the desktop
window (`receipt_store.rs:50-52`). Verdict order (per read/retry): row **absent** ⇒ `stream_unknown`
(Phase 3, swept); `now_ms > expires_at_ms` ⇒ `stream_expired` (Phase 2, tombstone present) — **inclusive
boundary**, `now_ms == expires_at_ms` LIVE; `receipt_id`/`execution_attempt_id` ≠ request ⇒
`stream_binding_mismatch`; `seq` out of range ⇒ `seq_out_of_range`; else serve. **Phase 1 (pre-logical-
expiry):** COMPLETED retry returns the SAME token; same `seq` byte-identical; restart re-drives from the
durable row. **Phase 2 (post-logical-expiry, tombstone present):** **NEVER mint a replacement token** —
a COMPLETED retry re-serves the same (now-expired) `output_stream_id`, every read returns the one
deterministic `stream_expired`. **Phase 3 (post physical retention, row swept at `now_ms >
retained_until_ms`):** reads ⇒ `stream_unknown` (the one-way `stream_expired → stream_unknown`
transition, keyed on `retained_until_ms`); the terminal record stays the sole output authority so no
result is lost. **Sweep:** a `OUTPUT_STREAM_SWEEP_INTERVAL_MS = 60000` background + startup pass DELETEs
rows past `retained_until_ms` (within `2× = 120000` of eligibility) — **row only; it MUST NOT unlink the
content-addressed `store/rec/<output_handle>`** (§2.3: the bytes are pinned by the terminal record §4.8 +
execution receipt §4.7 that reference the handle, and are collected only by the store's own
content-addressed GC when unreferenced — so output bytes OUTLIVE the stream row). **Quota (fail-closed,
per install):** before inserting a new row, sweep this install's `retained_until_ms`-expired rows; if
present-row count would reach `MAX_OUTPUT_STREAMS_PER_INSTALL = 64` or `Σ output_bytes` reach
`MAX_OUTPUT_STREAM_BYTES_PER_INSTALL`, FIFO-evict the oldest by `created_at_ms` (evicted ⇒
`stream_unknown` early — never a correctness loss, bytes remain) until both hold, then insert; a
completing turn's stream is **always** created. No stream enumeration is ever exposed. **Tests:**
restart-mid-pull; expiry boundary (`==` LIVE / `+1` expired); delayed-sweep (logically expired, row
present ⇒ `stream_expired`, not `stream_unknown`); quota FIFO-evict; same-token COMPLETED retry;
no-remint after expiry; tombstone-expiry ⇒ `stream_unknown` (one-way); concurrent reads; output-bytes
outlive the swept stream (store GC collects only when unreferenced).

**Supervisor hop — `brops.governed-turn-output-read.v1`** (sidecar→supervisor, one-req/one-resp
`brops_socket`). Frame ≤ `MAX_FRAME_BYTES = 262144`.
```jsonc
// request:
{ "protocol": "brops.governed-turn-output-read.v1", "output_stream_id": "<43-char b64url>",
  "receipt_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>", "seq": <int ≥0> }
// reply (ok): { "protocol": "brops.governed-turn-output-read-result.v1", "ok": true,
//   "output_stream_id": "<same>", "seq": <same>,
//   "bytes_b64": "<b64url of output[seq·184320 : (seq+1)·184320], decoded ≤ 184320>", "eof": <bool>, "error": null }
// reply (refused): { "protocol": "brops.governed-turn-output-read-result.v1", "ok": false,
//   "output_stream_id": "<same or null>", "seq": <int or null>, "bytes_b64": null, "eof": null,
//   "error": { "reason": "stream_unknown"|"stream_expired"|"stream_binding_mismatch"|"seq_out_of_range"|"malformed" } }
```
**Binding compare (P1-3, LOCKED):** the supervisor looks up the row by `output_stream_id` and then:
token absent ⇒ `stream_unknown`; `now_ms > expires_at_ms` ⇒ `stream_expired`; row's `receipt_id` OR
`execution_attempt_id` ≠ the request's ⇒ `stream_binding_mismatch`; only on a full 3-tuple match does
it serve the requested immutable range. The desktop sources `receipt_id`/`execution_attempt_id` from
the **verified §4.9 signed envelope** (authenticated values, not transport claims).

**Desktop hop — `bridge.governed-turn-output-read.v1`** (desktop→sidecar) + its
`bridge.governed-turn-output-read-result.v1` reply (P0-2 — the previously-missing bridge side).
Each is one stdin request / one stdout reply of a **fresh one-shot sidecar subprocess**, spawned by an
**INTERNAL backend helper** (`governed_turn_output_read`, a private function of the one
`governed_turn_execute` command — **NOT** a frontend-exposed `#[tauri::command]`; it must NOT appear in
`generate_handler!`, so the output pull never round-trips the webview), mirroring `governed_engine`'s
one-shot spawn; a NEW `protocol`-keyed branch in `engine_sidecar` validates the bridge
request, forwards exactly ONE `brops.governed-turn-output-read.v1` to the supervisor socket,
validates the reply, reframes and exits. `bridge.task-request` is untouched.
```jsonc
// desktop→sidecar request (the sidecar forwards these fields UNCHANGED to the supervisor):
{ "protocol": "bridge.governed-turn-output-read.v1", "output_stream_id": "<43-char b64url>",
  "receipt_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>", "seq": <int ≥0> }
// sidecar→desktop reply (ok):
{ "protocol": "bridge.governed-turn-output-read-result.v1", "ok": true, "output_stream_id": "<same>",
  "seq": <same>, "bytes_b64": "<b64url ≤ 245760>", "eof": <bool>, "error": null }
// sidecar→desktop reply (refused): the sidecar RELAYS a supervisor verdict verbatim (it originates NO
//   supervisor/signature verdict of its own), so this reason enum is IDENTICAL to the supervisor's (NOT a superset):
{ "protocol": "bridge.governed-turn-output-read-result.v1", "ok": false, "output_stream_id": "<same or null>",
  "seq": <int or null>, "bytes_b64": null, "eof": null,
  "error": { "reason": "stream_unknown"|"stream_expired"|"stream_binding_mismatch"|"seq_out_of_range"|"malformed" } }
// NOTE (P1-5): a LOCAL transport failure of the one-shot sidecar (spawn/connect/timeout/oversize-or-
//   malformed-reply/unexpected-exit) is NOT one of these reasons and produces NO reply frame — it is an
//   out-of-band Tauri command error ⇒ the desktop Blocks with no result (§6.1 step 14, §7.1).
```
Chunk size = **184320** decoded (= 245760 b64url + a small JSON envelope ≤ 262144). For an 8 MiB
output: `ceil(8388608 / 184320) = 46` chunks, **`seq` 0..45** (last chunk 94208 bytes, `eof=true`).
**Zero-byte output (P1-3, LOCKED):** when `output_bytes == 0` the `governed_output_streams` row
still exists; a read with `seq == 0` returns `ok:true, bytes_b64:"", eof:true`; any `seq > 0` ⇒
`seq_out_of_range`; the desktop then asserts `reassembled_len == 0 == envelope.output_bytes` and
`SHA256("") == envelope.output_sha256`. Reads are **idempotent**: the same `seq` always returns the
exact same byte range (offset `seq · 184320`); a lost reply is safely retried (no `next_seq`
consume). The desktop reassembles all chunks into a bounded ≤ 8 MiB buffer **outside any DB
transaction** (never hold `BEGIN IMMEDIATE` across the per-chunk subprocess/socket I/O —
`receipt_store.rs::in_immediate_tx` rejects a nested tx), then asserts `reassembled_len ==
envelope.output_bytes` **and** `SHA256(reassembled) == envelope.output_sha256` **before** any
normalization/render (§7.1). The **signed envelope** is the sole authority, so a tampered/re-ordered/
dropped/cross-turn chunk fails the whole-output digest → Block. Tests: exact-max chunk, zero-byte
output, `seq` out-of-range, `stream_expired` after TTL, **`stream_binding_mismatch` on a valid
other-turn token presented with the wrong `receipt_id`/`execution_attempt_id`** (now caught
server-side), supervisor-restart-mid-pull re-drives from the durable row, `COMPLETED` retry returns
the same token, idempotent re-read returns identical bytes, and a 1-byte-tampered chunk.

### 4.10(g) Desktop→sidecar governed INGRESS — `bridge.governed-turn-submit.v1` (P0-1)

This is the missing normative hop the rev-16/17 flow consumed "by assumption": nothing carried
the signed challenge document or the raw input bytes **to the sidecar**. The frozen
`bridge.task-request` (`bridge/contracts/task-request.schema.json`, `additionalProperties:false`,
`required:[task_id,task_class,rationale,system,history,request]`, no `challenge_doc_b64`, no discriminator) cannot be extended
(3b-1A positive control depends on it byte-for-byte), so 3b-1B ADDS a **new** ingress frame in a
new schema file `bridge/contracts/bridge-governed-turn-submit.schema.json`. **Challenge-document
carriage (Track E risk #2):** §2.1 already has the **trusted verifier/broker service** as the challenge
authority's only AF_UNIX peer; the authority returns the signed `{payload,sig}` document **to the broker**
(never to the renderer) in that same reply, and the **broker** (holding the raw bytes) base64url-encodes
it into `challenge_doc_b64` here. No new principal handles the document.

**Request (desktop → one-shot sidecar `stdin`, one JSON object):**
```json
{ "protocol": "bridge.governed-turn-submit.v1",
  "task_id": "<string ≤128>",
  "challenge_doc_b64": "<base64url of the exact signed {payload,sig} bytes, decoded ≤ 4096>",
  "system": "<string, UTF-8, ≤ 262144 bytes>",
  "history": [ { "role": "user"|"assistant"|"system", "content": "<string>" }, … ],
  "generation_config": {                 // ONE closed FLAT string→string object (P1-1 — every value a validated canonical STRING; NO JSON numbers)
    "engine_id":         "<string, regex ^[A-Za-z0-9._-]{1,128}$; the frozen default is exactly \"brops.governed-engine.sidecar.v1\" (§4.10(g) resolver, not overridable)>",
    "model":             "<string, regex ^[A-Za-z0-9._:-]{1,128}$>",
    "max_output_tokens": "<string, regex ^[1-9][0-9]{0,6}$  AND 1 ≤ int(v) ≤ 1048576>",
    "temperature":       "<string, regex ^[0-2]\\.[0-9]{2}$ AND 0 ≤ 100·intdigit + int(2 fraction digits) ≤ 200>",
    "top_p":             "<string, regex ^[01]\\.[0-9]{2}$  AND 0 ≤ 100·intdigit + int(2 fraction digits) ≤ 100>" } }
```
`additionalProperties:false` at BOTH levels; top-level `required:[protocol,task_id,challenge_doc_b64,
system,history,generation_config]`; `generation_config` is a **closed FLAT string→string object**
(P1-1) with `additionalProperties:false` and `required:[engine_id,model,max_output_tokens,temperature,top_p]`
— **every value is a validated canonical STRING, never a JSON number** (see the P1-1 note below): the
numeric bounds are enforced by **regex + integer-range validation at strict-decode time (in BOTH Rust
and Python)**, which REJECTS exponent form, signed zero, extra/insufficient precision, and
bare-integer float forms **before** canonicalization — so a non-canonical value can never reach JCS,
and `JCS(generation_config)` reduces to the already-proven string→string primitive (no numeric
serialization on either side). `temperature`/`top_p` are fixed-point decimal strings with **exactly 2
fractional digits** (the integer-range check uses pure integer arithmetic on the digits, no float
parse); `max_output_tokens` is a canonical decimal-integer string (no leading zeros). This is
strictly more fail-closed than an opaque string. The
top-level `protocol` const both admits this frame and (being absent from
`bridge.result`/`bridge.task-request`) keeps it disjoint from the frozen family. `role` is a closed
enum `{user,assistant,system}`; caps: `system` ≤ `MAX_SYSTEM_BYTES = 262144`
(`ai.rs:71`), `JCS(history)` ≤ `MAX_CONVERSATION_BYTES = 8388608` (`ai.rs:73`), `history` ≤
`MAX_MESSAGES = 1000` (`ai.rs:74`) with each `content` ≤ `MAX_MESSAGE_BYTES = 1048576` (`ai.rs:72`)
mirror the real code, and the **governed-family** `JCS(generation_config)` ≤
`MAX_GENERATION_CONFIG_BYTES = 65536` (a NEW 3b-1B constant for the flat string→string object form — NOT an `ai.rs` cap);
overflow ⇒ out-of-band ingress error (below), no frame emitted.

**Canonical input bytes (governed family — LOCKED, with a NEW parallel `generation_config`
formula that does NOT touch the frozen 3b-1A path).** The sidecar derives the three staged
artifacts' bytes, and the signed challenge commits to their SHA-256:
- `system_bytes  = system.encode("utf-8")` — raw UTF-8, **no trim/NFC/NFKC/CRLF normalize**
  (the shipped `brops_canonical.system_bytes`, `brops_canonical.py:98-101`).
- `history_bytes = JCS([{ "content":…, "role":… } for each turn])` — RFC 8785 canonical JSON of the
  normalized `{content,role}` objects (the shipped `brops_canonical.history_bytes`,
  `brops_canonical.py:104-109`); **Rust↔Python JCS parity** is the same primitive proven for
  receipts (`core/src/receipt.rs::jcs_bytes:235-237` ↔ `bro_signature.canonical_bytes:158-160`,
  parity test `receipt.rs:1283-1289`).
- `generation_config_bytes = JCS(generation_config)` — where `generation_config` is a **FLAT
  string→string object** (every value a validated canonical string). This rides the **EXACT proven
  string→string primitive**: Rust `core/src/receipt.rs::jcs_bytes:235-237` (a `BTreeMap<String,String>`
  serializer — its own doc-comment scopes it to a flat `string → string` object and there is **no**
  numeric/general-RFC-8785 serializer anywhere in the core crate) ↔ Python
  `bro_signature.canonical_bytes:158-160` (`json.dumps(sort_keys=True, separators=(",",":"),
  ensure_ascii=False)`), already cross-language parity-proven by `receipt.rs::brops_all_formula_parity_matches_python:1200`
  (the flat-object minimal-escaping shape is additionally pinned by `receipt.rs:1284`). **No JSON number is ever
  serialized on either side** (P1-1 — the rev-18 `JCS(number)` form was representation-ambiguous:
  Python `json.dumps` uses CPython float-repr while Rust `serde_json` uses `ryu`, and neither matches
  RFC 8785 ECMAScript number formatting, so a legitimate numeric config could be committed by the
  Rust authority and re-hash differently on the Python sidecar → false `handle_not_challenge`/
  `sha_mismatch` Block). All numeric bounds are instead enforced by **regex + integer-range validation
  at strict-decode time in BOTH languages**, which REJECTS exponent form, signed zero, extra/
  insufficient precision, and bare-integer float forms before canonicalization — so a non-canonical
  value never reaches JCS. *(Reconciliation — this is a **NEW, strictly additive** canonicalization
  for the 3b-1B governed family, per the §2.2 KEEP + ADD law, and does NOT modify anything frozen: the
  shipped `brops_canonical.generation_config_bytes` (raw UTF-8 of an arbitrary config **string** via
  `generation_config: &str`, e.g. `{"model":"claude","temperature":0}` hashed as raw bytes,
  `brops_canonical.py:118-122` / `ai.rs:1221`), the frozen 3b-1A parity fixture
  (`receipt.rs:1216-1219`, which hashes the raw-UTF-8 string form), and `prepare_governed_turn`'s
  `generation_config: &str` signature (`ai.rs:1221/1231`) all stay **byte-for-byte unchanged** on the
  frozen path. The 3b-1B canonicalizer ADDS a `governed_generation_config_bytes(obj) = JCS(obj)`
  function over the validated flat string→string object alongside the frozen one, and the governed
  desktop-challenge-authority hashes exactly `SHA256(JCS(generation_config))` so the challenge-commit
  ↔ staged-digest equality holds within the governed family; a mismatch fails closed via
  `handle_not_challenge`. A **new Rust↔Python parity fixture** (distinct from and additive to the
  frozen `receipt.rs:1216-1219` string fixture, which is untouched) pins the object/JCS form on the
  string→string shape, and MUST cover: (1) an accepted canonical instance canonicalizes byte-identically
  Rust==Python with a pinned `SHA256`; (2) boundary values `temperature`/`top_p` `"0.00"`/`"1.00"`/`"2.00"`
  and `max_output_tokens` `"1"`/`"1048576"` accepted + identical; (3) exponent form (`"1e0"`,`"1E2"`,`"1e3"`)
  rejected in BOTH; (4) signed zero (`"-0.00"`,`"-0"`) rejected; (5) integral-float / precision mismatch
  (`"1"`,`"1.0"`,`"1.000"` where `"1.00"` is required) rejected; (6) high-precision input
  (`"0.300000000000000004"`,`"0.9999"`) rejected; (7) leading-zero / out-of-range integer
  (`"0256"`,`"0"`,`"1048577"`) rejected; (8) out-of-range fixed-point (`"2.01"`,`"3.00"`,`"1.01"` for
  `top_p`) rejected by the integer-hundredths bound though the regex passes. A flat string→string object
  is deliberately more fail-closed than the opaque config string it replaces on the governed path, and
  by construction makes cross-language numeric divergence structurally impossible.)*
`challenge_doc bytes = JCS({payload,sig})` for the open-time canonicality gate (§4.10(a0),
unchanged).

**Desktop governed-turn preparation contract (P0-1, v1b — the SINGLE immutable object-JCS-hash
source).** The frozen `prepare_governed_turn(system, messages, now_ms, workspace_id, install_id,
generation_config: &str)` (`ai.rs:1214-1235`) hashes `generation_config` as a **raw UTF-8 string**
(`generation_config_sha256 = sha256_hex(generation_config.as_bytes())`, `ai.rs:1231`) and stores that
raw-string hash in `GovernedRequestContext` (`ai.rs:1169-1177`) → `IssuedRequest`
(`receipt.rs:270-294`, built at `commands.rs:856-864`) → the `receipt_challenges` pre-store
(`issue_challenge`, `receipt_store.rs:109-126`) → the final `Expected` compare
(`receipt_store.rs:322-327`). The governed family instead requires
`generation_config_sha256 = SHA256(JCS(flat string→string generation_config OBJECT))` (the P1-1
form). Those two hashes **differ**, so 3b-1B MUST NOT reuse the frozen `&str` preparation — otherwise
the desktop pre-stores a raw-string-based `request_sha256` while the authority/staging derive the
object-JCS-based one ⇒ a `request_sha256` mismatch that fails closed at **every** gate on the path —
the authority/supervisor `handle_not_challenge`, the desktop `Verified::bind` recompute
(`receipt.rs:467`/`:484`), and the pre-stored-challenge vs Expected compare
(`receipt_store.rs:322-327`) — so **every** legitimate turn Blocks (the split-authority the Architect
flagged). 3b-1B therefore ADDS **one new, immutable**
preparation function that is the sole source of the object-JCS hash for the entire chain:
```rust
// NEW — additive; the frozen prepare_governed_turn(&str) + its fixtures are byte-for-byte untouched.
pub struct PreparedGovernedTurnV1B {
    pub system: String,                     // exact bytes sent AND hashed (raw UTF-8)
    pub history: Vec<ChatMsg>,              // canonical trimmed history sent AND hashed (JCS)
    pub generation_config: GovernedGenerationConfig,   // the VALIDATED flat string→string OBJECT (retained — the frozen struct dropped the raw string)
    pub generation_config_jcs: Vec<u8>,     // JCS(object) computed ONCE
    pub context: GovernedRequestContext,    // request_nonce + the OBJECT-JCS generation_config_sha256 + the other hashes
}
pub fn prepare_governed_turn_v1b(
    system: &str, messages: &[ChatMsg],
    generation_config: GovernedGenerationConfig,   // OBJECT, not &str
    now_ms: u64, workspace_id: &str, install_id: &str,
) -> Result<PreparedGovernedTurnV1B, String>
```
It **MUST, in ONE pass, produce every downstream value from the same inputs**: (1) `validate` the flat
`generation_config` object (§4.10(g) per-field regex + integer-range, rejecting exponent/`-0.0`/
precision/bare-int **before** canonicalization); (2) compute `generation_config_jcs = JCS(object)`
**once** and `generation_config_sha256 = SHA256(generation_config_jcs)` — the **object-JCS** hash, never
`generation_config.as_bytes()`; (3) normalize `system` (raw UTF-8) + `history` (JCS) once; (4) mint
`request_nonce = brops_core::id()` (UUIDv4) **once**; (5) build **one immutable**
`GovernedRequestContext`/`IssuedRequest` carrying that object-JCS `generation_config_sha256`; (6) be the
**single source** from which the desktop derives, with no re-hashing and no second config
representation: **(a)** the `receipt_challenges` pre-store `IssuedRequest` (`issue_challenge` →
`request_sha256()`), **(b)** the create-pending (A) request (§2.1), **(c)** the
`bridge.governed-turn-submit.v1` submit frame (§4.10(g) — which carries the **validated object** so the
authority + sidecar staging recompute the identical `SHA256(JCS(object))`), and **(d)** the final
`Expected.request` used at §6.1 step-14 verification (`receipt.rs:418-486`). Because all four derive
from the one `PreparedGovernedTurnV1B`, the **same** object-JCS `generation_config_sha256` — and hence
the same `request_sha256` — flows through `receipt_challenges` → authority pending row → §4.1 challenge
→ §2.4 staging → terminal record → `Expected`, with **no split authority**. **Frozen (untouched, §2.2
KEEP+ADD):** `prepare_governed_turn(&str)` (`ai.rs:1214-1235`), `GOVERNED_GENERATION_CONFIG: &str =
"brops.governed-engine.sidecar.v1"` (`commands.rs:785`), the raw-string hash line (`ai.rs:1231`), and
the raw-string parity fixture (`receipt.rs:1215-1219`) all stay byte-for-byte; v1b is a **new**
function/struct beside them. **Mandatory tests (P0-1):** (i) the frozen fixture's raw-string hash
`SHA256("{\"model\":\"claude\",\"temperature\":0}") = 963be7a4…` (`receipt.rs:1215-1219`) is asserted
**≠** the object-JCS `generation_config_sha256` of the corresponding validated object — proving the two
formulas are distinct and the frozen path is not silently reused; (ii) an E2E assertion that **only**
the object-JCS `generation_config_sha256` appears at every 3b-1B hop — the desktop `receipt_challenges`
row, the authority `governed_pending_challenge` row, the §4.1 challenge payload, the §2.4
`generation_config` staged-artifact re-hash, the terminal record, and the §7 `Expected` — and the
raw-string hash appears **nowhere** on the 3b-1B path.

**ONE trusted Rust orchestration command `governed_turn_execute` (P0-1 LOCKED — the
`PreparedGovernedTurnV1B` lifecycle NEVER crosses the frontend/webview boundary).**

**Principal binding (rev-28 P0-1 — this is a BROKER-SERVICE operation, NOT an in-process renderer/Tauri
authority).** `governed_turn_execute` and every step below execute **inside the trusted desktop
verifier/BROKER service process** (dedicated service UID/SID, §0 role #2), which alone owns the receipt
DB, the pinned manifest, the `PreparedGovernedTurnV1B` object, all hashes/nonces, the challenge-authority/
sidecar/supervisor/signer sockets, and the final verification verdict. Throughout §4.10(g), §6.1 and
§7/§7.1 the words "backend"/"backend execution"/"the desktop" (as the trusted producer/verifier) denote
**this broker service process**, never the renderer/webview. The renderer/login process holds a **thin
`#[tauri::command]` proxy** that does **nothing** but forward a **closed `{conversation_id, agent?, client_request_id}`**
command to the broker over the renderer↔broker IPC (below) and render the broker's committed reply; the
proxy **may carry ONLY `conversation_id`, an optional authorized `agent` identifier, and a non-authoritative `client_request_id` correlation token (§4.10(g) request frame)** and **may NOT own
or access** the receipt DB, the pinned manifest, the prepared object, any hash/nonce, the challenge
authority, the sidecar/supervisor/signer sockets, or any verification-verdict construction. **Only the
broker** — after its verification transaction commits and the accepted output is persisted — **emits the
final UI-safe committed result** back to the renderer proxy; a renderer can never fabricate one.

**Renderer↔broker IPC (rev-28 P0-1 — NORMATIVE, the sole renderer→broker channel).** The proxy reaches
the broker over an authenticated local IPC (Linux `AF_UNIX` + `SO_PEERCRED`; Windows named-pipe token-SID,
§0.W). **Peer auth:** the broker verifies the connecting peer is the interactive login/renderer identity
and refuses any other peer; the renderer symmetrically pins the broker peer UID/SID. **Request (P1-1 — adds a NON-authoritative correlation token):** exactly
one frame `brops.renderer-governed-turn.v1 { "protocol", "conversation_id": "<string ≤128>", "agent":
"<string ≤128, optional>", "client_request_id": "<UUIDv4 string>" }` — `additionalProperties:false`,
unknown-field + duplicate-key rejection, request frame ≤ `RENDERER_IPC_FRAME_BYTES = 8192`; any
`system`/`history`/`generation_config`/hash/nonce/`run_id`/`task_id`/`broker_turn_id`/`request_nonce`/
prepared-object/verdict/receipt field present ⇒ `malformed` (the broker resolves them itself from trusted
state, never from the renderer). **`client_request_id` is a NON-authoritative renderer-supplied
correlation token ONLY** — it MUST match
`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$` (else `malformed`) and grants **no**
signing, verification, or persistence authority whatsoever; it never enters
`request_sha256`/`IssuedRequest`/`Expected` and never selects or creates a receipt/trust row. On accepting
the request the **broker mints its OWN authoritative identities** — `broker_turn_id = brops_core::id()`
(UUIDv4, the durable turn identity) and the `request_nonce` (the §4.10(g) `prepare_governed_turn_v1b`
step-1 nonce) — which the renderer can neither supply nor influence.

**Reply (P0 — broker-committed output delivery, LOCKED single model).** The broker returns exactly one
closed frame carrying the **broker-produced immutable UI projection** of the verified+persisted turn. On a
committed turn:
`brops.renderer-governed-turn-result.v1 { "protocol", "status": "committed", "client_request_id",
"broker_turn_id", "conversation_id", "message": { "message_id", "role": "assistant", "author", "body",
"created_at_ms", "trust_state": "trusted_verified" } }`. On a refused/blocked turn the frame carries **NO**
`message` object:
`brops.renderer-governed-turn-result.v1 { "protocol", "status": "blocked", "client_request_id",
"broker_turn_id", "conversation_id", "reason" }` — where **`reason` is a CLOSED enum ∈ {`malformed`, `peer_denied`, `retry_conflict`, `turn_in_progress`, `commit_readback_mismatch`, `upstream_blocked`}** (any other value is a protocol violation). Every reply (committed **or** blocked) echoes the
request's `client_request_id` and the broker's `broker_turn_id`; the frame is UI-safe and carries NO store
handle, key, envelope, hash, nonce, or verdict internals. **Delivery invariants (P0 — NORMATIVE):**
- The returned `message.body` is the **exact strict-UTF8-decoded bytes** whose byte-`length` AND `SHA-256`
  matched the signed accepted-output envelope (§4.7/§6.1); any decode/length/hash disagreement ⇒ the turn
  fails closed as `blocked`, never a committed frame.
- `message.message_id`, `message.body`, and `message.trust_state` **equal the exact row the broker
  verification transaction committed** — the broker re-reads the committed row inside the same transaction
  boundary and, on ANY mismatch between the persisted row and the accepted output, **FAILS CLOSED**
  (`blocked`+`commit_readback_mismatch`, no committed frame emitted).
- **ONLY the broker verification transaction** creates the verified message and sets
  `trust_state:"trusted_verified"`. The renderer **NEVER** reads or writes the broker receipt/trust DB
  directly, **cannot** create/edit/mark a message `trusted_verified`, and **cannot** mint or forge this
  frame. Pre-existing generic renderer-side chat WRITE commands (draft/edit/delete/insert) operate only on
  renderer-local chat state and **cannot mutate a broker-verified message or its trust state** — the
  broker-owned verified row is not writable through any renderer command path.
- The renderer **receives and renders ONLY** this broker-produced projection; `trusted_verified` is
  displayed as "Verified" **solely** from a broker-emitted committed frame authenticated over the
  peer-pinned IPC (§ Peer auth) — a forged or renderer-originated event can **never** render a message as
  Verified.
- **Output-bytes equality is test-enforced:** the bytes the executor wrote through FD 6 (§2.7/§4.7) ==
  the persisted `message.body` == the `body` returned in this frame (one byte string compared for equality
  end-to-end); a break anywhere fails the turn closed.
**Timeout / replay / idempotency (P1-1 — payload-aware correlation; REPLACES the prior "idempotent on
`conversation_id` re-attach" rule, which is now wrong).** The broker keys idempotency on the **exact
normalized tuple `{client_request_id, conversation_id, agent}`** (the validated `conversation_id` +
sanitized `agent` + lowercase-canonical `client_request_id`), mapped to the authoritative `broker_turn_id`:
- An **identical LIVE duplicate** (same `{client_request_id, conversation_id, agent}` while that turn is
  still in flight) **re-attaches to the SAME `broker_turn_id`** and never starts a second turn — the
  duplicate reply echoes that same `broker_turn_id`.
- The **same `client_request_id` with a DIFFERENT `conversation_id` or `agent`** ⇒ `blocked`+`retry_conflict`
  (a correlation token may not be reused across a different conversation or agent); no new turn is started.
- A **DIFFERENT request** (new `client_request_id`) **while the conversation already has a live turn** ⇒
  explicit `blocked`+`turn_in_progress` — **NOT** silent re-attachment: at most one in-flight governed turn
  per `conversation_id` is still enforced, but a mismatched correlation is refused explicitly rather than
  folded into the existing turn.
- **Every reply echoes `client_request_id` + `broker_turn_id`**, so the proxy binds each reply to the
  request it issued; a **LATE reply from an earlier timed-out/abandoned request cannot satisfy a newer
  request** — the proxy accepts a reply only when BOTH echoed `client_request_id` and `broker_turn_id`
  match the still-outstanding request and drops any reply whose pair is stale.
- Correlation IDs (`client_request_id`, `broker_turn_id`) grant **NO** signing, verification, or
  persistence authority (§ Request above); the broker's `request_nonce` consume /
  `record_pre_verification_block` remains the durable single authority.
The proxy applies a bounded overall deadline and, on any transport failure or timeout, surfaces a `blocked`
result WITHOUT retrying the turn; on reconnect it MAY re-issue the **same** `client_request_id` to
re-attach to a still-live `broker_turn_id` (idempotent live re-attach) or to learn the committed/blocked
outcome, never to start a duplicate turn (the broker's `request_nonce` consume /
`record_pre_verification_block` is the durable authority, below). **Error behavior:** the renderer proxy
originates **no** verdict and **no** signed artifact; a malformed/oversized/wrong-peer request is refused
by the broker with `blocked`+`malformed`/`peer_denied` and no side effect. Submit is **NOT**
a separate frontend-invoked Tauri command that re-accepts raw fields: that would sever the single
immutable object at the Tauri boundary (the object cannot survive to submit/`Expected` without a
webview re-serialize/reconstruct, re-opening the split-authority — a frontend-supplied
`system`/`history`/`generation_config` could then differ from the already-pre-stored `request_sha256`
⇒ fail-closed Block). Instead 3b-1B adds **exactly one** frontend-exposed governed
`#[tauri::command]` — a **thin renderer-side proxy** (the sole NEW entry in `generate_handler!`,
`apps/desktop/src-tauri/src/lib.rs:95-166`) that carries **only** `{conversation_id, agent?}` to the
broker over the renderer↔broker IPC above and owns none of the orchestration — while the **broker-service**
orchestration **`governed_turn_execute`** it invokes **mirrors the merged single-backend-command shape of
`stream_reply`** (`commands.rs:794`, which today already does prepare → `issue_challenge` pre-store →
`governed_turn` execute → build `Expected` → `verify_and_record_receipt` in ONE backend execution,
`commands.rs:844-935`), now executed **inside the broker service process** (§0 role #2), never the webview. It takes ONLY the **renderer-owned inputs** — **`conversation_id`** (the active
conversation) and optional **`agent`** — exactly like the merged `stream_reply(conversation_id, agent,
on_event)` (`commands.rs:793-799`); it does **NOT** accept `system`/`history`/`workspace_id`/`install_id`/
`generation_config`/`run_id`/`task_id` from the renderer (those are backend-resolved or backend-generated,
below — the renderer cannot inject them). In **one backend execution** it constructs and owns a single
**backend-owned orchestration object** (P0-1 — the routing identities the flow needs, never crossing the
Tauri/webview boundary):
```rust
// backend-owned; never serialized to the renderer
struct GovernedTurnExecutionV1B {
    conversation_id: String,   // the renderer's active conversation — feeds the receipt_challenges FK + the final accepted-output persist
    run_id: String,            // backend-generated brops_core::id() — bound into the §4.1 challenge `run_id` (no run_id exists in the frozen path; 3b-1B generates it here)
    task_id: String,           // backend-generated governed_task_id() — bound into the §4.1 signed challenge (run_id/task_id, verified open-time §4.10(a0)) but NOT into request_sha256/IssuedRequest/Expected
    prepared: PreparedGovernedTurnV1B,  // carries request_nonce + the object-JCS hash + the resolved system/history/generation_config
}
```
**Backend-resolved / -generated identities (NOT renderer-re-sent):** `system`/`history` are resolved
server-side from the message store keyed by `conversation_id` (`repo::chat::list_messages`,
`commands.rs:801-815`; `system` built from the sanitized `agent`); `workspace_id`/`install_id`/
`supervisor_id`/`policy_id`/`policy_version` come from the `GOVERNED_*` backend constants
(`commands.rs:780-787`); `request_nonce`/`run_id`/`task_id` are backend-generated (`brops_core::id()` /
`governed_task_id()`). **The full `generation_config` OBJECT has ONE trusted backend source (P0-1(B)
LOCKED)** — a new
```rust
fn resolve_governed_generation_config_v1b() -> Result<GovernedGenerationConfig, String>
```
that returns **all five** fields from **locked governed defaults / trusted host config only** (never the
renderer, never the sidecar), validated **once** by the §4.10(g) flat-string→string regex + integer-range
rules, then frozen into the immutable object. **The five FROZEN LITERAL default values (P0-2 LOCKED — no
`e.g.`, no approximate value):**

| field | literal default | const | source / justification |
|---|---|---|---|
| `engine_id` | `"brops.governed-engine.sidecar.v1"` | reuses `GOVERNED_GENERATION_CONFIG` (`commands.rs:785`) | the frozen governed-engine id, reused verbatim; **NOT overridable** (it pins the execution mechanism) |
| `model` | `"claude-sonnet-5"` | `GOVERNED_MODEL` | mirrors `DEFAULT_ANTHROPIC_MODEL` (`ai.rs:26`) byte-for-byte |
| `max_output_tokens` | `"4096"` | `GOVERNED_MAX_OUTPUT_TOKENS` | governed default; ungoverned `1024` (`ai.rs:1449`) truncates a governed reply; `4096` is a conservative deterministic ceiling within `1..1048576`, matches `^[1-9][0-9]{0,6}$` |
| `temperature` | `"0.00"` | `GOVERNED_TEMPERATURE` | greedy/deterministic decode; matches `^[0-2]\.[0-9]{2}$`, hundredths `0` |
| `top_p` | `"1.00"` | `GOVERNED_TOP_P` | full nucleus mass, pairs with `temperature="0.00"`; matches `^[01]\.[0-9]{2}$`, hundredths `100` |

The default object canonicalizes to exactly
`{"engine_id":"brops.governed-engine.sidecar.v1","max_output_tokens":"4096","model":"claude-sonnet-5","temperature":"0.00","top_p":"1.00"}`
with `generation_config_sha256 = 732b58634d0a83e9b7fdf1ca69db78df145bd9dd79ac8922fed3e79cf5faab22` and thus
`model_profile_id = cfg-sha256:732b58634d0a83e9b7fdf1ca69db78df145bd9dd79ac8922fed3e79cf5faab22`.
**Trusted-host override contract (EXACT — P0-2 LOCKED):** overrides are read ONLY from the desktop
backend's trusted host process environment (never renderer, never sidecar). Exactly **four** fields are
overridable (`engine_id` is immutable, no override var): `model`←`BROPS_GOVERNED_MODEL` (`^[A-Za-z0-9._:-]{1,128}$`);
`max_output_tokens`←`BROPS_GOVERNED_MAX_OUTPUT_TOKENS` (`^[1-9][0-9]{0,6}$` AND `1≤int≤1048576`);
`temperature`←`BROPS_GOVERNED_TEMPERATURE` (`^[0-2]\.[0-9]{2}$` AND `0≤hundredths≤200`);
`top_p`←`BROPS_GOVERNED_TOP_P` (`^[01]\.[0-9]{2}$` AND `0≤hundredths≤100`). An unset/empty var ⇒ the frozen
literal default; a set-but-invalid value ⇒ the resolver returns `Err` and `governed_turn_execute`
terminates the turn as an out-of-band Block (fail-closed, never silently defaulted); an override producing
a hash not in `GOVERNED_EXECUTION_ALLOWLIST` ⇒ acceptance Block `model_profile_unknown` (§4.5), no lease
(the identity is still well-defined; to run an overridden config its `SHA256(JCS(object))` must be added to
the allowlist via a supervisor restart). The resolver's returned object is what `prepare_governed_turn_v1b`
canonicalizes (`generation_config_jcs = JCS(object)` → `generation_config_sha256`), so a single trusted
object flows the whole chain — the frozen opaque-string path (`GOVERNED_GENERATION_CONFIG` passed to the
frozen `prepare_governed_turn(&str)`) is **untouched** (§2.2 KEEP+ADD); the resolver + its consts are new.
Owning this one object, `governed_turn_execute` performs in order:
1. `prepare_governed_turn_v1b(…)` **once** (validate the config object; `generation_config_jcs =
   JCS(object)` + `generation_config_sha256` once; mint `request_nonce` once);
2. `receipt_challenges` pre-store via `issue_challenge(&conn, &conversation_id, &prepared.issued_request(),
   now_ms)` (`receipt_store.rs:109-126`) — keyed by the orchestration object's `conversation_id`, **before**
   any submit;
3. challenge **create-pending (A)** (carrying the backend `run_id` + turn facts) then **issue (B)** over
   the authority `AF_UNIX` channel (§2.1) — the orchestration object stays in the backend across both
   authority round-trips;
4. **`governed_turn_submit_prepared(execution: &GovernedTurnExecutionV1B, challenge_document: &ChallengeDocument)`**
   — an **INTERNAL Rust helper, NOT a `#[tauri::command]` and NOT in `generate_handler!`** — takes the
   **whole orchestration object** (so `task_id`/`run_id` are in scope; `PreparedGovernedTurnV1B` alone does
   NOT carry `task_id`, P0-1(A)). It builds the `bridge.governed-turn-submit.v1` frame from
   `execution.task_id` + `execution.prepared` (the validated system/history/`generation_config` object +
   its object-JCS bytes) + the `challenge_document` (`challenge_doc_b64`). **Before it writes the frame it
   asserts the exact cross-bindings (P0-1 LOCKED) — else terminal Block:** `submit.task_id ==
   execution.task_id == challenge_document.payload.task_id`; `challenge_document.payload.run_id ==
   execution.run_id`; `SHA256(JCS(execution.prepared.generation_config)) ==
   challenge_document.payload.generation_config_sha256`. Then it spawns the one-shot governed sidecar
   exactly as `ai.rs::governed_engine` does today (`ai.rs:1346-1412`: spawn, write the submit JSON to
   `stdin` `:1369-1376`, read one reply from `stdout` `:1391-1399` bounded by `MAX_STDOUT_BYTES = 9 MiB
   :43`, await exit), under the existing `MAX_CONCURRENT_GENERATIONS = 2` permit (`ai.rs:212`), returning
   the **metadata-only** result;
5. the **internal output-pull loop** (fresh one-shot sidecars per chunk, §4.10(f)) — also an internal
   backend function driven by `governed_turn_execute`, **not** a frontend-exposed command;
6. build the final `Expected` from the **same** orchestration object and verify/persist
   (`receipt.rs:418-486`, `verify_and_record_receipt`); on accept the reply is written into the
   conversation recovered **from the consumed challenge row** (`receipt_store.rs:366-406`), never
   re-supplied by the renderer.
**No post-prepare webview round-trip (LOCKED):** after step 1, `system`/`history`/`generation_config`/
its hashes/`context`/`conversation_id`/`run_id` are **never** re-serialized to, or re-accepted from, the
frontend; the only renderer interactions are the initial **thin-proxy Tauri command** carrying **only** `{conversation_id, agent?}` to the broker (the renderer does **not** invoke `governed_turn_execute` — that is a BROKER-SERVICE operation, §0/§4.10(g); the renderer never names the prepared object, its hashes, nonces or the verdict) and the final broker-emitted committed result, rendered read-only. **Encapsulation enforcement (P0-1 LOCKED):** `PreparedGovernedTurnV1B` fields are **private**;
no mutable public copy of the object/JCS/context is exposed; every cross-stage read is via a
**read-only accessor**; and **before submit** the backend asserts
`SHA256(prepared.generation_config_jcs) == prepared.context.generation_config_sha256` **and**
`prepared.issued_request().request_sha256() == the pre-stored receipt_challenges.request_sha256` — a
tampered/reconstructed object cannot reach submit. **Mandatory tests (P0-1):** (i) a frontend that mutates
`generation_config`/`system`/`history` after `governed_turn_execute` begins **cannot** reach submit or
alter the pre-stored request (there is no post-prepare frontend input path; the single in-process
`GovernedTurnExecutionV1B` is the sole source of the submit bytes and the `Expected`); (ii) a
**whole-chain identity E2E**: the SAME `task_id`, `run_id`, and `generation_config` JCS bytes flow
identically through the authority pending row → the signed §4.1 challenge → the
`bridge.governed-turn-submit.v1` frame → the governed-turn lease (§4.3) → the terminal record (§4.8) →
the isolated-signer receipt envelope (§4.9) — any divergence at any hop ⇒ terminal Block (the §4.10(a0)
open-time `run_id`/`task_id` verify, the submit-time cross-binding asserts above, and the §7 `Expected`
compare each catch it). **Permitted
alternative (only if a future architecture must split the stages across processes):** a server-side
**opaque `prepared_turn_id`** state machine — a bounded, TTL'd, supervisor-or-backend-owned store with
closed transitions `PREPARED → CHALLENGED → SUBMITTED → FINALIZED`, one-time-consume, crash/retry
semantics; the frontend receives **only** the opaque id, and the authority request, submit frame, and
final `Expected` are all produced from the **same stored immutable object**. 3b-1B mandates the
single-backend-command form above; the `prepared_turn_id` state machine is the **only** other
permitted shape — a frontend-exposed raw-field submit command is **forbidden**.

**Authority-channel failure boundary (P1-1 LOCKED — the post-pre-store authority hops are durable too).**
The desktop↔sidecar terminal-durable-Block contract (§6.1) is **extended to the authority `AF_UNIX`
hops**. After the `receipt_challenges` pre-store (step 2), EVERY failure of the authority channel has
**exactly two** permitted outcomes inside `governed_turn_execute`, selected **deterministically by the
failure class** (§2.1.1(f)), never a third:
- **(a) bounded internal idempotent retry** — **only** for an **ambiguous transport failure** (socket
  unavailable, a lost reply, or a transport-malformed/oversize/unparseable frame — no verdict received)
  — with the **same live `GovernedTurnExecutionV1B`**: the §2.1 authority protocols are lost-reply-safe
  idempotent (a repeat `create-pending` with the same `(install_id, request_nonce)` returns the SAME
  `pending_challenge_id`; a repeat `issue` with the same `pending_challenge_id` re-returns the
  byte-identical stored `{payload,sig}`), so a retry from the still-in-memory object recovers the same
  pending row / challenge and the chain continues — bounded by `MAX_AUTHORITY_ATTEMPTS = 3` (=
  `MAX_AUTHORITY_RETRIES 2` + the first attempt, §2.1.1), each attempt `AUTHORITY_ATTEMPT_TIMEOUT_MS =
  2000` with `AUTHORITY_RETRY_BACKOFF_MS = 1000`; OR
- an **explicit well-formed `status:"refused"` verdict** (any reason in the §2.1(A)/(B) closed sets,
  incl. `reason:"malformed"`) is **TERMINAL, never retried** (a deterministic denial) → outcome (b);
- **(b) terminal durable Block** — `record_pre_verification_block` (`receipt_store.rs:175-208`): consume
  the `request_nonce` + write **exactly one** durable `blocked` attempt (`StreamEvent::Blocked{reason}`);
  the nonce is spent (a later receipt on it ⇒ `Replay` Block).

There is **no** third outcome that returns from the command with an **unconsumed** desktop nonce while
the in-memory object is gone (that was the rev-22/rev-23 non-durable seam, one hop earlier). An
authority-side row left behind by a terminal Block is harmless: it binds **no
execution right** and is swept by its state-specific retention (§2.1: a `PENDING` row by `PENDING_TTL`;
an `ISSUED` row — which must retain its signed document for byte-identical replay — by
`ISSUED_RETENTION_MS`), and it can never become a reusable/orphan logical turn because the desktop
nonce is already consumed. **Mandatory tests (P1-1):**
authority-socket-unavailable, lost `create-pending` reply, lost `issue` reply, explicit authority
`refused`, and malformed authority reply — each MUST end in exactly one of the two outcomes: the same
challenge recovered (idempotent retry) and the chain proceeds, **or** the nonce terminal-consumed with
exactly one `blocked` attempt and no reusable turn.

**Sidecar orchestrator (`bridge/engine_sidecar.py::run`, `:266-303`, a NEW dispatch branch beside the
frozen `_real_callables`, `:232-260`).** On a `bridge.governed-turn-submit.v1` frame the one-shot
subprocess drives the governed turn against the supervisor over `brops_socket`
(one-request/one-response), in this **exact order — `governed-turn-open` MUST precede the first
`governed-staging-open`** (§4.10(a0)→(a): staging-open requires the `UPLOADING`
`governed_turn_staging` row that ONLY `governed-turn-open` creates, so any staging-open sent first
is refused `no_staging_row`):
1. `brops.governed-turn-open.v1` (§4.10(a0)) submitting `challenge_doc_b64` — the **FIRST** governed
   message; the supervisor runs the open-time preliminary verify + publish and CAS-creates the
   `governed_turn_staging` row (`VERIFYING`→`UPLOADING`). Nothing may be staged before this returns
   `opened`.
2. then, for each of the three artifacts (system, history, generation_config),
   `brops.governed-staging-open.v1` (§4.10(a)) → `-staging-chunk.v1` ×N (§4.10(b), §2.4 bounds) →
   `-staging-final.v1` (§4.10(c)); each `declared_sha256` MUST equal the challenge's committed
   `*_sha256`, advancing the row to `INPUTS_READY`.
3. `brops.governed-evidence-request.v1` (§4.10(d)) to execute/finalize.
4. receive the **metadata-only** `brops.governed-turn-result.v1` (§4.10(e)) — envelope/attestation +
   `output_bytes`/`output_sha256` + a transport `output_stream_id`, **no inline output**. This
   submit subprocess pulls **NO** output: the §4.10(f) `brops.governed-turn-output-read.v1` loop is
   driven LATER by the **backend `governed_turn_execute` command's internal output-pull loop** (fresh
   one-shot sidecars — an internal backend helper, NOT a frontend-exposed command; §4.10(f), §6.1
   steps 13–14), never inside this submit subprocess.
5. re-frame the §4.10(e) summary into `bridge.governed-turn-result.v1` (§4.6) and emit **exactly
   one** such frame on `stdout`, then exit.

**Reply.** Success ⇒ the sidecar's single `stdout` frame is the **metadata-only**
`bridge.governed-turn-result.v1` (§4.6) — envelope/attestation + `output_bytes`/`output_sha256` +
a transport `output_stream_id`, **NO inline output and NO output pulled in this subprocess**. The
backend `governed_turn_execute` command verifies this frame at §6.1 step 14 / §7.1 and then drives the
§4.10(f) output pull **itself** via its **internal output-pull loop** (a fresh one-shot sidecar per
chunk — an internal backend helper, NOT a frontend-exposed command; §4.10(f), §6.1 steps 13–14); the
submit subprocess has already exited. **Local ingress/transport
failure is out-of-band (P1-5):** a spawn failure, socket error, `EXECUTION_TIMEOUT_MS` expiry, an
oversize/malformed sidecar reply, or an unexpected non-zero exit surfaces as a **Tauri command error
to the desktop-UI (a `Block`, NO result frame)** — the sidecar is a transport proxy and originates
**no** supervisor or signature verdict (§4.10(f), §7.1). **Tests:** submit round-trips to a `signed`
**metadata-only** bridge result (no output bytes in the submit reply); **exact call-order test — a
`governed-staging-open` issued before a successful `governed-turn-open` ⇒ `no_staging_row`, and
`governed-turn-open` MUST precede the first `governed-staging-open` (asserts the §4.10(a0)→(a)
ordering, and that turn-open creates the `UPLOADING` row staging-open requires);** the submit
subprocess emits its one metadata frame and exits **without** issuing any
`brops.governed-turn-output-read.v1` call (output-pull happens only via `governed_turn_execute`'s
internal loop); a frozen `bridge.task-request` fed to the governed command is
refused (missing `protocol` const); an oversize `system`/`history` ⇒ ingress error, no frame; a
sidecar-spawn failure ⇒ desktop Block, no result; the three staged `*_sha256` mismatching the
challenge digests ⇒ `handle_not_challenge` refusal relayed as a Block.

**Routing/rejection (LOCKED + tested):** each control-plane message
is dispatched by its `protocol` const; a governed handler refuses any v1 `protocol` value and
each v1 handler refuses any `brops.governed-*` value — no shared schema file, enum, or
required-key list.

### 4.10(h) Internal upstream-refusal transport — the NON-SUCCESS DIAGNOSTIC (P0-1, LOCKED)

**The gap this closes.** The §4.10(a0/a/b/c/d) supervisor↔sidecar sub-protocols and the §2.1
challenge-authority `create-pending`/`issue` channel each produce a **closed set of per-protocol
internal refusal reasons** (`peer_denied`, `noncanonical`, `sig_invalid`, `no_staging_row`,
`session_corrupt`, `handle_not_challenge`, `seq_mismatch`, `digest_mismatch`, `quota_turns`/
`quota_sessions`/`quota_bytes`/`quota_pending`, `field_invalid`, `pending_expired`, `key_unavailable`,
`challenge_expired`, `no_inputs_ready`, and every other literal in the routing table below). These are
**intentionally ABSENT** from the closed `GOVERNED_REFUSAL_REASONS` (§4.5) and remain a **disjoint
namespace, never merged into it**. The sidecar originates **no** governed verdict: it may neither mint
a `GOVERNED_REFUSAL_REASONS` reason nor emit a `signed` `bridge.governed-turn-result.v1`. Yet §5/§6.1
require every internal refusal to reach the desktop as exactly one durable Block. This subsection is
the single transport.

**Two carriers, ONE terminal-Block sink.** An internal refusal reaches the desktop by exactly one of:
- **Carrier 1 — sidecar NON-SUCCESS DIAGNOSTIC** for the **sidecar-driven** hops the one-shot submit
  subprocess runs over `brops_socket` (§4.10(g) orchestrator: `governed-turn-open`, `staging-open`,
  `staging-chunk`, `staging-final`, the pre-acceptance `evidence-request` gate). On a well-formed
  internal `refused` reply the sidecar emits ONE diagnostic frame and exits 0.
- **Carrier 2 — backend-direct authority reply** for the `challenge-authority-create-pending`/`issue`
  hops `governed_turn_execute` calls directly over the authority `AF_UNIX` channel (never through the
  sidecar); an explicit authority `refused` is consumed in-process and mapped to the same bounded
  reason format.

A **genuine governed verdict** — a `signed` `bridge.governed-turn-result.v1`, or a `refused` with a
`GOVERNED_REFUSAL_REASONS` literal, or a `brops.governed-turn-output-read-result.v1` `refused` — is
NOT an internal refusal: it is **relayed verbatim** (§4.5) and carried by neither carrier.

**The diagnostic frame — `bridge.governed-turn-diagnostic.v1`.** A **distinct top-level discriminator**
(the frozen `bridge.result` rejects it — no `protocol` key, `additionalProperties:false`; and
`bridge.governed-turn-result.v1` rejects it — requires `ok`/`receipt`/`error`, all absent). It carries
**transport/diagnostic data only, grants NO authority**, and can never satisfy the `signed` predicate
(which REQUIRES `envelope_jcs_b64` + `signature_b64` + `output_stream_id`, §4.10(e)):
```jsonc
// sidecar → desktop, stdout, exactly one object; additionalProperties:false; required all three:
{ "protocol": "bridge.governed-turn-diagnostic.v1",
  "stage": "governed-turn-open" | "staging-open" | "staging-chunk" | "staging-final" | "evidence-request",
  "upstream_reason": "<one literal from the per-stage set in the routing table>" }
```
- **Encoding:** compact UTF-8 JSON on stdout, strict-decoded (unknown-key + duplicate-key rejection),
  exactly the shape above; no `ok`/`receipt`/`error`/`envelope_jcs_b64`/`signature_b64`/`output_stream_id`.
- **`MAX_DIAGNOSTIC_BYTES = 256`** (a generated worst-case instance ≈121 B; CI asserts `len ≤ 256`).
- **Exit status:** the submit subprocess writes the diagnostic and **exits 0** (identical to the
  signed/refused paths — the verdict/diagnostic rides the payload, never the exit code);
  `governed_turn_execute` classifies by the top-level `protocol` discriminator, never by exit code.

**`governed_turn_execute` classification + terminal Block (P0-1, LOCKED).** After the one-shot submit
subprocess exits, `governed_turn_execute` reads stdout under the existing `MAX_STDOUT_BYTES = 9 MiB`
bound (`ai.rs:43,1394`) and classifies by the top-level `protocol`:
1. `bridge.governed-turn-result.v1` + `ok==true` + `receipt` bearing `envelope_jcs_b64` +
   `signature_b64` + non-null `output_stream_id` → **governed success**; proceed to the §4.10(f) pull +
   §6.1 step-14 verify (the ONLY path that may persist a message/signed receipt, after full verify).
2. `bridge.governed-turn-result.v1` + `ok==false` + `error.reason ∈ GOVERNED_REFUSAL_REASONS` →
   **governed refused verdict**; one terminal Block via `record_pre_verification_block`, bounded reason
   `governed_verdict_refused:{reason}`.
3. `bridge.governed-turn-diagnostic.v1`, `len ≤ 256`, exact 3-field shape, `stage` + `upstream_reason`
   in the closed sets → **internal refusal**; one terminal Block, bounded reason
   `governed_internal_refusal:{stage}:{upstream_reason}`.
4. **Anything else** (other/missing `protocol`, a frozen `bridge.result` fail frame, empty/unparseable
   stdout, an oversize/unknown-stage/unknown-reason/extra-key diagnostic, a non-zero exit, or a
   `GOVERNED_REFUSAL_REASONS` value under the wrong discriminator) → **pure transport failure**; one
   terminal Block, bounded reason `governed_transport_failure:{detail}`. A malformed/oversize
   diagnostic is thus treated exactly as a transport failure — it grants no authority.

**Exactly once:** every non-success path (2/3/4) calls `record_pre_verification_block(&conn,
&request_nonce, &bounded_reason, now_ms)` (`receipt_store.rs:175-208`) **exactly once**, in one
`BEGIN IMMEDIATE` tx: consume the one-time `request_nonce`, write **exactly one** durable `blocked`
attempt (reason ≤ `MAX_REASON_BYTES = 8192`, `receipt_store.rs:144`), emit `StreamEvent::Blocked{reason}`
(`commands.rs:964`). **No message, signed receipt, output, or acceptance row is persisted.** The three
bounded-reason prefixes — `governed_verdict_refused:` / `governed_internal_refusal:` /
`governed_transport_failure:` — are **disjoint and machine-greppable**, so a verdict, an internal
refusal, and a transport failure each produce ONE Block by **distinct, non-confusable** provenance, and
**none is a signed verdict** (a signed verdict never reaches `record_pre_verification_block`).

**Terminal vs. retryable (LOCKED — cross-ref §4.10(g) authority boundary + §2.1.1(f)).** An **explicit**
authority/supervisor `refused` (well-formed internal `refused` on any hop, Carrier 1 or 2) is
**TERMINAL and MUST NOT be retried**. Only an **ambiguous transport failure / lost reply** (socket
unavailable, a lost reply with no verdict, a transport-malformed frame) may use **bounded idempotent
retry**, and **only on the backend-direct authority hops** (§4.10(g)(a): repeat `create-pending` →
same `pending_challenge_id`; repeat `issue` → byte-identical `{payload,sig}`), bounded by
`MAX_AUTHORITY_ATTEMPTS = 3` (§2.1.1); exhaustion ⇒ the Carrier-2 terminal Block. Sidecar-driven hops
have **no** per-hop retry (the submit subprocess is one-shot).

**Complete routing table** (every literal internal reason appears in exactly one row):

| Originating protocol | Internal reason(s) | Terminal/retryable | Carrier | Desktop outcome |
|---|---|---|---|---|
| §2.1(A) create-pending | `peer_denied,malformed,field_invalid,timestamp_invalid,oversize,retry_conflict,quota_pending` | Terminal | 2 (authority reply, stage `challenge-authority-create-pending`) | 1 Block · `governed_internal_refusal:challenge-authority-create-pending:{r}` |
| §2.1 authority lost-reply/socket (no reason) | — (ambiguous) | Retryable (bounded, `MAX_AUTHORITY_ATTEMPTS`); exhaustion→Terminal | 2 (backend re-drive) | on exhaustion 1 Block · `governed_transport_failure:{detail}` |
| §2.1(B) issue | `peer_denied,no_pending_row,pending_expired,key_unavailable,malformed` | Terminal | 2 (stage `challenge-authority-issue`) | 1 Block · `governed_internal_refusal:challenge-authority-issue:{r}` |
| §4.10(a0) governed-turn-open | `peer_denied,doc_oversize,malformed,noncanonical,handle_mismatch,registry_unknown,key_invalid,sig_invalid,context_mismatch,challenge_expired,retry_conflict,quota_turns` | Terminal | 1 (stage `governed-turn-open`) | 1 Block · `governed_internal_refusal:governed-turn-open:{r}` |
| §4.10(a) staging-open | `peer_denied,no_staging_row,artifact_invalid,digest_mismatch,oversize,retry_conflict,quota_sessions,quota_bytes,session_corrupt,malformed` | Terminal | 1 (stage `staging-open`) | 1 Block · `governed_internal_refusal:staging-open:{r}` |
| §4.10(b) staging-chunk | `session_unknown,seq_mismatch,retry_conflict,oversize_chunk,oversize_frame,over_declared,nondeterministic_chunk,too_many_chunks,session_corrupt,malformed` | Terminal | 1 (stage `staging-chunk`) | 1 Block · `governed_internal_refusal:staging-chunk:{r}` |
| §4.10(c) staging-final | `session_unknown,seq_mismatch,len_mismatch,sha_mismatch,handle_not_challenge,publish_divergent,retry_conflict,session_corrupt,malformed` | Terminal | 1 (stage `staging-final`) | 1 Block · `governed_internal_refusal:staging-final:{r}` |
| §4.10(d) evidence-request pre-acceptance gate | `peer_denied,no_inputs_ready,session_corrupt,retry_conflict,malformed` | Terminal | 1 (stage `evidence-request`) | 1 Block · `governed_internal_refusal:evidence-request:{r}` |
| §4.10(e)/§4.5 signer/supervisor final governed verdict | (the closed `GOVERNED_REFUSAL_REASONS` union) | Terminal (authoritative) | governed verdict, relayed verbatim | 1 Block · `governed_verdict_refused:{reason}` |
| §4.10(f) output-read | `stream_unknown,stream_expired,stream_binding_mismatch,seq_out_of_range,malformed` | Terminal | governed verdict, relayed verbatim | pull cannot complete → 1 Block · `governed_output_read_refused:{reason}` |
| any desktop↔sidecar local transport failure (§6.1) | — (no verdict frame) | Terminal (one-shot) | neither carrier (out-of-band Tauri error) | 1 Block · `governed_transport_failure:{detail}` |

**§4.10(d) pre-acceptance reply (added).** Before a `governed_turn_acceptance` row exists, an
`evidence-request` gate failure returns `brops.governed-evidence-request-result.v1 {status:"refused",
reason: "peer_denied"|"no_inputs_ready"|"session_corrupt"|"retry_conflict"|"malformed"}` (`no_inputs_ready`
= no `INPUTS_READY` staging row); these five are a disjoint namespace, carried via the diagnostic
(stage `evidence-request`). Frame ≤ 4 KiB. Once a row exists, the acceptance/signer verdict is the
`brops.governed-turn-result.v1` tagged union (e) — `signed` or a `GOVERNED_REFUSAL_REASONS` `refused`.

**Tests (P0-1):** (1) for each Carrier-1 stage, inject each literal → exactly one diagnostic, exit 0,
no `envelope_jcs_b64`/`signature_b64`; (2) each authority literal → one `governed_internal_refusal:*`
Block, nonce consumed, no message/receipt, no sidecar diagnostic; (3) exactly one `blocked` row + zero
message/receipt/acceptance rows on every non-success path; (4) explicit `refused` never re-driven; only
authority lost-reply/socket retries (bounded) then terminal; (5) a run through an internal refusal, a
`GOVERNED_REFUSAL_REASONS` verdict, and a transport failure yields three Blocks with disjoint prefixes;
(6) a diagnostic fed to §7.1 is rejected before signature verify (no envelope/signature) — never a
signed verdict; (7) oversize/unknown-stage/unknown-reason/extra-key diagnostic → `governed_transport_failure:*`;
(8) replay on a consumed nonce ⇒ `Replay` Block; (9) static routing-completeness: every per-protocol
reply enum literal appears in exactly one routing row.

---

## 5. Durable supervisor acceptance — state machine + outbox (P0-2)

> ### ⚠️ §5 v2 — NORMATIVE AMENDMENT (independent audit 2026-08-06, **F-01 P0**)
>
> **The problem this amendment exists to fix.** §5 below specified this durable state machine
> correctly, and it was implemented in `apps/desktop/src-tauri/core/src/supervisor_ledger.rs` —
> but **nothing ever called it.** Every function except `create_schema` had only `#[cfg(test)]`
> callers. The live supervisor ran stateless: `accept_open` minted a lease from `uuid4()` and
> persisted nothing, `launch_gate` judged a lease the CALLER handed back, and `attest-run`
> accepted a `facts` object on the wire, shape-validated it, stamped `decision="completed"` and
> signed it. The broker uid — the one principal the four-uid key split exists to constrain —
> could therefore obtain a genuine Ed25519-signed `brops.governed-receipt-envelope.v1` for a run
> that never happened: no challenge, no lease, no launcher, no executor, no model.
>
> **The amendment.** The supervisor's authority is now the durable state it owns, and the wire
> protocol is shaped so no other source of evidence exists.
>
> **(a) Where the schema lives.** The DDL below is no longer inlined in either implementation.
> The single normative source is [`engine/runtime/supervisor_ledger.sql`](../../engine/runtime/supervisor_ledger.sql),
> loaded verbatim by the Python supervisor (`governed_supervisor_ledger.py`, the production
> writer) and compiled into `brops-core::supervisor_ledger` from a byte-identical mirror. The
> fail-closed CI gate `tools/check_ledger_ddl_parity.py` refuses any divergence, any missing
> copy, or the removal of a load-bearing constraint. **The SQL is the enforcement** — the
> `UNIQUE`s, the `state` CHECK, the transition trigger, the write-once completion PK, the floor
> PK — so neither language can weaken it alone.
>
> **(b) The acceptance row carries the request binding.** In addition to the columns below it
> persists `lease_id`, `lease_issued_at_ms`, `lease_expires_at_ms`, `receipt_id`,
> `supervisor_id`, `requested_at_ms`, `request_sha256`, `system_handle`, `history_handle` and
> `generation_config_handle` — all copied out of the **signature-verified** challenge payload or
> stamped from the supervisor's own clock. `receipt_id` is **minted per turn by the supervisor**
> and carries a `UNIQUE` index, because the §7.1(d) global-unique replay key cannot be a
> deployment constant (audit F-02).
>
> **(c) A new write-once completion table.** `governed_turn_completion` (PK
> `execution_attempt_id`, FK → acceptance) records the ONLY §4.9 values the supervisor cannot
> derive itself: `output_handle`, `containment_evidence_handle`, `record_handle`, `lease_handle`,
> `execution_receipt_handle`, `completed_at_ms` and the four `evidence_*` counters. The PK is the
> write-once gate: an identical retry is idempotent, any divergence is refused. Recording a
> completion also drives the evidence-head anti-rollback/anti-fork floor in the same
> transaction, so a stale or forked head refuses the whole completion.
>
> **(d) The §5 v2 wire.** Five ops walk ONE durable attempt through its lifecycle. Every request
> shape is EXHAUSTIVE — an unknown field is a hard error, never an ignored one:
>
> | op | request | effect |
> |---|---|---|
> | `accept-open` | `{challenge_doc}` | two-phase verify + **Phase C**: the challenge's signed `supervisor_id` must be THIS supervisor (else `supervisor_mismatch`) → CAS an acceptance row keyed on the supervisor's own `challenge_handle = sha256(JCS(payload))` → `LEASE_READY`. A replayed challenge returns the **ORIGINAL** lease; it never mints a second attempt. |
> | `launch-gate` | `{execution_attempt_id}` | the §5 step-8a budget gate against the lease window the **supervisor persisted** → `EXECUTION_STARTING`, or durably `EXPIRED` with the gate reason. The caller presents no lease and cannot choose the expiry it is judged against (also closes audit F-23). |
> | `execution-started` | `{execution_attempt_id, process_group_id, cgroup_id, execution_started_marker}` | `EXECUTION_STARTING → EXECUTING`. |
> | `complete-run` | `{execution_attempt_id, produced}` | write-once completion + evidence floor → `COMPLETED`. `produced` carries ONLY run-produced values; every id, nonce, identity and acceptance timestamp is rejected as an unknown field. |
> | `attest-run` | `{run_id, execution_attempt_id}` | build the §4.9 evidence from durable terminal state + supervisor config, stamp `decision="completed"`, sign. **No `facts` parameter exists.** |
>
> **(e) The identities the signer allowlists are supervisor-provisioned.** `executor_id`,
> `builder_id`, `policy_id`, `policy_version` and `policy_bundle_handle` move out of the broker's
> config into the supervisor's. `isolated_signer._check_identity` allowlists these values, so a
> broker that supplied them was choosing what it would be checked against — it simply copied them
> out of the world-readable deployment config. `supervisor_id` comes from the acceptance row, so
> a later config edit cannot retroactively rewrite what was accepted.
>
> **(f) The signer sees the attested bytes.** The broker no longer rebuilds the evidence object
> for `sign-result`; it **parses it from the exact `evidence_jcs` the supervisor signed**. The
> signer's re-hash and the final acceptance's `attestation_evidence_sha256` check are therefore
> over identical bytes by construction.
>
> **The property this establishes:** *a fabricated run has no acceptance row, so it has no
> completion, so there is no evidence for the supervisor to build and no signature to obtain.*
> `attest-run` on an unknown, unfinished, failed or mismatched run returns
> `no_terminal_run_state`.
>
> **What this amendment does NOT fix.** The containment/record/execution-receipt handles and the
> four `evidence_*` counters are still deployment-static config constants rather than
> measurements of the run (audit **F-02**); F-01 makes them supervisor-recorded and write-once,
> not derived. The request↔output binding (**F-08**), the TCB integrity floor (**F-10**) and the
> custody defects (**F-07/F-17/F-28**) are untouched. `platform_governed_execution_supported()`
> stays `false`; `main()` keeps `UpstreamBlockedExecutor`.

A database transaction **cannot** atomically include an external private-key signature and a
filesystem publish. Acceptance is therefore a **durable state machine with an outbox**, not a
single "issue-or-prepare" step.

**Acceptance ledger (supervisor-owned durable DB, `0700`):**
```sql
CREATE TABLE governed_turn_acceptance (
  install_id                     TEXT NOT NULL,
  request_nonce                  TEXT NOT NULL,
  challenge_handle               TEXT NOT NULL,   -- 64hex
  run_id                         TEXT NOT NULL,
  task_id                        TEXT NOT NULL,
  workspace_id                   TEXT NOT NULL,
  execution_attempt_id           TEXT NOT NULL,
  challenge_accepted_at_ms       INTEGER NOT NULL,
  challenge_registry_handle      TEXT NOT NULL,
  challenge_registry_hash        TEXT NOT NULL,
  challenge_registry_epoch       INTEGER NOT NULL,
  challenge_registry_root_key_id TEXT NOT NULL,
  lease_payload_sha256           TEXT NOT NULL,   -- sha256 of the EXACT canonical lease payload bytes
  lease_payload_bytes            BLOB NOT NULL,    -- the exact JCS(payload) to be signed
  lease_handle                   TEXT,             -- 64hex, set at LEASE_READY
  state                          TEXT NOT NULL CHECK (state IN (   -- closed enum enforced by the DB (P1-4)
      'ACCEPTED_PREPARED','LEASE_READY','EXECUTION_STARTING','EXECUTING',
      'COMPLETED','BLOCKED','FAILED','EXPIRED','RECOVERY_REQUIRED')),  -- UNSEEN = absent/no-row, never stored
  execution_started_marker       TEXT,
  cgroup_id                      TEXT,
  process_group_id               TEXT,
  terminal_record_handle         TEXT,
  failure_reason                 TEXT,
  created_at_ms                  INTEGER NOT NULL,
  updated_at_ms                  INTEGER NOT NULL,
  UNIQUE (install_id, request_nonce),
  UNIQUE (challenge_handle),
  UNIQUE (execution_attempt_id)
);
```
The three `UNIQUE` constraints (not a single composite "at least" key) mean: a reused
`request_nonce` collides on `(install_id, request_nonce)`; a reused `challenge_handle`
collides on `challenge_handle`; one challenge maps to **exactly one** `execution_attempt_id`.
A retry that presents a nonce/challenge pairing different from the stored row (different
`run_id`/`task_id`/`workspace_id`/`challenge_handle`) is a **conflict** and is refused. Any
new attempt requires a **new signed challenge + new nonce**.

**State enum (full lifecycle across the two tables) — CLOSED + DETERMINISTIC (P1-4):**
pre-accept in `governed_turn_staging` (§2.4): `VERIFYING` → `UPLOADING` → `INPUTS_READY`
(no `execution_attempt_id`, **no execution right**); then in `governed_turn_acceptance` the exact
closed set (DB `CHECK` above; `UNSEEN` = **absent/no-row**, never stored, so the 9 stored states are)
`ACCEPTED_PREPARED` → `LEASE_READY` → `EXECUTION_STARTING` → `EXECUTING` → `COMPLETED`; terminal
`BLOCKED`, `FAILED`, `EXPIRED`, `RECOVERY_REQUIRED`.

**Non-terminal transition triggers (LOCKED — every edge names its trigger):** `ACCEPTED_PREPARED →
LEASE_READY` = the signed governed-turn lease is published + re-hashed + `validate_governed_turn_lease`
passes (§5 step 4/6); `LEASE_READY → EXECUTION_STARTING` = the §5 step-8a lease-expiry launch gate passes
and the launcher is spawned (the last auto-launchable edge); **`EXECUTION_STARTING → EXECUTING` = the
launcher confirms the child process is running AND its process metadata (`process_group_id`/`cgroup_id`)
is durably persisted in the acceptance row** — the single event that flips STARTING→EXECUTING (before
it, a crash is `RECOVERY_REQUIRED`; there is never an implicit or dual-destination edge); `EXECUTING →
COMPLETED` = the terminal record exists + re-verifies; `EXECUTING → FAILED` = authoritative evidence the
attempt produced no acceptable governed result.

**Deterministic state-purpose matrix (P1-4, LOCKED — every condition maps to exactly ONE state; no
slash/or alternatives):**
- **`EXPIRED`** (terminal; predecessor `LEASE_READY` only): the ONLY destination of a pre-launch
  lease-expiry gate failure (§5 step 8a / §6.1 step 5) — `now_ms > lease_expires_at_ms`, `now_ms <
  lease_issued_at_ms`, or remaining `< MIN_LAUNCH_REMAINING_MS`. No launch occurs.
- **`RECOVERY_REQUIRED`** (terminal, operator-inspect-only; predecessors `EXECUTION_STARTING`/
  `EXECUTING`): the ONLY destination of an **ambiguous post-launch crash** where execution may have
  occurred but complete terminal proof is unavailable. Never auto-relaunch.
- **`BLOCKED`** (terminal; predecessors `ACCEPTED_PREPARED`/`LEASE_READY` only): a
  **deterministic post-acceptance pre-execution** security/policy/identity/schema/binding refusal —
  never a crash-cut and never lease-expiry. **`UNSEEN` is NOT a predecessor (P1-5):** `UNSEEN` =
  absent/no-row is not a persisted state, so it cannot transition to a stored `BLOCKED` row. A
  **pre-acceptance** (pre-row) deterministic refusal — anything the supervisor rejects during
  `brops.governed-turn-open.v1` / staging / the `evidence-request` gate (§4.10(a0/a/b/c/d)), before a
  `governed_turn_acceptance` row exists — creates **NO acceptance row**; it returns that path's own
  internal protocol reason (`peer_denied`/`noncanonical`/`sig_invalid`/`challenge_expired`/`no_staging_row`/
  `no_inputs_ready`/`session_corrupt`/… ), which the sidecar carries to the desktop as the §4.10(h)
  NON-SUCCESS DIAGNOSTIC ⇒ one durable `governed_internal_refusal:*` Block via
  `record_pre_verification_block` — **not** a `BLOCKED` acceptance-ledger row and **not** a
  `GOVERNED_REFUSAL_REASONS` verdict. `BLOCKED` is reserved
  for a refusal decided **after** the row is `ACCEPTED_PREPARED`/`LEASE_READY`.
- **`FAILED`** (terminal; predecessor `EXECUTING`): a known completed operational failure with
  authoritative evidence the attempt produced NO acceptable governed result.
- **`COMPLETED`** (terminal; predecessor `EXECUTING`): the exact terminal record exists + re-verifies;
  idempotent retry re-serves the same record.

There is **no circular dependency**: staging is gated by the *verified signed challenge* (§2.4), and the
acceptance row is created only **after** the staging row reaches `INPUTS_READY` — the two never
depend on each other.

**Outbox sequence (exact):**
1. **Pre-accept ingress (§2.4) — OPEN-TIME PRELIMINARY only:** `brops.governed-turn-open.v1`
   (§4.10(a0)) delivers the exact signed challenge document; the supervisor runs the **open-time
   preliminary** verification (canonicality gate; root sig; challenge sig; key validity **as of
   `challenge_issued_at_ms`**; context) — NOT the final §7 as-of-acceptance predicate — publishes
   the exact challenge bytes, and creates the `governed_turn_staging` row (`VERIFYING`→`UPLOADING`);
   the sidecar uploads only system/history/generation_config; the **supervisor self-resolves +
   publishes + binds** the policy bundle (§2.4 policy note). When all three inputs are published +
   re-hash to the challenge digests, the staging row is `INPUTS_READY`. **No acceptance/clock/
   nonce-consume happens here.**
2. Only once the staging row is `INPUTS_READY`, read the supervisor clock **exactly once** →
   `challenge_accepted_at_ms`.
3. **ACCEPTANCE-TIME AUTHORITATIVE verification (P0-3):** **re-resolve the CURRENT accepted
   root-signed registry snapshot** (a fresh `load_trusted_keys`-style reload + floor — do NOT reuse
   the open-time snapshot), re-verify the challenge `sig` under **that** snapshot, and apply the
   **full §7 key-validity predicate as of `challenge_accepted_at_ms`** (`valid_from_ms ≤
   challenge_accepted_at_ms ≤ valid_to_ms`, `revoked_at_ms IS NULL OR revoked_at_ms >
   challenge_accepted_at_ms`, `challenge_issued_at_ms ≤ challenge_accepted_at_ms ≤
   challenge_expires_at_ms`, `requested_at_ms ≤ challenge_accepted_at_ms`). A key revoked/removed or
   a registry rotated between open and acceptance is refused here (`challenge_invalidated`). Bind
   this exact acceptance-time `challenge_registry_handle`/`_hash`/`_epoch`/`_root_key_id` into the
   acceptance row → lease → record → attestation → envelope.
4. **One DB transaction:** CAS insert `absent → ACCEPTED_PREPARED` into `governed_turn_acceptance`
   (the three UNIQUE constraints enforce the CAS); reserve `execution_attempt_id`; persist every
   authoritative binding (challenge/registry/context/policy/`challenge_accepted_at_ms`); compute
   and persist the **exact canonical lease payload bytes** (`lease_payload_bytes` +
   `lease_payload_sha256`).
5. **Commit.**
6. **Idempotently sign + atomically publish** that exact persisted lease document
   (create-if-absent under `lease_handle = SHA256(JCS({payload,signature}))`; an existing
   identical handle is idempotent success).
7. CAS `ACCEPTED_PREPARED → LEASE_READY` **only after** the lease document exists in the
   store and **re-hashes + re-verifies** (`validate_governed_turn_lease`), recording
   `lease_handle`.
8. **Execution is forbidden before `LEASE_READY`.**
8a. **Lease-expiry launch gate (P0-4/P1-5, LOCKED) — checked immediately before the CAS in step 9,
    on every first launch AND every recovery.** Read the **wall clock once** → `now_ms` and
    require ALL: (i) not-pre-valid / not-expired `lease_issued_at_ms ≤ now_ms ≤
    lease_expires_at_ms`; (ii) sufficient remaining budget `lease_expires_at_ms − now_ms ≥
    MIN_LAUNCH_REMAINING_MS = 180000`, where `180000 = EXECUTION_TIMEOUT_MS(120000) + grace(5000) +
    teardown(10000) + post_exec_signing_reserve(40000) = 175000` worst-case critical path **+ 5000
    launch/scheduling slack** (the gate reads `now_ms` before the CAS + launcher fsync-marker +
    setuid + exec + cgroup setup + model-endpoint connect, whose latency `L` must not push
    `completed_at_ms` past `lease_expires_at_ms`). This guarantees `finished_at_ms` **and**
    `completed_at_ms` land inside the lease window. Exact-`175000` remaining **refuses**;
    exact-`180000` **proceeds**. If either check fails → CAS `LEASE_READY → EXPIRED` (P1-4 — a
    lease-expiry gate failure is DETERMINISTICALLY `EXPIRED`, never `BLOCKED`);
    **do NOT launch**; a new execution requires a newly signed challenge + new `request_nonce` + new
    `execution_attempt_id` (no reuse). The gate uses the **wall clock** (it compares signed `_ms`
    fields); the in-execution timeout then uses the **monotonic** clock (§4.7).
9. Persist `LEASE_READY → EXECUTION_STARTING` **before** launching the recorder/executor (only
   after the step-8a gate passes).
   Optionally, the privileged launcher writes + `fsync`s an **immutable launch-start marker**
   (`execution_started_marker`: attempt id + launch nonce + cgroup binding) before `exec`, for
   forensics — **but that marker MUST NOT authorize any re-execution.**
10. **NO AUTO-RELAUNCH AFTER `EXECUTION_STARTING` (P0-1, LOCKED).** `LEASE_READY` is the **last
    state from which an automatic first launch is permitted**. The launch is preceded by a CAS
    `LEASE_READY → EXECUTION_STARTING`; **once `EXECUTION_STARTING` is durable the attempt is
    NEVER automatically relaunched** — the child may already have started, issued a remote
    model request, or produced external effects and then exited before `EXECUTING`/process
    metadata became durable, so "no live child + no output" does **not** prove non-execution.
    A restart finding `EXECUTION_STARTING` or `EXECUTING` without **complete terminal proof**
    moves to `RECOVERY_REQUIRED` (fail-closed). An owner/operator may **inspect**
    evidence but MUST NOT reuse the same `challenge_handle` / `request_nonce` /
    `execution_attempt_id` for another execution; **a new execution requires a newly signed
    challenge + new `request_nonce` + new attempt.**
11. A `COMPLETED` retry returns **only** the same attempt's independently re-verified
    terminal record/result (idempotent).
12. A failed or conflicting retry **never** creates a new attempt.

**Crash recovery at every cut point** (each maps to a durable state; auto-launch is possible
ONLY from `LEASE_READY`):
crash in `VERIFYING`/`UPLOADING`/`INPUTS_READY` (pre-accept staging) → the staging row alone
**never** authorizes execution; a sweep unlinks orphan `.tmp-*.part` and deletes an expired/
abandoned staging row **WITHOUT consuming the challenge nonce** (the desktop may re-issue against
the same signed challenge until `challenge_expires_at_ms`); before acceptance commit → no
acceptance row persisted, clean retry; after commit before signature →
`ACCEPTED_PREPARED`, re-sign from `lease_payload_bytes` (deterministic); after signature
before publish → publish is create-if-absent, idempotent; after publish before `LEASE_READY`
→ re-hash/re-verify then advance; **`LEASE_READY` (the only auto-launchable state) → the
supervisor re-runs the step-8a lease-expiry gate on the current wall clock and, ONLY if it
passes, CASes to `EXECUTION_STARTING` then launches once — an expired or
insufficient-remaining-budget `LEASE_READY` found on restart moves to `EXPIRED` and is
NEVER auto-launched (P0-4);** **after `EXECUTION_STARTING`
commit but before the launcher call → `RECOVERY_REQUIRED`, never relaunch;** **crash
inside the launcher before `exec` → `RECOVERY_REQUIRED`;** **crash immediately after
`exec` / child exits before `EXECUTING` persistence / a remote model call occurred but no
output/receipt exists → `RECOVERY_REQUIRED`, never relaunch;** after receipt/evidence
before terminal record → re-drive record signing from the already-published verified artifacts
(idempotent create-if-absent, no new execution); after terminal record before ledger
`COMPLETED` → set `COMPLETED` from the existing verified record.

**Negative tests (normative):** concurrent duplicate submissions (exactly one
`ACCEPTED_PREPARED` + one attempt; losers get the idempotent result, never a 2nd execution);
same-nonce/different-challenge (refused); same-challenge/different-nonce (refused);
conflicting `run_id`/`task_id` on retry (refused); and — proving **zero automatic second
execution** — crash **after `EXECUTION_STARTING` commit before the launcher call**, crash
**inside the launcher before `exec`**, crash **immediately after `exec`**, **child exits
before `EXECUTING` persistence**, and **a remote model call occurred but no output/receipt
exists**: each must land in `RECOVERY_REQUIRED` with no relaunch. **Lease-expiry gate
(P0-4):** expired-`LEASE_READY` recovery (`now_ms > lease_expires_at_ms` on restart →
`EXPIRED`, zero launch); exact-expiry boundary (`now_ms == lease_expires_at_ms` passes
(i) but must fail remaining-budget (ii); `now_ms == lease_expires_at_ms + 1` → expired);
insufficient-remaining-budget at the true threshold boundary (`lease_expires_at_ms − now_ms ==
179999` → blocked; `== 180000` → proceeds); and a wall-clock **NTP step** between `LEASE_READY`
persist and the gate re-evaluates on
the stepped clock and blocks if expired (the monotonic in-execution timeout must not smuggle an
expired lease past the wall-clock gate).

**Relationship to the desktop nonce (both hold):** the desktop's `request_nonce`
compare-and-consume in `verify_and_record_receipt` still governs final **receipt**
acceptance (whole-turn replay + `receipt_id` uniqueness, §7); the supervisor ledger above
governs **execution** replay. Neither substitutes for the other.

---

## 6. Atomic publish order (who signs what they published)

1. **Supervisor publishes into `store/sup/`, before execution:** the signed challenge document
   (`challenge_handle`), the accepted registry snapshot (`challenge_registry_handle`) under
   the crash-consistent publish→floor sequence (§7 anti-rollback), the **three sidecar-uploaded
   input artifacts** (system/history/generation_config, which arrive **only** via the §2.4
   authenticated pre-accept bounded ingress — each must exist + re-hash to the challenge's
   committed `*_sha256` before this point), the **supervisor-self-resolved `policy_bundle`**
   (published by the supervisor from its own authoritative policy registry/config — never a
   sidecar upload, §2.4 policy note — binding `policy_bundle_sha256`), and the governed-turn
   lease (`lease_handle`, §5 step 6). All are content-addressed create-if-absent
   (temp→fsync→verify size+sha256→exclusive publish).
2. **Recorder publishes what IT owns + signs over those handles:** the exact `output` bytes
   (`output_handle`), the containment artifact (`containment_evidence_sha256`), and the exact
   signed **`brops.governed-turn-execution-receipt.v1`** document (published content-addressed
   create-if-absent → `execution_receipt_handle`), plus the containment-confirmed evidence
   event + head (evidence-recorder key).
3. **Supervisor verifies the recorder chain by handle** (fetch the receipt by
   `execution_receipt_handle`, re-hash, `verify_governed_turn_receipt`; `load_head`+
   `validate_chain`; containment cross-bind) and **signs the terminal record**
   (`governed-turn-recorder` key) binding every verified handle/id/hash — including
   `lease_handle` + `execution_receipt_handle` — + the ledger's `challenge_accepted_at_ms`;
   never a caller input. The `execution_receipt_handle` (and `lease_handle`) MUST already
   exist + re-hash before the record is signed.
4. **Atomic terminal write:** temp→fsync→`os.link`/`O_CREAT|O_EXCL` into
   `<run_id>__<execution_attempt_id>.json`; `EEXIST` ⇒ byte-compare (identical=idempotent,
   differ=refuse); fsync dir. A crash before this leaves no record ⇒ Block; after ⇒ a
   complete re-verifiable record and ledger `COMPLETED`.

Store ACL (§2.3): supervisor writes `store/sup/` (challenge, registry, inputs, lease,
record), recorder writes `store/rec/` (output, containment, receipt); the isolated signer
reads both (group `brops-store`, read-only); executor/sidecar/desktop have no store or key
access.

### 6.1 The COMPLETE end-to-end order (LOCKED, P1-5) — through the isolated signer + desktop

No output renders before step 14 commits.
0. **Broker-service governed orchestration (P0-1, §4.10(g)):** the renderer's **thin Tauri proxy** forwards
   the closed `{conversation_id, agent?}` command to the **broker service** over the renderer↔broker IPC
   (§4.10(g)); the **broker** runs **`governed_turn_execute(conversation_id, agent)`** — the ONLY renderer
   inputs (mirroring `stream_reply(conversation_id, agent, on_event)`); `system`/`history`/`workspace_id`/
   `install_id`/`generation_config`/`run_id`/`task_id` are broker-resolved or -generated, never renderer
   inputs. In **one broker-service execution owning a single backend orchestration object
   `GovernedTurnExecutionV1B{conversation_id, run_id, task_id, prepared}`** it: resolve `system`/`history`
   from the message store keyed by `conversation_id` + the `GOVERNED_*` constants → `prepare_governed_turn_v1b`
   once → `receipt_challenges` pre-store (`issue_challenge(&conn, &conversation_id, …)`) → the §2.1
   authority **create-pending (with the backend `run_id`) + issue** calls (obtaining the signed challenge
   document **in the backend**, never via the webview) → the **internal**
   `governed_turn_submit_prepared(execution: &GovernedTurnExecutionV1B, challenge_document: &ChallengeDocument)`
   helper (takes the WHOLE orchestration object — `PreparedGovernedTurnV1B` alone does not carry `task_id`,
   P0-1(A)), which — after asserting `submit.task_id == execution.task_id == challenge_document.payload.task_id`,
   `challenge_document.payload.run_id == execution.run_id`, and
   `SHA256(JCS(execution.prepared.generation_config)) == challenge_document.payload.generation_config_sha256`
   (else terminal Block) — spawns the one-shot governed sidecar (as `ai.rs::governed_engine`) and writes a
   single **`bridge.governed-turn-submit.v1`** frame carrying `{task_id, challenge_doc_b64, system, history,
   generation_config}` **derived from `execution` (`task_id` from `execution.task_id`, the rest from
   `execution.prepared`)** (no frontend re-serialize). The sidecar derives the three canonical input-byte
   blobs via the governed-family formulas (system=raw UTF-8, history=JCS, generation_config=JCS of the closed
   config object — §4.10(g)) and becomes the originator of steps 1–2. A post-pre-store authority-channel
   failure follows the §4.10(g) Authority-channel failure boundary (bounded idempotent retry with the same
   live `execution` OR terminal Block, P1-1); a local desktop↔sidecar
   spawn/socket/timeout/oversize-reply/unexpected-exit failure here is a **terminal durable Block**
   (`governed_turn_execute` → `record_pre_verification_block`: consume the nonce + write a `blocked`
   record, `StreamEvent::Blocked{reason}`; NOT retryable — P1-1); nothing downstream exists "by assumption".
1. **Challenge open + OPEN-TIME PRELIMINARY verify + publish (P0-2/P0-3):** the sidecar sends
   **`brops.governed-turn-open.v1`** (§4.10(a0)) carrying the **exact signed challenge document
   bytes** (`challenge_doc_b64`). The supervisor strict-decodes, applies the **canonicality gate**
   (`decoded == canonical_bytes({payload,sig})` else `noncanonical`), computes `challenge_handle =
   SHA256(decoded_document_bytes)`, resolves the current accepted root-signed challenge-key registry
   **from its own state** (§4.2 root pin + floor), runs the **open-time preliminary** predicate (key
   validity **as of `challenge_issued_at_ms`**, NOT the as-of-acceptance §7 predicate) +
   `sig`/context, **atomically publishes the exact `decoded_document_bytes` into `store/sup/`**, and
   CAS-creates the `governed_turn_staging` row `VERIFYING→UPLOADING`. **No clock read, no nonce
   consume** here — this only admits the turn to upload; the binding authority is the acceptance-time
   re-verification (step 3). (The supervisor now *possesses* the exact challenge bytes.)
2. **Bounded input staging** (§2.4): `governed-staging-open/-chunk/-final` publish the three
   sidecar-uploaded inputs (each `== the challenge's committed *_sha256`); the supervisor
   self-resolves+publishes+binds `policy_bundle`; the row advances to `INPUTS_READY`.
3. **Acceptance ledger / outbox** (§5): on the execute trigger (§4.10(d)), read the clock once →
   `challenge_accepted_at_ms`; **CAS insert `absent → ACCEPTED_PREPARED`** (create-if-absent — `UNSEEN`
   = no-row is not a stored predecessor, P1-5); reserve `execution_attempt_id`;
   persist bindings + exact lease payload bytes; commit.
4. **Lease publication + `LEASE_READY`**: idempotently sign + publish the governed-turn lease
   (`lease_handle`, `lease_issued_at_ms == challenge_accepted_at_ms`, `lease_expires_at_ms =
   +LEASE_DURATION_MS`); CAS to `LEASE_READY` only after it re-hashes + `validate_governed_turn_lease`.
5. **Lease-expiry gate + one-time recorder/executor launch (P0-4/P1-5):** run the §5 step-8a gate
   (read `now_ms`; require the lease valid + `lease_expires_at_ms − now_ms ≥ MIN_LAUNCH_REMAINING_MS
   = 180000`), else `EXPIRED`; only if it passes, CAS `LEASE_READY → EXECUTION_STARTING`
   (never auto-relaunch after, §5 P0-1); the launcher enforces the FD/executable contract (§4.7).
6. **Output + containment publication** by the recorder (`output_handle`,
   `containment_evidence_sha256`).
7. **Governed execution receipt + evidence/head publication** by the recorder
   (`execution_receipt_handle`, evidence-recorder key).
8. **Supervisor verification** of the recorder chain by handle.
9. **Terminal governed-turn record publication** (`governed-turn-recorder` key), binding
   `lease_handle` + `execution_receipt_handle` + all §4.8 fields (atomic create-if-absent).
10. **Supervisor constructs the exact attested `brops.governed-sign-request.v1`** (§4.4) and
    signs it with the supervisor attestation key.
11. **Isolated signer invokes `LiveRunStateProvider`** (§7) — the ONLY deep protected-store
    verifier — to verify the terminal chain (record + lease-by-handle + receipt-by-handle +
    challenge + registry + containment + evidence head, incl. the lease-time invariants (P0-4)
    and the **signer-owned durable head-floor CAS `governed_evidence_head_floor`**, committed
    before the envelope is minted, §7 P1-7). The desktop never does this (no store access).
12. **Isolated signer builds + signs the `brops.governed-receipt-envelope.v1`** (§4.9,
    isolated-signer key) binding record/lease/receipt handles + nonce/attempt + head +
    attestation digest + `output_sha256`/`output_bytes` (the output authority), and returns
    **`brops.governed-sign-result.v1`** (§4.5) — `signed` (envelope + signature + attestation
    record) or `refused`.
13. **Supervisor→sidecar `brops.governed-turn-result.v1`** (§4.10(e)) — a metadata-only summary
    (envelope/attestation + `output_bytes`/`output_sha256` + a transport `output_stream_id`, NO
    inline output); the sidecar re-frames it as **`bridge.governed-turn-result.v1`** (§4.6,
    top-level `protocol` discriminator) — transport-only. The desktop then pulls the output
    **through the sidecar** via idempotent **`brops.governed-turn-output-read.v1`** reads
    (§4.10(f)) and reassembles the bytes; the signed envelope's `output_sha256`/`output_bytes`
    (not the transport `output_stream_id`) is the authority.
14. **Broker final acceptance (P0-3 ordering — inside the broker service, §0 role #2):** FIRST, **outside** any DB transaction, obtain
    the output bytes by driving the §4.10(f) pull loop (reassemble into a bounded ≤ 8 MiB
    buffer) and verify the envelope signature + attestation, then assert `len(bytes) ==
    envelope.output_bytes` **and** `SHA256(bytes) == envelope.output_sha256` (raw bytes, **no
    normalization before the check**), keeping the verified immutable bytes. THEN open one
    `BEGIN IMMEDIATE` tx (NO store access, NO network I/O inside the lock): **equality-check**
    every bridge/sign-result echo against the verified envelope → strict-UTF8 decode for display
    only (invalid UTF-8 ⇒ Block) → consume the one-time `request_nonce` (`receipt_challenges`) →
    assert `receipt_id` global uniqueness (`receipt_ids_seen`) → check receipt freshness (`_ms`)
    → persist. A stale/rolled-back evidence head was already refused by the signer's durable
    head-floor (step 11, §7 P1-7). Only on commit does the broker emit the committed UI-safe result to the renderer proxy to render.

**Out-of-band transport-failure contract (P1-1/P1-5, LOCKED — covers the desktop↔sidecar steps 0/13/14;
the post-pre-store authority `create-pending`/`issue` hops have their own equally-durable boundary at
§4.10(g) "Authority-channel failure boundary", P1-1).** The
desktop↔sidecar hops (step 0 submit, step 13/14 output pull) run over one-shot Tauri subprocesses
and an `AF_UNIX` socket that can fail *without* producing any governed reply frame. Distinct from a
supervisor **verdict** (a `refused` reason from `GOVERNED_REFUSAL_REASONS`, which is authoritative
and relayed verbatim), a **local transport failure** — sidecar spawn failure, sidecar unexpected
exit, the **supervisor `AF_UNIX` socket unavailable**, a sidecar↔supervisor connect/read error,
`EXECUTION_TIMEOUT_MS` expiry, a reply that is oversize (> `MAX_STDOUT_BYTES = 9 MiB`) or
malformed/unparseable, or an invalid supervisor `protocol`/result — is **NOT** a governed reason: it
is a **TERMINAL DURABLE BLOCK (P1-1, LOCKED — matching the merged `stream_reply` transport-failure
arm, `commands.rs:891-905`).** `governed_turn_execute` catches the error inside its own backend
execution and calls **`record_pre_verification_block(&conn, &request_nonce, &bounded_reason, now_ms)`**
(`receipt_store.rs:175-208`), which in ONE immediate tx **consumes the one-time `request_nonce`**
(`receipt_challenges.consumed_at`) **and writes a durable `blocked` evidence attempt** carrying the
real bounded reason (NO message row, NO signed receipt). NO output is rendered and NO partial output
persisted; the desktop-UI is notified via `StreamEvent::Blocked{reason}` (the durable reason == the UI
reason, `bounded_reason` `receipt_store.rs:151-166`). **The challenge/nonce can NEVER be retried** — a
later receipt bearing that nonce finds `consumed_at != NULL` ⇒ `NonceState::Replay` ⇒ Block
(`receipt_store.rs:262-264`); there is **no** durable in-memory prepared object / challenge document /
pending id to resume from once the command returns, so the fail-closed contract is terminal, not
retryable (the alternative — a durable orchestration journal with resume — is explicitly out of scope;
3b-1B matches the merged terminal-Block model). The sidecar **never fabricates** a `signed` result or a
refusal reason to paper over a transport failure — it originates no supervisor/signature verdict
(§4.5, §4.10(f)). Because the signed envelope's `output_sha256`/`output_bytes` is the sole output
authority, a truncated/dropped/reordered pull can never be mistaken for a complete output: the
whole-output digest fails ⇒ Block. **Tests:** submit-hop spawn failure ⇒ terminal Block (nonce
consumed + `blocked` record, no message); pull-hop socket drop mid-stream ⇒ digest-mismatch terminal
Block; oversize sidecar reply ⇒ Block; timeout ⇒ Block; a genuine supervisor `refused` ⇒ relayed
reason Block (distinct path); **each consumes the nonce + writes exactly one durable `blocked` attempt
and persists no signed receipt / no message; a retry of the same consumed nonce ⇒ `Replay` Block.**

---

## 7. Verification — `LiveRunStateProvider` (runs INSIDE the isolated signer; all cross-bindings)

**`LiveRunStateProvider` is executed by the isolated signer** (which has `brops-store`
read access, §2.3), NOT by the desktop. `verify_artifact(record,
"brops.governed-turn-record.v1")` first (a forged/edited record fails here — no unsigned JSON
is authority), then require, all fail-closed:

- **Lease (fetch by handle):** fetch the exact signed lease document by the record's
  **`lease_handle`**, **re-hash the exact document bytes** (`== lease_handle`), verify the
  issuer signature, then `validate_governed_turn_lease` (§4.3, NOT the base validator); the
  record's `lease_id`/`lease_nonce`(==lease `nonce`)/`challenge_accepted_at_ms` +
  challenge/registry bindings equal the lease's; `allowed_capabilities ==
  ["INVOKE_GOVERNED_MODEL"]`, `max_tool_calls == 0`.
- **Model-identity binding (P0-2 LOCKED — formula recomputation, NO mutable lookup):** the isolated
  signer **independently recomputes** the identity from the fetched lease's own signed bytes and
  requires, all fail-closed: (1) `lease.model_profile_id` matches `^cfg-sha256:[0-9a-f]{64}$`;
  (2) `lease.model_profile_id == "cfg-sha256:" + lease.generation_config_sha256` (the deterministic
  formula, recomputed here — **not** re-derived from any registry or allowlist, neither of which the
  signer reads); (3) `lease.generation_config_sha256 == challenge.generation_config_sha256` (the
  challenge fetched + re-hashed by `challenge_handle` above); (4)
  `challenge.generation_config_sha256 == the staged/executed config's hash` (already re-hashed from the
  exact stored `generation_config` bytes by handle). So the signed lease's declared model profile is
  provably the one derived from the exact `generation_config` the executor read; a lease claiming any
  `model_profile_id ≠ "cfg-sha256:"+generation_config_sha256`, or a `generation_config_sha256 ≠` the
  challenge's, is refused **before** the envelope is minted (per §6.1, before the desktop accepts; a
  mismatch never reaches launch). **Historical stability (P0-2):** every input is a signed field (lease
  payload + terminal record §4.8, both carrying `generation_config_sha256`) and the derivation is a
  pure function of those bytes; the signer consults **no** `GOVERNED_EXECUTION_ALLOWLIST` and **no**
  registry, so a change to the supervisor's allowlist / resolver defaults / overrides **after** a record
  is signed cannot invalidate, fork, or reinterpret that record's identity — it re-derives identically
  forever. (Tests: lease `model_profile_id ≠ "cfg-sha256:"+generation_config_sha256` → refuse; lease
  `generation_config_sha256 ≠` challenge's → refuse; a config whose hash ∉ allowlist ⇒
  `model_profile_unknown` at acceptance, no lease, never reaching §7; an allowlist mutated after
  execution ⇒ the historical record still re-derives + verifies identically — §9 whole-chain test.)
- **Lease-time invariants (P0-4/P1-5, all fail-closed):** on the fetched lease, `lease_issued_at_ms
  == challenge_accepted_at_ms` and `lease_expires_at_ms − lease_issued_at_ms == LEASE_DURATION_MS
  (210000)`; and the **complete** execution time-chain must fall **inside** the lease window:
  `lease_issued_at_ms ≤ started_at_ms ≤ finished_at_ms ≤ completed_at_ms ≤ lease_expires_at_ms`
  (P1-5 — `completed_at_ms ≤ lease_expires_at_ms` is the durable, verify-time guarantee that the
  launch gate alone cannot provide since it is never re-checked after launch; `completed_at_ms` is
  the §4.8 terminal-record field, supervisor-stamped at record publication). A receipt/record
  produced under an expired lease (any inequality violated) is refused here — the isolated signer
  will not mint an envelope for it. (Tests: started-before-lease, finished-after-lease,
  `completed < finished`, **`completed_at_ms > lease_expires_at_ms` with `finished` in-window** →
  refuse, a wall-clock NTP step during execution that stamps `completed` past `lease_expires` →
  refuse, duration/equality mismatch — each refuses; boundary `completed == lease_expires_at_ms`
  accepts.)
- **Challenge (fetch by handle + re-hash, P0-3):** fetch the exact signed challenge document by
  `challenge_handle`, **re-hash the exact stored bytes** (`SHA256(bytes) == challenge_handle`, and
  `bytes == canonical_bytes({payload,sig})` — closing the canonicality gap, matching the registry
  step below), verify `sig` under the key resolved from the bound **acceptance-time** registry
  snapshot; recompute `request_sha256`; the challenge's identities/`*_sha256`/`requested_at_ms`
  equal the record's. The challenge does **not** contain `challenge_accepted_at_ms`. (This §7
  predicate is the **acceptance-time authority** — evaluated as-of `challenge_accepted_at_ms`; the
  §4.10(a0) open-time check is preliminary only, as-of `challenge_issued_at_ms`.)
- **Registry snapshot:** fetch the exact signed document by `challenge_registry_handle`,
  re-hash the full document (`== challenge_registry_handle`), verify `root_sig` over
  `JCS(payload)` under the pinned `challenge_registry_root_key_id`, recompute `registry_hash
  == challenge_registry_hash`, `registry_epoch == challenge_registry_epoch`; then the **full
  key-validity predicate as of `challenge_accepted_at_ms`**: `challenge_key_id` present
  exactly once, `public_key` schema valid, `key_epoch` accepted,
  `valid_from_ms ≤ challenge_accepted_at_ms ≤ valid_to_ms`,
  `revoked_at_ms IS NULL OR revoked_at_ms > challenge_accepted_at_ms`, and the challenge
  `sig` valid under that exact snapshot key — presence alone is insufficient.
- **Temporal (as-of-acceptance, never wall-clock now):** `requested_at_ms ≤
  challenge_accepted_at_ms` and `challenge_issued_at_ms ≤ challenge_accepted_at_ms ≤
  challenge_expires_at_ms`; a record in-window stays valid forever.
- **`challenge_accepted_at_ms` equality chain (supervisor-authoritative only):** byte-equal
  across `brops.governed-turn-lease.v1` → `brops.governed-sign-request.v1` attestation →
  `brops.governed-sign-result.v1` → `bridge.governed-turn-result.v1` → record → the signer
  envelope (§4.9). It is **not** a challenge field.
- **Receipt/output (fetch by handle):** fetch the exact signed execution-receipt document by
  the record's **`execution_receipt_handle`**, **re-hash the exact document bytes**
  (`== execution_receipt_handle`), verify the **evidence-recorder** signature, then
  `verify_governed_turn_receipt`; `output_sha256 == output_handle == SHA256(exact output
  bytes)`; the receipt's `receipt_id`/`execution_attempt_id`/`lease_id` equal the record's.
- **Containment:** the containment artifact's run/attempt/lease/runner equal the record's,
  `contained==true`, its evidence event `payload_hash == containment_evidence_sha256`.
- **Evidence head + anti-rollback (SIGNER-OWNED durable floor, P1-7 / P0-2 — NO desktop head-floor
  table).** The reused `bro_evidence` head/chain has no timestamp comparison; its anti-truncation
  is **structural**, keyed on the **chain-content** invariants `event_count` / `last_sequence` /
  `final_event_hash` (the per-event `event_hash`/`sequence` linkage). **`head_sequence` is NOT a
  chain-length — it is a re-ANCHOR / re-SIGN counter** that rises **every time the identical chain
  is re-anchored and re-signed**, per the recorder contract documented at `bro_evidence.py:63-67`
  ("the recorder bumps it every time it re-signs, so a retained stale head always carries a lower
  number") — an unchanged chain's `event_count`/`last_sequence`/`final_event_hash` stay fixed while
  `head_sequence` climbs. rev 17 stored only
  `highest_sequence`+`final_event_hash` and gated advance on `head_sequence` as if it were a chain
  length, which **falsely forks a legitimate re-anchor of an unchanged chain** — the P0-2 defect. The
  fixed floor is keyed on **`head_sequence` monotonicity (the primary axis — the real code's stale
  check `bro_evidence.py:112-116` compares `head_sequence` and raises "stale")** COMBINED with the
  **chain-content identity** `(event_count, last_sequence, final_event_hash)`. Today `min_head_sequence`
  is a caller-only parameter never persisted (`bro_completion.py` `TODO(L-4)` defaults it to the
  store's own current head → self-referential no-op); the fix makes it a **durable
  `brops-signer`-owned floor DB**, separate from the read-only `brops-store` artifact store (the
  signer is read-only there, §2.3), dir `0700` / file `0600`:
  ```sql
  CREATE TABLE governed_evidence_head_floor (
    install_id            TEXT NOT NULL,          -- supervisor-supplied turn context (NOT in bro_evidence)
    task_id               TEXT NOT NULL,          -- EvidenceHead.task_id
    highest_head_sequence INTEGER NOT NULL CHECK (highest_head_sequence >= 1),  -- re-anchor high-water
    event_count           INTEGER NOT NULL CHECK (event_count >= 1),
    last_sequence         INTEGER NOT NULL CHECK (last_sequence >= 1),          -- == event_count (1-based)
    final_event_hash      TEXT NOT NULL,          -- 64-hex
    updated_at_ms         INTEGER NOT NULL,       -- SIGNER wall-clock write time (bro_evidence has only issued_at_epoch seconds; NOT chain-derived)
    PRIMARY KEY (install_id, task_id) );
  ```
  (`bro_evidence` exposes `task_id`/`event_count`/`last_sequence`/`final_event_hash`/`head_sequence`
  via `load_head` `:84-119`; `install_id` is supervisor turn context, and `updated_at_ms` is the
  signer's own write clock — the head carries only `issued_at_epoch` seconds, so `_ms` is NOT derived
  from the chain.) Inside `LiveRunStateProvider`, **before minting the §4.9 envelope**, the signer
  runs `load_head` → `(head_sequence, event_count, last_sequence, final_event_hash)` + a **new
  `validate_chain_detailed`** helper (the existing `validate_chain` returns ONLY the final digest —
  `bro_evidence.py:171` — and discards the per-event hashes it computes at `:158`; the detailed
  variant returns the **ordered per-event hash list** AND each event's stored `previous_event_hash`
  field — `EVENT_FIELDS`, `bro_evidence.py:43` — so D-ii/D-iii below are checkable). Then in **one
  `BEGIN IMMEDIATE`** tx (write-lock up front, reject nested — the proven `receipt_store.rs`
  `in_immediate_tx` shape) `SELECT … WHERE install_id=? AND task_id=?` and decide by the exact
  **head_sequence-keyed A–E matrix**:
  - **A. `head_sequence < stored.highest_head_sequence`** → **refuse `stale_evidence`** (a stale /
    rolled-back / truncated head — a retained older signed head always carries a LOWER re-anchor
    number; this is the real code's `bro_evidence.py:112-116` stale check made durable). *(No row exists
    yet on the very first turn → this branch is unreachable then; see bootstrap below.)*
  - **B. `head_sequence == stored.highest_head_sequence`** → if `(event_count, last_sequence,
    final_event_hash)` **all equal** the stored triple → **idempotent retry** (re-sign the
    byte-identical envelope, no field changes); **any** difference → **refuse `evidence_fork`**.
  - **C. `head_sequence > stored.highest_head_sequence` AND `(event_count, last_sequence,
    final_event_hash)` all equal** the stored triple → a **valid unchanged-chain re-anchor**: advance
    **only** `highest_head_sequence` (= the new head_sequence) `+ updated_at_ms`; the content columns
    are unchanged; mint an envelope with **identical chain-content fields** but binding the **new
    `evidence_head_sequence`** (§4.9) — NOT byte-identical to a prior envelope (only case B, equal head,
    is byte-identical). *(This is exactly the re-anchor rev 17 forked.)*
  - **D. `head_sequence > stored.highest_head_sequence` AND `event_count`/`last_sequence` INCREASED** →
    accept **ONLY** when the fully-validated new chain contains the stored chain as its **exact
    prefix**, proven from `validate_chain_detailed`: (i) the stored `event_count` is reproduced
    exactly (the new chain's first `stored.event_count` events exist in order); (ii) the per-event hash
    at sequence `stored.event_count` (0-based list index `stored.event_count − 1`, since `bro_evidence`
    sequences are 1-based — `enumerate(..., start=1)`, `:142`) equals `stored.final_event_hash`; (iii)
    the NEXT event's stored `previous_event_hash` equals `stored.final_event_hash`; (iv) `event_count`
    and `last_sequence` advance consistently (`new.event_count == new.last_sequence`,
    `new.event_count > stored.event_count`). All four hold → `UPDATE … SET highest_head_sequence=?,
    event_count=?, last_sequence=?, final_event_hash=?, updated_at_ms=?` (every field). Any sub-condition
    fails → **refuse `evidence_fork`** (divergent lineage).
  - **E. every other higher-`head_sequence` case** (e.g. `head_sequence >` stored but `event_count`/
    `last_sequence` did NOT increase and content differs, or a shorter chain with a higher head, or a
    length/seq disagreement) → **refuse `evidence_fork`**.
  - **Bootstrap (no row):** `INSERT (install_id, task_id, highest_head_sequence, event_count,
    last_sequence, final_event_hash, updated_at_ms)` from the validated head.
  (A divergent-content chain that is nonetheless validly signed would require **evidence-recorder key
  compromise**, which is **OUT of the §0 threat model** — the signer does not silently bless it; it
  refuses.) **Commit the floor BEFORE returning the signed envelope**; concurrent same-chain attempts
  serialize on `BEGIN IMMEDIATE` + the `(install_id, task_id)` PK (closing the TOCTOU). Crash after
  floor-commit before response → the retry hits case B (idempotent, equal head_sequence + equal
  content) and re-signs the identical envelope (no advance, no re-execution). **Startup integrity (scoped honestly, P1-7 — Option A):** on open, verify each
  floor row is internally self-consistent (`final_event_hash` is 64-hex, `event_count ≥ 1`,
  `last_sequence ≥ 1` = `event_count`, `highest_head_sequence ≥ 1` — matching the DDL CHECKs and the
  real `bro_evidence.py:107-109` `< 1` rejection) and refuse a malformed/corrupt DB, fail-closed.
  This floor detects and refuses — **against the current persisted floor** — a stale/rolled-back head
  (case A, lower `head_sequence` → `stale_evidence`), a same-length or same-head content fork (case B,
  equal head + any content difference → `evidence_fork`), a longer chain that does not reproduce the
  stored prefix (case D divergent lineage → `evidence_fork`), and every other higher-head anomaly
  (case E → `evidence_fork`), i.e. rollback/fork mounted **through the running signer** by the
  in-scope sidecar (which per §2.3 cannot read or write this `brops-signer` `0700`/`0600` DB at all). **This local table CANNOT
  detect a full-DB restore to an older self-consistent backup** — no external anchor exists to
  compare against, and the restored DB returns the restored (lower) floor as authoritative.
  Offline/root/admin backup restore of the signer-owned DB requires privileges that are **OUT of
  the §0 threat model** (admin/root/kernel), so it is **not** defended here. **External monotonic
  anti-rollback anchoring** (an operator-held pin outside the DB, mirroring `resolve_registry_floor`'s
  `BRO_OPERATOR_REGISTRY_MIN_FILE`, or a hardware monotonic counter) is **DEFERRED to 3b-2**;
  unlike the registry floor (whose strength comes from that external anchor), this evidence-head
  floor makes **no** cross-restart backup-rollback claim. The envelope binds `evidence_event_count`/
  `evidence_last_sequence`/`evidence_final_event_hash`/`evidence_head_sequence` (§4.9) so the signed
  artifact commits to the exact chain content **and** the re-anchor counter. **Mandatory tests (the
  A–E matrix + concurrency/crash):** (1) same chain + **equal** `head_sequence` → case B idempotent;
  (2) same chain + **higher** `head_sequence` → case C valid unchanged re-anchor (advances ONLY
  `highest_head_sequence`, NOT a fork — the exact P0-2 regression guard); (3) extension by ONE event
  that reproduces the stored prefix → case D advance; (4) extension by MANY events that reproduce the
  prefix → case D advance; (5) **higher** `head_sequence` + **shorter** chain → case E `evidence_fork`;
  (6) same `event_count` + **different** `final_event_hash` → case B `evidence_fork`; (7) extension
  MISSING the stored prefix (D-ii/D-iii fail) → `evidence_fork`; (8) concurrent unchanged re-anchor vs
  extension → exactly one commits, the other re-evaluates on the new floor; (9) crash after floor
  commit before the envelope response → retry hits case B, identical re-sign, no second advance; plus
  the **lower `head_sequence`** case → `stale_evidence`, and the bootstrap no-row → INSERT. (The
  Wave-3a desktop SQLite has **no** `evidence_head_floor` table — this primitive is signer-side; a
  stale head is refused here at the signer, before any envelope is minted. Note: the shipped
  `tests/test_evidence_chain.py` only exercises `head_sequence == 1`; the `min_head_sequence`
  stale-reject path is currently **uncovered** and these tests add that coverage.)
- **Registry anti-rollback (supervisor side, crash-consistent):** verify full signed
  registry → create-if-absent publish exact doc + fsync file&dir → durable floor tx persists
  `(highest_registry_epoch, registry_hash, challenge_registry_handle, root_key_id)` → the
  floor is never usable unless its snapshot exists + re-hashes → same-epoch/different-hash +
  divergent-handle refused; startup verifies the floor's snapshot before use, else
  fail-closed.

`RunState` is built from the verified signed record only. On success the signer mints the
`brops.governed-receipt-envelope.v1` (§4.9); on any failure it returns `refused` (§4.5).

### 7.1 Broker acceptance (§6.1 step 14) — signatures only, NO store access

The **trusted verifier/broker service** (§0 role #2 — NOT the renderer/login process) verifies the **isolated-signer envelope** (§4.9) + the **supervisor attestation**,
equality-checks the transport echoes, and binds the real Wave-3a broker-owned replay primitives —
all without reaching the protected store. **Ordering (P0-3):** the envelope-signature +
attestation verification and the **output fetch/reassemble/hash happen FIRST, OUTSIDE the DB
transaction** (the §4.10(f) pull loop is network/subprocess I/O and must never run while holding
`BEGIN IMMEDIATE` — `receipt_store.rs::in_immediate_tx` rejects a nested tx); the verified
immutable bytes are kept, THEN the tx opens for the replay/persist steps below.
- **Envelope signature** — Ed25519 over `JCS(envelope.payload)` under the **pinned
  isolated-signer manifest key**; a bad signature Blocks.
- **Attestation** — verify the supervisor attestation signature over
  `attestation_evidence_jcs_b64` against the manifest `supervisor_attestation` key, and confirm
  `SHA256(that JCS) == envelope.attestation_evidence_sha256`.
- **One-time nonce** — compare-and-consume `receipt_challenges` (`nonce` PK, bound to
  `request_sha256`; `UPDATE … SET consumed_at=? WHERE nonce=? AND consumed_at IS NULL`).
- **`receipt_id` global uniqueness** — insert into `receipt_ids_seen` (PK) only on ACCEPT.
- **Freshness** — the `_ms` window (`FreshnessWindow{future_skew_ms: 60000, max_age_ms: 300000}`
  vs `now_ms`, the real `receipt_store.rs` values); every governed-turn `_ms` field nests inside
  it (§1 window-nesting).
- **Output binding (P0-3, done OUTSIDE the tx)** — obtain the exact output bytes by driving the
  §4.10(f) `brops.governed-turn-output-read.v1` pull loop through the sidecar into a bounded ≤ 8
  MiB buffer; assert `len(bytes) == envelope.output_bytes` **and** `SHA256(bytes) ==
  envelope.output_sha256` over the **raw** bytes with **no trim/NFC/NFKC/CRLF/lossy** normalization;
  only then strict-UTF8 decode for display (invalid UTF-8 Blocks). A mismatch/wrong-length/
  tampered/replayed-chunk Blocks. Restores the binding the v1 path had at `receipt.rs`
  (`sha256_hex(output) == output_sha256`).
- **Echo equality** — every `bridge.governed-turn-result.v1`/`brops.governed-turn-result.v1` echo
  equals the verified envelope; a mismatch Blocks. A bare echo never authorizes anything.
The nonce-consume + `receipt_id` uniqueness + freshness + echo-equality + persist run in one
`BEGIN IMMEDIATE` tx (the already-verified output bytes are used, no I/O in the lock); render only
on commit.
- **Out-of-band transport failure (P1-1/P1-5)** — a local sidecar-hop failure (spawn/connect/timeout/
  oversize-or-malformed-reply/unexpected-exit) at the submit (§6.1 step 0) or pull (§4.10(f)) hop is
  **not** a signer/attestation/echo verdict and yields **no** governed reply frame; it is an
  out-of-band Tauri error ⇒ `governed_turn_execute` records a **terminal durable Block** via
  `record_pre_verification_block` (`receipt_store.rs:175-208`): it **consumes the `request_nonce`** and
  writes a durable `blocked` evidence attempt (no output, no signed receipt, no message), surfacing
  `StreamEvent::Blocked{reason}` — matching the merged `stream_reply` transport-failure arm. **The
  challenge/nonce is NOT retryable** (a later receipt on that nonce ⇒ `Replay` Block). The sidecar never
  fabricates a `signed` result or a refusal reason to mask it (§4.5, §6.1 out-of-band contract).

---

## 8. Authorities (governed-turn functions only)

- **Lease:** `issue_governed_turn_lease` (governed-turn lease issuer) +
  `validate_governed_turn_lease` (§4.3). The base `issue_lease`/`validate_execution_lease`
  are **NOT** used for this path (a governed-turn lease presented to the base validator is
  refused).
- **Terminal record:** the **`governed-turn-recorder`** is a **supervisor-held signing-key
  authority, NOT a distinct OS principal** (P1-5). It is registered as a `bro_signature`
  `AUTHORITY_TYPES` entry + a `broctl` key class + an `ARTIFACT_AUTHORITY` mapping, its key held
  in a `0700` owner-only dir under the **`brops-supervisor`** principal (alongside the
  attestation key). The supervisor invokes **only** the exact terminal-record constructor
  (`broctl sign --artifact brops.governed-turn-record.v1`, mirroring the existing
  `broctl` artifact-authority gate) — there is **no public `sign(payload)` oracle** (`bro_signature`
  only ever verifies). It signs **only** `brops.governed-turn-record.v1`; it MUST NOT sign
  `evidence-event`/`evidence-head`/any lease, and `verify_artifact` refuses a record signed by
  any other authority. (The separate `brops-recorder` OS principal holds the distinct
  **evidence-recorder** key and writes `store/rec/`, §2.3 — the two are different things.)
- **Receipt + evidence:** `brops.governed-turn-execution-receipt.v1` and the containment/
  evidence events/head are signed by the **evidence-recorder runner** and verified by
  `verify_governed_turn_receipt` (NOT the generic `bro_run_receipt.run_and_sign` /
  `verify_passing_receipt`).
- **Challenge:** the dedicated `desktop-challenge-authority` (its own principal/UID; §2.1).
- **Registry root:** the binary-pinned challenge-root anchor (separate from the receipt keys).
- **Supervisor attestation:** the supervisor-attestation key signs **only**
  `brops.governed-sign-request.v1` evidence (`brops.run-attestation.v1`); re-verified by the
  isolated signer and the desktop against the manifest `supervisor_attestation` key.
- **Governed receipt envelope:** the **isolated-signer** key signs **only**
  `brops.governed-receipt-envelope.v1` (§4.9); it is the desktop's sole trust root for the
  turn (pinned in the desktop manifest). It MUST NOT sign leases/records/evidence.
- **Authority separation is total:** no authority may sign another class's artifact
  (Appendix B authority matrix).

---

## 9. Acceptance criteria (for 3b-1B implementation, AFTER Architect design-GREEN)

Positive: a real desktop→sidecar→supervisor(accept+execute+record)→signer E2E yielding a
`signed` governed-result whose receipt binds the exact request + output; the Linux isolation
job's positive control uses a genuinely-executed record. Negative matrix: forged/edited
record; replayed old evidence head; output/containment/nonce not matching the signed
artifacts; missing lease/receipt; the §1/§2/§5/§7 negative tests (mixed-unit timestamps,
capability overgrant, ledger replay/conflict, crash-cut recovery, historical key-validity,
transport-only echo mismatch). Engine + isolation exact-head CI GREEN. **STOP unchanged:**
`NoTrustedManifest`, no production "Verified".

**TCB-integrity + principal + platform-gate matrix (P0 — §0.1, §2.5, §2.6, NEW in rev 26 prep-P0
closure).** (a) login-user-writable executor image ⇒ `verify_tcb_integrity()` refuses at start (no
governed mode); (b) executor bytes swapped after pinning ⇒ launcher `fexecve` re-hash mismatch ⇒
`tcb_integrity_violation` Block, **no receipt**; (c) wrong-owner launcher / signer / config, or a
writable **ancestor directory** of any TCB path ⇒ start refused; (d) a lease naming any
`launcher_executable_sha256` / `executor_executable_sha256` other than the start-time pins ⇒
`validate_governed_turn_lease` rejects; (e) any two principals sharing a UID, or `sidecar` UID ==
login/desktop-UI UID, or an unset principal UID ⇒ `verify_distinct_principals()` Block; (f) a platform
shim reporting any single §0.1 primitive missing ⇒ `platform_governed_execution_supported()` == false
⇒ governed turn Blocks with **no lease**; (g) on a non-supported platform (Windows today) the gate is
false and the desktop renders dev/blocked, **never** `trusted_verified`; (h) the all-present 7-distinct-
UID Linux fixture ⇒ the gate is true and the four §2.1 same-service-UID isolation proofs still hold.

**Principal-topology + launcher-model matrix (P0 — §0/§2.6/§2.7, rev-28, P0-1 + P0-2).** (i) the
**trusted verifier/broker** UID == the login/renderer UID, or == the **`desktop-challenge-authority`**
UID ⇒ `verify_distinct_principals()` Block (a compromised renderer can never *become* the final verifier;
the broker can never be the authority — P0-1); (j) **renderer-isolation (Actor B, login identity):**
the renderer cannot read/write/list the verifier DB or pinned manifest, cannot call the challenge-
authority IPC, cannot reach the sidecar/supervisor/signer IPC, cannot supply `system`/`history`/`config`/
hashes/nonces/receipt fields, and a forged renderer "Verified" event **cannot** create a verified message
(only the broker's committed verification tx does) — the broker accepts only the closed
`{conversation_id, agent?}` command and resolves all authoritative inputs itself; (k) Actor C (dedicated
**sidecar service UID**, NOT login, NOT broker) attempts to connect the signer socket / read any key or
store / make an authority sign caller-supplied evidence ⇒ DENIED (peer-auth + ACL); it may only trigger
a run + relay the final receipt; (l) the seven runtime **service** principals must be pairwise-distinct
AND ≠ login (any collision ⇒ Block); (m) **launcher Model A:** wrong caller UID (≠ recorder), extra
argv / non-empty env / extra inherited FD, a data FD 3–6 arriving `FD_CLOEXEC` (would close executor I/O),
target executable ≠ pinned `executor_executable_sha256`, target UID **or** GID ≠ executor, residual
supplementary groups or residual eff/perm/inh/ambient/bounding capability after the drop, a failed
`setgroups`/`setresgid`/`setresuid`/`prctl`/`capset`, image hash/owner/mode/path swap, cgroup mismatch,
`fexecve` failure ⇒ each refuses with **no receipt**; the launcher binary is root/TCB-owned mode-4750
(not a runtime UID) ⇒ `verify_tcb_integrity()` confirms, `verify_distinct_principals()` does NOT count it;
the **success** path (a tiny pinned executor reading FDs 3/4/5 and writing FD 6) MUST run end-to-end
(FD survival + privilege drop proven); (n) each of the 3 threat actors (A login user / B renderer / C
sidecar-service-UID) × each protected asset (auth key, pending store, receipt/attestation keys, protected
evidence store, verifier DB + manifest, TCB binaries) ⇒ DENIED with the stated enforcing mechanism (the
Linux mechanism here; the equivalent Windows SID denial matrix is specified in §0.W).

---

## Appendix A — NON-NORMATIVE revision history (does not define current contracts)

The current normative design is §0–§9 above. This log is historical only.
- **rev 1–5:** initial 3b-1B design-lock, closing Architect REDs on topology, oracle removal,
  containment binding, ingress, launcher TCB, schema de-dangling.
- **rev 6:** dedicated `desktop-challenge-authority`; challenge binds run/task; fixed input
  delivery; one bounded ingress; challenge bound in record.
- **rev 7:** authority builds challenge from trusted DB (no caller bytes); canonical launcher
  FD table; supervisor publishes signed challenge; self-contained challenge-key registry;
  as-of-run historical verification.
- **rev 8:** dedicated-principal pending-store + direct-file-mutation CI denial; supervisor
  `challenge_accepted_at`; full registry trust contract; read-only regular-file input FDs.
- **rev 9:** registry payload-hash vs exact-document handle split; crash-consistent
  snapshot-publish→floor; full historical key-validity predicate; (attempted) signed
  `challenge_accepted_at` schema.
- **rev 10:** supervisor atomic challenge consumption (first cut); governed-turn-lease as a
  "superset" (had unit/field conflicts + an impossible challenge equality).
- **rev 11:** one-pass consolidation — canonical ms time model; dedicated durable acceptance
  state machine + outbox; closed `governed-model-turn-v1` capability profile; relay schemas +
  transport-only echoes; §8 governed-turn functions; single artifact matrix as the source of
  truth; revision history demoted to this appendix.
- **rev 12:** surgical corrections to the rev-11 structure — no auto-relaunch after
  `EXECUTION_STARTING`; full challenge-authority creation-channel contract restored (§2.1);
  registry `revoked`/`revoked_at_ms` invariant; relay schemas + `builder_id` removed; terminal
  record binds `lease_handle` + `execution_receipt_handle` + 13-step E2E; CLAUDE.md doc-law loop
  corrected.
- **rev 13:** implementation-readiness closure via a 6-track fan-out — **P0-1** separate
  `brops.governed-*`/`bridge.governed-*` protocol family so the GREEN 3b-1A v1 schemas stay
  byte-for-byte (§2.2, §4.4–4.6); **P0-2** one authenticated bounded chunked-upload ingress to
  supervisor staging + per-artifact caps (§2.4); **P0-3** the `brops-store` group ACL model + a
  desktop-vs-signer authority split — the signer's `LiveRunStateProvider` deep-verifies the store
  and emits a signed receipt envelope the desktop verifies with no store access (§2.3, §4.6, §4.9,
  §6.1, §7.1); **P1-4** `bro_evidence` marked legacy epoch-seconds; **P1-5** complete receipt/
  containment/record/envelope schemas + one `execution_receipt_handle` name + `record_handle`;
  **P1-6** `MAX_OUTPUT_BYTES = 8 MiB` output ceiling.
- **rev 14:** 7-track fan-out closure — `2750` owner-write ACL; pre-accept `governed_turn_staging`
  FSM + supervisor-self-resolved policy; `output_b64` desktop hash gate; `MAX_STAGING_CHUNK_BYTES
  = 184320`; §4.10 control-plane schemas + bridge parent; `EXECUTION_TIMEOUT_MS = 120000`;
  signer-owned `governed_evidence_head_floor` CAS.
- **rev 15:** transport/version/lease closure — freeze the shipped `brops.governed-result.v1`,
  rename the 3b-1B result `brops.governed-turn-result.v1`/`bridge.governed-turn-result.v1` with a
  top-level `protocol` const; `brops.governed-turn-open.v1` challenge submission; idempotent PULL
  output-read; `LEASE_DURATION_MS = 210000` + pre-launch gate; governed-turn-recorder = supervisor
  key authority; always-stream metadata-only summary; Option-A evidence-floor scope + extend-or-scope.
- **rev 16:** protocol/proxy/state-consistency closure — KEEP+ADD parallel `GOVERNED_TURN_RESULT_PROTOCOL`;
  desktop→sidecar `bridge.governed-turn-output-read.v1` + `governed_output_streams` table; two-phase
  challenge verify; closed 9-value state enum + `GOVERNED_REFUSAL_REASONS`; `MIN_LAUNCH_REMAINING_MS
  = 180000` + `completed ≤ lease_expires`; exact ingress idempotency.
- **rev 17:** targeted durability/idempotency/stream-binding/state closure via a mandatory
  **4-track fan-out (A FS/SQLite crash-consistency · B idempotency/schema · C output-stream
  capability/threat · D closed state/reason machine) + one integrator + a fresh independent
  red-team** — **P0-1** staging mixed a mutable append file with SQLite state (no atomic file↔DB
  ordering; `running_sha256` is a finalized digest, not a resumable hash context) → **immutable
  per-chunk storage** (`<session_id>/<seq>.chunk`, O_EXCL→fsync→link→fsync-dir→**then** the DB tx,
  ACK only after commit), 3 restart-recovery reconciliation rules, and final SHA-256 recomputed from
  byte zero (§2.4, §4.10(b/c)); **P1-2** deleted the stale collapsed `seq != next_seq ⇒ refuse`,
  fixed §4.10(a) `next_seq: 0` → `<int ≥ 0>` (reopen = current cursor), and tightened the chunk-reply
  discriminated union (§2.4, §4.10(a/b)); **P1-3** both output-read hops now carry
  `{output_stream_id, receipt_id, execution_attempt_id, seq}` so the supervisor catches a valid
  other-turn token server-side (`stream_binding_mismatch`), the false sidecar-confidentiality claim
  is replaced with the honest threat scope, zero-byte output is defined, and the bridge reason enum
  is literal-identical to the supervisor's (§4.10(f)); **P1-4** removed every `EXPIRED/BLOCKED` /
  `RECOVERY_REQUIRED/BLOCKED` slash-alternative for one deterministic destination per condition
  (lease-gate → `EXPIRED`; post-launch crash → `RECOVERY_REQUIRED`; never `BLOCKED`), added a `CHECK
  (state IN …)` constraint + the deterministic state-purpose matrix, and replaced every `<enum>`/
  "superset" placeholder with a **literal closed reason array** (§4.7, §5, §6.1, §4.5, §4.6, §4.10).
- **rev 18 (this doc):** desktop-ingress / evidence-floor / bounded-staging closure via a mandatory
  **5-track fan-out (A desktop→sidecar→supervisor transport · B evidence-head re-anchor semantics ·
  C staging resource/concurrency · D state/reason + transport-failure homing · E full adversarial
  E2E) + one integrator + a fresh independent red-team** — **P0-1** the desktop→sidecar governed
  INGRESS frame was undefined (the signed challenge document + raw input bytes reached the sidecar
  "by assumption"; the frozen `bridge.task-request` cannot carry them) → new
  **`bridge.governed-turn-submit.v1`** ingress frame + Tauri `governed_turn_submit` command + the
  one-shot sidecar orchestrator; byte formulas: `system`=raw UTF-8 + `history`=JCS reuse
  `brops_canonical.py`, and **`generation_config` = a closed JSON object with `JCS(object)`** — a NEW
  strictly-additive governed-family formula (owner-mandated) that leaves the frozen 3b-1A
  raw-UTF-8-string `generation_config_bytes` + its `receipt.rs:1216-1219` parity fixture untouched
  (§2.2 KEEP+ADD); plus the §2.1 authority→desktop-UI document return path, and §6.1 step 0
  (§2.1, §2.2, §4.10(g), §6.1); **P0-2**
  the evidence-head floor gated advance on `head_sequence` (a re-ANCHOR/re-SIGN counter that rises on
  an unchanged chain — falsely forking a legitimate re-anchor) → the floor keys on `head_sequence`
  monotonicity + chain-content `(event_count, last_sequence, final_event_hash)` via a **head-keyed A–E
  matrix** (case A lower head → new `stale_evidence` reason; B/D/E → `evidence_fork`; C unchanged
  re-anchor advances head only; D prefix-extend) + a `validate_chain_detailed`
  helper, `head_sequence` demoted to a `highest_head_sequence` high-water counter, envelope binds `event_count`/`last_sequence`
  (§7, §4.9); **P1-3** staging chunks had no min length + no count bound (tiny-chunk amplification) →
  deterministic `expected_chunk_len` + `MAX_STAGING_CHUNKS = 46` + exact numeric quotas (2 turns / 6
  sessions / 49 files-per-turn / 98 per-install / 17 MiB / 60 s sweep) (§2.4, §4.10(b/c)); **P1-4**
  the FAILED staging session dead-ended, the session-state CHECK drifted (`INPUTS_ARTIFACT_READY` vs
  the row's `INPUTS_READY`), and CHECKs/the publish primitive were vague → `os.link` create-if-absent
  freeze, a `SESSION_CORRUPT` terminal contract (`session_corrupt` in the a/b/c enums), CHECK
  constraints on state/`next_seq`/`byte_count` (§2.4, §4.10(a/b/c)); **P1-5** `BLOCKED` wrongly listed
  `UNSEEN` (no-row) as a predecessor and "the sidecar originates no reasons" was over-absolute →
  `BLOCKED` predecessors are `ACCEPTED_PREPARED`/`LEASE_READY` only (pre-accept refusals create NO
  row) and local transport failures are homed as **out-of-band Tauri Blocks** distinct from supervisor
  verdicts (§5, §4.5, §4.10(f), §6.1, §7.1). Also, per the owner's re-mandate, `generation_config`
  became a **closed JSON object canonicalized via `JCS`** (P0-1, additive to the frozen family), and
  the **GitHub-only continuation law** was applied outside this doc in the same commit: `START_HERE.md`
  names the active design file, `NEXT_CHAT.md §3.1` gives the exact-HEAD resolution method (GitHub is
  authoritative), `AGENTS.md` was added to `config/canonical-read-manifest.json`, and
  `tools/check_coordination.py` now asserts every manifest path exists (a new CI gate) so the startup
  chain `START_HERE → NEXT_CHAT → manifest → design files` can never silently orphan.
- **rev 19 (this doc):** orchestrator-ordering / generation_config-canonicalization /
  challenge-creation-channel closure of the rev-18 Architect Design RED (**1 P0 + 2 P1** @
  `89d0df4c7211c97c85c582090cea05c5da02bc42`, exact-head CI #124 SUCCESS 8/8 — CI GREEN ≠ design GREEN)
  via a mandatory **read-only fan-out + one integrator + a fresh independent red-team** — **P0-1**
  §4.10(g)/§6.1 the one-shot sidecar submit subprocess sequenced `staging×3 → turn-open →
  evidence-request → result → PULL` inside the submit path, but `governed-staging-open` requires the
  `UPLOADING` row only `governed-turn-open` creates (`no_staging_row` otherwise), so no turn could
  execute → reordered to `turn-open → staging×3 → evidence-request → metadata-result → reframe → exit`
  with **no** `brops.governed-turn-output-read.v1` output pull in the submit path (pull confined to the
  §6.1 step-13/14 desktop-driven subprocess) + an exact call-order test; **P1-2** §2.1/§4.1 the
  challenge-authority creation channel left a choice between two trust models (§2.1 "facts OR row-id"
  vs §4.1 "row-id only") → a single **protected-row-ID model with two explicit messages**
  (`brops.governed-challenge-create-pending.v1` stores validated facts in the authority's own `0700`
  row, no signing; `brops.governed-challenge-issue.v1` takes row-id only, the authority builds the
  §4.1 payload from its own row and signs once, one-time-consume), with full request/reply + pending-row
  schemas, validation, idempotency, frame limits; **P1-1** §2.2/§4.10(g) `generation_config_bytes =
  JCS(object)` relied on representation-ambiguous JCS numeric canonicalization (Python `json.dumps`
  float-repr vs Rust `ryu`; the real `receipt.rs::jcs_bytes:235-237` is `BTreeMap<String,String>`-only,
  no numeric serializer exists) → `generation_config` is now a **flat string→string object**
  (fixed-point decimal + canonical integer strings, regex + integer-range validated to reject
  exponent/`-0.0`/precision/bare-int forms before canonicalization), riding the already-proven
  string→string primitive with no number ever serialized; strictly additive to the frozen 3b-1A string
  `generation_config_bytes` + `receipt.rs:1216-1219` fixture (§2.2 KEEP+ADD, untouched). Fresh
  independent red-team over the full rev-19 diff + the real repo returned **no BLOCKER**; the frozen
  3b-1A family proven untouched; the `check_coordination` manifest gate + its tests run GREEN live.
  **NOT Architect-GREEN; 3b-1B code not started.**
- **rev 20 (this doc):** single-P0 closure of the rev-19 Architect Design RED (**1 P0 · 0 P1** @
  `8d3451e28b542f290cc9b7c981c4636aec3dc54b`, exact-head CI #125 SUCCESS 8/8 — CI GREEN ≠ design GREEN;
  the rev-18 P0 orchestrator ordering + P1 generation_config canonicalization were CONFIRMED CLOSED)
  via a mandatory read-only real-code investigation + one integrator + a fresh independent red-team.
  **P0-1** — the rev-19 challenge creation channel had the **authority mint `request_nonce`** while the
  desktop supplied `request_sha256`, decoupling the pair; but the ratified/merged Wave-3a contract is
  desktop-minted `request_nonce` (`ai.rs:1228`), `request_sha256 = SHA256(JCS(request-envelope))` with
  the nonce **inside** the hashed envelope (`receipt.rs:245-264` ↔ `brops_canonical.py:157-179`), and a
  desktop `receipt_challenges` pre-store (`receipt_store.rs:109-126`, `commands.rs:866-883`) consumed at
  acceptance by `expected.request.request_nonce` (`receipt_store.rs:256-271`) — so an authority-minted
  nonce forces every happy-path turn to Block. **rev 20 (§2.1):** create-pending (A) carries the
  desktop `request_nonce` + envelope fields and **no** `request_sha256`; the authority **recomputes**
  `request_sha256` via the byte-identical merged formula and stores the desktop nonce + recomputed hash;
  issue (B) signs with that exact pair; a normative desktop `receipt_challenges` pre-store step + a
  mandatory E2E test (authority recompute == supervisor open-time recompute == the desktop's pre-stored
  row) lock the single-envelope chain; the authority-minted-nonce variant is deferred to a separate
  ratified redesign. Fresh independent red-team over the rev-20 diff + real repo: no BLOCKER; the frozen
  3b-1A + Wave-3a request/nonce path proven untouched; `check_coordination` + `check_capabilities` GREEN
  live. NOT Architect-GREEN; 3b-1B code not started.
- **rev 21 (this doc):** single-P0 closure of the rev-20 Architect Design RED (**1 P0 · 0 P1** @
  `85240edf9bd66673d9f3e8f94e732aab155273f9`, exact-head CI #126 — two mandatory Wave-3b engine gates +
  coordination gate GREEN; CI GREEN ≠ design GREEN; the rev-19 nonce/hash P0 was CONFIRMED CLOSED) via a
  read-only real-code investigation + one integrator + a fresh independent red-team. **P0-1** — the
  desktop `generation_config` hash source was contradictory: the frozen `prepare_governed_turn(&str)`
  (`ai.rs:1214-1235`) hashes the **raw UTF-8 string** (`ai.rs:1231`) into
  `GovernedRequestContext`→`IssuedRequest`→the `receipt_challenges` pre-store, and
  `GOVERNED_GENERATION_CONFIG` is a plain string (`commands.rs:785`), while 3b-1B requires
  `generation_config_sha256 = SHA256(JCS(flat string→string OBJECT))` — so the desktop pre-stored a
  raw-string-based `request_sha256` and the authority/staging derived the object-JCS-based one ⇒ every
  turn Blocks (`receipt_store.rs:322-327`), with no single immutable desktop source. **rev 21
  (§4.10(g)):** adds a NEW immutable preparation contract **`prepare_governed_turn_v1b`** /
  `PreparedGovernedTurnV1B` that in ONE pass validates the config **object**, computes
  `generation_config_jcs = JCS(object)` + its hash once, mints the nonce once, and is the single source
  for the `receipt_challenges` pre-store `IssuedRequest`, the create-pending (A) request, the
  `bridge.governed-turn-submit.v1` submit frame (carrying the validated object), and the final
  `Expected` — so the same object-JCS hash flows `receipt_challenges` → authority row → §4.1 → §2.4
  staging → terminal record → `Expected`, no split authority; the frozen `prepare_governed_turn(&str)` +
  `GOVERNED_GENERATION_CONFIG: &str` + the `receipt.rs:1215-1219` fixture stay byte-for-byte (§2.2
  KEEP+ADD). Mandatory tests: frozen raw-string hash ≠ object-JCS hash; only the object-JCS hash appears
  at every 3b-1B hop. Fresh independent red-team over the rev-21 diff + real repo: no BLOCKER; the frozen
  3b-1A/Wave-3a prep path proven untouched; `check_coordination` + `check_capabilities` GREEN live. NOT
  Architect-GREEN; 3b-1B code not started.
- **rev 22 (this doc):** single-P0 closure of the rev-21 Architect Design RED (**1 P0 · 0 P1** @
  `a05629b7179e9ee87f315e5ac8452e88c8f4f89a`, exact-head CI #127 mandatory-gates SUCCESS; CI GREEN ≠
  design GREEN; the rev-20 generation_config hash-source split was CONFIRMED CLOSED) via a read-only
  real-code investigation + one integrator + a fresh independent red-team. **P0-1** — rev 21's
  `PreparedGovernedTurnV1B` lifecycle was severed at the Tauri/frontend boundary: submit was a separate
  frontend-invoked Tauri command re-accepting raw fields after challenge creation + `receipt_challenges`
  pre-store, with no defined way for the same in-process object to reach submit/`Expected` without a
  webview re-serialize — so the submit bytes could diverge from the pre-stored `request_sha256` ⇒ Block.
  **rev 22 (§4.10(g), §6.1):** submit is no longer a frontend command; 3b-1B adds exactly one
  frontend-exposed governed Tauri command **`governed_turn_execute`** (mirroring the merged
  single-backend `stream_reply`, `commands.rs:794/844-935`) that owns the whole lifecycle of one
  in-process `PreparedGovernedTurnV1B` — prepare-v1b once → `receipt_challenges` pre-store → authority
  create-pending + issue → the **internal** `governed_turn_submit_prepared(&prepared, …)` helper (NOT a
  Tauri command) → internal output-pull loop → final `Expected` from the same `&prepared`; nothing
  round-trips the webview after prepare; `PreparedGovernedTurnV1B` fields are private with read-only
  accessors; a pre-submit assert binds `SHA256(generation_config_jcs) == context.generation_config_sha256`
  and `issued_request().request_sha256() == the pre-stored receipt_challenges.request_sha256`; a
  frontend-exposed raw-field submit command is forbidden, the only alternative a server-side opaque
  `prepared_turn_id` state machine; mandatory test: frontend-mutated config/system/history cannot reach
  submit or alter the pre-stored request. Fresh independent red-team over the rev-22 diff + real repo: no
  BLOCKER; the frozen 3b-1A/Wave-3a path + the merged `stream_reply` shape proven cited byte-exact;
  `check_coordination` + `check_capabilities` GREEN live. NOT Architect-GREEN; 3b-1B code not started.
- **rev 23 (this doc):** dual-finding closure of the rev-22 Architect Design RED (**1 P0 · 1 P1** @
  `4703351` — the rev-22 design content `a84ee12`; exact-head CI #129 8/8 SUCCESS; the rev-21
  lifecycle P0 was CONFIRMED CLOSED) via a read-only real-code investigation + one integrator + a fresh
  independent red-team. **P0-1** — `governed_turn_execute` omitted `conversation_id` (needed for the
  `receipt_challenges` pre-store + final persist) and `run_id` (challenge create-pending), and wrongly
  took `system`/`history`/`workspace_id`/`install_id`/`generation_config` from the renderer — but the
  merged `stream_reply(conversation_id, agent, on_event)` (`commands.rs:793-799`) takes only
  `conversation_id`+`agent`, resolves `system`/`history` from the message store (`commands.rs:801-815`)
  and identities/policy from the `GOVERNED_*` constants (`commands.rs:780-787`), and has **no `run_id`**.
  **rev 23 (§4.10(g)/§6.1):** `governed_turn_execute(conversation_id, agent)` builds a backend-owned
  `GovernedTurnExecutionV1B{conversation_id, run_id, task_id, prepared}` — `run_id`/`task_id`/
  `request_nonce` backend-generated, `system`/`history`/identities backend-resolved, renderer re-sends
  none. **P1-1** — rev 22's "transport failure ⇒ nonce not consumed, challenge retryable" was not durable
  (the in-process prepared object/challenge/pending-id are gone after the command returns). **rev 23 (§6.1
  out-of-band contract):** transport failure is a **terminal durable Block** via
  `record_pre_verification_block` (`receipt_store.rs:175-208`) — consume the nonce + write a `blocked`
  record; not retryable (later receipt on that nonce ⇒ `Replay` Block) — matching the merged path. Fresh
  independent red-team over the rev-23 diff + real repo: no BLOCKER; the frozen 3b-1A/Wave-3a `stream_reply`
  + `record_pre_verification_block` shapes proven cited byte-exact; `check_coordination` +
  `check_capabilities` GREEN live. NOT Architect-GREEN; 3b-1B code not started.
- **rev 24 (this doc):** dual-finding closure of the rev-23 Architect Design RED (**1 P0 · 1 P1** @
  `b89bab9`, exact-head CI #130 8/8 SUCCESS; the rev-22 routing-identities P0 + non-durable-transport-retry
  P1 were CONFIRMED CLOSED) via a read-only real-code investigation + one integrator + a fresh independent
  red-team. **P0-1** — the backend single-source orchestration was not constructible: (A) `task_id` lived
  in `GovernedTurnExecutionV1B` but not `PreparedGovernedTurnV1B`, so `governed_turn_submit_prepared(&prepared,…)`
  could not derive the submit frame's top-level `task_id`; (B) the 5-field `generation_config` object had no
  trusted source (only the frozen opaque `GOVERNED_GENERATION_CONFIG` string). **rev 24 (§4.10(g)):** (A) the
  helper becomes `governed_turn_submit_prepared(execution: &GovernedTurnExecutionV1B, challenge_document:
  &ChallengeDocument)`, asserting `submit.task_id == execution.task_id == challenge.payload.task_id`,
  `challenge.payload.run_id == execution.run_id`, `SHA256(JCS(execution.prepared.generation_config)) ==
  challenge.payload.generation_config_sha256`; (B) a new `resolve_governed_generation_config_v1b()` returns
  all five fields from locked governed defaults / trusted host config (engine_id = frozen
  `GOVERNED_GENERATION_CONFIG`; new `GOVERNED_MODEL`/`GOVERNED_MAX_OUTPUT_TOKENS`/`GOVERNED_TEMPERATURE`/
  `GOVERNED_TOP_P`), validated once; + a whole-chain E2E (same task_id/run_id/config-JCS through authority
  row → challenge → submit → lease → record → envelope). **P1-1** — rev 23's terminal-durable-Block covered
  only desktop↔sidecar hops; the authority `create-pending`/`issue` hops after pre-store could return with an
  unconsumed nonce. **rev 24 (§4.10(g) Authority-channel failure boundary):** every post-pre-store authority
  failure has exactly two outcomes — bounded idempotent retry with the same live `GovernedTurnExecutionV1B`
  (lost-reply-safe §2.1 protocols) bounded by `MAX_AUTHORITY_RETRIES`, or `record_pre_verification_block`
  (consume nonce + one `blocked` attempt); no orphan. Fresh independent red-team over the rev-24 diff + real
  repo: no BLOCKER; frozen 3b-1A/Wave-3a + `stream_reply`/`record_pre_verification_block`/`DEFAULT_ANTHROPIC_MODEL`
  cites byte-exact; `check_coordination` + `check_capabilities` GREEN live. NOT Architect-GREEN; 3b-1B code not started.
- **rev 25 (this doc):** dual-finding closure of the rev-24 Architect Design RED (**1 P0 · 1 P1** @
  `232be53`, exact-head CI #131 8/8 SUCCESS; the rev-23 single-source-constructibility P0 +
  authority-failure-boundary P1 were CONFIRMED CLOSED) via a read-only real-code investigation + one
  integrator + a fresh independent red-team. **P0** — model identity had two independent authorities: the
  desktop `generation_config` (read by the executor via FD) vs the lease's `model_profile_id`, unbound — a
  signed lease could declare "profile A" over a "model B" config. **rev 25 (§2, §4.3, §7):** a
  supervisor-owned deterministic model-profile registry `SHA256(JCS(generation_config)) → model_profile_id`
  (unknown ⇒ `model_profile_unknown` acceptance Block); the supervisor derives the profile pre-acceptance
  from the staged config; `issue_governed_turn_lease` sets `model_profile_id` = derived and binds
  `generation_config_sha256` in the signed lease; `validate_governed_turn_lease` + `LiveRunStateProvider`
  re-derive and refuse unless `lease.model_profile_id == registry[lease.generation_config_sha256]` and
  `lease.generation_config_sha256 == challenge's == executed config's hash` — mismatch Blocks before launch.
  **P1** — the ISSUED authority-row cleanup was contradictory (rev 24 claimed `PENDING_TTL` sweeps an ISSUED
  row, but ISSUED is terminal + retains the signed document for replay). **rev 25 (§2.1):** PENDING rows
  expire at `PENDING_TTL_MS`; ISSUED rows are retained `ISSUED_RETENTION_MS = challenge_expiry_window +
  AUTHORITY_REPLAY_WINDOW_MS` then swept; `MAX_ISSUED_ROWS_PER_INSTALL`/`MAX_ISSUED_BYTES_PER_INSTALL` quota;
  deterministic `PENDING_SWEEP_INTERVAL_MS = 60000` sweep; post-retention replay ⇒ `no_pending_row`; the
  §4.10(g) "PENDING_TTL sweeps ISSUED" wording corrected. Fresh independent red-team over the rev-25 diff +
  real repo: no BLOCKER; the frozen 3b-1A/Wave-3a path + `model_profile_id`/lease/§7-provider cites
  byte-exact; `check_coordination` + `check_capabilities` GREEN live. NOT Architect-GREEN; 3b-1B code not started.
- **rev 26 (this doc):** the FINAL CONSOLIDATED remediation of the rev-25 Architect Design RED
  (**2 P0 · 3 P1** @ `bcd24fe`, exact-head CI #132 8/8 SUCCESS; rev-24 model-identity P0 + issued-cleanup P1
  CONFIRMED CLOSED) via the mandated **parallel fan-out (Tracks A–F) + one integrator + a fresh independent
  red-team over the whole §0–§9 + real code**. **P0-1 (§4.10(h))** internal a0/a/b/c/d + authority refusals
  ride a NEW signature-free `bridge.governed-turn-diagnostic.v1{stage, upstream_reason}` (≤256 B) /
  backend-direct authority reply → one `record_pre_verification_block` Block with a disjoint bounded-reason
  prefix (`governed_internal_refusal:` vs `governed_verdict_refused:` vs `governed_transport_failure:`),
  complete routing table, never confusable with a signed verdict; explicit `refused` terminal, only
  transport retries. **P0-2 (§2/§4.3/§7)** identity is the pure formula `"cfg-sha256:"+generation_config_sha256`
  (no mutable lookup); the registry becomes a non-identity `GOVERNED_EXECUTION_ALLOWLIST`; the 5-field
  resolver frozen to exact literals + `BROPS_GOVERNED_*` override contract; §7 recomputes from signed bytes
  so allowlist changes never reinterpret a past record. **P1-1 (§2.1.1)** canonical literal constants table;
  idempotent-before-quota; synchronous logical expiry; `pending_expired` vs `no_pending_row`; issue reply →
  `challenge_document_b64` in an 8192 frame. **P1-2 (§4.10(f))** three-phase output-stream lifecycle (LIVE/
  tombstone/`stream_unknown`) + `retained_until_ms`/`install_id` DDL columns + sweep + per-install quota +
  no-remint + output-bytes-outlive-stream. **P1-3 (§4.10(a0)/§2.4)** resource-admission `challenge_expired`
  gate + live-only staging quota. Track F swept the doc: all governed constants now literal, `e.g.` removed,
  the `EXECUTION_STARTING→EXECUTING` trigger + the `challenge_replay`/`acceptance_conflict`/`lease_not_ready`
  producing gates pinned. Fresh independent red-team over the full §0–§9 + real repo: no BLOCKER;
  `check_coordination` + `check_capabilities` GREEN live. NOT Architect-GREEN; 3b-1B code not started.
- **rev 26 preparation-P0 closure (this doc; rebased onto the repaired `main` `b6c6712` after Phase-0
  PR #33 merged):** three preparation-review P0 (independent, NOT the Architect verdict) closed on this
  HEAD before the audit. **P0-a — TCB code-integrity floor (§2.5, §4.3, §4.7):** lease pins
  `executor_executable_sha256` alongside the launcher; the launcher re-hashes the executor and
  `fexecve`s the exact verified `fd` (no TOCTOU); every TCB binary/config must be TCB-owned +
  non-writable by any runtime/login UID, verified fail-closed at start (`verify_tcb_integrity()`);
  new refusal `tcb_integrity_violation`. **P0-b — distinct-principal linchpin (§2.6):** the sidecar's
  own dedicated UID is now checked; `verify_distinct_principals()` refuses unless all seven runtime UIDs
  are set, pairwise-distinct, and ≠ the login UID (no single-UID collapse). **P0-c — enforced platform
  gate + Windows normative (§0.1, §0.W):** `platform_governed_execution_supported()` is a tested runtime
  gate (five primitives), Windows real-mode stays DISABLED (gate false) until a separately-audited
  Windows broker exists (required primitives specified); new refusal `platform_unsupported`; new §9
  TCB/principal/platform test matrix. Still NOT Architect-GREEN; 3b-1B code not started.
- **rev 27 (this doc) — closes the rev-26 Architect design RED (2 P0 + 3 P1 @ exact HEAD `b604cbc`, CI
  run 30270454903 9/9 GREEN; CI ≠ design GREEN).** **P0-1 (§0/§2.1/§2.6)** — the contradictory
  "desktop-UI/challenge-authority" is split into **eight principals**: the desktop-UI/backend client is an
  untrusted request producer owning NO challenge key/store; `desktop-challenge-authority` is a separate
  service/principal (own UID/SID) whose key + pending store are unreadable/unlistable/unwritable by the
  client, login user, sidecar, and every other principal; desktop→authority IPC authenticates the exact
  client principal; the **three threat actors** (login user / renderer-client / dedicated sidecar SERVICE
  UID — explicitly NOT "same-login-user") are stated separately; `verify_distinct_principals()` checks the
  **seven runtime service UIDs** (launcher excluded); topology diagram + platform gate + provisioning +
  Windows SIDs + ACL/IPC matrices + tests updated. **P0-2 (§2.7)** — the launcher is LOCKED to **Model A**:
  a root/TCB-owned setuid helper (mode 4750), invoked ONLY by the recorder, effective identity root/TCB,
  NOT a persistent runtime UID; fixed closed argv + cleared env + fixed FD set; drops all caps then
  permanently to the executor UID and `fexecve`s the pinned verified image; every field (binary/file
  owner, real/effective/saved UID, capabilities, invoking principal, direct-exec boundary, argv/env,
  inherited FDs, target exe+UID, start+exec integrity, failure/teardown, Windows equivalent, confused-
  deputy/oracle negative matrix) is fixed. **P1-1** canonical-state contradictions reconciled to one truth
  (`config/current_state.json` + 3 doc mirrors + PR body): preparation-P0 CLOSED, Architect verdict RED,
  open = the 2 P0 + 3 P1, next = rev-27 re-audit. **P1-2** PR #31 bound to a real exact-head
  `AUDIT_CANDIDATE_HEAD` marker (the `self_carrier` head-drift exemption REMOVED; nothing is exempt;
  checker generalized so a design-audit carrier uses the marker without a merge-transition block).
  **P1-3** global "no code" claims corrected: no Architect-approved or merged 3b-1B implementation exists;
  PR #32 is unapproved Draft/WIP with no authority over the design; adapt only after design GREEN. Still
  NOT Architect-GREEN; no Architect-approved 3b-1B implementation.
- **rev 28 (this doc) — closes the rev-27 Architect design RED (2 P0 + 4 P1 @ exact HEAD `0e41ef6`, CI
  run 30275888743 9/9 GREEN; CI ≠ design GREEN).** **P0-1 (§0/§2.1/§2.6)** — rev-27 wrongly folded the
  trusted Rust/Tauri backend (final verifier + persistence authority) into the untrusted client. rev-28
  splits **Renderer/session UI** (interactive login identity, fully untrusted, no key/DB/manifest/trust-
  state, reaches only the broker via a closed `{conversation_id, agent?}` command), **Trusted desktop
  verifier/broker** (dedicated service UID/SID, separate process, owns the receipt DB + pinned manifest +
  orchestration + final verification, resolves all authoritative inputs itself, never accepts renderer-
  supplied hashes/objects/verdicts/receipt fields), and **`desktop-challenge-authority`** (separate UID/
  SID, accepts create-pending/issue only from the broker UID). Broker-compromise stated OUT of scope (TCB
  final authority). `verify_distinct_principals()` checks the seven runtime service UIDs (broker/authority/
  sidecar/supervisor/recorder/executor/signer); renderer = login role, launcher = root/TCB helper. Renderer
  denial tests added. **P0-2 (§2.7/§4.7)** — launcher made executable + privilege-safe: the data FDs 3–6
  have `FD_CLOEXEC` explicitly CLEARED (survive both exec boundaries; rev-27's `O_CLOEXEC` would have closed
  the executor I/O); the exact privilege-drop syscall sequence is locked (verify → root cgroup setup →
  `setgroups([])` → `setresgid` → drop bounding/ambient caps via `CAP_SETPCAP` → `setresuid` → clear all cap
  sets → verify unprivileged → `PR_SET_NO_NEW_PRIVS` → `fexecve`); a setuid-root helper starts fully
  privileged (corrected); a real executable integration test + full negative matrix required. **P1-1** the
  obsolete "same-login-user sidecar" wording removed from the normative §2.1/§2.5 (3-actor model; history
  wording stays in this appendix). **P1-2** canonical state uses separate last_reviewed_candidate /
  last_architect_verdict / current_candidate / current_candidate_gate fields (rev-28 does not inherit the
  rev-27 verdict). **P1-3** banner + top STATUS identify rev-28; removed "rev-26 is the proposed candidate"
  and "3b-1B code has NOT started". **P1-4** PR #31 gains a carrier_transition (OPEN ⇒ design/impl/code-
  audit gate; MERGED ⇒ verify main + rebase PR #32) + a main-push anti-self-stale check; the checkers were
  generalized to snapshot-declared gate names so a design-audit carrier's transition validates without the
  Phase-0 gate values. Still NOT Architect-GREEN; no Architect-approved 3b-1B implementation.

## Appendix B — consistency-audit matrices (verification aids, non-normative)

- **Authority matrix:** challenge-authority→challenge only; challenge-root→registry only;
  lease-issuer→governed-turn-lease only; evidence-recorder→receipt/containment/evidence only;
  governed-turn-recorder (a supervisor-held key class, NOT a principal, P1-5)→terminal record only; supervisor-attestation→governed-sign-request
  attestation only; isolated-signer→governed-receipt-envelope only. No authority may sign
  another class's artifact (each artifact's validator pins its own `artifact_type`).
- **Handle matrix (a handle is always `SHA256(exact stored bytes)`, but "the bytes" differ by
  kind):**
  - **signed-document handles** (`challenge_handle`, `challenge_registry_handle`,
    `lease_handle`, `execution_receipt_handle`, **`record_handle`**) =
    `SHA256(JCS(exact signed document))`, i.e. `SHA256(JCS({payload, sig|root_sig|signature}))`;
  - **raw-artifact handles** (`system_handle`, `history_handle`,
    `generation_config_handle`, `output_handle`, `policy_bundle_handle`) =
    `SHA256(exact RAW artifact bytes)` (no JCS, no prefix) — these equal their `*_sha256`;
  - **containment handle** `containment_evidence_sha256` = `SHA256(JCS(containment artifact))`
    (a JCS-document digest; the `_sha256` suffix is legacy naming, not a raw-byte handle);
  - the **signer receipt envelope** (#12) is **transported**, not stored — no store handle;
  - **payload/identity hashes** (`registry_hash`, `request_sha256`, raw `*_sha256`,
    `attestation_evidence_sha256`) are digests, distinct from the document handles above and
    never used as a store lookup for a signed document.
- **Time matrix:** all governed-turn fields `_ms` integer; the reused **`bro_evidence`
  event/head is LEGACY epoch-seconds** (`issued_at_epoch`) and is **never compared to an ms
  window** (only its structural bindings cross in); base `execution-lease` `*_epoch` (seconds)
  untouched and unused here.
- **Replay matrix:** challenge `request_nonce` (one-time, desktop `receipt_challenges`) +
  `governed_turn_staging` (`UNIQUE(install_id,request_nonce)`+`UNIQUE(challenge_handle)`,
  pre-accept, no execution right) + supervisor acceptance ledger (execution, three UNIQUE
  constraints) + lease `nonce` + `receipt_id` (global, desktop `receipt_ids_seen`) +
  `execution_attempt_id` (unique) + `registry_epoch`/`registry_hash` (registry floor) +
  **signer-owned durable** evidence-head floor `governed_evidence_head_floor` (BEGIN IMMEDIATE
  CAS keyed on `head_sequence` monotonicity + chain-content `(event_count, last_sequence,
  final_event_hash)` — head-keyed A–E matrix; case A lower head → `stale_evidence`, B/D/E →
  `evidence_fork`, C unchanged re-anchor, D prefix-extend; `head_sequence` is a re-anchor counter,
  `highest_head_sequence` high-water; NO desktop head-floor table exists).
- **Principal/ACL matrix (P0-1 mode-fix `2750` owner-write / group read-only):** `brops-store`
  group = {`brops-supervisor`, `brops-recorder`, `brops-signer`(read-only)}; `store/sup/` owner
  `brops-supervisor` **`2750`**, `store/rec/` owner `brops-recorder` **`2750`** (group `r-x`,
  **NO group `w`** — only the namespace owner creates/renames/unlinks; the other owner + signer
  read/traverse only), artifacts `0640`, `umask 0027`, setgid kept only for group-inheritance;
  `_harden_dir` refuses `S_IWGRP`. Private-key dirs `0700` owner-only (incl. the
  **`governed-turn-recorder` key under `brops-supervisor`** — a supervisor-held key class, NOT a
  separate principal, P1-5); **evidence-head floor DB** `brops-signer` `0700`/`0600`; acceptance
  ledger + `governed_turn_staging` (+ its session/chunk tables, P1-6) + **`governed_output_streams`**
  (P0-2) `0700` supervisor-only; sidecar/executor/desktop = none.
- **Capability matrix:** executor = `INVOKE_GOVERNED_MODEL` only; `max_tool_calls=0`; no
  builder grants; launcher digest + model profile pinned.
- **Protocol matrix (P0-1 — KEEP shipped + ADD parallel, nothing renamed):** FROZEN
  (`brops.sign-request.v1`/`brops.sign-result.v1`/`brops.evidence-request.v1`/
  **`brops.governed-result.v1`** (the shipped `{status,output,receipt}` shape — `GOVERNED_RESULT_PROTOCOL`
  constant + emitter + `engine_sidecar` consumer stay byte-for-byte)/`bridge.result`/`bridge.task-request`)
  UNCHANGED; the NEW governed family — added in parallel (new `GOVERNED_TURN_RESULT_PROTOCOL`) —
  (the desktop→sidecar ingress **`bridge.governed-turn-submit.v1`** (P0-1, the frozen
  `bridge.task-request` cannot carry the challenge doc/inputs) / `brops.governed-turn-open.v1` /
  `brops.governed-sign-request.v1` / `brops.governed-sign-result.v1`
  / `brops.governed-evidence-request.v1` / **`brops.governed-turn-result.v1`** / the ingress
  `brops.governed-staging-open/-chunk/-final.v1` / the egress **pull**
  `brops.governed-turn-output-read.v1` (supervisor) + **`bridge.governed-turn-output-read.v1`**
  (desktop→sidecar) / `brops.governed-receipt-envelope.v1` / **`bridge.governed-turn-result.v1`** and
  their `-result` replies, §4.10) is disjoint; every governed protocol has ONE complete schema +
  `protocol` const discriminator + producer/consumer (§4.4–4.10); each path refuses the other's
  documents. Every `bridge.governed-*` schema is disjoint from `bridge.result` via its **required
  top-level `protocol` const** (NOT via `envelope_jcs_b64`, which is required in `bridge.result`
  too). All governed refusals draw from the closed **`GOVERNED_REFUSAL_REASONS`** union (§4.5, P1-4);
  the acceptance state enum is the closed 9-value set incl. **`EXPIRED`** (§5, P1-4).
