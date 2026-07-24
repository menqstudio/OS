# Wave 3b-1B — authoritative execution→receipt binding · ARCHITECT ADDENDUM (design-lock, rev 14 — CONSOLIDATED)

> **STATUS: ❌ DESIGN RED being closed — rev 14 is a PROPOSED design-GREEN candidate, NOT
> Architect-GREEN. 3b-1B code has NOT started.** rev 13 was Architect-reviewed at exact HEAD
> `415e3fdef10b8a571b2544ec889c9758ca883071` (exact-head CI **#117 / run 30056584243** fully
> GREEN — **CI GREEN ≠ design GREEN**); the Architect returned **Design RED** with **3 P0 + 4 P1
> targeted implementation-readiness findings** and directed a **mandatory parallel fan-out audit
> + one integrator + a fresh independent red-team, NOT a rewrite.** rev 14 was produced exactly
> that way: **seven independent read-only audit tracks** (A POSIX-ACL · B staging/acceptance FSM ·
> C output integrity · D framing/limits · E protocol/schema/routing · F evidence-floor ·
> G end-to-end adversarial) read the real repo code, a **single integrator** consolidated their
> evidence and edited in place, and a **fresh independent red-team** re-checked the diff. The
> rev-13 → rev-14 findings closed here: **P0-1** the `2770` store granted GROUP WRITE to signer +
> both namespace owners (breaking signer-read-only / no-cross-namespace-write) → an **enforceable
> `2750` owner-write / group read-only** model (dedicated `brops-recorder` principal, `umask 0027`,
> `_harden_dir` refuses `S_IWGRP`, per-principal machine tests + mode-regression guard) (§2.3);
> **P0-2** staging-open required an acceptance-ledger row that acceptance itself needed staging to
> create (deadlock), and the sidecar was told to upload `policy_bundle` against a nonexistent
> challenge hash → a **pre-accept `governed_turn_staging` state machine** (VERIFYING→UPLOADING→
> INPUTS_READY, gated by the verified challenge, no execution right) + **supervisor self-resolves/
> publishes/binds policy** (sidecar never uploads it) (§2.4, §5, §6); **P0-3** the rendered reply
> rode an unauthenticated transport string (a regression vs the v1 `receipt.rs` digest check) →
> **`output_b64`** bound by a desktop **length + SHA256 gate before any normalization** (§4.6,
> §6.1 s13, §7.1); **P1-4** a 256 KiB decoded chunk overflows the 256 KiB frame after base64 →
> **`MAX_STAGING_CHUNK_BYTES = 184320` (180 KiB)** + a dual decoded-and-frame cap with byte proof
> (§2.4); **P1-5** two orphan protocols + three field-list-only staging messages + an inner-only
> bridge object → **complete §4.10 control-plane schemas** + the full `{ok, output_b64, receipt,
> error}` bridge parent (§4.6); **P1-6** `EXECUTION_TIMEOUT` had no value → **`EXECUTION_TIMEOUT_MS
> = 120000`** nested inside `max_age_ms = 300000`, monotonic-elapsed / wall-signed, immediate
> SIGKILL + 5 s grace + 10 s cgroup teardown (§4.7, §1); **P1-7** the evidence-head floor had no
> storage/authority/CAS → a **signer-owned durable `governed_evidence_head_floor`** with a
> `BEGIN IMMEDIATE` CAS committed before the envelope is minted (§7). **All contracts below are
> OPEN until the Architect returns design-GREEN at the exact pushed HEAD.** STOP gates:
> `NoTrustedManifest` unchanged, no production "Verified", 3b-2/3b-3 not started, PR #31 not merged.

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
supervisor (owns the acceptance ledger §5 + the governed-turn lease issuer + the
            governed-turn-recorder key; signs the TERMINAL RECORD only)
  → EVIDENCE-RECORDER RUNNER  (dedicated recorder UID; holds the evidence-recorder key;
        signs the governed-turn execution RECEIPT + evidence chain/head; owns the
        executor pidfd/cgroup + output pipe + teardown measurement)
      → NARROW PRIVILEGED LAUNCHER  (tiny setuid helper: only setuid(executor)+exec the
            pinned model executor in a fresh cgroup/process group; holds NO key)
          → CONTAINED MODEL EXECUTOR  (executor UID; NO key/store access; reads 3 read-only
                input FDs, writes 1 output FD — nothing else, §2)
