# Wave 3b — Isolated Signer + Signed Manifest + Production "Verified" · DESIGN (rev 4, design-only)

> **Status: DESIGN-ONLY.** No product code ships under this document until it is
> **Architect-GREEN + Owner-approved**. This is the **3b-0** deliverable (design PR).
> Builds on Wave 3a (slices 1–3, merged: `6c920d0`, `9b214e5`, `8a580028`) and on the
> ratified Wave 3 design ([`WAVE_3_RECEIPT_PROTOCOL_V1_DESIGN.md`](./WAVE_3_RECEIPT_PROTOCOL_V1_DESIGN.md) §1 Option B-core, §5).
>
> **Revision history.**
> - **rev 1** (`6a6882e`) — first boundaries. Architect design **RED** (PR #30): 4 P0.
> - **rev 2** (`9801489`) — closed rev-1's 4 P0 (dedicated OS principal, authenticated
>   evidence chain, context-aware resolver, concrete schemas). Architect design **RED**:
>   2 P0 + 3 P1 residual.
> - **rev 3** (`fa1b8cb`) — closed rev-2's residuals: **P0-1** the evidence-production API
>   is not an oracle and the topology is single (§1.3); **P0-2** containment (and every
>   large input) binds to **real artifact bytes** via a content-addressed protected
>   store (§1.3–1.4, §4); **P1-3** one fixed IPC frame cap — large inputs are
>   **artifact handles**, never inline (§1.9, §4.1); **P1-4** the resolver query is
>   sourced from the **trusted `Expected`/turn**, never the unsigned receipt (§1.7);
>   **P1-5** durable manifest snapshot persisted atomically with the floor + semantic
>   uniqueness (§1.6, §4.3). Architect design **YELLOW** (architecture approved; 5
>   contract redlines).
> - **rev 4** (this) — closes rev-3's 5 contract redlines: **P1-1** normative
>   per-artifact canonical-bytes table matching the merged desktop formulas + all-formula
>   parity (§4.0a); **P1-2** the nonce schema now matches the merged `brops_core::id()`
>   UUIDv4 string, not `hex(32B)` (§4.1); **P1-3** the durable forensic-attestation
>   record — `sign-result` carries the attestation + run IDs, with a defined durable
>   store, and the containment bridge-transport field is exact (§4.2); **P1-4** the
>   supervisor process split / service / ACL / IPC is reclassified **BUILD** (not REUSE)
>   with 4 same-user-isolation acceptance tests (§3, §5); **P1-5** the protected-store
>   atomic publish algorithm (§4.0).
>
> **Հայերեն:** Սա design-only ա։ Private-key custody-ն հենց trust boundary-ն ա։ Product
> code չի land-ում մինչև Architect-GREEN + Owner։

## 0. The gap this closes

Wave 3a shipped the desktop verifier, fail-closed, with a `ReceiptKeyAuthority` seam
whose only implementation (`NoTrustedManifest`) always returns `KeyResolution::Unavailable`
— so **every governed turn Blocks** and no `trusted_verified` ("Verified") can ever
render. Wave 3b provides the missing trusted-key chain:

1. an **isolated signer** that mints a real `brops.receipt.v1` signature,
2. an **operator-provisioned signed key manifest** the desktop validates against a
   **binary-pinned root anchor**, with **anti-rollback**, and
3. a **desktop resolver** implementing `ReceiptKeyAuthority` that mints a real
   `ResolvedManifestKey` — so a **production**-class key finally renders "Verified".

**Crux:** this is not a wiring task. **The private-key custody boundary is the trust
boundary.** The receipt is defeated if a compromised sidecar can sign, if the signer
will sign attacker-chosen bytes, if the **evidence producer** will attest attacker-
chosen facts, or if a hashed *reference* stands in for a real, audit-able artifact.

## 1. Ratified boundaries (the decisions this PR must LOCK)

### 1.1 Process boundary — separate process, dedicated OS principal, single topology

- The receipt signer is a **separate OS process** running under a **dedicated OS account
  / service identity** distinct from the sidecar and the desktop. It is **not** a
  module/function of the sidecar or the supervisor.
- The receipt-signing **key files** are ACL'd to the **signer identity only**; the
  sidecar and desktop identities are **denied read and list**. The **signer binary and
  its config** are **non-writable** by the sidecar/desktop identity.
- **Linux:** dedicated service **UID** (own systemd unit), `0700` key dir owned by that
  UID, `ptrace`/process-inspection isolation from the sidecar UID. **Windows:**
  dedicated **service SID / virtual account**, private-key ACL to that SID only, and
  process + named-pipe ACLs denying the sidecar/desktop SID `PROCESS_VM_READ`/debug/
  pipe-connect beyond the defined endpoint.
