# Wave 3b — Isolated Signer + Signed Manifest + Production "Verified" · DESIGN (rev 1, design-only)

> **Status: DESIGN-ONLY.** No product code ships under this document until it is
> **Architect-GREEN + Owner-approved**. This is the **3b-0** deliverable (design PR).
> Builds on Wave 3a (slices 1–3, merged: `6c920d0`, `9b214e5`, `8a580028`) and on the
> ratified Wave 3 design ([`WAVE_3_RECEIPT_PROTOCOL_V1_DESIGN.md`](./WAVE_3_RECEIPT_PROTOCOL_V1_DESIGN.md) §1 Option B-core, §5).
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
sign, or if the signer will sign attacker-chosen bytes.

## 1. Ratified boundaries (the decisions this PR must LOCK)

### 1.1 Process boundary — separate signer process

- The receipt signer is a **separate OS process**, **not** a module/function of the
  sidecar (`bridge/engine_sidecar.py`) or the supervisor (`bro_supervisor`). The
  sidecar talks to it only over the narrow IPC (§1.3); it **never imports** the
  signer's key-loading code or holds the signing key in-process.
- **Rationale (threat: compromised sidecar):** a sidecar RCE must not become a
  signing oracle. If the signer were a sidecar module, one RCE would forge receipts.
- The desktop spawns the sidecar; the **operator** provisions + launches the signer
  process independently (its own service/unit), so the sidecar cannot start it with
  attacker-controlled state.

### 1.2 Key custody — the receipt-signing key is unreachable by the sidecar

- The receipt signer has its **own key class/store**, distinct from the engine's
  existing `issuer` / `evidence-recorder` / `builder` keys.
- The receipt-signing **private key** lives in a directory reachable **only by the
  signer process** — owner-only, `0700`, born outside the repo, keys `O_EXCL 0600`
  (reuse the `broctl._require_private_key_dir` / `_write_key` custody discipline, but
  in a **separate store**).
- The sidecar's (and supervisor's) **environment and process tree carry NO path or
  handle** to the receipt-signing private key. **`BRO_KEYDIR` sharing for the receipt
  key is forbidden** — `BRO_KEYDIR` (which the sidecar reads for `issuer.json` etc.)
  must never contain the receipt-signing key.
- Only the signer process reads the receipt key; only the signer verifies with it.

### 1.3 Narrow IPC — the signer is NOT a `sign(arbitrary_bytes)` oracle

- The signer accepts **only a defined, structured "run-evidence" message** — **never**
  arbitrary bytes, **never** a prepared/ready-made envelope, **never** hash claims to
  trust.
- Given the structured evidence, the signer **independently validates** the run and
  **recomputes every hash** (`system_sha256`, `history_sha256`, `output_sha256`,
  `request_sha256`, `containment_evidence_sha256`, `generation_config_sha256`, …)
  from the **exact structured inputs** — it never trusts an incoming hash claim.
- The signer **constructs the canonical `brops.receipt.v1` envelope itself** (JCS over
  the 21 `RECEIPT_FIELDS`) and signs the **exact canonical bytes**. It signs **only its
  own canonically-constructed receipt** for a run it recognizes as **completed and
  contained** (design §1). This closes the confused-deputy threat.
- The IPC is one-shot request/response (structured evidence in → receipt-or-refusal
  out), size-capped and strict-parsed both directions (§1.7).

### 1.4 Authorization checklist — the signer's independent gate

Before emitting a signature, the signer MUST verify ALL of (any failure ⇒ **no
signature**, a structured `refused` with a reason — never a partial/unsigned success):

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

### 1.5 Manifest contract (desktop-side; design §5)

- A **signed key manifest** (operator-provisioned) validated against a **binary-pinned
  root trust anchor** compiled into the Rust desktop binary — not a baked-in leaf key,
  not TOFU, not a plain editable config. **No webview key command.**