```

Distinct OS principals: **desktop-UI/challenge-authority**, **sidecar** (compromised
in-scope, same login user), **supervisor**, **evidence-recorder runner**, **privileged
launcher**, **contained executor**, **isolated receipt signer**, **governed-turn-recorder**.
Threat scope (from the ratified base design): sidecar RCE at the **same login user** is
IN scope; admin/root/kernel is OUT of scope. Where a platform cannot separate the
desktop-UI principal from the sidecar UID, governed real-mode is **FAIL-CLOSED** on that
platform (Windows is fail-closed until its broker is separately audited).

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
- The governed-turn lease **omits** the builder-only fields `repository`, `branch`,
  `worktree`, `head_sha`, `tree_identity`, and `protected_scope` — none has a verifier for a
  model turn. (If a future justified use reintroduces `protected_scope`, its type is an
  **array of exact non-pattern paths**, never a string.)

### 2.1 Challenge-authority trust boundary + creation channel (P0-2, NORMATIVE — no oracle)

The sidecar is compromised-in-scope (same login user). The desktop signed challenge
(artifact #1) is minted by a **dedicated `desktop-challenge-authority`** that is neither a
`sign(payload)` oracle nor a `create_pending(arbitrary_bytes) → sign(id)` two-step oracle.
The exact current contract (not history):

- **Store ownership:** the **pending-challenge store** (the trusted rows the authority builds
  challenges from) and the authority private key are owned by the authority's **own dedicated
  OS principal (UID/SID)**, mode owner-only (`0700`). **The sidecar UID can neither read, nor
  write, nor list** it — so it can neither exfiltrate the key nor tamper a row directly.
- **Distinct principals:** the **desktop-UI principal MUST be a UID distinct from the
  sidecar** principal. Where a platform cannot provide that separation, governed real-mode is
  **FAIL-CLOSED** on that platform (mirrors the Windows-broker stance, §0).
- **Creation channel:** pending-challenge rows are created **only** through an
  **authority-owned `AF_UNIX` channel**; on Linux the authority authenticates the peer with
  **`SO_PEERCRED`, allowlisting the exact desktop-UI UID** — the sidecar UID is denied. The
  caller supplies **structured authoritative turn facts** (`run_id`/`task_id`/context +
  `system_sha256`/`history_sha256`/`generation_config_sha256`/`request_sha256`/
  `requested_at_ms`) **or** an **authority-resolved protected row identifier** — **never
  challenge bytes and never a caller-chosen canonical payload.**
- **Authority builds the payload itself:** from its protected state the authority
  **constructs** the exact `brops.governed-turn-challenge.v1` payload (§4.1), stamps
  `challenge_issued_at_ms`/`challenge_expires_at_ms`, and signs once (consuming the pending
  id). It never signs caller-supplied bytes/fields.
- **How desktop facts cross the boundary without giving the sidecar the same capability:** the
  desktop-UI principal (a **distinct UID**) is the only peer the `SO_PEERCRED` allowlist
  admits; it hands the structured facts over the authenticated channel, and the authority
  writes its **own** store. The sidecar (a different UID) is denied the channel by
  `SO_PEERCRED` **and** the store by file ownership — so it can present neither facts the
  authority will trust nor bytes the authority will sign.
- **Mandatory Linux isolation tests:** the sidecar principal cannot (a) read/list the
  authority key dir, (b) `ptrace` the authority, (c) create a pending row via the channel
  (peer-UID denied), (d) directly read/write/list/mutate the pending store file(s)/DB, or
  (e) obtain a signature over caller-chosen bytes — all machine-proven, alongside the 3b-1A
  denials.

Full principal/ACL matrix in Appendix B. The acceptance ledger + protected content-addressed
store: **acceptance ledger** is supervisor-only `0700`; the **published content-addressed
store** is the group-shared model of §2.3 (NOT a literal `0700` — see §2.3); executor/sidecar
have no store or key access.

### 2.2 Protocol versioning (P0-1) — NEVER mutate the GREEN 3b-1A v1 protocols

The governed turn introduces new fields (integer `_ms` timestamps, no `builder_id`, new
echoes, new refusal reasons) that the **already-GREEN 3b-1A** strict `additionalProperties:
false` v1 schemas would reject. The ratified v1 protocols — **`brops.sign-request.v1`**
(requires `builder_id` + string `requested_at`/`completed_at`), **`brops.sign-result.v1`**
(closed 12-value `reason` enum), **`brops.evidence-request.v1`**, the **`bridge.result`**
receipt, and the **`bridge.task-request`** — are **frozen byte-for-byte** and MUST NOT be
changed; the 3b-1A signer-isolation positive control (`brops_isolation_prover.py` +
`test_brops_services.py` + `test_brops_isolation.py`) depends on them exactly.

The governed turn therefore uses a **separate `brops.governed-*` / `bridge.governed-*`
protocol family, in its own schema files**, selected by the `protocol` const (bridge
variants, which have no `protocol` const, are selected by a **separate sidecar emit branch**):
- **`brops.governed-sign-request.v1`** — `engine/contracts/brops-governed-sign-request.v1.schema.json`
- **`brops.governed-sign-result.v1`** — `engine/contracts/brops-governed-sign-result.v1.schema.json`
- **`brops.governed-evidence-request.v1`** — `engine/contracts/brops-governed-evidence-request.v1.schema.json`
- **`brops.governed-result.v1`** — `engine/contracts/brops-governed-result.v1.schema.json`
  (the supervisor→sidecar tagged union, COMPLETE in §4.10(e); the constant
  `GOVERNED_RESULT_PROTOCOL = "brops.governed-result.v1"` already exists in
  `brops_supervisor_service.py`)
- **`brops.governed-evidence-request.v1`** — the sidecar→supervisor execute/finalize trigger,
  COMPLETE in §4.10(d) (the governed path uses THIS, never the v1 `brops.evidence-request.v1`)
- **`brops.governed-staging-open/-chunk/-final.v1`** (+ their `-result` replies) — the bounded
  ingress control plane, COMPLETE in §4.10(a–c) (§2.4)
- **`brops.governed-result-open/-chunk/-final.v1`** (+ their `-result` replies) — the bounded
  chunked **result-return** stream for outputs > 131072 B (128 KiB), COMPLETE in §4.10(f) (symmetric egress)
- **`brops.governed-receipt-envelope.v1`** — the isolated-signer receipt envelope (§4.9)
- **`bridge.governed-result.v1`** — `bridge/contracts/bridge-governed-result.schema.json`
  (the COMPLETE parent `{ok, output_b64, receipt, error}`, §4.6; a distinct schema + a distinct
  sidecar emit branch; **`receipt.envelope_jcs_b64` is a required key absent from `bridge.result`**
  so the two are structurally disjoint; `bridge.result` stays untouched)

**Compatibility rule (LOCKED + tested):** the old v1 path accepts ONLY old v1 documents and
**refuses** any governed document; the governed path accepts ONLY governed documents and
**refuses** any v1 document. No shared file, enum, or required-key list. The 3b-1A v1 schema
files, parser functions, and tests are unchanged, and their positive-control round-trip runs
identically.

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
  attestation keys→`brops-supervisor`, recorder key→`brops-recorder`, governed-turn-recorder
  key→its owner). The **evidence-head floor DB** (§7 P1-7) is `brops-signer`-owned, dir `0700`/
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
  state TEXT NOT NULL,                    -- VERIFYING(transient) → UPLOADING → INPUTS_READY
  challenge_expires_at_ms INTEGER NOT NULL, created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL,
  UNIQUE (install_id, request_nonce), UNIQUE (challenge_handle) );
```
Staging states: **`VERIFYING`** (uncommitted — verify the signed challenge §4.1 + bound
registry snapshot §4.2: root sig, exact-document handle, full key-validity predicate; **do NOT
read the acceptance clock, do NOT consume the challenge nonce**) → CAS insert `absent →
`**`UPLOADING`** (the three `*_sha256` copied from the *verified* challenge) → **`INPUTS_READY`**
(all three published + re-hashed). Frozen protocol:
- **`brops.governed-staging-open.v1`** `{install_id, challenge_handle, request_nonce, artifact
  ∈ {system,history,generation_config}, declared_len, declared_sha256}` — the supervisor
  authenticates the peer UID, requires an `UPLOADING` `governed_turn_staging` row for
  `(install_id, request_nonce, challenge_handle)` (creating it via `VERIFYING` on first open),
  requires `declared_sha256 == the verified challenge's committed *_sha256` for that artifact,
  rejects `declared_len` over the per-artifact ceiling, and returns an opaque
  `staging_session_id` bound to exactly `(challenge_handle, request_nonce, install_id,
  artifact)`; one in-flight session per (tuple, artifact); duplicate open refused. `policy_bundle`
  is **not** an accepted `artifact` value (refused).
- **`brops.governed-staging-chunk.v1`** `{staging_session_id, seq, bytes_b64}` — each chunk ≤
  **`MAX_STAGING_CHUNK_BYTES = 184320` decoded bytes (180 KiB, P1-4)**. Per session `{next_seq
  (0-based, strictly increasing), running_sha256, byte_count, O_EXCL temp fd}`: `seq != next_seq`
  ⇒ refuse (dup / gap / out-of-order in one predicate); `byte_count+len > declared_len` (or >
  ceiling) ⇒ refuse.
