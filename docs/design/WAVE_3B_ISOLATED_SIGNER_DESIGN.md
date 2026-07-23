# Wave 3b — Isolated Signer + Signed Manifest + Production "Verified" · DESIGN (rev 2, design-only)

> **Status: DESIGN-ONLY.** No product code ships under this document until it is
> **Architect-GREEN + Owner-approved**. This is the **3b-0** deliverable (design PR).
> Builds on Wave 3a (slices 1–3, merged: `6c920d0`, `9b214e5`, `8a580028`) and on the
> ratified Wave 3 design ([`WAVE_3_RECEIPT_PROTOCOL_V1_DESIGN.md`](./WAVE_3_RECEIPT_PROTOCOL_V1_DESIGN.md) §1 Option B-core, §5).
>
> **rev 2** closes the four Architect design blockers on rev 1 (PR #30, RED @ `6a6882e`):
> **P0-1** dedicated OS security principal (§1.1–1.2), **P0-2** an authenticated run-
> evidence chain — recompute is not authenticity (§1.3), **P0-3** a context-aware
> resolver + anti-rollback transaction semantics (§1.7), **P0-4** normative interface
> schemas (§4).
>
> **Հայերեն:** Սա design-only ա։ Product code չի land-ում մինչև Architect-GREEN + Owner։
> Private-key custody-ն հենց trust boundary-ն ա; engine perimeter-ը audited ա — deliberate,
> tested, չշտապեցված։

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
boundary.** The whole point of the receipt is defeated if a compromised sidecar can
sign, if the signer will sign attacker-chosen bytes, or if the signer will sign
**attacker-fabricated run evidence** that merely happens to be self-consistent.

## 1. Ratified boundaries (the decisions this PR must LOCK)

### 1.1 Process boundary — separate process AND separate OS security principal

Rev 1 required a separate process with a `0700` key dir. **That is insufficient**: if
the signer and a compromised sidecar run under the **same OS user (Windows user / Unix
UID)**, `0700` gives no isolation — a sidecar RCE with that account's rights can read
the key file, rewrite the signer executable/config, or obtain a process/debug handle to
the running signer. The boundary must therefore be an **OS security principal boundary**,
normatively:

- The receipt signer is a **separate OS process** **running under a dedicated OS
  account / service identity** distinct from the account that runs the sidecar and the
  desktop. It is **not** a module/function of the sidecar (`bridge/engine_sidecar.py`)
  or the supervisor.
- The receipt-signing **key files** are ACL'd to the **signer identity only**; the
  sidecar and desktop identities are **denied read and list** on the key directory.
- The **signer binary and its config** are **non-writable** by the sidecar/desktop
  identity (so an RCE cannot swap the signer or point it at a foreign key).
- **Linux:** dedicated service **UID** (own systemd unit / user), key dir owned `0700`
  by that UID, and **`ptrace`/process-inspection isolation** from the sidecar UID
  (e.g. `ptrace_scope`, no shared debug rights, distinct cgroup/namespace where
  available).
- **Windows:** dedicated **service identity** (own service SID / virtual account),
  **private-key ACL** granting only that SID, and **process + named-pipe ACLs** that
  deny the sidecar/desktop SID `PROCESS_VM_READ` / debug / pipe-connect beyond the
  defined endpoint.
- **Transport is local IPC only** — a **Unix domain socket** (Linux) or **named pipe**
  (Windows), ACL'd to the signer + its authenticated caller (§1.3). **Never TCP** (no
  loopback socket a co-located process could also bind/connect without the ACL gate).
- The **operator** provisions + launches the signer under its dedicated identity
  independently of the sidecar; the sidecar cannot start it with attacker-controlled
  state.

