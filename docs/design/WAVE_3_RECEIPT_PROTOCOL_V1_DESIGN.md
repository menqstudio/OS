# Wave 3 — Receipt Protocol v1 · DESIGN (rev 4, design-only)

> **Status:** DESIGN-ONLY. rev 4 closes the final protocol-sweep normative points:
> the **signed-envelope wire format** + strict decode/parse rules; **tri-state**
> storage/outcome (dev-untrusted renders+persists); **every signed field bound** in
> the verification checklist; **manifest key `trust_class` + anti-rollback on
> same-epoch-different-hash**. **No product code** ships until this is Architect-GREEN.
> Builds on merged T-010 + T-011.
>
> **Implementation status (2026-07-22):** this design is **APPROVED + merged** (PR #23, `35a6ab5`).
> **Slice 1 (protocol core, `brops-core::receipt`)** is **DONE + merged** — PR #24, zero-trust
> GREEN (approved HEAD `c51031e`, merge commit `6c920d0`) after three RED rounds. **Slice 2**
> (storage & atomicity: migration 0014, atomic verify→consume→persist, one-time nonce, freshness)
> is the next task, **not started**; slice 3 (transport + UI) and Wave 3b (isolated signer +
> manifest + production "Verified") follow. Exact live state: root
> [`NEXT_CHAT.md`](../../NEXT_CHAT.md). This document remains the design spec.

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

### 2.3 Wire format & strict decoding — Ratified (normative)
The signature covers the **exact canonical bytes**, so those exact bytes travel on the
wire (never a re-serialized object):
```
receipt.envelope_jcs_b64 = base64url( JCS(envelope) bytes )
receipt.signature_b64    = base64url( Ed25519 signature )
```
The desktop MUST, in order:
1. base64url-**decode** to the exact envelope bytes (enforce a **max size**, e.g. 64 KiB).
2. **Strict-parse** the bytes as JSON with: **UTF-8 only, reject duplicate keys, reject
   unknown fields, fixed field types**, required fields present, and each hash field a
   lowercase 64-hex string.
3. Require **`JCS(parsed) == decoded bytes`** — the received bytes are already canonical
   (rejects a maliciously non-canonical encoding that a lax parser would accept).
4. **Verify the signature over the decoded bytes** (not over a re-encode).
5. **Store the decoded bytes unchanged** (§4).

This closes JSON parser-differential attacks: two parsers must not be able to read the
same bytes with different meaning.

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
8. **Every remaining signed field is bound**, not merely present:
   - `containment_evidence_sha256` == the hash of the **stored/returned containment
     evidence artifact** (the artifact is persisted, so the hash is semantically
     auditable later — a bare hash with no artifact proves nothing).
   - `executor_id` / `builder_id` are in the **expected/allowed** set for this install.
   - `receipt_id` is **globally unique** (never seen before — durable check).
   - `requested_at <= completed_at`, and both satisfy the **allowed freshness / clock-skew
     window** (a stale or future-dated receipt is refused).
9. Any mismatch/absence → **Blocked**. "No verified signature ⇒ no result."

Pure and unit-testable: each binding has a negative test (bad signature, wrong key,
out-of-window/revoked key, policy/config mismatch, replayed/absent nonce, wrong
workspace/install, output mismatch → Blocked; a fully-matching receipt → the reply).

## 4. Storage & atomicity — migration **0014** (normative)

> 0013 is T-011's `run_steps.execution_attempt_id`; the receipt migration is **0014**.

**Accepted output and blocked evidence are stored separately, tri-state:**
- **`messages`** holds **accepted output** — both `trusted_verified` **and**
  `development_untrusted` render **and** persist (they differ only in the badge, §6). A
  `blocked` verification **never** becomes an agent message.
- **`receipt_verification_attempts`** holds every attempt's evidence: the **exact
  canonical envelope bytes** (as decoded, not re-serialized) + **signature** + `key_id`
  + **`outcome` (tri-state: `trusted_verified` | `development_untrusted` | `blocked`)** +
  `verification_error` + `verified_at` + a link to the resulting message for the two
  accepted outcomes. This is the auditable/re-verifiable record. The message's rendered
  trust badge is derived from its attempt's `outcome`.

**Atomic verify → consume → persist (one DB transaction):**
```
BEGIN
  verify the receipt (§3) -> resolve outcome (trusted_verified | development_untrusted | blocked)
  consume the issued nonce (mark the desktop's one-time challenge spent)
  insert the receipt_verification_attempts row (envelope bytes + signature + outcome)
  if outcome is ACCEPTED (trusted_verified OR development_untrusted):
      insert the agent message (linked to the attempt; badge derived from outcome)
COMMIT
```
So a crash can neither persist an accepted message without consuming its nonce, nor
consume a nonce without persisting the message. A `blocked` attempt records evidence +
error and **does not** insert a `messages` row.

## 5. Keys, signed manifest & anti-rollback — Ratified

- **Algorithm:** Ed25519 (`ed25519-dalek` / `pynacl`).
- **Trust anchoring:** a **binary-pinned root trust anchor** validates an
  **operator-provisioned signed key manifest**. Not a baked-in leaf key, not
  unauthenticated TOFU, not a plain editable config. The **webview has no key-registry
  command.**
- **Manifest fields:** top-level `manifest_version`, `manifest_epoch`, `issued_at`,
  `expires_at`, root signature; **per key:** `key_id`, `public_key`, `supervisor_id`,
  `workspace`/scope, `valid_from`/`valid_to`, `key_epoch`, revocation status, and — new —
  **`trust_class: production | development`**, **`allowed_protocols`** (e.g.
  `["brops.receipt.v1"]`), and **`allowed_audiences`/install scope**. A key's
  `trust_class` is what decides `trusted_verified` vs `development_untrusted` (§6) — the
  classification is **signed into the manifest**, not inferred.
- **Anti-rollback:** a signed OLD manifest stays cryptographically valid and could
  re-introduce a revoked key. The desktop **durably records the highest accepted
  `manifest_epoch` AND that manifest's hash**, and refuses a manifest when:
  `epoch < highest_epoch`, **OR** `epoch == highest_epoch AND manifest_hash differs`,
  **OR** `now > expires_at`. Persisting `(highest_epoch, manifest_hash)` is **atomic**.
- **Wave 3a never hard-codes `trusted_verified`** — a missing/invalid/rolled-back
  manifest yields `blocked` (or `development_untrusted` only for an explicit dev key in
  dev mode), never a forced "Verified".

## 6. Trust states (3a) — Ratified (normative)

The desktop resolves every governed reply to exactly one state:

| State | Renders? | Persists to `messages`? | Badge |
|---|---|---|---|
| `trusted_verified` | yes | yes | **Verified** — full signature + all §3 bindings under a key whose manifest `trust_class == production`. **Only reachable after Wave 3b.** |
| `development_untrusted` | yes | yes | **Development / untrusted** — signature + bindings pass but the key's `trust_class == development` (explicit dev mode). Never "Verified". |
| `blocked` | no | **no** | none — missing/invalid/untrusted/policy-mismatched/replayed/rolled-back receipt. Evidence → `receipt_verification_attempts` only. |

The state is decided by the signed `trust_class` of the verifying key (§5), not
inferred by the desktop.

**Wave 3a never yields `trusted_verified`** — it ships the verifier and the dev/blocked
states; production "Verified" appears only once 3b's isolated signer + provisioned
manifest exist.

## 7. Streaming — Ratified: sign-on-complete (v1)

Sign the **final assembled output** once, on completion. Until final verification,
governed deltas MUST NOT render as trusted, MUST NOT persist as an `agent` message, and
MUST NOT get a verified badge. V1 flow: **buffer the whole governed output → verify →
display one verified chunk.** Per-delta hash-chain / Merkle receipts are deferred.

## 8. Rollout

1. **This design (rev 4)** → Architect + Owner **GREEN**. Gate.
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
9. **Wire format** = `envelope_jcs_b64` + `signature_b64`; strict decode (size cap,
   duplicate-key + unknown-field rejection, fixed types, `JCS(parsed)==decoded bytes`,
   verify over decoded bytes, store bytes unchanged) — no parser differentials (§2.3).
10. **Tri-state** everywhere: both `trusted_verified` and `development_untrusted`
    render **and** persist to `messages` (differ only in badge); `receipt_verification_
    attempts.outcome` is the tri-state (§4).
11. **All signed fields bound** — `containment_evidence_sha256` (== stored artifact
    hash), `executor_id`/`builder_id` allowed, `receipt_id` globally unique,
    `requested_at <= completed_at` + freshness/skew (§3.8).
12. **Manifest key `trust_class` (production|development) + allowed_protocols/audiences**
    are signed; anti-rollback also refuses `epoch == highest AND manifest_hash differs`;
    `(highest_epoch, manifest_hash)` persisted atomically; 3a never hard-codes
    `trusted_verified` (§5).

**No product code is authored under this document.** Implementation begins only after
Architect + Owner approval.
