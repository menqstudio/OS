# Wave 3 — Receipt Protocol v1 · DESIGN (rev 3, design-only)

> **Status:** DESIGN-ONLY. rev 3 closes the four normative points the Architect
> required before Wave 3a implementation (canonicalization + exact output bytes;
> complete verification checklist; atomic nonce-consume+persist with blocked evidence
> kept off `messages`; manifest anti-rollback + normative 3a trust states). **No
> product code** ships until this is Architect-GREEN. Builds on merged T-010 + T-011.

## 0. The defect (audit P0-2)

A governed turn returns a **self-asserted** receipt (`receipt.verified: bool`) that
both the Python adapter and the desktop trust. A compromised sidecar can set it `true`.
Wave 3 replaces the boolean with a **signature the desktop cryptographically verifies**
against a pinned key, so an unforgeable "Verified" is the only way a governed reply
renders.

## 1. Key custody — Ratified: **Option B-core**

Crypto plumbing alone does not close P0-2: if the private key is reachable by the
sidecar (P0-3), a compromised sidecar signs a forged receipt as easily as it sets the
boolean today. So the trusted-signer boundary's **minimal core is in Wave 3**.

- **Wave 3a** — protocol + **desktop verifier** (fail-closed). UI shows
  **development/untrusted**, never "Verified".
- **Wave 3b** — **minimal isolated trusted signer** with real key custody (private key
  unreachable by the sidecar). **Only after 3b does "Verified" render.**
- **Wave 5** — full signer/supervisor hardening.

The signer is **not a generic `sign(arbitrary_bytes)` oracle**: it independently
validates the supervisor outcome / policy / containment evidence and signs **only its
own canonically-constructed receipt** for a run it recognizes as completed-and-contained.

## 2. Canonicalization & the receipt envelope — Ratified (normative)

- **Canonicalization = RFC 8785 (JSON Canonicalization Scheme, JCS).** Normative; the
  Rust signer/verifier and the Python adapter MUST produce **byte-identical** canonical
  bytes for the same envelope (cross-language byte-equality is tested).
- `receipt_signature = Ed25519(private_key, JCS(envelope))`.

Envelope fields (all mandatory unless noted):

```
protocol                 "brops.receipt.v1"     domain separation
receipt_id                                        unique per receipt
key_id                                             signing key (manifest, §5)
workspace_id                                       the workspace
install_id / audience                              THIS install (separate from workspace_id)
request_nonce                                       DESKTOP-generated challenge (§3)
request_sha256                                      JCS-hash of the canonical request envelope (§2.2)
decision                 completed|denied|uncontained   (only "completed" is a grant)
policy_id
policy_version
policy_bundle_sha256                               the exact policy bundle in force
containment_evidence_sha256                        proof the run stayed contained
generation_config_sha256                           provider/model/tools/limits
system_sha256                                       exact system prompt behind the wall
history_sha256                                      exact turn input behind the wall
output_sha256                                       SHA-256 of the exact reply bytes (§2.1)
executor_id / builder_id                            who ran the turn
supervisor_id                                       signing supervisor identity
requested_at
completed_at
```
The boolean `receipt.verified` is **removed** — verification is a signature check.
Policy binding + containment-evidence hash are **mandatory**: a signature without them
proves only "some signer signed this output", not "produced under *this* policy and
contained".

### 2.1 Exact output bytes — Ratified (normative)
`output_sha256 = SHA-256(exact UTF-8 result bytes)`. **No NFC normalization, no
trimming, no line-ending rewrite, no transformation of any kind.** The **byte sequence
that is hashed, rendered, and persisted is literally identical** — the output is
treated as opaque bytes end-to-end.

### 2.2 Canonical request envelope — Ratified
`request_sha256` is the **JCS-hash of a defined canonical request envelope** (not a
vague "exact governed request"): `{ protocol: "brops.request.v1", workspace_id,
install_id, request_nonce, system_sha256, history_sha256, generation_config_sha256,
requested_at }`. The desktop builds this envelope when it issues the request, hashes it
(JCS + SHA-256), and later requires the receipt's `request_sha256` to equal it.