**Threat scope (stated, per Architect):** a **sidecar RCE running under the same
desktop *login* user is IN SCOPE** — it must not yield a forged receipt; the dedicated
signer principal + ACLs above are what defeat it. **Local administrator / root / kernel
compromise is explicitly OUT OF SCOPE** (an attacker who is already `root`/`SYSTEM` or
in the TCB can read any key regardless of custody). This scope is copied into §2 and
into `apps/desktop/SECURITY.md` when 3b lands.

### 1.2 Key custody — the receipt-signing key is unreachable by the sidecar

- The receipt signer has its **own key class/store**, distinct from the engine's
  existing `issuer` / `evidence-recorder` / `builder` keys.
- The receipt-signing **private key** lives in a directory reachable **only by the
  signer identity** — owner-only, `0700`, born outside the repo, keys `O_EXCL 0600`
  (reuse the `broctl._require_private_key_dir` / `_write_key` custody discipline, but in
  a **separate store owned by the signer principal**, ACL'd per §1.1).
- The sidecar's (and supervisor's) **environment and process tree carry NO path or
  handle** to the receipt-signing private key. **`BRO_KEYDIR` sharing for the receipt
  key is forbidden** — `BRO_KEYDIR` (which the sidecar reads for `issuer.json` etc.)
  must never contain the receipt-signing key.
- The signer **signs** with the receipt private key; only the **desktop verifier**
  holds the corresponding **public** key (via the manifest, §1.6) and **verifies** with
  it. (rev 1 mis-stated this as "the signer verifies with it".)

### 1.3 Authenticity of the run evidence — recompute is NOT authenticity (P0-2)

Rev 1 said the signer "recomputes every hash" from the structured evidence. **Recompute
alone proves only internal self-consistency, not authenticity.** The sidecar is the
process nearest the signer; a **compromised sidecar can fabricate a fully self-
consistent fake run** — correct nonce, `decision=completed`, a fake containment
artifact, chosen identities, and matching hashes — and recompute would pass. So the
"sidecar can only DoS" claim is only true once evidence **authenticity** is anchored to
a principal the sidecar cannot impersonate. **Locked chain (option 1 + option 3):**

- The **supervisor** — the external `bro_supervisor` process introduced in Wave 3a (a
  **separate OS principal** that issues execution leases and is the enforcement wall) —
  is the **trusted evidence producer** and the signer's **only authenticated caller**.
- The run-evidence message is a **supervisor attestation**: the supervisor signs the
  canonical structured run evidence with a **supervisor attestation key** that is (a)
  **distinct** from the receipt-signing key, (b) held **only** by the supervisor
  principal under §1.2-class custody, and (c) **unreachable by the sidecar**.
- The signer **pins the supervisor attestation public key** (in signer-owned config,
  non-writable by the sidecar per §1.1) and, **before anything else, verifies the
  attestation signature**. An unauthenticated message, a bad attestation signature, or a
  message whose authenticated origin is the sidecar ⇒ **refused** (§1.5).
- The **sidecar is transport only**: it may relay the supervisor's attested evidence to
  the signer and relay the signer's result back, but **its own claims are never
  authoritative**. The signer treats **every authority field** (`decision`, policy,
  identities, timestamps, containment, the input hashes) as authoritative **only because
  it is inside the supervisor-attested payload** — never because it arrived over IPC.
- **Recompute is defense-in-depth on top of authenticity, not a substitute for it:**
  after verifying the attestation, the signer still recomputes the hashes from the
  attested structured inputs (catching a producer bug or a truncation in transit) and
  **constructs** the receipt envelope itself. Authenticity rests on the attestation;
  correctness rests on the recompute; **both** are required.

*(If the supervisor and the evidence producer are ever separated further in a later
wave, the invariant that must hold is unchanged: the signer's authenticated caller is a
principal the sidecar cannot impersonate, and no sidecar-supplied field is authority.)*

### 1.4 Narrow IPC — the signer is NOT a `sign(arbitrary_bytes)` oracle

- The signer accepts **only** the defined, structured, **supervisor-attested**
  "run-evidence" message (§1.3, §4.1) — **never** arbitrary bytes, **never** a
  prepared/ready-made envelope, **never** hash claims to trust.