- **Single topology (resolves the rev-2 contradiction — P0-1):** the signer's **only
  connecting peer is the supervisor**, over a **direct local IPC** endpoint (Unix domain
  socket / named pipe) whose ACL admits **only the supervisor identity**. **The sidecar
  never connects to the signer.** The sidecar is transport for two things only: it
  *triggers* the supervised run (carrying the desktop's request) and it *relays the
  final receipt wire* back to the desktop. It is **never** in the sign path.
- The **operator** provisions + launches the signer under its dedicated identity; the
  sidecar cannot start it with attacker-controlled state.

**Threat scope (stated):** a **sidecar RCE running as the same desktop login user is IN
SCOPE**; **local administrator / root / `SYSTEM` / kernel compromise is OUT OF SCOPE**
(already in the TCB). Copied to §2 and to `apps/desktop/SECURITY.md` when 3b lands.

### 1.2 Key custody — the receipt-signing key is unreachable by the sidecar

- The receipt signer has its **own key class/store**, distinct from the engine's
  `issuer` / `evidence-recorder` / `builder` keys.
- The receipt-signing **private key** lives in a directory reachable **only by the
  signer identity** (owner-only `0700`, born outside the repo, keys `O_EXCL 0600`, ACL'd
  per §1.1). The sidecar/supervisor **environment and process tree carry NO path or
  handle** to it. **`BRO_KEYDIR` sharing for the receipt key is forbidden.**
- The signer **signs** with the receipt private key; only the **desktop verifier** holds
  the corresponding **public** key (via the manifest, §1.6) and **verifies** with it.

### 1.3 Evidence authenticity — the supervisor BUILDS evidence; nothing signs caller bytes (P0-1, P0-2)

Recompute proves self-consistency, not authenticity, and a compromised sidecar can
fabricate a self-consistent fake run. The authenticity anchor is therefore the
**supervisor** (the external `bro_supervisor` from Wave 3a — a separate OS principal that
holds the lease/enforcement wall), locked as follows:

- **No attestation oracle anywhere.** There is **no** `sign_payload(bytes)`,
  `attest(evidence)`, or any endpoint — on the signer **or the supervisor** — that
  signs/attests **caller-supplied** structured evidence. Moving an oracle from the signer
  into the supervisor is explicitly forbidden.
- **The supervisor constructs the evidence itself.** Its receipt-evidence endpoint
  accepts **only a `{run_id, execution_attempt_id}` handle** (no evidence object). From
  those it reads its **own internal terminal run state** and independently gathers the
  authoritative facts, verifying: a valid **lease** for that attempt, a **terminal
  `completed` status**, the **policy bundle** in force, the **containment artifact**, and
  the **evidence-chain head** for the attempt. Any check failing ⇒ it produces **no
  evidence** (structured refusal).
- **Large inputs and containment are real, content-addressed artifacts, not
  references-to-hash (P0-2, P1-3).** During the run the supervisor writes each large
  artifact — `system`, `history`, `output`, `containment_evidence`, the policy bundle —
  into a **protected, append-only, content-addressed evidence store** (see §1.9/§4.1).
  A **handle** is the artifact's `sha256` over its **exact bytes**; content-addressing
  makes tampering detectable. The evidence the supervisor builds carries **handles**, not
  inline megabytes. Hashing a bare reference string is **forbidden** — a handle is only
  valid if the store holds bytes whose `sha256` equals it.
- **Direct authenticated channel + forensic attestation.** The supervisor calls the
  signer over the §1.1 direct ACL'd IPC (so the signer's authenticated caller **is** the
  supervisor by OS ACL) **and** signs `JCS(evidence)` with a **supervisor attestation
  key** (own custody per §1.2, unreachable by the sidecar) — carried into the receipt
  record for durable **forensic non-repudiation**. The signer verifies the attestation
  before acting; an unauthenticated caller or bad attestation ⇒ refused. The attested
  payload includes the **`run_id` / `execution_attempt_id` / `lease_id`** for forensic
  binding.
- **Recompute is defense-in-depth on top.** The signer reads each artifact from the
  store **by handle**, confirms `sha256(bytes) == handle`, and derives every `*_sha256`
  from those exact bytes — catching a producer bug or store corruption. Authenticity
  rests on the supervisor build + attestation; correctness on the recompute; **both**
  are required.

### 1.4 Narrow IPC — the signer is NOT an oracle, and neither is the supervisor

- The signer accepts **only** the defined, supervisor-attested `brops.sign-request.v1`
  (§4.1) delivered over the §1.1 channel — **never** arbitrary bytes, a prepared
  envelope, or hash claims to trust. It reads large inputs from the store **by handle**
  and recomputes.
- The supervisor exposes **only** `{run_id, execution_attempt_id}` (§4.4) — it never
  accepts a caller's evidence object.
- The signer **constructs the canonical `brops.receipt.v1` envelope itself** (JCS over
  the 21 `RECEIPT_FIELDS`) and signs the **exact canonical bytes** — only its own
  canonically-constructed receipt for a run it independently validated. This closes the
  confused-deputy threat on both processes.
- Both IPC legs are one-shot request/response, size-capped, strict-parsed (§1.9, §4).

### 1.5 Authorization checklist — the signer's independent gate