## 3. Verification seam — desktop = final authority, fail-closed

**The desktop verifier is the final authority; the Python adapter check is
defense-in-depth only.** Before returning any governed reply the desktop MUST verify —
each with an **expected-value comparison**, any failure → **Blocked**:

1. `protocol == "brops.receipt.v1"`; Ed25519 signature valid over `JCS(envelope)`
   against the **pinned public key** for `key_id` from the trusted manifest (§5).
2. `decision == "completed"`.
3. `request_nonce` == the one-time challenge THIS desktop issued for this turn, still
   unconsumed (durable one-time state, §4); `request_sha256` == the desktop's canonical
   request-envelope hash (§2.2).
4. **Identity/scope bindings all match expected:** `workspace_id`, `install_id`/audience,
   `supervisor_id`.
5. **Policy/config bindings all match expected:** `policy_id`, `policy_version`,
   `policy_bundle_sha256`, `generation_config_sha256`.
6. **Key bindings:** the `key_id`'s manifest entry is in **scope**, inside its
   **validity window** (`valid_from`/`valid_to`), at an accepted **key epoch**, and
   **not revoked** (§5).
7. `output_sha256` (§2.1) recomputed from the returned bytes == envelope; `system_sha256`
   / `history_sha256` == what the desktop sent.
8. Any mismatch/absence → **Blocked**. "No verified signature ⇒ no result."

Pure and unit-testable: each binding has a negative test (bad signature, wrong key,
out-of-window/revoked key, policy/config mismatch, replayed/absent nonce, wrong
workspace/install, output mismatch → Blocked; a fully-matching receipt → the reply).

## 4. Storage & atomicity — migration **0014** (normative)

> 0013 is T-011's `run_steps.execution_attempt_id`; the receipt migration is **0014**.

**Accepted output and blocked evidence are stored separately:**
- **`messages`** holds **only accepted (verified) output.** A blocked verification
  never becomes an agent message.
- **`receipt_verification_attempts`** holds every attempt's evidence: the **exact
  canonical envelope bytes** (as received, not a re-serialized object) + **signature**
  + `key_id` + `outcome` (`verified`|`blocked`) + `verification_error` + `verified_at`
  + a link to the resulting message when accepted. This is the auditable/re-verifiable
  record.

**Atomic verify → consume → persist (one DB transaction):**
```
BEGIN
  verify the receipt (§3)
  consume the issued nonce (mark the desktop's one-time challenge spent)
  insert the receipt_verification_attempts row (envelope bytes + signature + outcome)
  if verified: insert the agent message (linked to the attempt)
COMMIT
```
So a crash can neither persist a verified message without consuming its nonce, nor
consume a nonce without persisting the verified message. A blocked attempt records
evidence + error and **does not** insert a `messages` row.

## 5. Keys, signed manifest & anti-rollback — Ratified

- **Algorithm:** Ed25519 (`ed25519-dalek` / `pynacl`).
- **Trust anchoring:** a **binary-pinned root trust anchor** validates an
  **operator-provisioned signed key manifest**. Not a baked-in leaf key, not
  unauthenticated TOFU, not a plain editable config. The **webview has no key-registry
  command.**
- **Manifest fields:** top-level `manifest_version`, `manifest_epoch`, `issued_at`,
  `expires_at`, root signature; per key: `key_id`, `public_key`, `supervisor_id`,
  `workspace`/scope, `valid_from`/`valid_to`, `key_epoch`, revocation status.
- **Anti-rollback:** a signed OLD manifest is still cryptographically valid and could
  re-introduce a revoked key. The desktop **durably records the highest accepted
  `manifest_epoch`** and **refuses any manifest with a lower epoch** (and any past
  `expires_at`). Revocation is therefore not undo-able by replaying an old manifest.
