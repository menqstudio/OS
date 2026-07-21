# Wave 3 — Receipt Protocol v1 · DESIGN (rev 2, design-only)

> **Status:** DESIGN-ONLY, revised to the Architect's ratified decisions (YELLOW →
> direction approved with redlines). **No product code** ships under this document
> until it is approved. Every "Decision" below is now **ratified** unless marked open.
> Builds on the merged, bounded control plane: T-010 (capability boundary) + T-011
> (durable approval + native confirmation + atomic execution claim).

## 0. The defect (audit P0-2)

A governed turn returns a **self-asserted** receipt: the bridge-result carries
`receipt.verified: bool`, and both the Python adapter and the desktop
(`ai::interpret_bridge_result`) accept the reply when `ok && receipt.verified`. But
`verified` is a field a process **sets** — a compromised sidecar can set it `true` and
mint a forged "Verified" reply. **Even the desktop check is self-asserted today** (it
trusts the boolean in the bridge-result). Wave 3 makes the receipt a **signature the
desktop cryptographically verifies**, so an unforgeable "Verified" is the only way a
governed reply renders.

## 1. Key custody — Ratified: **Option B-core**

A signature is only as trustworthy as **who holds the signing key**. If the private
key lives in the sidecar process, a compromised sidecar (P0-3) signs a forged receipt
just as easily as it sets `verified: true` today — so crypto plumbing **alone** does
not close P0-2. Therefore the trusted-signer boundary's **minimal core is pulled into
Wave 3**, not deferred to Wave 5.

**Sequence (ratified):**
- **Wave 3a** — protocol + **desktop verifier** (fail-closed). Verification is real,
  but until 3b the governed path stays **opt-in + fail-closed** and the UI shows
  **Development / untrusted**, never "Verified".
- **Wave 3b** — **minimal isolated trusted signer** with real key custody (the private
  key lives in a boundary the sidecar cannot reach). **Only after 3b does "Verified"
  appear.**
- **Wave 5** — full signer/supervisor hardening.

**The trusted signer is NOT a generic `sign(arbitrary_bytes)` oracle.** It
independently **validates** the supervisor outcome / policy / containment evidence and
signs **only its own canonically-constructed receipt** for a run it recognizes as
completed-and-contained. A signer that will sign any bytes handed to it is equivalent
to the boolean.

## 2. Receipt envelope (what gets signed)

A canonical envelope, **RFC 8785 (JSON Canonicalization Scheme)** or canonical CBOR —
**not** merely "fixed JSON field order". Cross-language (Rust signer/verifier ↔ Python
adapter) **byte equality is part of the specification**; the chosen canonicalization is
normative and tested for identical bytes on both sides.

Fields (all mandatory unless noted):

```
protocol            "brops.receipt.v1"          domain separation
receipt_id                                       unique per receipt
key_id                                            which signing key (manifest, §5)
workspace_id / audience                           binds the receipt to this install
request_nonce                                     DESKTOP-generated challenge (§3)
request_sha256                                    hash of the exact governed request
decision            completed | denied | uncontained   (only "completed" is a grant)
policy_id
policy_version
policy_bundle_sha256                              the exact policy bundle in force
containment_evidence_sha256                       proof the run stayed contained
generation_config_sha256                          provider/model/tools/limits
system_sha256                                     exact system prompt behind the wall
history_sha256                                    exact turn input behind the wall
output_sha256                                     exact reply bytes (see §2.1)
executor_id / builder_id                          who ran the turn
supervisor_id                                     the signing supervisor identity
requested_at
completed_at
```
`receipt_signature = Ed25519(private_key, canonical(envelope))`. The bridge-result
becomes `{ ok, result, receipt: { envelope, signature }, error }`; the boolean
`receipt.verified` is **removed** — verification is a signature check, not a field.

**Policy binding + containment-evidence hash are mandatory.** Without them a valid
signature proves only "some signer signed this output", not "this output was produced
under *this* policy and stayed contained".

### 2.1 Exact output bytes (normative)
The signed `output_sha256` MUST be the hash of the **exact byte sequence that is
rendered and persisted** — no post-signature transformation. Define one rule: the
output is **UTF-8, NFC-normalized, with trailing-whitespace trimmed** (final spec TBD
in 3a), applied **before** hashing, rendering, and persistence, so the three are the
same bytes.

## 3. Verification seam (desktop = final authority, fail-closed)

**The desktop verifier is the final authority; the Python adapter's check is
defense-in-depth only.** Before returning any governed reply, the desktop MUST:

1. Parse `receipt.envelope` + `receipt.signature`.
2. Verify Ed25519 against the **pinned public key** for `key_id` from the trusted key
   manifest (§5) — never a key taken from the bridge-result.
3. `protocol == "brops.receipt.v1"` and `decision == "completed"`.
4. `request_nonce` equals the **one-time challenge this desktop generated** for this
   turn and has not been consumed — stored in **durable one-time state** (a
   signer-generated nonce does not prevent replay). `workspace_id`/audience match.
5. Recompute `output_sha256` (per §2.1) from the returned `result` and require
   equality — the signature must cover the exact rendered/persisted bytes.
6. (Bind the turn) `system_sha256`/`history_sha256`/`request_sha256` match what the
   desktop sent.
7. Any failure → **Blocked**, never rendered, never persisted as an agent message.
   "No verified signature ⇒ no result."

