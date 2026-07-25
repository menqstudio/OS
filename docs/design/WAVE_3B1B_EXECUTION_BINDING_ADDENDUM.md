# Wave 3b-1B — authoritative execution→receipt binding · ARCHITECT ADDENDUM (design-lock, rev 23 — CONSOLIDATED)

> **STATUS: ❌ DESIGN RED being closed — rev 23 is a PROPOSED design-GREEN candidate, NOT
> Architect-GREEN. 3b-1B code has NOT started.** rev 22's normative design was Architect-reviewed at the
> live tip `47033511bbb44bf4ca174a34e3c92fd4780c069c` (exact-head CI **#129** 8/8 SUCCESS; the rev-22
> design content is at `a84ee12`, also 8/8 GREEN — `4703351` was a coordination-only commit, so the
> rev-22 normative design was unchanged — **CI GREEN ≠ design GREEN**); the Architect **CONFIRMED CLOSED**
> the rev-21 `PreparedGovernedTurnV1B`-lifecycle P0 (rev 22's single `governed_turn_execute` backend
> command), but returned RED with **1 P0 · 1 P1** on the same command's contract, and directed a
> **read-only real-code investigation + one integrator + a fresh independent red-team, NOT a rewrite.**
> rev 23 closes both in place:
> **P0-1 — missing routing identities.** rev 22's `governed_turn_execute` inputs omitted `conversation_id`
> (the `receipt_challenges` pre-store + the final accepted-output persist need it) and `run_id` (challenge
> create-pending binds it), and wrongly listed `system`/`history`/`workspace_id`/`install_id`/
> `generation_config` as renderer inputs — but the merged `stream_reply(conversation_id, agent, on_event)`
> (`commands.rs:793-799`) takes **only** `conversation_id` + `agent` from the renderer and **resolves
> `system`/`history` from the message store** (`commands.rs:801-815`) and `workspace_id`/`install_id`/
> `generation_config`/`supervisor_id`/`policy_*` from the **`GOVERNED_*` backend constants**
> (`commands.rs:780-787`); there is **no `run_id`** in the frozen governed path. **rev 23 (§4.10(g),
> §6.1):** `governed_turn_execute(conversation_id, agent)` takes only those renderer inputs and constructs
> a **backend-owned orchestration object `GovernedTurnExecutionV1B{conversation_id, run_id, task_id,
> prepared: PreparedGovernedTurnV1B}`** — `run_id`/`task_id`/`request_nonce` backend-generated
> (`brops_core::id()`/`governed_task_id()`), `system`/`history` resolved from the message store keyed by
> `conversation_id`, identities/policy from the `GOVERNED_*` constants; the renderer re-sends none of them.
> **P1-1 — the transport-failure retry contract was not durable.** rev 22 said a transport failure leaves
> the nonce **not** consumed so the challenge "may be retried" — but after the command returns the
> in-process prepared object / challenge document / pending id are gone, so nothing durable can resume,
> and the merged path makes a transport failure a **terminal durable Block**. **rev 23 (§6.1 out-of-band
> contract):** a transport failure is a **terminal durable Block** — `governed_turn_execute` calls
> `record_pre_verification_block` (`receipt_store.rs:175-208`) which in ONE tx **consumes the
> `request_nonce`** + writes a durable `blocked` evidence record (`StreamEvent::Blocked{reason}`); the
> challenge/nonce is **not** retryable (a later receipt on that nonce ⇒ `Replay` Block). The "nonce not
> consumed / retryable" claim is removed; the durable-orchestration-journal alternative is out of scope.
> *(rev-18 → … → rev-22 findings — orchestrator ordering, generation_config canonicalization,
> two-trust-model channel, nonce/`request_sha256` decoupling, generation_config hash-source split,
> prepared-object lifecycle — remain closed; see the non-normative Appendix A.)*
> **All contracts below are OPEN until the Architect returns design-GREEN at the exact pushed HEAD.**
> STOP gates: `NoTrustedManifest` unchanged, no production "Verified", 3b-2/3b-3 not started, PR #31
> not merged.

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
in-scope, same login user), **supervisor**, **evidence-recorder runner** (the
`brops-recorder` principal that writes `store/rec/`), **privileged launcher**, **contained
executor**, **isolated receipt signer**. The **`governed-turn-recorder` is NOT a distinct OS
principal** — it is a supervisor-held **signing-key authority** (an `ARTIFACT_AUTHORITY` key
class owned by the `brops-supervisor` principal) that signs the terminal record only (§8, P1-5);
do not confuse it with the `brops-recorder` OS principal above.
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
`sign(payload)` oracle nor a `create_pending(arbitrary_bytes) → sign(id)` two-step oracle (the
mandated create-pending/issue split below is **not** such an oracle: create-pending stores only
strictly-validated fixed-shape hashes/ids — never arbitrary bytes — and issue signs only what the
authority itself assembles from its own row).
The exact current contract (not history):