- Given the attested evidence, the signer **independently validates** the run and
  **recomputes every hash** (`system_sha256`, `history_sha256`, `output_sha256`,
  `request_sha256`, `containment_evidence_sha256`, `generation_config_sha256`, …) from
  the **exact structured inputs**.
- The signer **constructs the canonical `brops.receipt.v1` envelope itself** (JCS over
  the 21 `RECEIPT_FIELDS`) and signs the **exact canonical bytes**. It signs **only its
  own canonically-constructed receipt** for a run it recognizes as **completed and
  contained** (design §1). This closes the confused-deputy threat.
- The IPC is one-shot request/response (attested evidence in → receipt-or-refusal out),
  size-capped and strict-parsed both directions (§1.9, §4).

### 1.5 Authorization checklist — the signer's independent gate

Before emitting a signature, the signer MUST verify ALL of (any failure ⇒ **no
signature**, a structured `refused` with a reason — never a partial/unsigned success):

0. **Attestation authenticity (§1.3)** — the message carries a valid supervisor
   attestation over the exact evidence payload, verified against the pinned supervisor
   attestation public key; the authenticated caller is the supervisor, not the sidecar.
1. `decision == completed` — the run terminated COMPLETED and contained.
2. **Nonce / request binding** — the run's `request_nonce` + `request_sha256` match the
   desktop-issued challenge context (recomputed from the exact `system`/`history`/
   `generation_config` hashes + `workspace_id`/`install_id` + `requested_at`).
3. **Exact input hashes** — `system_sha256`, `history_sha256` recomputed from the
   **structured** `system` + `history[]` (the Wave-3a R2 authority); `output_sha256`
   recomputed from the exact reply bytes.
4. **Policy / config** — `policy_id`, `policy_version`, `policy_bundle_sha256`,
   `generation_config_sha256` in force.
5. **Containment** — the containment-evidence artifact is present and its
   `containment_evidence_sha256` matches.
6. **Identity** — `executor_id` / `builder_id` / `supervisor_id` in the allowed set.
7. **Timestamps** — `requested_at <= completed_at`, both sane (no future/rollback).

### 1.6 Manifest contract (desktop-side; design §5)

- A **signed key manifest** (operator-provisioned) validated against a **binary-pinned
  root trust anchor** compiled into the Rust desktop binary — not a baked-in leaf key,
  not TOFU, not a plain editable config. **No webview key command.**
- Top-level fields: `manifest_version`, `manifest_epoch`, `issued_at`, `expires_at`,
  root signature. **Per key:** `key_id`, `public_key`, `supervisor_id`,
  `workspace`/scope, `valid_from`/`valid_to`, `key_epoch`, revocation status, and — the
  render authority — **`trust_class: production | development`**, **`allowed_protocols`**
  (e.g. `["brops.receipt.v1"]`), **`allowed_audiences`/install scope**. A key's
  `trust_class` (signed into the manifest, never inferred) decides `trusted_verified`
  vs `development_untrusted`.
- **Anti-rollback (normative):** the desktop durably records the **highest accepted
  `manifest_epoch` AND that manifest's hash**, and refuses a manifest when
  `epoch < highest_epoch`, **OR** `epoch == highest_epoch AND manifest_hash differs`,
  **OR** `now > expires_at`. The read/check/update of this floor has defined transaction
  semantics — see §1.7 and §4.3.
- **Template to mirror (REUSE):** the engine already implements exactly this shape for
  its registry — `bro_signature.resolve_operator_root_pin` (binary/owner-pinned root),
  `resolve_registry_floor` (anti-rollback floor: sha256-digest pin or integer version),
  `load_trusted_keys` (root-signed registry). The desktop manifest mirrors this pattern
  in Rust.

### 1.7 Resolver contract — context-aware + transactional (P0-3)