- **`brops.governed-staging-final.v1`** `{staging_session_id, seq==next_seq}` — fsync temp,
  assert `byte_count == declared_len` and `running_sha256 == declared_sha256`, compute
  `handle = digest`, and **require `handle == the challenge's committed `*_sha256`** for that
  artifact (else refuse — never publish bytes the challenge did not authorize); then atomic
  create-if-absent publish into `store/sup/` (divergent existing handle refused); record the
  handle on the staging row. When all three input handles are set, the row advances to
  `INPUTS_READY`.
- **Frame sizing proof (P1-4, LOCKED):** the IPC frame body cap is `MAX_FRAME_BYTES = 262144`
  (`brops_protocol.py`, body-only, compact JSON, base64url **no padding**). A `184320`-byte
  decoded chunk base64url-encodes to `4·⌈184320/3⌉ = 245760` bytes; plus the chunk-frame JSON
  envelope (`{"protocol":"brops.governed-staging-chunk.v1","staging_session_id":"…",
  "seq":<int>,"bytes_b64":"…"}`, ≤ ~211 bytes with a ≤128-char session id + ≤10-digit seq) =
  **≤ 245971 ≤ 262144** (≥ 16 KiB headroom). A 256 KiB decoded chunk would encode to `349526` +
  envelope > 262144 — **rejected**. The validator MUST check **BOTH** caps independently and
  fail-closed: (1) `decoded_len ≤ 184320`, **and** (2) the serialized frame ≤ `262144` (reuse
  `encode_frame`/`read_frame`). Tests: exact-max (184320 → accept), max+1 (184321 → refuse on
  the DECODED cap even though its frame still fits), oversized-serialized-frame (refuse on the
  FRAME cap before decode), and a `256 KiB`-decoded regression (refused by both).
- **Per-artifact ceilings (LOCKED):** `system ≤ 256 KiB`, `history ≤ 8 MiB`,
  `generation_config ≤ 64 KiB` (match the desktop's real `ai.rs` caps); `policy_bundle ≤ 64 KiB`
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
- **Quota / expiry / crash:** per-`install_id` staging quota; a session/row **TTL bound to the
  signed challenge's own `challenge_expires_at_ms`** (NOT an acceptance window — none exists
  yet); startup + sweep unlink orphan `.tmp-*.part` and delete expired/abandoned staging rows
  **WITHOUT consuming the challenge nonce** — the desktop may re-issue against the same signed
  challenge until the challenge itself expires (this denies the sidecar a nonce-burning DoS). A
  partial temp is never linked to a handle; `read(handle)` re-verifies sha.
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
| 1 | `brops.governed-turn-challenge.v1` | desktop-UI **challenge-authority** | `desktop-challenge-authority` key (`challenge_key_id`) | supervisor §5; `LiveRunStateProvider` §7 | ms | `challenge_handle = SHA256(JCS({payload,sig}))` | supervisor store (published §6) | `request_nonce` (one-time) | binds `run_id`/`task_id`/context + `*_sha256` |
| 2 | `brops.challenge-key-registry.v1` | operator (root-signed) | challenge-**root** anchor (`root_key_id`) | supervisor §5; provider §7 | ms | `challenge_registry_handle = SHA256(JCS({payload,root_sig}))` | supervisor store | `registry_epoch` + `registry_hash` (anti-rollback) | `registry_hash = SHA256(JCS(payload))` (identity, ≠ handle) |
| 3 | acceptance-ledger row (§5) | supervisor | — (durable DB, not signed) | supervisor (recovery); provider (indirect) | ms | — | supervisor acceptance DB (`0700`) | `UNIQUE(install_id,request_nonce)`, `UNIQUE(challenge_handle)`, `UNIQUE(execution_attempt_id)` | holds lease_payload bytes + state |
| 4 | `brops.governed-turn-lease.v1` | supervisor **governed-turn lease issuer** | lease-issuer key | recorder; supervisor; provider §7 | ms | `lease_handle = SHA256(JCS({payload,signature}))` | supervisor store | `nonce` (lease) + `execution_attempt_id` | binds challenge #1 via `challenge_handle`/`challenge_key_id` + registry #2 + `challenge_accepted_at_ms` |
| 5 | `brops.governed-sign-request.v1` (attested evidence) | supervisor | **supervisor attestation** key (`supervisor_attestation_key_id`) over `JCS(evidence)` | isolated signer §6.1; desktop re-verifies the attestation bytes | ms | (transported, not stored) | — | `request_nonce` + `execution_attempt_id` | echoes #4/#6 handles; every `*_sha256` DERIVED by signer |
| 6 | `brops.governed-turn-execution-receipt.v1` | recorder runner | **evidence-recorder** key | isolated signer's `LiveRunStateProvider` §7; `verify_governed_turn_receipt` | ms | `execution_receipt_handle = SHA256(JCS({payload,signature}))` | recorder store namespace (§2.3) | `receipt_id` (global unique) | `output_handle == output_sha256`; binds attempt/lease |
| 7 | `brops.governed-turn-containment.v1` | recorder runner | evidence event (evidence-recorder) | provider §7 | ms | `containment_evidence_sha256 = SHA256(JCS(artifact))` | recorder store namespace | attempt+lease | `contained==true`, closed `teardown_outcome` enum |
| 8 | evidence event / head (`bro_evidence`, REUSED) | recorder runner | **evidence-recorder** key | isolated signer's `LiveRunStateProvider` §7 | **legacy epoch-seconds (never compared to ms)** | `event_hash` chain | evidence chain + **signer-owned `governed_evidence_head_floor`** (§7 P1-7) | signer-owned `head_sequence` vs durable `highest_sequence` high-water (BEGIN IMMEDIATE CAS) | head seq strictly-increasing per chain (structural) |
| 9 | `brops.governed-sign-result.v1` | isolated signer | signer key (the receipt envelope #12) | supervisor → bridge → desktop | ms | (transported) | — | `receipt_id` | tagged union `signed`/`refused`; echoes TRANSPORT-ONLY |
| 10 | `bridge.governed-result.v1` receipt | sidecar (transport) | — (carries #9/#12 signed bytes) | **desktop verifies signatures, NO store access** | ms | (transported) | — | `receipt_id` | echoes TRANSPORT-ONLY; desktop equality-checks vs the verified signed envelope #12 |
| 11 | `brops.governed-turn-record.v1` | supervisor | **`governed-turn-recorder`** key (dedicated) | isolated signer's `LiveRunStateProvider` §7 | ms | `record_handle = SHA256(JCS({payload,signature}))` (also create-if-absent at `<run_id>__<execution_attempt_id>.json`) | supervisor store namespace | `(run_id, execution_attempt_id)` | binds ALL of #1,#2,#4 (via `lease_handle`),#6 (via `execution_receipt_handle`),#7,#8 + `challenge_accepted_at_ms` |
| 12 | governed **receipt envelope** (`brops.governed-receipt-envelope.v1`) | isolated signer | **isolated-signer** key (pinned by desktop) | **desktop** (§6.1 step 13) | ms | (inside `envelope_jcs_b64`) | — | `receipt_id` | binds `record_handle`/`lease_handle`/`execution_receipt_handle`/`request_nonce`/`execution_attempt_id`/head fields/attestation digest |

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
The authority **builds** this from the trusted desktop DB (caller supplies only a
protected pending-challenge ID, never bytes; §5 P0-1 history); it does **not** carry
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
    "model_profile_id": "<string ≤128>",               // bound model endpoint/profile
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
  resolved registry bindings; enforces `requested_at_ms ≤ challenge_accepted_at_ms` and
  `lease_issued_at_ms ≤ challenge_accepted_at_ms ≤ lease_expires_at_ms` at signing; signs.
- **`validate_governed_turn_lease`:** `verify_artifact` (issuer) → strict-decode the exact
  key set → return fields. Refuses a missing/extra key, non-int `_ms`, `schema != 1`,
  `nonce` length ∉ [16,128], `allowed_capabilities != ["INVOKE_GOVERNED_MODEL"]`,
  `max_tool_calls != 0`. **Separate** from the base `validate_execution_lease` (which would
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
    "evidence_head_sequence": <int>, "evidence_final_event_hash": "<64hex>" } }
```
`evidence` is authoritative ONLY because `attestation.sig` covers `JCS(evidence)`; every
`*_handle`/`*_sha256` is **DERIVED by the signer** from the store bytes, never trusted from
the wire. Malformed/oversize ⇒ `refused` (§4.5).