- **Store ownership:** the **pending-challenge store** (the trusted rows the authority builds
  challenges from) and the authority private key are owned by the authority's **own dedicated
  OS principal (UID/SID)**, mode owner-only (`0700`). **The sidecar UID can neither read, nor
  write, nor list** it — so it can neither exfiltrate the key nor tamper a row directly.
- **Distinct principals:** the **desktop-UI principal MUST be a UID distinct from the
  sidecar** principal. Where a platform cannot provide that separation, governed real-mode is
  **FAIL-CLOSED** on that platform (mirrors the Windows-broker stance, §0).
- **Creation channel (TWO explicit messages, ONE canonical trust model — P1-2 LOCKED):**
  pending-challenge rows are created and challenges are issued **only** through the
  **authority-owned `AF_UNIX` channel**; on Linux the authority authenticates the peer with
  **`SO_PEERCRED`, allowlisting the exact desktop-UI UID** — the sidecar UID is denied on both
  messages. The channel carries exactly two request/reply protocols, and **neither ever carries
  challenge bytes or a caller-chosen canonical payload** (this replaces the rev-18 "facts **or**
  row-id" disjunction, which left the implementer a choice between two trust models):
  - **(A) `brops.governed-challenge-create-pending.v1`** (create-pending / propose — **does NOT
    sign**). The desktop-UI supplies the **DESKTOP-minted `request_nonce`** (the ratified Wave-3a
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
    desktop's, already pre-stored by the desktop in `receipt_challenges`, see the pre-store bullet
    below); it returns that `pending_challenge_id`. No signature is produced and no
    `brops.governed-turn-challenge.v1` payload exists yet. Reply
    `brops.governed-challenge-create-pending-result.v1`. **Frame ≤ 4 KiB** each way.
  - **(B) `brops.governed-challenge-issue.v1`** (issue / sign — **signs exactly once**). The
    desktop-UI supplies **ONLY the `pending_challenge_id`** (never facts, never bytes). The authority
    **resolves the row from its OWN protected store**, **constructs the exact
    `brops.governed-turn-challenge.v1` payload (§4.1) itself** — selecting `challenge_key_id` from its
    active registry key, filling `workspace_id`/`install_id`/`supervisor_id` from its own trusted
    config, copying the stored `*_sha256`/`requested_at_ms`/`run_id`/`task_id`/`request_nonce`, and
    stamping `challenge_issued_at_ms`/`challenge_expires_at_ms` from its own clock — **signs once**,
    **one-time-consumes** the pending row (`PENDING → ISSUED`, non-reusable), and returns the signed
    `{payload,sig}` document. Reply `brops.governed-challenge-issue-result.v1`. **Frame ≤ 4 KiB** each
    way (the signed document decodes ≤ 4096, matching `challenge_doc_b64` at §4.10(a0)/§4.10(g)).
- **Single trust invariant (LOCKED):** the caller **NEVER** supplies challenge bytes or a
  caller-chosen canonical payload; the authority **ALWAYS** builds the signed
  `brops.governed-turn-challenge.v1` payload from its **own stored row**. Turn facts enter the system
  **only** at create-pending (A), where they are validated and stored; at issue (B) they are
  re-derived from the authority's own store and **never re-accepted from, or signed verbatim as,
  caller-controlled bytes.** There is no path by which supplied facts and a signature occur in the
  same message. (This closes the `create_pending(arbitrary_bytes) → sign(id)` oracle: (A) stores only
  strictly-validated fixed-shape hashes/ids — never free bytes — and (B) signs only what the authority
  itself assembled.)
- **Desktop nonce authority + `receipt_challenges` pre-store (P0-1 LOCKED — preserves the ratified
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

Creation-channel schemas (both on the authority-owned `AF_UNIX` + `SO_PEERCRED` desktop-UI-UID
channel; `additionalProperties:false`, unknown-field + duplicate-key rejection, schema-validated
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
//   "challenge_document": { "payload": { … §4.1 … }, "sig": "<b64url Ed25519>" } }
// (B) reply (refused):  { "protocol": "brops.governed-challenge-issue-result.v1", "status": "refused",
//   "reason": "peer_denied"|"no_pending_row"|"pending_expired"|"key_unavailable"|"malformed" }
//   (NOTE: an already-ISSUED row is NOT a refusal — it takes the idempotent replay path below and re-returns the stored `issued`.)
```
The authority's **protected pending-challenge store** (owner-only `0700`, §2.3) row:
```sql
CREATE TABLE governed_pending_challenge (
  pending_challenge_id     TEXT PRIMARY KEY,          -- opaque, authority-minted (≥128-bit random)
  request_nonce            TEXT NOT NULL,             -- DESKTOP-minted (brops_core::id() UUIDv4, prepare_governed_turn_v1b §4.10(g)); pre-stored by the desktop in receipt_challenges BEFORE (A); the authority stores it verbatim, NEVER mints it (feeds §4.1 request_nonce)
  run_id TEXT NOT NULL, task_id TEXT NOT NULL, workspace_id TEXT NOT NULL, install_id TEXT NOT NULL,
  supervisor_id            TEXT NOT NULL,             -- authority's OWN config, never caller-supplied
  system_sha256 TEXT NOT NULL, history_sha256 TEXT NOT NULL,
  generation_config_sha256 TEXT NOT NULL,
  request_sha256           TEXT NOT NULL,             -- authority-RECOMPUTED via receipt.rs::request_envelope_sha256:245-264 / brops_canonical.request_sha256:157-179 from request_nonce+context+hashes (protocol brops.request.v1); NOT caller-supplied
  requested_at_ms          INTEGER NOT NULL,
  created_at_ms            INTEGER NOT NULL,          -- authority clock at create-pending
  pending_expires_at_ms    INTEGER NOT NULL,          -- created_at_ms + PENDING_TTL_MS
  state                    TEXT NOT NULL,             -- 'PENDING' → 'ISSUED' (one-time-consume); terminal
  issued_challenge_document TEXT,                     -- the EXACT signed {payload,sig} JCS document (base64url), stored verbatim at issue so a lost-reply retry replays byte-identical bytes (a hash cannot reproduce its preimage)
  issued_challenge_handle  TEXT,                      -- SHA256(decode(issued_challenge_document)) — integrity only, NOT the replay source
  UNIQUE(install_id, request_nonce),                  -- nonce one-time per install (mirrors §4.10(a0))
  UNIQUE(install_id, request_sha256) );               -- idempotency key: one pending row per identical request
```
- **Validation (A):** peer UID == allowlisted desktop-UI UID else `peer_denied`; strict UTF-8 JSON +
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
  for integrity), inside the same commit that flips the state; a repeat (B) on an already-`ISSUED` row
  **re-returns that stored document byte-for-byte** — it never re-signs, never re-stamps
  `challenge_issued_at_ms`/`challenge_expires_at_ms`, never re-selects `challenge_key_id`, and never
  alters the stored desktop `request_nonce` (a one-way handle could not reproduce the bytes, so the
  exact document MUST be persisted, not just its hash); a concurrent-CAS loser observes `ISSUED` and
  takes that same replay path; an unknown id ⇒ `no_pending_row`, an expired row ⇒ `pending_expired`.
- **Authority builds the payload itself:** at issue (B), from its protected row the authority
  **constructs** the exact `brops.governed-turn-challenge.v1` payload (§4.1), stamps
  `challenge_issued_at_ms`/`challenge_expires_at_ms`, and signs once (consuming the pending id). It
  never signs caller-supplied bytes/fields.
- **Return path (P0-1, closes the "by-assumption" document carriage):** the authority returns the
  **exact signed `{payload,sig}` document bytes** to the desktop-UI **in the reply on the same
  authenticated `AF_UNIX` channel** — the desktop-UI is the only `SO_PEERCRED`-allowlisted peer, so
  no other principal receives it. The desktop-UI (which now holds the document bytes) base64url-
  encodes them into `challenge_doc_b64` and passes them to the sidecar **only** via the
  `bridge.governed-turn-submit.v1` ingress frame (§4.10(g), §6.1 step 0). The sidecar first sees the
  document here; it can neither mint nor alter it (the canonicality gate + `challenge_handle` re-hash
  at §4.10(a0) bind the exact bytes). No step delivers the document "by assumption".
- **How desktop facts cross the boundary without giving the sidecar the same capability:** the
  desktop-UI principal (a **distinct UID**) is the only peer the `SO_PEERCRED` allowlist
  admits; it hands the structured facts over the authenticated channel **at create-pending (A)**,
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
  - **`MAX_CONCURRENT_GOVERNED_TURNS = 2`** in-flight `governed_turn_staging` rows (matches the
    desktop `MAX_CONCURRENT_GENERATIONS = 2`, `ai.rs:212`); a 3rd `governed-turn-open` ⇒ `quota_turns`.
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
| 1 | `brops.governed-turn-challenge.v1` | desktop-UI **challenge-authority** | `desktop-challenge-authority` key (`challenge_key_id`) | supervisor §5; `LiveRunStateProvider` §7 | ms | `challenge_handle = SHA256(JCS({payload,sig}))` | supervisor store (published §6) | `request_nonce` (one-time) | binds `run_id`/`task_id`/context + `*_sha256` |
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
  resolved registry bindings. **Lease time is frozen, not issuer-chosen (P0-4, LOCKED):**
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
stream_binding_mismatch, seq_out_of_range`). `stale_evidence` (P0-2, §7 case A — a lower-`head_sequence`
rolled-back/truncated head) is **distinct** from `evidence_fork` (a divergent-content fork, §7 cases
B/D/E). The previously-prose-only reasons (`evidence_fork`/`stale_evidence` from §7, `lease_expired`/
`EXPIRED` from the §7 lease-time invariants, acceptance-time `challenge_invalidated`, idempotency
`retry_conflict`, output-stream `stream_expired`/`stream_binding_mismatch`) are now closed members —
no reason is prose-only. (The §4.10 a0/a/b/c internal supervisor↔sidecar producer codes —
`peer_denied`, `noncanonical`, `session_unknown`, `seq_mismatch`, `oversize_chunk`, … — live in
their own per-message reply schemas; the desktop-facing relays carry the `GOVERNED_REFUSAL_REASONS`
union per the relay literal-embed rule below.) A `signed` result REQUIRES both `envelope_jcs_b64` and
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

**Authority rule (LOCKED, P0-3) — the desktop verifies SIGNATURES, it does NOT read the
protected store.** The protected store is on the engine host, group-`brops-store`, and is
**not readable by the desktop principal** (§2.3); the desktop may also be a different runtime/
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
//   "reason": "peer_denied"|"doc_oversize"|"malformed"|"noncanonical"|"handle_mismatch"|"registry_unknown"|"key_invalid"|"sig_invalid"|"context_mismatch"|"retry_conflict" }
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
context + recompute `request_sha256`; **atomically create-if-absent publish the EXACT
`decoded_document_bytes`** into `store/sup/` (the §6 step-1 publish); CAS-create the
`governed_turn_staging` row `absent→VERIFYING→UPLOADING` keyed
`UNIQUE(install_id,request_nonce)`+`UNIQUE(challenge_handle)`; return `challenge_handle`. **No clock
read, no nonce consume, no execution right — this only *admits* the turn to upload; the binding
authority is the acceptance-time re-verification (§5).** Refused reasons: `peer_denied, doc_oversize,
malformed, noncanonical, handle_mismatch, registry_unknown, key_invalid, sig_invalid,
context_mismatch, retry_conflict` (idempotent re-open, P1-6), plus `quota_turns` (P1-3: a 3rd
concurrent `governed_turn_staging` row for the `install_id` — `MAX_CONCURRENT_GOVERNED_TURNS = 2`). The untrusted sidecar transports bytes
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
`brops.evidence-request.v1` const on the governed path. Reply is `brops.governed-turn-result.v1` (e).
Frame ≤ 4 KiB.
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
CREATE TABLE governed_output_streams (
  output_stream_id     TEXT PRIMARY KEY,          -- 43-char base64url, 256-bit
  receipt_id           TEXT NOT NULL UNIQUE,
  execution_attempt_id TEXT NOT NULL UNIQUE,
  output_handle        TEXT NOT NULL,             -- content-addressed store handle (store/rec)
  output_bytes         INTEGER NOT NULL,
  output_sha256        TEXT NOT NULL,
  created_at_ms        INTEGER NOT NULL,
  expires_at_ms        INTEGER NOT NULL );        -- created_at_ms + OUTPUT_STREAM_TTL_MS
```
The row is **durably committed BEFORE** the §4.10(e) result summary is returned; a supervisor
restart preserves it, and a `COMPLETED` retry returns the **same** `output_stream_id`. Each read
re-checks `output_handle`/length/hash and serves `store.read(output_handle)[seq·184320 …]` (the
supervisor has group read on `store/rec`, §2.3). **`OUTPUT_STREAM_TTL_MS = 360000`** (the desktop
`max_age_ms 300000` + `future_skew_ms 60000`, `receipt_store.rs`) — a stream must outlive the widest
window in which the desktop may still accept the receipt; after `expires_at_ms` the supervisor
returns `stream_expired`. No stream enumeration is ever exposed.

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
carriage (Track E risk #2):** §2.1 already has the desktop-UI as the challenge authority's only
AF_UNIX peer; the authority returns the signed `{payload,sig}` document to the desktop-UI in that
same reply, and the desktop-UI (holding the raw bytes) base64url-encodes it into `challenge_doc_b64`
here. No new principal handles the document.

**Request (desktop → one-shot sidecar `stdin`, one JSON object):**
```json
{ "protocol": "bridge.governed-turn-submit.v1",
  "task_id": "<string ≤128>",
  "challenge_doc_b64": "<base64url of the exact signed {payload,sig} bytes, decoded ≤ 4096>",
  "system": "<string, UTF-8, ≤ 262144 bytes>",
  "history": [ { "role": "user"|"assistant"|"system", "content": "<string>" }, … ],
  "generation_config": {                 // ONE closed FLAT string→string object (P1-1 — every value a validated canonical STRING; NO JSON numbers)
    "engine_id":         "<string, regex ^[A-Za-z0-9._-]{1,128}$ — e.g. brops.governed-engine.sidecar.v1>",
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
`PreparedGovernedTurnV1B` lifecycle NEVER crosses the frontend/webview boundary).** Submit is **NOT**
a separate frontend-invoked Tauri command that re-accepts raw fields: that would sever the single
immutable object at the Tauri boundary (the object cannot survive to submit/`Expected` without a
webview re-serialize/reconstruct, re-opening the split-authority — a frontend-supplied
`system`/`history`/`generation_config` could then differ from the already-pre-stored `request_sha256`
⇒ fail-closed Block). Instead 3b-1B adds **exactly one** frontend-exposed governed
`#[tauri::command]` — **`governed_turn_execute`** (the sole NEW entry in `generate_handler!`,
`apps/desktop/src-tauri/src/lib.rs:95-166`) — that **mirrors the merged single-backend-command shape of
`stream_reply`** (`commands.rs:794`, which today already does prepare → `issue_challenge` pre-store →
`governed_turn` execute → build `Expected` → `verify_and_record_receipt` in ONE backend execution,
`commands.rs:844-935`). It takes ONLY the **renderer-owned inputs** — **`conversation_id`** (the active
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
`commands.rs:801-815`; `system` built from the sanitized `agent`); `workspace_id`/`install_id`/the
`generation_config` engine-id/`supervisor_id`/`policy_id`/`policy_version` come from the `GOVERNED_*`
backend constants (`commands.rs:780-787`); `request_nonce`/`run_id`/`task_id` are backend-generated
(`brops_core::id()` / `governed_task_id()`). Owning this one object, `governed_turn_execute` performs in
order:
1. `prepare_governed_turn_v1b(…)` **once** (validate the config object; `generation_config_jcs =
   JCS(object)` + `generation_config_sha256` once; mint `request_nonce` once);
2. `receipt_challenges` pre-store via `issue_challenge(&conn, &conversation_id, &prepared.issued_request(),
   now_ms)` (`receipt_store.rs:109-126`) — keyed by the orchestration object's `conversation_id`, **before**
   any submit;
3. challenge **create-pending (A)** (carrying the backend `run_id` + turn facts) then **issue (B)** over
   the authority `AF_UNIX` channel (§2.1) — the orchestration object stays in the backend across both
   authority round-trips;
4. **`governed_turn_submit_prepared(&prepared, challenge_document)`** — an **INTERNAL Rust helper, NOT
   a `#[tauri::command]` and NOT in `generate_handler!`** — which builds the
   `bridge.governed-turn-submit.v1` frame from **`&prepared`** (the validated object + its object-JCS
   bytes) + `challenge_doc_b64` and spawns the one-shot governed sidecar exactly as
   `ai.rs::governed_engine` does today (`ai.rs:1346-1412`: spawn, write the submit JSON to `stdin`
   `:1369-1376`, read one reply from `stdout` `:1391-1399` bounded by `MAX_STDOUT_BYTES = 9 MiB :43`,
   await exit), under the existing `MAX_CONCURRENT_GENERATIONS = 2` permit (`ai.rs:212`), returning the
   **metadata-only** result;
5. the **internal output-pull loop** (fresh one-shot sidecars per chunk, §4.10(f)) — also an internal
   backend function driven by `governed_turn_execute`, **not** a frontend-exposed command;
6. build the final `Expected` from the **same** orchestration object and verify/persist
   (`receipt.rs:418-486`, `verify_and_record_receipt`); on accept the reply is written into the
   conversation recovered **from the consumed challenge row** (`receipt_store.rs:366-406`), never
   re-supplied by the renderer.
**No post-prepare webview round-trip (LOCKED):** after step 1, `system`/`history`/`generation_config`/
its hashes/`context`/`conversation_id`/`run_id` are **never** re-serialized to, or re-accepted from, the
frontend; the only frontend interactions are the initial `governed_turn_execute(conversation_id, agent)`
call and the final rendered result. **Encapsulation enforcement (P0-1 LOCKED):** `PreparedGovernedTurnV1B` fields are **private**;
no mutable public copy of the object/JCS/context is exposed; every cross-stage read is via a
**read-only accessor**; and **before submit** the backend asserts
`SHA256(prepared.generation_config_jcs) == prepared.context.generation_config_sha256` **and**
`prepared.issued_request().request_sha256() == the pre-stored receipt_challenges.request_sha256` — a
tampered/reconstructed object cannot reach submit. **Mandatory test (P0-1):** a frontend that mutates
`generation_config`/`system`/`history` after `governed_turn_execute` begins **cannot** reach submit or
alter the pre-stored request (there is no post-prepare frontend input path; the single in-process
`PreparedGovernedTurnV1B` is the sole source of the submit bytes and the `Expected`). **Permitted
alternative (only if a future architecture must split the stages across processes):** a server-side
**opaque `prepared_turn_id`** state machine — a bounded, TTL'd, supervisor-or-backend-owned store with
closed transitions `PREPARED → CHALLENGED → SUBMITTED → FINALIZED`, one-time-consume, crash/retry
semantics; the frontend receives **only** the opaque id, and the authority request, submit frame, and
final `Expected` are all produced from the **same stored immutable object**. 3b-1B mandates the
single-backend-command form above; the `prepared_turn_id` state machine is the **only** other
permitted shape — a frontend-exposed raw-field submit command is **forbidden**.

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
  `brops.governed-turn-open.v1` / staging (§4.10(a0/a/b/c)), before a `governed_turn_acceptance` row
  exists — creates **NO acceptance row**; it returns that path's own protocol reason
  (`peer_denied`/`noncanonical`/`sig_invalid`/`no_staging_row`/`session_corrupt`/… ) and the desktop
  renders it as a Block via the out-of-band relay (§4.5, §6.1 step 0/step 14). `BLOCKED` is reserved
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
0. **Desktop backend governed orchestration (P0-1, §4.10(g)):** the frontend invokes the **one**
   governed Tauri command **`governed_turn_execute(conversation_id, agent)`** — the ONLY renderer inputs
   (mirroring `stream_reply(conversation_id, agent, on_event)`); `system`/`history`/`workspace_id`/
   `install_id`/`generation_config`/`run_id`/`task_id` are backend-resolved or -generated, never renderer
   inputs. In **one backend execution owning a single backend orchestration object
   `GovernedTurnExecutionV1B{conversation_id, run_id, task_id, prepared}`** it: resolve `system`/`history`
   from the message store keyed by `conversation_id` + the `GOVERNED_*` constants → `prepare_governed_turn_v1b`
   once → `receipt_challenges` pre-store (`issue_challenge(&conn, &conversation_id, …)`) → the §2.1
   authority **create-pending (with the backend `run_id`) + issue** calls (obtaining the signed challenge
   document **in the backend**, never via the webview) → the **internal**
   `governed_turn_submit_prepared(&prepared, challenge_document)` helper, which spawns the one-shot
   governed sidecar (as `ai.rs::governed_engine`) and writes a single **`bridge.governed-turn-submit.v1`**
   frame carrying `{task_id, challenge_doc_b64, system, history, generation_config}` **derived from
   `&prepared`** (no frontend re-serialize). The sidecar derives the three canonical input-byte blobs via
   the governed-family formulas (system=raw UTF-8, history=JCS, generation_config=JCS of the closed config
   object — §4.10(g)) and becomes the originator of steps 1–2. A local
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
14. **Desktop final acceptance (P0-3 ordering):** FIRST, **outside** any DB transaction, obtain
    the output bytes by driving the §4.10(f) pull loop (reassemble into a bounded ≤ 8 MiB
    buffer) and verify the envelope signature + attestation, then assert `len(bytes) ==
    envelope.output_bytes` **and** `SHA256(bytes) == envelope.output_sha256` (raw bytes, **no
    normalization before the check**), keeping the verified immutable bytes. THEN open one
    `BEGIN IMMEDIATE` tx (NO store access, NO network I/O inside the lock): **equality-check**
    every bridge/sign-result echo against the verified envelope → strict-UTF8 decode for display
    only (invalid UTF-8 ⇒ Block) → consume the one-time `request_nonce` (`receipt_challenges`) →
    assert `receipt_id` global uniqueness (`receipt_ids_seen`) → check receipt freshness (`_ms`)
    → persist. A stale/rolled-back evidence head was already refused by the signer's durable
    head-floor (step 11, §7 P1-7). Only on commit does the desktop render.

**Out-of-band transport-failure contract (P1-5, LOCKED — covers steps 0/13/14).** The
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

### 7.1 Desktop acceptance (§6.1 step 14) — signatures only, NO store access

The desktop verifies the **isolated-signer envelope** (§4.9) + the **supervisor attestation**,
equality-checks the transport echoes, and binds the real Wave-3a desktop replay primitives —
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