Rev 1's seam (`ResolvedManifestKey{key_id, public_key, trust_class}`, authority keyed by
`key_id` alone) **cannot enforce the manifest's scope** (workspace/install/supervisor/
protocol) or verification-time validity/revocation. Locked replacement:

- **Context-aware query.** The authority is consulted with the full verification
  context, not a bare `key_id`:

  ```rust
  struct KeyResolutionQuery<'a> {
      key_id:        &'a str,
      protocol:      &'a str,   // e.g. "brops.receipt.v1"
      workspace_id:  &'a str,
      install_id:    &'a str,
      supervisor_id: &'a str,
      now_ms:        u64,
  }

  trait ReceiptKeyAuthority {
      fn resolve(&self, q: &KeyResolutionQuery, tx: &Transaction)
          -> KeyResolution;    // Trusted(ResolvedManifestKey) | Unavailable(&'static str)
  }
  ```

- **Constraint enforcement.** The resolver **validates every manifest constraint
  against the query** — `allowed_protocols` ∋ `protocol`, `workspace`/scope matches
  `workspace_id`, audience/install matches `install_id`, `supervisor_id` matches,
  `valid_from <= now_ms <= valid_to`, key **not revoked**, manifest not expired. Any
  miss ⇒ `Unavailable(reason)`. The returned **`ResolvedManifestKey` is extended** to
  carry the **bound scopes** (`workspace`, `install`, `supervisor`, `protocol`,
  `valid_from`/`valid_to`, `key_epoch`, `trust_class`) so downstream `verify` **must**
  bind them (a resolved key cannot be used outside the scope it was resolved for). No
  bare public key escapes without its scope.
- **Anti-rollback transaction semantics (normative).** Manifest acceptance is a
  **two-phase** design:
  1. **Acceptance (rare, operator-triggered):** load + root-verify the manifest, then in
     **one `BEGIN IMMEDIATE` transaction** read `(highest_epoch, manifest_hash)`, apply
     the §1.6 rule, and — if accepted — update the floor **atomically** in the **same
     transaction**. On success the manifest is cached as an **immutable in-memory
     snapshot** keyed by `(manifest_epoch, manifest_hash)`.
  2. **Per-turn resolution:** `resolve(q, tx)` runs **inside the existing Wave-3a
     verify→consume→persist `BEGIN IMMEDIATE` transaction** (`tx` is that transaction).
     It validates `q` against the **immutable accepted snapshot** and **re-reads the
     durable floor in `tx`** to confirm the snapshot's `(epoch, hash)` still equals the
     accepted floor (defeating a concurrent acceptance / rollback between turns). A
     mismatch ⇒ `Unavailable`. Thus verification-time trust decisions and the anti-
     rollback floor are read **in the same transaction that consumes the nonce and
     persists the attempt** — never a separate uncoordinated read.
- **Concurrency/crash:** floor writes are single-writer under `BEGIN IMMEDIATE`; a crash
  mid-acceptance leaves the prior floor intact (no partial update); the snapshot is
  rebuilt from the durable manifest + floor on restart.

### 1.8 Failure model — fail-closed everywhere

- Signer **unavailable / crash / timeout / malformed response / key unavailable /
  attestation-invalid** ⇒ **Blocked** (via `receipt_store::record_pre_verification_block`
  with the **real**, `bounded_reason`-capped reason) — **never** a fallback, **never** an
  unsigned success.
- Manifest **missing / invalid / rolled-back / expired / out-of-scope for the query** ⇒
  **Blocked** (or `development_untrusted` only for an explicit **development**-class key
  in dev mode) — **never** a forced "Verified".
- A signature that verifies but whose key's `trust_class` is not `production` ⇒
  `development_untrusted` (renders, badged dev), never "Verified".

### 1.9 Protocol limits

- **IPC size caps** both directions; **strict parsing** (duplicate-key + unknown-field
  rejection, fixed types) mirroring the receipt wire strict-decode (§2.3 of Wave 3).
  Exact per-field caps in §4.