### 4.5 `brops.governed-sign-result.v1` — (artifact #9), COMPLETE tagged union
**NEW governed protocol (§2.2) — the ratified `brops.sign-result.v1` is untouched.**
`additionalProperties:false` per member; unknown/duplicate-key rejection; frame ≤ 64 KiB.
```jsonc
// status == "signed":
{ "protocol": "brops.governed-sign-result.v1", "status": "signed",
  "receipt_id": "<string ≤128>",
  "envelope_jcs_b64": "<b64url>", "signature_b64": "<b64url 86>", "key_id": "<string ≤128>",
  "attestation_evidence_jcs_b64": "<b64url>", "attestation_signature_b64": "<b64url 86>",
  "supervisor_attestation_key_id": "<string ≤128>",
  "run_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>", "lease_id": "<string ≤128>",
  // ── TRANSPORT-ONLY echoes (desktop equality-checks against verified authority) ──
  "task_id": "<string ≤128>", "challenge_accepted_at_ms": <int>,
  "challenge_handle": "<64hex>", "challenge_key_id": "<string ≤128>",
  "challenge_registry_handle": "<64hex>", "challenge_registry_hash": "<64hex>",
  "challenge_registry_epoch": <int>, "challenge_registry_root_key_id": "<string ≤128>",
  "lease_handle": "<64hex>", "execution_receipt_handle": "<64hex>",
  "evidence_head_sequence": <int>, "evidence_final_event_hash": "<64hex>" }
// status == "refused":
{ "protocol": "brops.governed-sign-result.v1", "status": "refused",
  "receipt_id": "<string ≤128>" | null, "reason": "<enum>" }
```
Closed `reason` enum (the ratified 12 + governed additions): `attestation_invalid,
not_completed, run_binding_invalid, nonce_mismatch, handle_missing, hash_mismatch,
policy_mismatch, containment_missing, identity_denied, timestamp_invalid, oversize,
malformed, challenge_replay, acceptance_conflict, lease_not_ready, output_oversize,
output_timeout`. A `signed` result REQUIRES both `envelope_jcs_b64` and `signature_b64`;
anything else ⇒ the desktop Blocks.

### 4.6 `bridge.governed-result.v1` — COMPLETE parent object (artifact #10)
**NEW bridge protocol (§2.2) — the ratified `bridge.result` is untouched; the governed path
uses a separate sidecar emit branch (bridge schemas carry no `protocol` const).** This is the
**full outer object** (mirrors the frozen `bridge-result.schema.json` parent
`{ok, result, receipt, error}`), NOT the inner receipt alone. `additionalProperties:false` on
both objects; unknown-field rejection; `receipt` non-null iff `ok==true`; `error` non-null iff
`ok==false`. **Governed/v1 discrimination (P1-5):** `receipt.envelope_jcs_b64` is a **required
key that never appears in `bridge.result`**, so a cross-fed v1/governed document is refused in
both directions (tested). **The exact output is bound by `output_sha256`/`output_bytes` (in the
signed envelope) and delivered by the bounded chunked result-stream (§4.10f) — NOT inlined in
this frame** (an 8 MiB output base64-encodes to ~11.2 MiB, far over the `262144` frame cap, so
inlining would be un-transportable; the egress mirrors the §2.4 chunked ingress). `output_b64`
appears inline **only** as the small-output fast path, gated at **`output_bytes ≤
INLINE_OUTPUT_MAX = 131072` (128 KiB)** — chosen so the whole `status:"signed"`/`ok:true` frame
stays ≤ `262144` **even with every co-resident field at its schema maximum**:
`output_b64(131072) = 4·⌈131072/3⌉ = 174764` + `containment_evidence_b64 ≤ 65536` +
`envelope_jcs_b64` (~4 KiB) + `attestation_evidence_jcs_b64` (~5.5 KiB) + two 86-char sigs + six
≤128 id echoes + hashes/structure ≈ **252032 ≤ 262144** (~10 KiB headroom). The larger
`MAX_STAGING_CHUNK_BYTES = 184320` is the **ingress** chunk cap (its frame has no co-resident
containment/envelope fields) and does **not** apply here. Any accepted output `> 131072` MUST
arrive via the §4.10f stream and `output_b64` is then `null`.
```jsonc
{ "ok": <bool>,
  "output_b64": "<b64url of the output bytes> | null",  // inline ONLY if output_bytes ≤ 131072 (128 KiB); else null → §4.10f stream
  "output_streamed": <bool>,                            // true iff the output arrived via the §4.10f chunked stream
  "receipt": {                                    // non-null iff ok==true; ALL fields TRANSPORT-ONLY
    "task_id": "<string ≤128>", "status": "<string ≤64>", "exit_code": <int> | null,
    "evidence": ["<string ≤256>", ...],           // ≤ 64 entries (bounded so the frame-fit proof holds)
    "envelope_jcs_b64": "<b64url>", "signature_b64": "<b64url 86>",        // REQUIRED when ok (governed discriminator)
    "containment_evidence_b64": "<b64url ≤64KiB>" | null,
    "attestation_evidence_jcs_b64": "<b64url>", "attestation_signature_b64": "<b64url 86>",
    "supervisor_attestation_key_id": "<string ≤128>",
    "run_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>", "lease_id": "<string ≤128>",
    "challenge_accepted_at_ms": <int>,
    "challenge_handle": "<64hex>", "challenge_key_id": "<string ≤128>",
    "challenge_registry_handle": "<64hex>", "challenge_registry_hash": "<64hex>",
    "challenge_registry_epoch": <int>, "challenge_registry_root_key_id": "<string ≤128>",
    "lease_handle": "<64hex>", "execution_receipt_handle": "<64hex>",
    "output_sha256": "<64hex>", "output_bytes": <int>,
    "evidence_head_sequence": <int>, "evidence_final_event_hash": "<64hex>" } | null,
  "error": { "reason": "<enum, mirrors §4.5>", "receipt_id": "<string ≤128>" | null } | null }
```
Exactly one output source is present: `output_b64` non-null **xor** `output_streamed==true`
(both-absent or both-present ⇒ Block). Either way the desktop applies the SAME length+SHA256
gate below over the (inline-decoded **or** reassembled) bytes.
**Output binding (P0-3, LOCKED) — the transported reply is cryptographically bound.** The
governed reply text does **not** ride an unauthenticated `bridge.result.result` string; it is
obtained as **exact bytes** either inline via `output_b64` (small-output fast path) or via the
bounded chunked result-stream (§4.10f, larger outputs). In the §6.1 step-13 / §7.1 desktop
transaction, **after** verifying the isolated-signer envelope signature and **before any
normalization/render**, the desktop MUST obtain the exact output bytes (decode `output_b64` **or**
reassemble the §4.10f stream into a bounded ≤ 8 MiB buffer), then assert `len(bytes) ==
envelope.output_bytes` (length gate) and `SHA256(bytes) == envelope.output_sha256` (digest gate,
over raw bytes — **no trim/NFC/NFKC/CRLF/lossy decode**); only then strict-UTF8 decode for UI
display (invalid UTF-8 ⇒ Block, unless the product explicitly supports binary output); render
only on `BEGIN IMMEDIATE` commit. Negative tests: substitution, one-byte mutation, truncation,
appended byte, Unicode-normalization (NFC/NFKC), CRLF conversion, invalid-UTF8→U+FFFD,
wrong-length, and — for the streamed path — a tampered/mis-ordered/short chunk (each MUST Block).

