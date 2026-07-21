# Wave 3 — Receipt Protocol v1 · DESIGN (DRAFT, design-only)

> **Status:** DRAFT for Architect + Owner review. **No product code** ships under this
> document until it is reviewed and approved — same gate as the Wave 2b design.
> Prepared autonomously to accelerate the review; treat every "Decision" below as a
> **proposal**, not a ratified choice.

## 0. The defect (audit P0-2)

Today a governed turn returns a **self-asserted** receipt: the bridge-result JSON
carries `receipt.verified: bool`, and both the Python adapter and the desktop
(`ai::interpret_bridge_result`) accept the reply only when `ok && receipt.verified`.
But `verified` is just a field a process **sets**. A compromised sidecar (or anything
that can produce the bridge-result) can set `verified: true` and mint a forged
"Verified" reply. The badge asserts provenance it cannot prove.

The seam for a real check already exists — `run_governed_turn(..., verify_receipt:
Callable)` injects a verifier, and `_receipt_of` defaults `verified=False` — but no
**cryptographic** verifier is wired. Wave 3 makes the receipt a **signature** the
desktop verifies, so an unforgeable "Verified" is the only way a reply renders.

## 1. The hard dependency this design must name up front

A signature is only as trustworthy as **who holds the signing key**. If the private
key lives in the **sidecar process**, then a compromised sidecar — exactly the P0-3
threat that **Wave 5 (trusted sidecar service)** exists to fix — can sign a forged
receipt, and Wave 3 buys nothing over the boolean.

So **Receipt Protocol v1 and the trusted-signer boundary are coupled.** This design
must decide (Architect):

- **Option A — Wave 3 defines the protocol + verification seam now; the key lives in
  the supervisor and real key-custody isolation lands with Wave 5.** Honest interim:
  until Wave 5, a compromised signer can still forge, so the governed path stays
  **fail-closed / opt-in** and the receipt is labeled "signed, custody-hardening
  pending". Ordering: Wave 3 (crypto plumbing + seam) → Wave 5 (key custody).
- **Option B — pull the trusted-signer boundary forward and do Wave 5 (or its key-
  custody core) BEFORE/with Wave 3**, so the signature is meaningful the day it ships.
  Safer, larger, reorders the roadmap.

**Recommendation:** Option A **only if** the governed path remains opt-in + fail-closed
and the UI never claims unconditional "Verified" until Wave 5; otherwise Option B.
This is the central question for the Architect.

## 2. Receipt envelope (what gets signed)

A canonical JSON envelope (fixed field order, no maps/floats → deterministic), hashed
and signed:

```
schema_version        1
turn_id               opaque id for this governed turn
key_id                which supervisor signing key (rotation-ready)
decision              "completed" | "denied" | "uncontained"   (only "completed" is a grant)
system_sha256         SHA-256 of the exact system prompt sent behind the wall
history_sha256        SHA-256 of the canonical turn input (messages) behind the wall
output_sha256         SHA-256 of the exact reply text returned
supervisor_id         the supervisor/verifier identity that ran the turn
issued_at             timestamp (ms)
nonce                 one-time value (anti-replay across turns)
```
`receipt_signature = Ed25519(private_key, canonical_json(envelope))`.

The bridge-result becomes `{ ok, result, receipt: { envelope, signature }, error }`.
`receipt.verified` (the boolean) is **removed** — verification is a signature check,
not a field.

## 3. Verification seam (desktop, fail-closed)

`ai::interpret_bridge_result` (and the Python adapter's `verify_receipt`) must, before
returning any reply:

1. Parse `receipt.envelope` + `receipt.signature`.
2. Verify the Ed25519 signature against the **pinned public key** for `key_id`
   (shipped with / provisioned to the desktop; NOT taken from the bridge-result).
3. Require `decision == "completed"`.
4. Recompute `output_sha256` from the returned `result` and require equality — the
   signature must cover the exact text being rendered (no swap after signing).
5. (Optional, stronger) bind `system_sha256`/`history_sha256` to what the desktop
   sent, so a replayed receipt for a different turn is refused.
6. Any failure → **Blocked**, never rendered. "No verified signature ⇒ no result."

Pure, unit-testable: signature-invalid, wrong key_id, decision≠completed, output
mismatch, replayed nonce → all Blocked; a valid receipt → the reply.

## 4. Storage (migration 0013 — renumbered)

> PR #13's held `0012_message_receipt` migration **must be renumbered to 0013**:
> 0012 is now T-011's `approval_provenance`.

`messages` gains a receipt record: `receipt_status` (`verified` | `blocked` | NULL),
plus verification metadata (`key_id`, `output_sha256`, `issued_at`) for audit. A
DB trigger keeps `receipt_status` in the allowed set. The client **never** writes a
`verified` receipt from the webview (Wave 2a posture) — only the governed reply path
does, after a real signature check.

## 5. Keys & rotation (proposal)

- **Algorithm:** Ed25519 (small, fast, well-supported; `ed25519-dalek` in Rust,
  `cryptography`/`pynacl` in Python).
- **Custody:** private key provisioned to the supervisor out-of-band by the operator
  (never in the repo, never in the webview). Public key **pinned** in the desktop.
- **Rotation:** `key_id` in the envelope selects the public key; the desktop holds a
  small pinned set. Revocation = remove the pinned public key.
- **Custody isolation** (the part that actually defeats a compromised sidecar) is the
  Wave 5 boundary — see §1.

## 6. Scope / non-goals

- **In scope:** the signed receipt envelope, Ed25519 sign (supervisor) + verify
  (desktop, fail-closed), output binding, migration 0013, the receipt-plumbing/UI
  (rebuild of PR #13 on the new basis), unit tests for the verification seam.
- **Out of scope (named):** key-custody isolation from a compromised sidecar (Wave 5);
  streaming receipts (a streamed governed turn signs the final assembled text — interim
  is non-streaming or sign-on-complete); supervisor hardening (Wave 4).

## 7. Open questions for Architect / Owner

1. **§1 — Option A vs B.** Ship the crypto now with custody-hardening deferred to
   Wave 5 (governed path stays opt-in + fail-closed, UI honest), or pull the trusted
   boundary forward first?
2. **Envelope completeness.** Is binding `system/history/output` sha256 + decision +
   nonce + key_id sufficient, or must more of the governed decision (policy id,
   containment evidence hash) be signed?
3. **Key provisioning** flow for the desktop (pinned public key): shipped in the
   binary, provisioned on first run, or operator-configured?
4. **Streaming:** acceptable to sign-on-complete (no per-delta receipt) for v1?

---

**No product code is authored under this document.** Implementation begins only after
Architect + Owner approval, and only after T-011 merges (this builds on the bounded,
durable control plane from T-010/T-011).