- **Domain separation** — distinct protocol tags for the receipt envelope
  (`brops.receipt.v1`), the request envelope (`brops.request.v1`), the supervisor
  **attestation** (`brops.run-attestation.v1`), and the **IPC message types**
  (`brops.sign-request.v1` / `brops.sign-result.v1`).
- **`receipt_id` global uniqueness** — already durable (`receipt_ids_seen`, migration
  0014); a replayed `receipt_id` ⇒ Blocked. The one-time **nonce** (already durable)
  governs replay of a whole turn. Signer idempotency in §4.2.

## 2. Threat model (what each boundary defeats)

**Scope:** a **compromised sidecar running as the same desktop login user is IN SCOPE**;
**local admin / root / `SYSTEM` / kernel compromise is OUT OF SCOPE** (already in the TCB).

| Threat | Defeated by |
|---|---|
| **Compromised sidecar** signs a forged receipt | separate signer **process + dedicated OS principal** with key ACL'd to the signer identity only, sidecar denied read/list, signer binary/config non-writable, local-IPC-only (§1.1–1.2) |
| **Compromised sidecar fabricates self-consistent fake run evidence** | the signer only accepts **supervisor-attested** evidence verified against a pinned attestation key the sidecar cannot reach; sidecar-origin/unauthenticated ⇒ refused (§1.3). Recompute confirms consistency but is **not** relied on for authenticity |
| **Compromised sidecar as transport** (relays/tampers) | its claims are non-authoritative; tampering breaks the attestation signature or a recomputed hash ⇒ refused; worst case is **DoS ⇒ Blocked** (§1.3, §1.8) |
| **Malicious desktop request** (tampered system/history/hashes) | the signer recomputes every hash from the **attested** structured evidence + binds the nonce (§1.4–1.5); mismatch ⇒ refused |
| **Stolen OLD manifest** re-introduces a revoked key | anti-rollback on `(highest_epoch, manifest_hash)`, read/checked/updated transactionally (§1.6–1.7) refuses it |
| **Out-of-scope key use** (a key valid for workspace/install/protocol A used for B) | context-aware `KeyResolutionQuery` + mandatory scope binding on `ResolvedManifestKey` (§1.7) |
| **Signer confused-deputy** (asked to sign arbitrary/prepared bytes) | the signer never signs arbitrary bytes / prepared envelopes / hash claims — only its own canonically-constructed receipt for an **attested** run it independently validated (§1.4) |
| **Key-file substitution** | dedicated-principal ACL custody (§1.1–1.2) + the manifest's signed `public_key` must match the signing key; a substituted key's receipts fail the manifest key binding + signature check |

## 3. Reuse vs build (from the engine-surface map)

**REUSE (exists, unchanged):**
- Ed25519 primitives + JCS `canonical_bytes` (identical formula to Rust) —
  `engine/runtime/bro_signature.py`, `engine/tools/broctl.py::sign_payload`.
- Root-anchor + anti-rollback-floor pattern (engine registry) — a proven template to
  mirror for the desktop manifest.
- Private-key custody discipline — `broctl._require_private_key_dir` / `_write_key`; the
  verify/sign process split.
- **The external supervisor** (Wave 3a) as the attesting principal + its lease/receipt
  path — extended to emit the `brops.run-attestation.v1` payload (§1.3).
- The whole Rust verify pipeline + `ReceiptKeyAuthority` / `KeyResolution` seam + the
  atomic tx + `receipt_verification_attempts` (migration 0014).
- Bridge transport — `run_governed_turn`, `_receipt_of` (already reads
  `receipt_envelope_jcs_b64` / `signature_b64`), the structured `system`+`history`
  contract, the provisioning gate.