- **Development key** may exist but drives only the `development_untrusted` state (§6) —
  never "Verified".

## 6. Trust states (3a) — Ratified (normative)

The desktop resolves every governed reply to exactly one state:

| State | Meaning |
|---|---|
| `trusted_verified` | Full signature + all §3 bindings pass under a **production** key. **Only reachable after Wave 3b** (isolated signer). The only state that renders "Verified". |
| `development_untrusted` | Signature valid but under a **development** key, in explicit dev mode. Renders **Development / untrusted** — never "Verified". |
| `blocked` | Missing / invalid / untrusted / policy-mismatched / replayed receipt. Not rendered, not persisted to `messages`; evidence goes to `receipt_verification_attempts`. |

**Wave 3a never yields `trusted_verified`** — it ships the verifier and the dev/blocked
states; production "Verified" appears only once 3b's isolated signer + provisioned
manifest exist.

## 7. Streaming — Ratified: sign-on-complete (v1)

Sign the **final assembled output** once, on completion. Until final verification,
governed deltas MUST NOT render as trusted, MUST NOT persist as an `agent` message, and
MUST NOT get a verified badge. V1 flow: **buffer the whole governed output → verify →
display one verified chunk.** Per-delta hash-chain / Merkle receipts are deferred.

## 8. Rollout

1. **This design (rev 3)** → Architect + Owner **GREEN**. Gate.
2. **Wave 3a** — JCS canonicalization + envelope (§2) + exact-output-bytes (§2.1) +
   desktop verifier with the full checklist (§3) + migration 0014 + the atomic
   verify→consume→persist transaction (§4) + `receipt_verification_attempts` +
   desktop nonce challenge & durable one-time state + trust states (§6, dev/blocked
   only) + receipt UI. Governed path opt-in; UI never "Verified". Negative-test matrix.
3. **Wave 3b** — isolated trusted signer + signed manifest + root anchor + anti-rollback
   (§5). Enables `trusted_verified` / production "Verified".
4. **Wave 4** supervisor hardening · **Wave 5** full signer/sidecar hardening.

## 9. Scope / non-goals

- **In scope:** JCS envelope + exact-bytes spec, Ed25519 sign (trusted signer) + verify
  (desktop, final authority, fail-closed) with the complete binding checklist, atomic
  verify→consume→persist, split storage (accepted vs. attempts) with full envelope
  bytes, desktop nonce challenge, migration 0014, signed manifest + root anchor +
  anti-rollback, trust-state machine, sign-on-complete, receipt UI (supersedes PR #13).
- **Out of scope:** per-delta streaming receipts; full supervisor/sidecar hardening
  (Waves 4–5; 3b brings the minimal key-custody core).

## 10. Ratified normative decisions (summary)

1. **Canonicalization = RFC 8785 JCS**, byte-equal Rust↔Python (tested).
2. **`output_sha256 = SHA-256(exact UTF-8 bytes)`** — no NFC/trim/line-ending rewrite;
   hashed == rendered == persisted, literally.
3. **`request_sha256`** = JCS-hash of the defined canonical **request** envelope (§2.2).
4. **Desktop verifier compares expected values** for every identity/policy/config/key
   binding (§3); the desktop is the final authority, Python is defense-in-depth.
5. **Nonce is desktop-generated + durable one-time**; verify→consume→persist is **one
   transaction**; **blocked evidence never enters `messages`** (goes to
   `receipt_verification_attempts`, storing exact envelope bytes + signature).
6. **Signed manifest** with `manifest_epoch` + **anti-rollback** (durable highest
   accepted epoch); binary-pinned root anchor; no webview key command; dev key drives
   `development_untrusted`, not "Verified".
7. **Trust states** `trusted_verified` (only after 3b) / `development_untrusted` /
   `blocked` are normative; **3a never renders "Verified"**.
8. **Migration 0014** stores the full envelope + signature + verified_at + error.

**No product code is authored under this document.** Implementation begins only after
Architect + Owner approval.