Pure and unit-testable: bad signature, wrong/absent `key_id`, `decision != completed`,
output mismatch, replayed/absent nonce, wrong workspace → all Blocked; a valid receipt
→ the reply.

## 4. Storage — migration **0014** (renumbered)

> 0013 is now T-011's `run_steps.execution_attempt_id`; the receipt migration is
> **0014**.

`messages` gains a **full auditable receipt record**, not just a status:
`receipt_status` (`verified` | `blocked` | NULL), the **full signed envelope JSON**,
the **signature**, `key_id`, `verified_at`, and `verification_error` (why a receipt was
blocked). Storing the whole envelope + signature lets a receipt be **re-verified /
audited later**. A DB trigger keeps `receipt_status` in the allowed set. The webview
never writes a `verified` receipt (Wave 2a posture) — only the governed reply path
does, after a real signature check.

## 5. Keys, manifest & rotation — Ratified

- **Algorithm:** Ed25519 (`ed25519-dalek` in Rust, `pynacl`/`cryptography` in Python).
- **Trust anchoring:** a **binary-pinned root trust anchor** + an **operator-provisioned
  signed key manifest**. **Not** a universal leaf public key baked into the binary,
  **not** unauthenticated first-run TOFU, **not** a plain editable config file.
- **Signed manifest** contains, per key: `key_id`, `public_key`, `supervisor_id`,
  `workspace`/scope, `valid_from` / `valid_to`, `key_epoch`, revocation status. The
  desktop accepts the manifest **only** if it validates against the binary-pinned root
  signature. The **webview has no command to change the key registry.**
- **Development key** may exist but the UI must label it **Development / untrusted** —
  never "Verified".
- **Rotation/revocation** via `key_id`/`key_epoch` selection over the pinned manifest.

## 6. Streaming — Ratified: sign-on-complete for v1

Sign the **final assembled output**, once, on completion. Until final signature
verification, governed deltas:
- MUST NOT render as trusted,
- MUST NOT persist as an `agent` message,
- MUST NOT receive a verified badge.

V1 flow: **buffer the whole governed output on the desktop → verify → display as a
single verified chunk.** Per-delta hash-chain / Merkle receipts are deferred to a later
version.

## 7. Rollout

1. **This design (rev 2)** → Architect + Owner approval. **Gate.**
2. **Wave 3a** — envelope + canonicalization spec + Ed25519 **desktop verifier**
   (fail-closed) wired into `ai::interpret_bridge_result` (replacing the boolean) +
   the Python adapter defense-in-depth check + migration 0014 + desktop-generated
   nonce challenge & durable one-time state + receipt storage/UI. Governed path stays
   opt-in; UI shows **Development / untrusted**. Negative-test matrix (§3).
3. **Wave 3b** — minimal **isolated trusted signer** with real key custody (private key
   unreachable by the sidecar) + the operator-provisioned signed key manifest + root
   anchor. **Only now does "Verified" render.**
4. **Wave 4** — supervisor hardening (P0-4). **Wave 5** — full signer/sidecar hardening.

## 8. Scope / non-goals

- **In scope:** the signed envelope + canonicalization spec, Ed25519 sign (trusted
  signer) + verify (desktop, final authority, fail-closed), policy + containment
  binding, exact-output-bytes rule, desktop nonce challenge, migration 0014 (full
  envelope + signature + verified_at + error), key manifest + root anchor, receipt
  UI rebuild (supersedes PR #13 on this basis), non-streaming/sign-on-complete.
- **Out of scope:** per-delta streaming receipts; full supervisor/sidecar hardening
  (Waves 4–5, though 3b brings the minimal key-custody core).

## 9. Ratified decisions (summary)

1. **Custody = Option B-core:** minimal trusted-signer boundary in Wave 3 (3a verifier
   → 3b isolated signer → then "Verified"); the signer validates outcome/policy/
   containment and signs only its own receipt — not a generic signing oracle.
2. **Envelope** includes protocol, receipt_id, workspace/audience, desktop nonce,
   request/system/history/output hashes, **policy_id/version/bundle hash**,
   **containment_evidence_sha256**, generation_config hash, executor/builder/supervisor
   ids, timestamps. **Canonicalization = RFC 8785 JCS or canonical CBOR**, byte-equal
   across Rust/Python (normative + tested).
3. **Provisioning** = binary-pinned root anchor + operator-provisioned signed manifest;
   no webview key command; dev key labeled untrusted.
4. **Streaming** = sign-on-complete; no trusted/persisted/badged deltas pre-verify.
5. **Desktop verifier is the final authority**; the Python adapter check is
   defense-in-depth. Nonce is **desktop-generated** + durable one-time.
6. **Migration 0014** stores the full envelope + signature + verified_at + error for
   re-verification.
7. **Exact output bytes** are specified (UTF-8/NFC/trim) and hashed == rendered ==
   persisted.

## 10. Open questions

- The exact output-normalization rule (§2.1) — confirm NFC + trailing-trim, or a
  stricter canonical text form?
- Canonicalization choice: **RFC 8785 JCS** (JSON, simpler tooling) vs **canonical
  CBOR** (compact, fewer float/string ambiguities) — recommend JCS unless CBOR is
  preferred for the signer.

**No product code is authored under this document.** Implementation begins only after
Architect + Owner approval.