**Authority rule (LOCKED, P0-3) — the desktop verifies SIGNATURES, it does NOT read the
protected store.** The protected store is on the engine host, group-`brops-store`, and is
**not readable by the desktop principal** (§2.3); the desktop may also be a different runtime/
host. So the **deep protected-store verification** (fetch record/lease/receipt/challenge/
registry/containment/head **by handle**, re-hash, re-verify each signature, cross-check
bindings) is performed by the **isolated signer's `LiveRunStateProvider`** (§6.1 step 10, §7),
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
length prefix); FD `6` is the write-only output pipe. The launcher validates each input FD is
`O_RDONLY`, `S_ISREG`, offset 0, size ≤ the per-artifact ceiling (system ≤256 KiB, history
≤8 MiB, generation_config ≤64 KiB), backed by a `brops-store` store inode; it closes every
other FD, validates the pinned `launcher_executable_sha256` + fixed caller/target UID, drops
caps, then `setuid(executor)+exec`. The executor reads each input to EOF and writes only its
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
  `orphan-quarantined`/`timed-out` ⇒ **no accepted record**. Grace + teardown (15000 ms) fit
  inside the 40000 ms post-exec reserve.
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
  partial-write crash (no receipt, ledger → `RECOVERY_REQUIRED`/`BLOCKED`).

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
    "evidence_final_event_hash": "<64hex>", "evidence_head_sequence": <int>,
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
`brops.governed-sign-result.v1` §4.5 + `bridge.governed-result.v1` §4.6).
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
    "evidence_final_event_hash": "<64hex>", "evidence_head_sequence": <int>,
    "supervisor_attestation_key_id": "<string ≤128>",
    "attestation_evidence_sha256": "<64hex>" },   // SHA256(the JCS(governed-sign-request evidence) the supervisor attested
  "signature": "<detached Ed25519 over JCS(payload), isolated-signer key>" }
```
The desktop (§6.1 step 13) verifies this signature under the pinned isolated-signer key, then
verifies the supervisor attestation and confirms `attestation_evidence_sha256` matches, then
consumes `request_nonce` + checks `receipt_id` uniqueness + freshness, then equality-checks the
bridge echoes — all without any protected-store access.

### 4.10 Control-plane protocols (P1-5) — staging, execute-trigger, supervisor→sidecar result

Every named governed protocol has ONE complete normative schema, a `protocol` const
discriminator, a producer, a consumer, and strict rejection of any v1 document (and vice
versa). `additionalProperties:false` + unknown/duplicate-key rejection everywhere; requests are
schema-validated **before** any side effect. These complete the two names that previously had no
§4 schema (`brops.governed-result.v1`, `brops.governed-evidence-request.v1`) and the three
staging messages that were field-lists only.

**(a) `brops.governed-staging-open.v1`** — sidecar→supervisor (§2.4). Reply
`brops.governed-staging-open-result.v1`. Frame ≤ 4 KiB.
```jsonc
// request:
{ "protocol": "brops.governed-staging-open.v1",
  "install_id": "<string ≤128>", "challenge_handle": "<64hex>", "request_nonce": "<string ≤128>",
  "artifact": "system" | "history" | "generation_config",     // policy_bundle REFUSED
  "declared_len": <int 0..8388608>, "declared_sha256": "<64hex>" }
// reply (opened):
{ "protocol": "brops.governed-staging-open-result.v1", "status": "opened",
  "staging_session_id": "<opaque string ≤128>", "next_seq": 0 }
// reply (refused): { "protocol": "brops.governed-staging-open-result.v1", "status": "refused", "reason": "<enum>" }
```
Refused reasons: `peer_denied, no_staging_row, artifact_invalid, digest_mismatch, oversize,
duplicate_session, malformed`. `declared_sha256` MUST equal the verified challenge's committed
`*_sha256` for `artifact`; `declared_len` ≤ that artifact's ceiling (§2.4).

**(b) `brops.governed-staging-chunk.v1`** — sidecar→supervisor. Reply
`brops.governed-staging-chunk-result.v1`. Frame ≤ `MAX_FRAME_BYTES = 262144`.
```jsonc
// request:
{ "protocol": "brops.governed-staging-chunk.v1", "staging_session_id": "<string ≤128>",
  "seq": <int ≥0>, "bytes_b64": "<b64url, decoded ≤ 184320 (P1-4)>" }
// reply: { "protocol": "brops.governed-staging-chunk-result.v1", "status": "ack" | "refused",
//          "next_seq": <int>, "reason": "<enum>" | null }
```
Refused reasons: `session_unknown, seq_mismatch, oversize_chunk, oversize_frame, over_declared,
malformed`. Validator enforces **both** `len(decode(bytes_b64)) ≤ 184320` **and** serialized
frame ≤ 262144 (§2.4 P1-4).

**(c) `brops.governed-staging-final.v1`** — sidecar→supervisor. Reply
`brops.governed-staging-final-result.v1`. Frame ≤ 4 KiB.
```jsonc
// request: { "protocol": "brops.governed-staging-final.v1", "staging_session_id": "<string ≤128>", "seq": <int ≥0> }
// reply (published):
{ "protocol": "brops.governed-staging-final-result.v1", "status": "published",
  "artifact": "system" | "history" | "generation_config", "handle": "<64hex>",
  "inputs_ready": <bool> }          // true once all three inputs are published + re-hashed
// reply (refused): { ..., "status": "refused", "reason": "<enum>" }
```
Refused reasons: `session_unknown, seq_mismatch, len_mismatch, sha_mismatch, handle_not_challenge,
publish_divergent, malformed`. Requires `handle == the challenge's committed *_sha256`.

**(d) `brops.governed-evidence-request.v1`** — sidecar→supervisor **execute/finalize trigger**
(the message that, once the staging row is `INPUTS_READY`, asks the supervisor to run the
governed turn and produce the signed result). Replaces the mis-named use of the v1
`brops.evidence-request.v1` const on the governed path. Reply is `brops.governed-result.v1` (e).
Frame ≤ 4 KiB.
```jsonc
{ "protocol": "brops.governed-evidence-request.v1",
  "install_id": "<string ≤128>", "challenge_handle": "<64hex>", "request_nonce": "<string ≤128>" }
```
The supervisor authenticates the peer UID, requires the `INPUTS_READY` staging row for
`(install_id, request_nonce, challenge_handle)`, then drives §5 acceptance→lease→execution→
record and the isolated-signer flow (§6.1). It carries **no** `execution_attempt_id` (the
supervisor reserves it, §5) and grants no authority by itself.