**BUILD (net-new):**
- **(a)** the **isolated `brops.receipt.v1` signer** — dedicated process + OS principal
  (§1.1), own key class/store (§1.2), **verifies the supervisor attestation** (§1.3),
  invoked sign-on-complete; emits base64url-JCS envelope + base64url detached Ed25519
  signature (**not** the engine's hex `{payload, signature}` wrapper). Replaces the
  `RuntimeError` in `engine_sidecar._real_callables`; extends the supervisor to attest.
- **(a′)** the **supervisor attestation** — the supervisor signs the run-evidence
  payload (`brops.run-attestation.v1`) with its own attestation key; the sidecar relays,
  never mints.
- **(b)** the **desktop signed key manifest + binary-pinned root anchor + anti-rollback**
  — manifest schema/fields, a pinned root anchor in the Rust binary, and a durable
  `(highest_epoch, manifest_hash)` table + transactional anti-rollback (§1.7).
- **(c)** the **desktop manifest resolver** (Rust, in-crate `brops-core`) — a type
  implementing the context-aware `ReceiptKeyAuthority` (§1.7), consulted **inside** the
  verify tx, returning a scope-bound `ResolvedManifestKey`. Swaps `NoTrustedManifest` at
  `ai.rs` + `commands.rs`.
- **(d)** **JCS receipt-envelope parity** — extend the parity test (currently
  request-only) to the full 21-field receipt envelope across the new Python signer ↔
  `receipt.rs` (the canonicalization formula is already shared, so this pins/verifies —
  not new crypto).

## 4. Normative interface definitions (the artifacts 3b-0 LOCKS)

> All JSON is **UTF-8**, **strict** (duplicate keys rejected, **unknown keys rejected**,
> fixed types, no NaN/Inf). All hashes are **lowercase hex sha256**. All keys/signatures
> are **base64url, no padding**, Ed25519 (32-byte key, 64-byte signature). Byte caps are
> hard; overflow ⇒ refused/parse-error. **Framing:** one length-prefixed message per
> request and per response (`u32` big-endian length + body), over the §1.1 local socket/
> pipe; the whole message is capped (below).

### 4.1 `brops.run-attestation.v1` → `brops.sign-request.v1` (caller → signer)

The signer's **input**. Envelope cap **256 KiB**. Fields:

| Field | Type | Required | Authoritative? | Cap |
|---|---|---|---|---|
| `protocol` | `"brops.sign-request.v1"` const | yes | — | — |
| `attestation` | object (below) | yes | **yes (authenticity root)** | — |
| `evidence` | object (below) | yes | authoritative **iff** covered by `attestation.sig` | 200 KiB |

`attestation`:

| Field | Type | Required | Notes |
|---|---|---|---|
| `attestation_protocol` | `"brops.run-attestation.v1"` const | yes | domain tag |
| `supervisor_key_id` | string ≤128 | yes | must equal the signer-pinned attestation key id |
| `sig` | base64url Ed25519(64B) | yes | **detached, over `JCS(evidence)`** (canonical bytes of the `evidence` object) |

`evidence` (the authoritative run facts — authoritative **only** because `attestation.sig`
covers them; caps per field):

| Field | Type | Cap | Authoritative / Derived |
|---|---|---|---|
| `request_nonce` | hex (32B) | 64 | authoritative |
| `receipt_id` | string | 128 | authoritative (idempotency key, §4.2) |
| `decision` | `"completed"` \| `"blocked"` | — | authoritative |
| `workspace_id`, `install_id`, `supervisor_id`, `executor_id`, `builder_id` | string | 128 each | authoritative |
| `policy_id`, `policy_version`, `policy_bundle_sha256` | string / hex | 128 / 64 | authoritative |
| `generation_config` | object | 16 KiB | authoritative; signer recomputes `generation_config_sha256` |
| `system` | string | 256 KiB\* | authoritative input; signer recomputes `system_sha256` |
| `history` | array of `{role,content}` | 8 MiB\* | authoritative input; signer recomputes `history_sha256` (JCS array) |
| `output` | string (exact reply bytes) | 8 MiB\* | authoritative input; signer recomputes `output_sha256` |
| `containment_evidence` | object/ref | 64 KiB | authoritative; signer recomputes `containment_evidence_sha256` |
| `requested_at`, `completed_at` | u64 ms | — | authoritative |
| *any `*_sha256` claim* | — | — | **DERIVED — signer ignores incoming, recomputes** |

\* The three large inputs share the **overall 200 KiB `evidence` cap** unless the
operator raises the message cap; the Wave-3a request-side caps (system ≤256 KiB, message
≤1 MiB, total ≤8 MiB) remain the ceiling and are re-checked here. **All `*_sha256`
fields are DERIVED**: if present in the message they are **ignored and recomputed**; a
mismatch between a supplied claim and the recomputed value ⇒ refused.

### 4.2 `brops.sign-result.v1` (signer → caller)

Result cap **64 KiB**. A **tagged union** — exactly one of:

```jsonc
// success
{ "protocol": "brops.sign-result.v1", "status": "signed",
  "receipt_id": "<echoed>",
  "envelope_jcs_b64": "<base64url JCS(21-field brops.receipt.v1)>",
  "signature_b64":   "<base64url Ed25519(64B) over the exact JCS bytes>",
  "key_id": "<receipt signing key id>" }
// refusal — NO signature, ever
{ "protocol": "brops.sign-result.v1", "status": "refused",
  "receipt_id": "<echoed if parseable>",
  "reason": "<bounded, ≤512B, enum-tagged: attestation_invalid | not_completed |
              nonce_mismatch | hash_mismatch | policy_mismatch | containment_missing |
              identity_denied | timestamp_invalid | oversize | malformed>" }
```

- **Replay / idempotency:** the signer is **stateless per request** but the desktop
  enforces one-time semantics — `request_nonce` (turn) and `receipt_id` (global) are
  compare-and-consumed in migration 0014's durable ledgers. A signer that is asked twice
  for the same `receipt_id` MAY re-emit an **identical** envelope (deterministic JCS) or
  refuse `duplicate`; the desktop rejects the second **at consume time** regardless. No
  partial/streamed result — one atomic response.
- **No unsigned success**: `status:"signed"` REQUIRES both `envelope_jcs_b64` and
  `signature_b64`; anything else parses as malformed ⇒ Blocked.

### 4.3 Manifest + root anchor + anti-rollback

**Manifest payload** (`brops.key-manifest.v1`), signed shape:

```jsonc
{ "payload": {                     // the signed bytes = JCS(payload)
    "manifest_protocol": "brops.key-manifest.v1",
    "manifest_version": 1,
    "manifest_epoch":   <u64>,     // monotonic; anti-rollback dimension
    "issued_at": <u64 ms>, "expires_at": <u64 ms>,
    "keys": [ {
        "key_id": "<string ≤128>",
        "public_key": "<base64url Ed25519 32B>",
        "trust_class": "production" | "development",
        "allowed_protocols": ["brops.receipt.v1"],
        "workspace": "<scope>", "allowed_audiences": ["<install scope>"],
        "supervisor_id": "<string>",
        "valid_from": <u64 ms>, "valid_to": <u64 ms>,
        "key_epoch": <u64>, "revoked": <bool>
    } ]
  },
  "root_sig": "<base64url Ed25519(64B) = detached signature over JCS(payload)>"
}
```

- **Signed bytes are explicit:** `root_sig` is a **detached Ed25519 signature over
  `JCS(payload)`** (the canonical bytes of the `payload` object **without** the
  `root_sig` field). Duplicate/unknown keys anywhere ⇒ reject. Encodings: keys/sigs
  base64url-no-pad, times u64 ms.
- **Root anchor (binary-pinned):** the acceptable **root public key(s)** are compiled
  into the desktop binary (mirroring `resolve_operator_root_pin`) — not read from a
  config file. `manifest_hash := sha256(JCS(payload))`.
- **Anti-rollback state** (new durable table, migration 001X):
  `manifest_floor(id INTEGER PRIMARY KEY CHECK(id=1), highest_epoch INTEGER NOT NULL,
  manifest_hash TEXT NOT NULL)`. **Acceptance algorithm** (one `BEGIN IMMEDIATE` tx):
  1. verify `root_sig` against a pinned root key; else reject.
  2. reject if `now > expires_at`.
  3. read `manifest_floor`; **reject** if `manifest_epoch < highest_epoch`, or
     `== highest_epoch AND manifest_hash != stored hash`.
  4. else `UPDATE manifest_floor SET highest_epoch, manifest_hash` and COMMIT; cache the
     immutable snapshot keyed by `(manifest_epoch, manifest_hash)`.
  Concurrency: single-writer under `BEGIN IMMEDIATE`; crash before COMMIT ⇒ floor
  unchanged. **Per-turn** `resolve` re-reads `manifest_floor` inside the verify tx and
  confirms it still matches the cached snapshot (§1.7).

### 4.4 Resolver contract (Rust)

The `KeyResolutionQuery` + `ReceiptKeyAuthority::resolve(&self, &KeyResolutionQuery,
&Transaction) -> KeyResolution` signature of §1.7; `ResolvedManifestKey` extended with
scope fields (`workspace`, `install`/audience, `supervisor`, `protocol`, `valid_from`,
`valid_to`, `key_epoch`, `trust_class`) and still no public ctor outside `brops-core`
(the resolver lives in-crate or the crate adds a manifest-module constructor). The verify
pipeline **binds** the resolved scopes and refuses if the receipt's context differs.

## 5. Slicing (implementation follows Architect GREEN on this doc)

- **3b-0 — Design PR (this doc).** Custody principal + authenticity chain + IPC +
  manifest/resolver contracts. **Architect GREEN mandatory** before any 3b
  implementation.
- **3b-1 — Isolated signer + supervisor attestation + 21-field JCS parity.** The signer
  process/principal + `brops.sign-request/result.v1`; the supervisor emits
  `brops.run-attestation.v1`; the sidecar relays. **Still `NoTrustedManifest`** → **no
  production "Verified"**. **STOP CONDITION:** 3b-1 must NOT change `NoTrustedManifest`
  and must NOT expose "Verified" in the UI.
- **3b-2 — Desktop manifest / root / anti-rollback.** Loader, migration/durable floor,
  full negative matrix (rolled-back epoch, same-epoch different-hash, expired, bad root
  signature, revoked/out-of-window/out-of-scope key).
- **3b-3 — Resolver integration + real e2e.** Context-aware `ReceiptKeyAuthority` swap
  (consulted in-tx), production key path, the **first `trusted_verified`**. **Merge only
  after exact-head zero-trust GREEN.**

## 6. Global stop condition — "Verified" opens only when the whole chain is GREEN

**No `trusted_verified` ("Verified") renders, and `NoTrustedManifest` is not swapped,
until the ENTIRE chain — isolated signer (dedicated principal) + supervisor attestation
+ signed manifest + binary-pinned root anchor + anti-rollback + context-aware resolver —
is GREEN.** Any partial landing (e.g. 3b-1 alone) keeps every governed turn Blocked.
"Verified" is a single, chain-complete event.

## 7. Non-goals (this design)

- Full supervisor/sidecar hardening (Waves 4–5) — 3b brings only the **minimal** key-
  custody core plus the authenticity anchor it depends on.
- Per-delta streaming receipts (deferred; sign-on-complete only, Wave 3 §7).
- Rotating the engine's existing key classes — the receipt signer is an **additional**
  key class, not a change to issuer/evidence/builder custody.

**No product code is authored under this document. Implementation begins only after
Architect + Owner approval of the boundaries in §1 and the schemas in §4.**