Before emitting a signature the signer MUST verify ALL of (any failure ⇒ **no
signature**, a structured `refused{reason}` — never a partial/unsigned success):

0. **Attestation authenticity** — valid supervisor attestation over `JCS(evidence)`
   against the pinned supervisor attestation key; caller is the supervisor (OS ACL).
1. **Run binding** — `run_id` / `execution_attempt_id` / `lease_id` present and internally
   consistent; `decision == completed`.
2. **Nonce / request binding** — `request_nonce` + `request_sha256` match the desktop
   challenge context (recomputed from the `system`/`history`/`generation_config` hashes +
   `workspace_id`/`install_id` + `requested_at`).
3. **Artifact handles** — for `system`, `history`, `output`, `containment_evidence`: read
   the store bytes by handle and confirm `sha256(bytes) == handle`; derive the receipt's
   `*_sha256` from those exact bytes.
4. **Policy / config** — `policy_id`, `policy_version`, `policy_bundle_sha256`,
   `generation_config_sha256` in force.
5. **Containment** — the containment artifact exists in the store and its handle equals
   `containment_evidence_sha256`.
6. **Identity** — `executor_id` / `builder_id` / `supervisor_id` in the allowed set.
7. **Timestamps** — `requested_at <= completed_at`, both sane (no future/rollback).

### 1.6 Manifest contract (desktop-side; design §5)

- A **signed key manifest** (operator-provisioned) validated against a **binary-pinned
  root trust anchor** compiled into the Rust desktop binary — not a baked-in leaf key,
  not TOFU, not a plain editable config. **No webview key command.**
- Signed payload fields (§4.3): `manifest_protocol`, `manifest_version`, `manifest_epoch`,
  **`root_key_id`** (selects the pinned root — see below), `issued_at`, `expires_at`, and
  `keys[]`. **Per key:** `key_id`, `public_key`, `trust_class: production | development`
  (the render authority, signed in — never inferred), `allowed_protocols`
  (e.g. `["brops.receipt.v1"]`), `workspace`/scope, `allowed_audiences`/install scope,
  `supervisor_id`, `valid_from`/`valid_to`, `key_epoch`, `revoked`.