**(e) `brops.governed-result.v1`** — supervisor→sidecar **COMPLETE tagged union** (the constant
`GOVERNED_RESULT_PROTOCOL = "brops.governed-result.v1"` already exists in
`brops_supervisor_service.py`). The sidecar re-frames it into `bridge.governed-result.v1`
(§4.6). Frame ≤ `MAX_FRAME_BYTES = 262144`; it carries `output_b64` **inline only when
`output_bytes ≤ INLINE_OUTPUT_MAX = 131072` (128 KiB)** — the frame-fit budget of §4.6 (which
counts the co-resident `containment_evidence_b64 ≤ 65536` + `envelope`/`attestation` fields),
NOT the larger ingress chunk cap — otherwise `output_b64 == null` and `output_streamed == true`
and the output arrives via §4.10(f). All non-signature fields TRANSPORT-ONLY.
```jsonc
// status == "signed":
{ "protocol": "brops.governed-result.v1", "status": "signed", "receipt_id": "<string ≤128>",
  "output_b64": "<b64url of output bytes> | null",   // inline ONLY if output_bytes ≤ 131072 (128 KiB); else null
  "output_streamed": <bool>,                          // true iff delivered via §4.10(f)
  "output_bytes": <int 0..8388608>, "output_sha256": "<64hex>",   // TRANSPORT echo of the signed envelope value
  "envelope_jcs_b64": "<b64url>", "signature_b64": "<b64url 86>", "key_id": "<string ≤128>",
  "attestation_evidence_jcs_b64": "<b64url>", "attestation_signature_b64": "<b64url 86>",
  "supervisor_attestation_key_id": "<string ≤128>",
  "containment_evidence_b64": "<b64url ≤64KiB>" | null,
  "run_id": "<string ≤128>", "execution_attempt_id": "<string ≤128>", "lease_id": "<string ≤128>" }
// status == "refused":
{ "protocol": "brops.governed-result.v1", "status": "refused",
  "receipt_id": "<string ≤128>" | null, "reason": "<enum, mirrors §4.5>" }
```
A `signed` result REQUIRES `envelope_jcs_b64` + `signature_b64` and **exactly one** output
source (`output_b64` non-null **xor** `output_streamed==true`); anything else ⇒ the
sidecar/desktop Blocks. The desktop's authority for the output is always the signed envelope's
`output_sha256`/`output_bytes`, applied to the inline-decoded or reassembled bytes (§4.6/§7.1).

**(f) `brops.governed-result-open/-chunk/-final.v1`** — the bounded **chunked result-return
stream** (supervisor→sidecar→desktop), symmetric to the §2.4 ingress, used whenever
`output_bytes > INLINE_OUTPUT_MAX = 131072` (each stream **chunk** still ≤ 184320 decoded, the
§2.4 frame math — the 131072 gate is only the inline-vs-stream threshold). Each governed hop reads then re-emits chunks; the desktop reassembles
into a bounded ≤ 8 MiB buffer and applies the §4.6/§7.1 length+SHA256 gate against the **signed
envelope** — so a tampered/re-ordered/dropped chunk from the untrusted sidecar is caught by the
digest, exactly as inline substitution is. Frames obey `MAX_FRAME_BYTES = 262144`.
```jsonc
// open (reply brops.governed-result-open-result.v1 {result_stream_id, next_seq:0}):
{ "protocol": "brops.governed-result-open.v1", "receipt_id": "<string ≤128>",
  "declared_output_bytes": <int 1..8388608>, "declared_output_sha256": "<64hex>" }   // MUST equal the envelope's
// chunk (reply -chunk-result {next_seq}):
{ "protocol": "brops.governed-result-chunk.v1", "result_stream_id": "<string ≤128>",
  "seq": <int ≥0>, "bytes_b64": "<b64url, decoded ≤ 184320 (P1-4 frame math)>" }
// final (reply -final-result {status}):
{ "protocol": "brops.governed-result-final.v1", "result_stream_id": "<string ≤128>", "seq": <int ≥0> }
```
Chunk rules mirror §2.4: `seq == next_seq` else refuse (dup/gap/out-of-order); running byte-count
`≤ declared_output_bytes`; each chunk decoded `≤ 184320` **and** serialized frame `≤ 262144`
(dual cap). On final the desktop asserts `reassembled_len == declared_output_bytes ==
envelope.output_bytes` and `SHA256(reassembled) == declared_output_sha256 ==
envelope.output_sha256` **before** any normalization/render (§7.1). `declared_output_*` are
transport-only; the **signed envelope** is the authority. Tests: exact-max chunk, max+1 (decoded),
oversized frame, mis-ordered seq, dropped final, and a 1-byte-tampered chunk (all Block).

**Routing/rejection (LOCKED + tested):** each control-plane message
is dispatched by its `protocol` const; a governed handler refuses any v1 `protocol` value and
each v1 handler refuses any `brops.governed-*` value — no shared schema file, enum, or
required-key list.

---

## 5. Durable supervisor acceptance — state machine + outbox (P0-2)

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
  state                          TEXT NOT NULL,    -- enum below
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

**State enum (full lifecycle across the two tables):**
pre-accept in `governed_turn_staging` (§2.4): `VERIFYING` → `UPLOADING` → `INPUTS_READY`
(no `execution_attempt_id`, **no execution right**); then in `governed_turn_acceptance`:
`UNSEEN` (absent) → `ACCEPTED_PREPARED` → `LEASE_READY` → `EXECUTION_STARTING` →
`EXECUTING` → `COMPLETED`; terminal `BLOCKED`, `FAILED`, `RECOVERY_REQUIRED`. There is **no
circular dependency**: staging is gated by the *verified signed challenge* (§2.4), and the
acceptance row is created only **after** the staging row reaches `INPUTS_READY` — the two never
depend on each other.

**Outbox sequence (exact):**
1. **Pre-accept ingress (§2.4):** verify the signed challenge (§4.1) + bound registry snapshot
   (§4.2) — root sig, exact-document handle, full key-validity predicate (§7); create the
   `governed_turn_staging` row (`VERIFYING`→`UPLOADING`); the sidecar uploads only
   system/history/generation_config; the **supervisor self-resolves + publishes + binds** the
   policy bundle (§2.4 policy note). When all three inputs are published + re-hash to the
   challenge digests, the staging row is `INPUTS_READY`. **No acceptance/clock/nonce-consume
   happens here.**
2. Only once the staging row is `INPUTS_READY`, read the supervisor clock **exactly once** →
   `challenge_accepted_at_ms`.
3. Validate the window + revocation using that exact value (§1, §7).
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
9. Persist `LEASE_READY → EXECUTION_STARTING` **before** launching the recorder/executor.
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
    moves to `RECOVERY_REQUIRED`/`BLOCKED` (fail-closed). An owner/operator may **inspect**
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
supervisor CASes to `EXECUTION_STARTING` then launches once;** **after `EXECUTION_STARTING`
commit but before the launcher call → `RECOVERY_REQUIRED`/`BLOCKED`, never relaunch;** **crash
inside the launcher before `exec` → `RECOVERY_REQUIRED`/`BLOCKED`;** **crash immediately after
`exec` / child exits before `EXECUTING` persistence / a remote model call occurred but no
output/receipt exists → `RECOVERY_REQUIRED`/`BLOCKED`, never relaunch;** after receipt/evidence
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
exists**: each must land in `RECOVERY_REQUIRED`/`BLOCKED` with no relaunch.

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

