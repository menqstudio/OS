# Security Model

## Trust boundaries

- Gev controls credentials, repository permissions, approval grants, and production access.
- Bro controls planning, routing, delegation, and reporting.
- The orchestration SST controls lifecycle, queue, checkpoint, budget, recovery, and governed command truth.
- The durable runtime stores validated task contracts and append-only records outside Git.
- Packs control scoped execution only.
- Verifiers control evidence-based verdicts, not implementation.
- Push Executor controls the final transport step but not approval or verification.

## Fail-closed controls

- stale or missing full-read receipt;
- repository tree mismatch;
- missing or invalid task contract;
- missing required skill receipt;
- review-mode mutation attempt;
- work-mode push attempt;
- release role mismatch;
- unsupported completion claim;
- invalid lifecycle transition or actor identity;
- runtime record sequence, identity, or hash-chain mismatch;
- concurrent claim without exclusive serialization;
- expired, mismatched, or evidence-free claim lease operation;
- stale or evidence-free checkpoint;
- silent soft or hard budget overrun;
- ambiguous in-flight cancellation without recovery evidence.

## Runtime integrity boundary

Live task state is not canonical repository truth and must not be committed accidentally. It is reconstructed from immutable task contracts and validated append-only records. Queue claims are serialized across processes and bound to expiring leases. Broken chains, duplicate claims, stale leases, unknown state, and unproved recovery are never GREEN.

## Proof boundary

A byte-level full-read receipt proves that files were read to EOF and hashed. It does not prove human-like semantic understanding. Canonical documents are additionally injected into model context, while task-relevant skills must be explicitly loaded before specialist execution.