- Top-level fields: `manifest_version`, `manifest_epoch`, `issued_at`, `expires_at`,
  root signature. **Per key:** `key_id`, `public_key`, `supervisor_id`,
  `workspace`/scope, `valid_from`/`valid_to`, `key_epoch`, revocation status, and —
  the render authority — **`trust_class: production | development`**,
  **`allowed_protocols`** (e.g. `["brops.receipt.v1"]`), **`allowed_audiences`/install
  scope**. A key's `trust_class` (signed into the manifest, never inferred) decides
  `trusted_verified` vs `development_untrusted`.
- **Anti-rollback (normative):** the desktop durably records the **highest accepted
  `manifest_epoch` AND that manifest's hash**, and refuses a manifest when
  `epoch < highest_epoch`, **OR** `epoch == highest_epoch AND manifest_hash differs`,
  **OR** `now > expires_at`. Persisting `(highest_epoch, manifest_hash)` is **atomic**.
- **Template to mirror (REUSE):** the engine already implements exactly this shape for
  its registry — `bro_signature.resolve_operator_root_pin` (binary/owner-pinned root),
  `resolve_registry_floor` (anti-rollback floor: sha256-digest pin or integer version),
  `load_trusted_keys` (root-signed registry). The desktop manifest mirrors this pattern
  in Rust.

### 1.6 Failure model — fail-closed everywhere

- Signer **unavailable / crash / timeout / malformed response / key unavailable** ⇒
  **Blocked** (via `receipt_store::record_pre_verification_block` with the **real**,
  `bounded_reason`-capped reason) — **never** a fallback, **never** an unsigned success.
- Manifest **missing / invalid / rolled-back / expired** ⇒ **Blocked** (or
  `development_untrusted` only for an explicit **development**-class key in dev mode) —
  **never** a forced "Verified".
- A signature that verifies but whose key's `trust_class` is not `production` ⇒
  `development_untrusted` (renders, badged dev), never "Verified".

### 1.7 Protocol limits

- **IPC size caps** both directions; **strict parsing** (duplicate-key + unknown-field
  rejection, fixed types) mirroring the receipt wire strict-decode (§2.3 of Wave 3).
- **Domain separation** — distinct protocol tags for the receipt envelope
  (`brops.receipt.v1`), the request envelope (`brops.request.v1`), and the **IPC
  message type** (a new tag, e.g. `brops.sign-request.v1` / `brops.sign-result.v1`).
- **`receipt_id` global uniqueness** — already durable (`receipt_ids_seen`, migration
  0014); a replayed `receipt_id` ⇒ Blocked. The one-time **nonce** (already durable)
  governs replay of a whole turn.

## 2. Threat model (what each boundary defeats)

| Threat | Defeated by |
|---|---|
| **Compromised sidecar** signs a forged receipt | separate signer process (§1.1) + key custody unreachable by the sidecar (§1.2); the sidecar can only DoS ⇒ Blocked (§1.6) |
| **Malicious desktop request** (tampered system/history/hashes) | the signer recomputes every hash from structured evidence + binds the nonce (§1.3–1.4); mismatch ⇒ refused |
| **Stolen OLD manifest** re-introduces a revoked key | anti-rollback on `(highest_epoch, manifest_hash)` (§1.5) refuses it |
| **Signer confused-deputy** (asked to sign arbitrary/prepared bytes) | the signer never signs arbitrary bytes / prepared envelopes / hash claims — only its own canonically-constructed receipt for a run it independently validated (§1.3) |
| **Key-file substitution** | owner-only custody (§1.2) + the manifest's signed `public_key` must match the signing key; a substituted key's receipts fail the manifest key binding + signature check |

## 3. Reuse vs build (from the engine-surface map)

**REUSE (exists, unchanged):**
- Ed25519 primitives + JCS `canonical_bytes` (identical formula to Rust) —
  `engine/runtime/bro_signature.py`, `engine/tools/broctl.py::sign_payload`.
- Root-anchor + anti-rollback-floor pattern (engine registry) — a proven template to
  mirror for the desktop manifest.
- Private-key custody discipline — `broctl._require_private_key_dir` / `_write_key`;
  the verify/sign process split.
- The whole Rust verify pipeline + `ReceiptKeyAuthority` / `KeyResolution` seam + the
  atomic tx + `receipt_verification_attempts` (migration 0014).