No output renders before step 13 commits.
1. **Verify** the signed challenge (§4.1) + the bound registry snapshot (§4.2) — root sig,
   exact-document handle, full key-validity predicate (§7).
2. **Acceptance ledger / outbox** (§5): read the clock once → `challenge_accepted_at_ms`;
   CAS `UNSEEN → ACCEPTED_PREPARED`; reserve `execution_attempt_id`; persist bindings + exact
   lease payload bytes; commit.
3. **Lease publication + `LEASE_READY`**: idempotently sign + publish the governed-turn lease
   (`lease_handle`); CAS to `LEASE_READY` only after it re-hashes + `validate_governed_turn_lease`.
4. **One-time recorder/executor launch** (CAS `LEASE_READY → EXECUTION_STARTING` first;
   never auto-relaunch after, §5 P0-1); the launcher enforces the FD/executable contract (§4.7).
5. **Output + containment publication** by the recorder (`output_handle`,
   `containment_evidence_sha256`).
6. **Governed execution receipt + evidence/head publication** by the recorder
   (`execution_receipt_handle`, evidence-recorder key).
7. **Supervisor verification** of the recorder chain by handle.
8. **Terminal governed-turn record publication** (`governed-turn-recorder` key), binding
   `lease_handle` + `execution_receipt_handle` + all §4.8 fields (atomic create-if-absent).
9. **Supervisor constructs the exact attested `brops.governed-sign-request.v1`** (§4.4) and
   signs it with the supervisor attestation key.
10. **Isolated signer invokes `LiveRunStateProvider`** (§7) — the ONLY deep protected-store
    verifier — to verify the terminal chain (record + lease-by-handle + receipt-by-handle +
    challenge + registry + containment + evidence head, incl. the **signer-owned durable
    head-floor CAS `governed_evidence_head_floor`**, committed before the envelope is minted,
    §7 P1-7). The desktop never does this (no store access).
11. **Isolated signer builds + signs the `brops.governed-receipt-envelope.v1`** (§4.9,
    isolated-signer key) binding record/lease/receipt handles + nonce/attempt + head +
    attestation digest, and returns **`brops.governed-sign-result.v1`** (§4.5) — `signed`
    (envelope + signature + attestation record) or `refused`.
12. **Bridge transports** it as **`bridge.governed-result.v1`** (§4.6) — transport-only.
13. **Desktop final acceptance transaction** (one `BEGIN IMMEDIATE`, NO store access): verify
    the **isolated-signer envelope signature** (pinned key) → verify the **supervisor
    attestation** signature + `attestation_evidence_sha256` match → **equality-check** every
    bridge/sign-result echo against the verified envelope → **bind the exact output (P0-3):**
    obtain the output bytes (decode inline `output_b64` **or** reassemble the §4.10(f) chunked
    stream into a bounded ≤ 8 MiB buffer), assert `len(bytes) == envelope.output_bytes` **and**
    `SHA256(bytes) == envelope.output_sha256` (raw bytes, **no normalization before the
    check**), then strict-UTF8 decode for display only (invalid UTF-8 ⇒ Block) → consume the
    one-time `request_nonce` (`receipt_challenges`) → assert `receipt_id` global uniqueness
    (`receipt_ids_seen`) → check receipt freshness (`_ms`) → persist the accepted message. A
    stale/rolled-back evidence head was already refused by the signer's **signer-owned durable
    head-floor** (step 10, §7 P1-7) and cannot be re-accepted (its `receipt_id` is not
    fresh/unique). Only on commit does the desktop render.

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
- **Challenge:** fetch by `challenge_handle`, verify `sig` under the key resolved from the
  bound registry snapshot; recompute `request_sha256`; the challenge's identities/`*_sha256`/
  `requested_at_ms` equal the record's. The challenge does **not** contain
  `challenge_accepted_at_ms`.
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
  `brops.governed-sign-result.v1` → `bridge.governed-result.v1` → record → the signer
  envelope (§4.9). It is **not** a challenge field.
- **Receipt/output (fetch by handle):** fetch the exact signed execution-receipt document by
  the record's **`execution_receipt_handle`**, **re-hash the exact document bytes**
  (`== execution_receipt_handle`), verify the **evidence-recorder** signature, then
  `verify_governed_turn_receipt`; `output_sha256 == output_handle == SHA256(exact output
  bytes)`; the receipt's `receipt_id`/`execution_attempt_id`/`lease_id` equal the record's.
- **Containment:** the containment artifact's run/attempt/lease/runner equal the record's,
  `contained==true`, its evidence event `payload_hash == containment_evidence_sha256`.
- **Evidence head + anti-rollback (SIGNER-OWNED durable floor, P1-7 — NO desktop head-floor
  table).** The reused `bro_evidence` head/chain has no timestamp comparison; its anti-truncation
  is **structural** (`event_hash`/`sequence`/`final_event_hash`/`head_sequence`). Today
  `min_head_sequence` is a caller-only parameter never persisted (`brops_live_runstate.py` calls
  `load_head`/`validate_chain` with **no** floor → a no-op); the fix makes it a **durable
  `brops-signer`-owned floor DB**, separate from the read-only `brops-store` artifact store (the
  signer is read-only there, §2.3), dir `0700` / file `0600`:
  ```sql
  CREATE TABLE governed_evidence_head_floor (
    install_id       TEXT NOT NULL, task_id TEXT NOT NULL,
    highest_sequence INTEGER NOT NULL, final_event_hash TEXT NOT NULL, updated_at_ms INTEGER NOT NULL,
    PRIMARY KEY (install_id, task_id) );
  ```
  Inside `LiveRunStateProvider`, **before minting the §4.9 envelope**, the signer runs `load_head`
  + `validate_chain` structurally → `(head_sequence, final_event_hash)`, then in **one
  `BEGIN IMMEDIATE`** tx (write-lock up front, reject nested — the proven `receipt_store.rs`
  `in_immediate_tx` shape) `SELECT … WHERE install_id=? AND task_id=?` and decide: **no row** →
  `INSERT`; **`head_sequence < highest_sequence`** → **refuse** (stale/rolled-back); **`==` with
  different `final_event_hash`** → **refuse** (fork at same seq); **`==` with same hash** →
  **idempotent** (do not advance; re-sign the byte-identical envelope, deterministic from the
  verified record); **`head_sequence > highest_sequence`** → **CAS advance** (`UPDATE … SET
  highest_sequence=?, final_event_hash=?, updated_at_ms=?`). **Commit the floor BEFORE returning
  the signed envelope**; concurrent same-chain attempts serialize on `BEGIN IMMEDIATE` + the
  `(install_id, task_id)` PK (closing the TOCTOU). Crash after floor-commit before response → the
  retry hits the equal-seq/equal-hash branch and re-signs the identical envelope (no second
  advance, no re-execution). **Startup integrity:** verify each floor row is self-consistent and
  refuse a backup-restored DB whose floor is **below** a prior high-water (fail-closed, mirroring
  the §7 registry-floor startup rule). The envelope binds `evidence_head_sequence`/
  `evidence_final_event_hash` (§4.9) so the signed artifact commits to the exact floor. **Tests:**
  concurrent (exactly one advances), crash-after-commit (identical re-sign), same-seq/same-hash
  (idempotent), same-seq/different-hash (refuse), lower-seq (refuse), greater-seq (advance),
  backup-rollback (refuse). (The Wave-3a desktop SQLite has **no** `evidence_head_floor` table —
  this primitive is signer-side; a stale head is refused here at the signer, before any envelope
  is minted.)