- **Root selection with multiple pinned roots:** if the binary pins more than one root
  key, the manifest's **`root_key_id` is inside the signed payload**; the desktop selects
  that pinned root and verifies `root_sig` against it, refusing if `root_key_id` is not
  in the pinned set. (A forger cannot name a different pinned root without also producing
  that root's signature.)
- **Semantic validation (reject, not just parse — P1-5):** duplicate `key_id`; the same
  `key_id` with a different `public_key` or `trust_class`; `issued_at > expires_at`;
  `valid_from > valid_to`; **ambiguous/wildcard scopes** (workspace/audience must be
  explicit — no `"*"`).
- **Anti-rollback (normative):** the desktop durably records the **highest accepted
  `manifest_epoch` AND that manifest's hash** and refuses a manifest when
  `epoch < highest_epoch`, **OR** `epoch == highest_epoch AND manifest_hash differs`,
  **OR** `now > expires_at`. Read/check/update semantics + **durable snapshot** in §1.7,
  §4.3.
- **Template to mirror (REUSE):** the engine already implements this shape —
  `bro_signature.resolve_operator_root_pin`, `resolve_registry_floor`,
  `load_trusted_keys`. The desktop manifest mirrors it in Rust.

### 1.7 Resolver contract — query source, scope binding, durable snapshot (P1-4, P1-5)

- **Context-aware query, sourced from the TRUSTED `Expected`/turn — never the unsigned
  receipt (P1-4).** The pre-verification type-state deliberately exposes only `key_id`
  from the parsed (unsigned) receipt; every **other** query field comes from the desktop-
  trusted turn context, normatively:

  ```
  key_id        = parsed.key_id()                     // the only unsigned-sourced field
  protocol      = RECEIPT_PROTOCOL                     // constant "brops.receipt.v1"
  workspace_id  = turn.expected.request.workspace_id   // trusted
  install_id    = turn.expected.request.install_id     // trusted
  supervisor_id = turn.expected.supervisor_id          // trusted
  now_ms        = turn.now_ms                           // trusted
  ```

  The verified receipt is then **`bind`ed to the same `Expected`** (Wave-3a type-state),
  so no unsigned field is ever trusted and the existing chain is preserved.

  ```rust
  struct KeyResolutionQuery<'a> {
      key_id: &'a str, protocol: &'a str,
      workspace_id: &'a str, install_id: &'a str, supervisor_id: &'a str,
      now_ms: u64,
  }
  trait ReceiptKeyAuthority {
      fn resolve(&self, q: &KeyResolutionQuery, tx: &Transaction) -> KeyResolution;
  }
  ```

- **Constraint enforcement + scope binding.** The resolver validates every manifest
  constraint against `q` (`allowed_protocols ∋ protocol`, workspace/audience/supervisor
  match, `valid_from <= now_ms <= valid_to`, not revoked, manifest not expired). Any miss
  ⇒ `Unavailable(reason)`. `ResolvedManifestKey` is extended to carry the **bound scopes**
  (`workspace`, `install`, `supervisor`, `protocol`, `valid_from`/`valid_to`,
  `key_epoch`, `trust_class`); downstream `verify`/`bind` **must** bind them — no bare key
  escapes its scope. Fields stay private, no public ctor outside `brops-core`.

- **Durable snapshot + anti-rollback transaction (P1-5).** Manifest acceptance is
  two-phase:
  1. **Acceptance (operator-triggered):** load + root-verify + semantically validate the
     manifest, then in **one `BEGIN IMMEDIATE` transaction** persist **atomically**
     (§4.3): the **exact canonical payload bytes**, `root_sig`, `root_key_id`,
     `manifest_epoch`, `manifest_hash`, `accepted_at`, and the floor
     `(highest_epoch, manifest_hash)` — all in the **same transaction**, so a floor bump
     can **never** outlive the manifest bytes (no permanent fail-closed after a crash).
     The in-memory snapshot is derived from the durable row.
  2. **Per-turn resolution:** `resolve(q, tx)` runs **inside the existing Wave-3a
     verify→consume→persist `BEGIN IMMEDIATE` transaction**, validates `q` against the
     snapshot, and **re-reads the durable floor + manifest row in `tx`** to confirm the
     snapshot still matches (defeating a concurrent acceptance/rollback). Mismatch ⇒
     `Unavailable`.
  - **Crash/restart:** the snapshot is rebuilt from the durable manifest row + floor; a
    crash mid-acceptance (before COMMIT) leaves both the floor and the bytes at their
    prior consistent state.

### 1.8 Failure model — fail-closed everywhere

- Signer/supervisor **unavailable / crash / timeout / malformed / key unavailable /
  attestation-invalid / handle-not-in-store** ⇒ **Blocked** (via
  `receipt_store::record_pre_verification_block`, `bounded_reason`-capped) — **never** a
  fallback, **never** an unsigned success.
- Manifest **missing / invalid / rolled-back / expired / out-of-scope for the query /
  semantically-invalid** ⇒ **Blocked** (or `development_untrusted` only for an explicit
  **development**-class key in dev mode) — **never** a forced "Verified".
- A signature that verifies but whose key's `trust_class` is not `production` ⇒
  `development_untrusted`, never "Verified".

### 1.9 Protocol limits

- **One fixed whole-frame cap (P1-3).** Every IPC message (both directions, both legs)
  is length-prefixed and capped at a **fixed 256 KiB frame**. **No inline large
  payloads:** `system`, `history`, `output`, `containment_evidence`, and the policy
  bundle travel **only as content-addressed handles**; the signer reads exact bytes from
  the protected store. The rev-2 "operator raises the cap" language is removed. The
  Wave-3a request-side ceilings (system ≤256 KiB, message ≤1 MiB, total ≤8 MiB) apply to
  the **stored artifacts**, checked at store-read time.
- **Strict parsing** — duplicate-key + unknown-field rejection, fixed types, no NaN/Inf,
  mirroring the receipt wire strict-decode.
- **Domain separation** — distinct tags: receipt `brops.receipt.v1`, request
  `brops.request.v1`, supervisor attestation `brops.run-attestation.v1`, IPC
  `brops.sign-request.v1` / `brops.sign-result.v1`, evidence request
  `brops.evidence-request.v1`, manifest `brops.key-manifest.v1`.
- **`receipt_id` global uniqueness** — durable (`receipt_ids_seen`, migration 0014);
  replay ⇒ Blocked. The one-time **nonce** governs whole-turn replay.

## 2. Threat model (what each boundary defeats)

**Scope:** a **compromised sidecar as the same desktop login user is IN SCOPE**;
**local admin / root / `SYSTEM` / kernel is OUT OF SCOPE**.

| Threat | Defeated by |
|---|---|
| **Compromised sidecar** signs a forged receipt | separate signer **process + dedicated OS principal**, key ACL'd to the signer only, sidecar denied read/list + non-writable binary/config, **signer's only peer is the supervisor** (sidecar never connects) (§1.1–1.2) |
| **Sidecar feeds fake self-consistent evidence** | nothing signs caller-supplied evidence; the **supervisor builds evidence from its own terminal run state** keyed by `{run_id, attempt_id}` (§1.3); a fabricated run has no lease/terminal state ⇒ no evidence |
| **Oracle moved into the supervisor** (`attest(caller_evidence)`) | explicitly forbidden — the supervisor endpoint accepts only `{run_id, attempt_id}`, never an evidence object (§1.3–1.4) |
| **Reference-instead-of-artifact** (hash a bare ref) | handles are **content addresses**; a handle is valid only if the store holds bytes whose `sha256` equals it; the signer reads and re-hashes the exact bytes (§1.3, §1.5) |
| **Sidecar as transport tampers** | its claims are non-authoritative; tampering breaks the attestation or a re-hashed handle ⇒ refused; worst case **DoS ⇒ Blocked** (§1.3, §1.8) |
| **Malicious desktop request** (tampered system/history) | the signer derives hashes from the **stored** artifacts and the desktop **binds** to its own `Expected`; a mismatch ⇒ Blocked (§1.5, §1.7) |
| **Stolen OLD manifest** re-introduces a revoked key | anti-rollback on `(highest_epoch, manifest_hash)`, read/checked/updated **transactionally** with the durable snapshot (§1.6–1.7) |
| **Out-of-scope key use** | context-aware `KeyResolutionQuery` sourced from trusted `Expected` + mandatory scope binding (§1.7) |
| **Crash between floor bump and manifest persist** | floor + exact manifest bytes persisted in **one transaction** (§1.7, §4.3) — no permanent fail-closed |
| **Signer confused-deputy** | signs only its own canonically-constructed receipt for an attested, independently-validated run (§1.4) |

## 3. Reuse vs build

**REUSE (exists, unchanged):**
- Ed25519 + JCS `canonical_bytes` — `engine/runtime/bro_signature.py`,
  `broctl.py::sign_payload`.
- Root-anchor + anti-rollback-floor pattern (engine registry) — template to mirror.
- Private-key custody discipline — `broctl._require_private_key_dir` / `_write_key`.
- **The supervisor's lease / terminal-state / evidence-chain LOGIC** — `engine/tools/
  bro_supervisor.py` already implements leases, execution receipts, and the evidence
  chain (with tests). That **logic** is reused to build the evidence from `{run_id,
  attempt_id}`.
- The Rust verify pipeline + `ReceiptKeyAuthority`/`KeyResolution` seam + the atomic tx +
  `receipt_verification_attempts` (migration 0014).
- Bridge transport — `run_governed_turn`, `_receipt_of`, the structured `system`+`history`
  contract, the provisioning gate.

**BUILD (net-new) — including the supervisor as a live separate principal (P1-4):**

> **Not a REUSE assumption.** In the current live path the desktop spawns
> `engine_sidecar.py` **directly** and the sidecar's real-mode callables are
> `RuntimeError` fail-closed (`engine_sidecar.py::_real_callables`) pending this wave;
> `bro_supervisor.py` exists only as engine **logic/tests**, **not** as a running
> separate-OS-principal service in the governed path. Therefore the supervisor **process
> split, service/unit installation, dedicated identity + ACLs, the content-addressed
> store, and the sidecar→supervisor + supervisor→signer IPC are all BUILD scope for
> 3b-1** — they are machine-proven only when 3b-1's tests pass, never assumed.

- **(a)** the **isolated `brops.receipt.v1` signer** — dedicated process/principal
  (§1.1), own key class/store (§1.2), verifies the supervisor attestation + reads store
  artifacts by handle (§1.3), sign-on-complete; emits base64url-JCS envelope + base64url
  detached Ed25519 signature (not the engine's hex `{payload, signature}` wrapper).
- **(a′)** the **supervisor evidence-production + attestation** — `{run_id, attempt_id}`
  → validate lease/terminal/policy/containment/chain-head → build evidence with handles
  → attest → call the signer directly. The **content-addressed protected evidence store**
  it writes to and the signer reads from.
- **(b)** the **desktop signed key manifest + binary-pinned root anchor + anti-rollback +
  durable snapshot** — schema, pinned root(s) with `root_key_id` selection, semantic
  validation, migration for the durable manifest row + floor, atomic acceptance.
- **(c)** the **desktop manifest resolver** (Rust, in-crate `brops-core`) — context-aware
  `ReceiptKeyAuthority` (§1.7), consulted **in-tx**, query sourced from `Expected`,
  returns a scope-bound `ResolvedManifestKey`. Swaps `NoTrustedManifest` at `ai.rs` +
  `commands.rs`.
- **(d)** **All-formula JCS parity** — extend the parity test beyond the request envelope
  to **every §4.0a artifact formula** (`system`/`history`/`output`/`generation_config`/
  `containment_evidence`/`policy_bundle`) **and** the full 21-field receipt envelope,
  across the Python signer ↔ `receipt.rs`.

## 4. Normative interface definitions (the artifacts 3b-0 LOCKS)

> JSON is **UTF-8**, **strict** (duplicate keys rejected, **unknown keys rejected**,
> fixed types, no NaN/Inf). Hashes/handles are **lowercase hex sha256**. Keys/signatures
> are **base64url, no padding**, Ed25519 (32-byte key, 64-byte sig). **Framing:** one
> length-prefixed message (`u32` big-endian length + body) over the §1.1 channel;
> **whole frame ≤ 256 KiB** (fixed). No inline large payloads — see the handle model.

### 4.0 Protected evidence store (content-addressed)

- **Append-only**, integrity by construction: an artifact's **handle** is `sha256(bytes)`
  (lowercase hex). Immutable once written; a handle can never map to different bytes.
- **Access:** readable by the supervisor + signer identities; **not** the sidecar/desktop
  login identity for the raw store (the desktop receives only what it must persist, §4.2).
- The signer reads bytes **by handle** and refuses unless `sha256(bytes) == handle`.
- **Atomic publish algorithm (normative — P1-5).** The supervisor publishes an artifact
  by: (1) write to a **temporary file** in the same filesystem/dir (private, `O_EXCL`);
  (2) **`flush` + `fsync`** the file (and `fsync` the directory after the rename);
  (3) **verify size + recompute `sha256`** over the written bytes to get the digest;
  (4) **atomic exclusive publish** — rename into place under the **digest name**
  (`<sha256>`), treating an existing identical digest as success (idempotent) and any
  other collision as an error; (5) **only after publish success** does the supervisor
  build/attest the evidence that references the handle; (6) the artifact is **not
  deleted** until the receipt flow reaches terminal completion **and** a defined
  retention policy elapses. This removes the signer's partial-read / TOCTOU window: a
  handle only ever names fully-written, fsync'd, digest-verified bytes.

### 4.0a Artifact canonical-byte formulas (normative — P1-1, MUST match merged desktop)

The signer derives each receipt `*_sha256` by hashing the **exact canonical bytes** of
the named artifact; the store handle equals that same `sha256`. The formulas below are
**pinned to the already-merged Wave-3a desktop code** — the signer MUST reproduce them
byte-for-byte or the desktop `bind` against `Expected` fails ⇒ Blocked.

| Artifact | Canonical bytes (exact) | Merged desktop source |
|---|---|---|
| `system` | **raw UTF-8 bytes** of the system string (no normalization) | `ai.rs` `sha256_hex(system.as_bytes())` |
| `history` | **compact JSON** of `[{ "content":…, "role":… }, …]` — one object per turn, **keys lexicographically ordered** (`content` before `role`), no whitespace (JCS-equivalent for this shape) | `ai.rs::governed_history_sha256` (`BTreeMap{role,content}` → `serde_json::to_vec`) |
| `output` | **exact UTF-8 reply bytes**, unmodified — no trim/normalization | `ai.rs` `interpret_bridge_result` (no `trim()`) |
| `generation_config` | **raw canonical bytes** of the generation-config string, matching the desktop's exact `GENERATION_CONFIG` serialization | `ai.rs` `sha256_hex(generation_config.as_bytes())` |
| `containment_evidence` | **exact JCS bytes** of the containment-evidence object the supervisor produces (strict canonical JSON; defined once and frozen in 3b-1) | net-new (3b-1) |
| `policy_bundle` | **exact bytes** of the operator-provisioned policy bundle as loaded (byte-identical to what the desktop pins as `policy_bundle_sha256`) | net-new (3b-1) |

**Parity (P1-1):** the 3b-1 Python-signer ↔ Rust-desktop parity suite MUST cover **every
formula above** (not only the final 21-field receipt envelope) — one cross-language
fixture per artifact asserting identical `sha256`, including a Unicode/emoji/embedded-NUL
history case and an empty-history case.

### 4.1 `brops.sign-request.v1` (supervisor → signer)

Frame ≤256 KiB. `evidence` carries **handles, never inline bytes**.

| Field | Type | Required | Notes |
|---|---|---|---|
| `protocol` | `"brops.sign-request.v1"` const | yes | — |
| `attestation` | `{ attestation_protocol:"brops.run-attestation.v1", supervisor_key_id:str≤128, sig:b64url(64B) }` | yes | `sig` = detached Ed25519 over `JCS(evidence)` |
| `evidence` | object (below) | yes | authoritative iff covered by `attestation.sig` |

`evidence` fields (all small; large inputs are handles):

| Field | Type | Cap | Kind |
|---|---|---|---|
| `run_id`, `execution_attempt_id`, `lease_id` | string | 128 each | authoritative (forensic binding) |
| `request_nonce` | **opaque string ≤128** (the merged `brops_core::id()` UUIDv4 hyphenated form — **not** `hex(32B)`; P1-2) | 128 | authoritative |
| `receipt_id` | string | 128 | authoritative (idempotency, §4.2) |
| `decision` | `"completed"` | — | authoritative |
| `workspace_id`, `install_id`, `supervisor_id`, `executor_id`, `builder_id` | string | 128 each | authoritative |
| `policy_id`, `policy_version` | string | 128 each | authoritative |
| `policy_bundle_handle` | hex sha256 | 64 | handle → store bytes; = `policy_bundle_sha256` |
| `generation_config_handle` | hex sha256 | 64 | handle; signer derives `generation_config_sha256` |
| `system_handle`, `history_handle`, `output_handle` | hex sha256 | 64 each | handle; signer derives `system_sha256`/`history_sha256`/`output_sha256` |
| `containment_evidence_handle` | hex sha256 | 64 | handle; signer derives `containment_evidence_sha256` |
| `requested_at`, `completed_at` | u64 ms | — | authoritative |

No `*_sha256` value is accepted inline — every hash is **derived** by the signer from the
store bytes named by the corresponding handle (`sha256(bytes) == handle`, else refused).

### 4.2 `brops.sign-result.v1` (signer → supervisor → [relayed] desktop)

Frame ≤64 KiB. Tagged union — exactly one of:

```jsonc
{ "protocol":"brops.sign-result.v1", "status":"signed",
  "receipt_id":"<echoed>",
  "envelope_jcs_b64":"<base64url JCS(21-field brops.receipt.v1)>",
  "signature_b64":"<base64url Ed25519(64B) over the exact JCS bytes>",
  "key_id":"<receipt signing key id>",
  // --- durable forensic-attestation record (P1-3): the signer echoes what it verified,
  // so the receipt<->run proof survives past runtime ---
  "attestation_evidence_jcs_b64":"<base64url JCS(evidence) the signer verified>",
  "attestation_signature_b64":"<base64url Ed25519(64B) supervisor attestation>",
  "supervisor_attestation_key_id":"<pinned supervisor attestation key id>",
  "run_id":"<echoed>", "execution_attempt_id":"<echoed>", "lease_id":"<echoed>" }

{ "protocol":"brops.sign-result.v1", "status":"refused",
  "receipt_id":"<echoed if parseable>",
  "reason":"attestation_invalid | not_completed | run_binding_invalid | nonce_mismatch |
            handle_missing | hash_mismatch | policy_mismatch | containment_missing |
            identity_denied | timestamp_invalid | oversize | malformed" }   // ≤512B
```

- **Durable forensic storage (P1-3).** The forensic fields above are persisted with the
  attempt so a later auditor can re-verify **receipt ↔ run** without the runtime. 3b-2
  migration adds either columns on `receipt_verification_attempts` or a linked
  `receipt_attestations(attempt_id FK ON DELETE RESTRICT, attestation_evidence_jcs BLOB,
  attestation_signature BLOB, supervisor_attestation_key_id TEXT, run_id TEXT,
  execution_attempt_id TEXT, lease_id TEXT)`. The desktop **re-verifies the attestation
  signature** (against the pinned/manifest-listed supervisor attestation key) at persist
  time and Blocks on failure — the attestation is recorded **only** when it verifies.
  The `sign-result` frame carrying these stays within the §4.2 **64 KiB** cap because
  `attestation_evidence_jcs` holds only handles + small fields (never inline artifacts).
- **Desktop persistence of containment bytes — exact transport (P1-3).** The containment
  artifact bytes do **not** ride the signer's 64 KiB `sign-result` frame. They travel on
  the **bridge result** as a dedicated field `receipt.containment_evidence_b64`
  (base64url of the exact containment bytes), **capped at 64 KiB there**; the desktop
  decodes it, re-checks `sha256 == containment_evidence_sha256`, and persists it in the
  attempt evidence, so audit does not depend on the engine store. (`bridge-result.schema.json`
  gains this field in 3b-1.)
- **Replay / idempotency:** `request_nonce` (turn) and `receipt_id` (global) are
  compare-and-consumed in migration 0014's durable ledgers; a re-asked `receipt_id` MAY
  re-emit an identical (deterministic-JCS) envelope or refuse `duplicate` — the desktop
  rejects the second at consume time. `status:"signed"` REQUIRES both `envelope_jcs_b64`
  and `signature_b64` (and the forensic fields); anything else ⇒ malformed ⇒ Blocked.

### 4.3 Manifest + root anchor + durable state

```jsonc
{ "payload": {                       // signed bytes = JCS(payload)
    "manifest_protocol":"brops.key-manifest.v1", "manifest_version":1,
    "manifest_epoch":<u64>, "root_key_id":"<pinned root selector>",
    "issued_at":<u64 ms>, "expires_at":<u64 ms>,
    "keys":[ { "key_id":"<≤128>", "public_key":"<b64url 32B>",
               "trust_class":"production"|"development",
               "allowed_protocols":["brops.receipt.v1"],
               "workspace":"<explicit scope>", "allowed_audiences":["<explicit>"],
               "supervisor_id":"<str>", "valid_from":<u64 ms>, "valid_to":<u64 ms>,
               "key_epoch":<u64>, "revoked":<bool> } ] },
  "root_sig":"<b64url Ed25519(64B) detached over JCS(payload)>" }
```

- **Signed bytes explicit:** `root_sig` is a detached Ed25519 signature over `JCS(payload)`
  (payload **without** `root_sig`). `manifest_hash := sha256(JCS(payload))`.
- **Root:** pinned root public key(s) compiled into the binary; `root_key_id` (in the
  signed payload) selects which; reject if not pinned. base64url-no-pad keys/sigs, u64 ms.
- **Semantic rejects (§1.6):** duplicate `key_id`; same `key_id` different
  `public_key`/`trust_class`; `issued_at > expires_at`; `valid_from > valid_to`; wildcard
  scope.
- **Durable state** (new migration 001X), written **atomically in the acceptance tx**:
  `manifest_current(id INTEGER PK CHECK(id=1), payload_bytes BLOB NOT NULL, root_sig TEXT
  NOT NULL, root_key_id TEXT NOT NULL, manifest_epoch INTEGER NOT NULL, manifest_hash TEXT
  NOT NULL, accepted_at INTEGER NOT NULL)` and
  `manifest_floor(id INTEGER PK CHECK(id=1), highest_epoch INTEGER NOT NULL, manifest_hash
  TEXT NOT NULL)`.
- **Acceptance algorithm** (one `BEGIN IMMEDIATE` tx): (1) verify `root_sig` against the
  pinned root named by `root_key_id`, else reject; (2) semantic-validate, else reject;
  (3) reject if `now > expires_at`; (4) read floor, reject if `epoch < highest_epoch` or
  (`== highest_epoch` and `manifest_hash` differs); (5) else `UPSERT manifest_current` +
  `UPDATE manifest_floor` and COMMIT; derive the snapshot. Single-writer; a crash before
  COMMIT leaves both rows at the prior consistent state.

### 4.4 `brops.evidence-request.v1` (sidecar/desktop trigger → supervisor)

The supervisor's **only** receipt-evidence input — accepts a handle, never evidence:

```jsonc
{ "protocol":"brops.evidence-request.v1",
  "run_id":"<≤128>", "execution_attempt_id":"<≤128>" }
```

The supervisor builds evidence from its internal terminal state for that attempt (§1.3);
it never accepts a caller-supplied evidence object or arbitrary bytes to attest/sign.

### 4.5 Resolver contract (Rust)

`KeyResolutionQuery` + `resolve(&self, &KeyResolutionQuery, &Transaction) -> KeyResolution`
(§1.7); query fields sourced from the trusted `Expected`/turn per the §1.7 mapping;
`ResolvedManifestKey` extended with scope fields, private, no public ctor outside
`brops-core`; the verify pipeline binds the resolved scopes and refuses on mismatch.

## 5. Slicing (implementation follows Architect GREEN on this doc)

- **3b-0 — Design PR (this doc).** **Architect GREEN mandatory** before any 3b code.
- **3b-1 — Isolated signer + supervisor evidence/attestation + content-addressed store +
  all-formula JCS parity.** Signer process/principal + `brops.sign-request/result.v1`;
  the supervisor (now a live separate principal — BUILD, §3) builds evidence from
  `{run_id, attempt_id}` + writes/reads the store via the §4.0 atomic publish; the
  sidecar relays. **Parity (P1-1):** cross-language fixtures for **every §4.0a formula**
  (`system`, `history`, `output`, `generation_config`, `containment_evidence`,
  `policy_bundle`) **and** the 21-field receipt envelope. **Same-login-user isolation
  acceptance tests (P1-4), all MUST pass** — a process running as the sidecar/desktop
  login user **cannot**: (1) connect to the signer socket/pipe; (2) read the supervisor
  attestation key or the receipt-signing key; (3) read or write the protected store;
  (4) get the supervisor to sign/attest **caller-supplied** evidence (only
  `{run_id, attempt_id}` is accepted). **Still `NoTrustedManifest`** → **no production
  "Verified"**. **STOP:** 3b-1 must NOT change `NoTrustedManifest` and must NOT expose
  "Verified".
- **3b-2 — Desktop manifest / root / anti-rollback / durable snapshot + forensic record.**
  Loader, migration (`manifest_current` + `manifest_floor` + the §4.2 forensic-attestation
  storage), desktop re-verify of the supervisor attestation at persist time, semantic +
  negative matrix (rolled-back epoch,
  same-epoch different-hash, expired, bad root sig, unknown `root_key_id`, duplicate/
  conflicting key_id, wildcard scope, revoked/out-of-window/out-of-scope key,
  crash-between-floor-and-bytes).
- **3b-3 — Resolver integration + real e2e.** Context-aware `ReceiptKeyAuthority` swap
  (in-tx, query from `Expected`), production key path, the **first `trusted_verified`**.
  **Merge only after exact-head zero-trust GREEN.**

## 6. Global stop condition — "Verified" opens only when the whole chain is GREEN

**No `trusted_verified` ("Verified") renders, and `NoTrustedManifest` is not swapped,
until the ENTIRE chain — isolated signer (dedicated principal) + supervisor evidence/
attestation + content-addressed store + signed manifest + binary-pinned root + anti-
rollback + durable snapshot + context-aware resolver — is GREEN.** Any partial landing
keeps every governed turn Blocked. "Verified" is a single, chain-complete event.

## 7. Non-goals (this design)

- Full supervisor/sidecar hardening (Waves 4–5) — 3b brings only the **minimal** key-
  custody core + the authenticity anchor + the content-addressed store it depends on.
- Per-delta streaming receipts (deferred; sign-on-complete only, Wave 3 §7).
- Rotating the engine's existing key classes — the receipt signer + the supervisor
  attestation key are **additional** classes, not changes to issuer/evidence/builder
  custody.

**No product code is authored under this document. Implementation begins only after
Architect + Owner approval of the boundaries in §1 and the schemas in §4.**
