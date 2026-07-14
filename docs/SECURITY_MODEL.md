# Security Model

## Trust boundaries

- Gev controls credentials, repository permissions, approval grants, and production access.
- Bro controls planning, routing, delegation, and reporting.
- Packs control scoped execution only.
- Verifiers control evidence-based verdicts, not implementation.
- Push Executor controls the final transport step but not approval or verification.

## Fail-closed controls

- stale or missing full-read receipt,
- repository tree mismatch,
- missing task contract,
- missing required skill receipt,
- review-mode mutation attempt,
- work-mode push attempt,
- release role mismatch,
- unsupported completion claim.

## Proof boundary

A byte-level full-read receipt proves that files were read to EOF and hashed. It does not prove human-like semantic understanding. Canonical documents are additionally injected into model context, while task-relevant skills must be explicitly loaded before specialist execution.