- **Registry anti-rollback (supervisor side, crash-consistent):** verify full signed
  registry → create-if-absent publish exact doc + fsync file&dir → durable floor tx persists
  `(highest_registry_epoch, registry_hash, challenge_registry_handle, root_key_id)` → the
  floor is never usable unless its snapshot exists + re-hashes → same-epoch/different-hash +
  divergent-handle refused; startup verifies the floor's snapshot before use, else
  fail-closed.

`RunState` is built from the verified signed record only. On success the signer mints the
`brops.governed-receipt-envelope.v1` (§4.9); on any failure it returns `refused` (§4.5).

### 7.1 Desktop acceptance (§6.1 step 13) — signatures only, NO store access

The desktop verifies the **isolated-signer envelope** (§4.9) + the **supervisor attestation**,
equality-checks the transport echoes, and binds the real Wave-3a desktop replay primitives —
all without reaching the protected store:
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
- **Output binding (P0-3)** — obtain the exact output bytes (decode inline `output_b64` **or**
  reassemble the §4.10(f) chunked stream into a bounded ≤ 8 MiB buffer); assert `len(bytes) ==
  envelope.output_bytes` **and** `SHA256(bytes) == envelope.output_sha256` over the **raw** bytes
  with **no trim/NFC/NFKC/CRLF/lossy** normalization; only then strict-UTF8 decode for display
  (invalid UTF-8 Blocks). A mismatch/wrong-length/tampered-chunk Blocks. Restores the binding the
  v1 path had at `receipt.rs` (`sha256_hex(output) == output_sha256`).
- **Echo equality** — every `bridge.governed-result.v1`/`brops.governed-sign-result.v1` echo
  equals the verified envelope; a mismatch Blocks. A bare echo never authorizes anything.
All in one `BEGIN IMMEDIATE` tx; render only on commit.

---

## 8. Authorities (governed-turn functions only)

- **Lease:** `issue_governed_turn_lease` (governed-turn lease issuer) +
  `validate_governed_turn_lease` (§4.3). The base `issue_lease`/`validate_execution_lease`
  are **NOT** used for this path (a governed-turn lease presented to the base validator is
  refused).
- **Terminal record:** the dedicated **`governed-turn-recorder`** authority signs **only**
  `brops.governed-turn-record.v1` (add `GOVERNED_TURN_RECORDER` to `bro_signature`
  `AUTHORITY_TYPES` / `broctl` key classes; map it in `ARTIFACT_AUTHORITY`; owner-only key at
  the supervisor boundary; it MUST NOT sign `evidence-event`/`evidence-head`/any lease, and
  `verify_artifact` refuses a record signed by any other authority).
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
- **rev 14 (this doc):** targeted implementation-readiness closure via a mandatory **7-track
  fan-out (A POSIX-ACL · B staging FSM · C output integrity · D framing · E protocol/schema ·
  F evidence-floor · G adversarial) + one integrator + a fresh independent red-team** — **P0-1**
  the `2770` store granted group-write to signer + both owners → enforceable **`2750` owner-write
  / group read-only** (dedicated `brops-recorder` principal, `umask 0027`, `_harden_dir` refuses
  `S_IWGRP`, per-principal machine tests + mode guard) (§2.3); **P0-2** staging↔acceptance
  deadlock + sidecar-supplied policy against a nonexistent challenge hash → **pre-accept
  `governed_turn_staging` FSM (VERIFYING→UPLOADING→INPUTS_READY, no execution right)** + supervisor
  self-resolves/publishes/binds policy (§2.4, §5, §6); **P0-3** the rendered reply was
  transport-only (regression vs v1 `receipt.rs`) → **`output_b64`** + desktop length+SHA256 gate
  before normalization (§4.6, §6.1 s13, §7.1); **P1-4** 256 KiB chunk overflows the 256 KiB frame
  → **`MAX_STAGING_CHUNK_BYTES = 184320`** + dual decoded/frame cap with byte proof (§2.4);
  **P1-5** two orphan protocols + field-list staging + inner-only bridge → **§4.10 complete
  control-plane schemas** + full `{ok, output_b64, receipt, error}` bridge parent (§4.6); **P1-6**
  **`EXECUTION_TIMEOUT_MS = 120000`** nested inside `max_age_ms = 300000`, monotonic-elapsed,
  immediate SIGKILL + 5 s grace + 10 s cgroup teardown (§4.7, §1); **P1-7** **signer-owned durable
  `governed_evidence_head_floor`** with a `BEGIN IMMEDIATE` CAS committed before the envelope is
  minted (§7).

## Appendix B — consistency-audit matrices (verification aids, non-normative)

- **Authority matrix:** challenge-authority→challenge only; challenge-root→registry only;
  lease-issuer→governed-turn-lease only; evidence-recorder→receipt/containment/evidence only;
  governed-turn-recorder→terminal record only; supervisor-attestation→governed-sign-request
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
  CAS; `head_sequence` vs `highest_sequence`; NO desktop head-floor table exists).
- **Principal/ACL matrix (P0-1, `2750` owner-write / group read-only):** `brops-store` group =
  {supervisor, recorder, signer(read-only)}; `store/sup/` owner `brops-supervisor` **`2750`**,
  `store/rec/` owner `brops-recorder` **`2750`** (group `r-x`, **NO group `w`** — only the
  namespace owner creates/renames/unlinks; the other owner + signer read/traverse only),
  artifacts `0640`, `umask 0027`, setgid kept only for group-inheritance; `_harden_dir` refuses
  `S_IWGRP`. Private-key dirs `0700` owner-only; **evidence-head floor DB** `brops-signer`
  `0700`/`0600`; acceptance ledger + `governed_turn_staging` `0700` supervisor-only;
  sidecar/executor/desktop = none (not in group, not owner).
- **Capability matrix:** executor = `INVOKE_GOVERNED_MODEL` only; `max_tool_calls=0`; no
  builder grants; launcher digest + model profile pinned.
- **Protocol matrix:** v1 (`brops.sign-request.v1`/`brops.sign-result.v1`/`brops.evidence-
  request.v1`/`bridge.result`/`bridge.task-request`) UNCHANGED; governed family
  (`brops.governed-sign-request.v1`/`brops.governed-sign-result.v1`/`brops.governed-evidence-
  request.v1`/`brops.governed-result.v1`/`brops.governed-receipt-envelope.v1`/`bridge.governed-
  result.v1` + the ingress control plane `brops.governed-staging-open/-chunk/-final.v1` + the
  egress result-stream `brops.governed-result-open/-chunk/-final.v1` and their `-result` replies,
  §4.10) is disjoint; every governed protocol has ONE complete schema +
  discriminator const + producer/consumer (§4.4–4.10); each path refuses the other's documents;
  `bridge.governed-result.v1` is structurally disjoint from `bridge.result` via the required
  `receipt.envelope_jcs_b64` key.