- Bridge transport — `run_governed_turn`, `_receipt_of` (already reads
  `receipt_envelope_jcs_b64` / `signature_b64`), the structured `system`+`history`
  contract, the provisioning gate.

**BUILD (net-new):**
- **(a)** the **isolated `brops.receipt.v1` signer** — a dedicated signing boundary
  (own process, own key class/store, own custody) invoked sign-on-complete; emits
  base64url-JCS envelope + base64url detached Ed25519 signature (**not** the engine's
  hex `{payload, signature}` wrapper). Replaces the `RuntimeError` in
  `engine_sidecar._real_callables`; extends `SupervisorResult`/`run_task` to carry the
  wire.
- **(b)** the **desktop signed key manifest + binary-pinned root anchor + anti-rollback**
  — manifest schema/fields, a pinned root anchor in the Rust binary, and a durable
  `(highest_epoch, manifest_hash)` table + atomic anti-rollback.
- **(c)** the **desktop manifest resolver** (Rust, in-crate `brops-core`) — a type
  implementing `ReceiptKeyAuthority` that validates the manifest against the pinned
  anchor and returns `KeyResolution::Trusted(ResolvedManifestKey)`. Because
  `ResolvedManifestKey` has private fields + no public ctor, the resolver lives in
  `brops-core` (or the crate adds a manifest-module constructor). Swaps
  `NoTrustedManifest` at `ai.rs` + `commands.rs`.
- **(d)** **JCS receipt-envelope parity** — extend the parity test (currently
  request-only) to the full 21-field receipt envelope across the new Python signer ↔
  `receipt.rs` (the canonicalization formula is already shared, so this pins/verifies,
  it is not new crypto).

## 4. Interfaces to lock (concrete artifacts 3b-0 delivers)

1. **IPC schemas** — `brops.sign-request.v1` (desktop/supervisor → signer: the
   structured run evidence) and `brops.sign-result.v1` (signer → caller: the receipt
   envelope + signature, OR a structured `refused{reason}`). Size caps + strict parse.
2. **Manifest schema** — the signed manifest fields (§1.5), the pinned-root-anchor
   format, and the durable anti-rollback state shape.
3. **Resolver contract** — the Rust `ReceiptKeyAuthority` impl signature + where it
   lives (in-crate) + how it mints `ResolvedManifestKey`.

## 5. Slicing (implementation follows Architect GREEN on this doc)

- **3b-0 — Design PR (this doc).** Custody boundary + IPC + manifest/resolver
  contracts. **Architect GREEN mandatory** before any 3b implementation.
- **3b-1 — Isolated signer + 21-field JCS parity.** The signer process + wire; the
  sidecar real-mode returns the signed wire. **Still `NoTrustedManifest`** → **no
  production "Verified"**. **STOP CONDITION:** 3b-1 must NOT change `NoTrustedManifest`
  and must NOT expose "Verified" in the UI.
- **3b-2 — Desktop manifest / root / anti-rollback.** Loader, migration/durable state,
  full negative matrix (rolled-back epoch, same-epoch different-hash, expired, bad root
  signature, revoked/out-of-window key).
- **3b-3 — Resolver integration + real e2e.** `ReceiptKeyAuthority` swap, production
  key path, the **first `trusted_verified`**. **Merge only after exact-head zero-trust
  GREEN.**

## 6. Global stop condition — "Verified" opens only when the whole chain is GREEN

**No `trusted_verified` ("Verified") renders, and `NoTrustedManifest` is not swapped,
until the ENTIRE chain — isolated signer + signed manifest + binary-pinned root anchor
+ anti-rollback + resolver — is GREEN.** Any partial landing (e.g. 3b-1 alone) keeps
every governed turn Blocked. "Verified" is a single, chain-complete event.

## 7. Non-goals (this design)

- Full supervisor/sidecar hardening (Waves 4–5) — 3b brings only the **minimal** key-
  custody core.
- Per-delta streaming receipts (deferred; sign-on-complete only, Wave 3 §7).
- Rotating the engine's existing key classes — the receipt signer is an **additional**
  key class, not a change to issuer/evidence/builder custody.

**No product code is authored under this document. Implementation begins only after
Architect + Owner approval of the boundaries in §1.**
