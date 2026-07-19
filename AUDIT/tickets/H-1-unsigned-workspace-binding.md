# H-1 — Workspace binding is declared operator-signed but loaded as unauthenticated JSON

- **Severity:** High (one auditor rated Critical; reconciled to High — see note)
- **Confidence:** High (3 auditors + source-verified)
- **Files:** `runtime/bro_workspace.py:114-148` (`load_workspace`); contrast `runtime/bro_control_plane.py:138-145` (signed `BRO_PROTECTED_AUTHORITY`)
- **Status:** Proposed patch (read-only audit)

## Problem
`bro_signature.py:85` classifies `"workspace-binding": OPERATOR` (an Ed25519-signable artifact), but `load_workspace` reads it as raw JSON from an agent-reachable env var and verifies **no signature**:
```python
raw = os.getenv("BRO_WORKSPACE_BINDING")
value = json.loads(binding_path.read_text(encoding="utf-8"))   # no verify_artifact
```
The binding supplies `allowed_paths`, `prohibited_paths`, `allowed_remote_repository`, `root`, `control_plane_digest`, and is the first gate every tool passes (`_bind_workspace`). The codebase defends the identical env-redirect exposure for `BRO_PROTECTED_AUTHORITY` with `verify_artifact` — the workspace binding is the one local-authority artifact left unprotected.

## Verification note (Critical → High)
`verify_control_plane_digest` **computes** ROOT's real digest and rejects on mismatch, and writing protected files is independently gated by the **signed** protected-authority — so a forged binding does **not** defeat control-plane integrity. Confirmed impact: forge a binding with `allowed_paths:["**"]`/`prohibited_paths:[]` to defeat operator workspace scope for **reads** (which have no second gate → read operator-restricted files inside the worktree, incl. `.git`/secrets), bypass workspace-level write prohibitions for paths still inside the signed contract scope, and neutralize `verify_workspace_remote`.

## Fix
In `load_workspace`, require a signed document and verify before trusting any field:
```python
document = json.loads(binding_path.read_text(encoding="utf-8"))
payload = verify_artifact(document, "workspace-binding", load_trusted_keys(root))
# then read allowed_paths/prohibited_paths/... from `payload`, not the raw doc
```
Jointly enforce the payload's `control_plane_digest`/`workspace_id` against the signed lease's, and (see M-8) enforce `expires_at_epoch`.

## Acceptance criteria
- [ ] An unsigned or wrong-signed `BRO_WORKSPACE_BINDING` is rejected (fail closed).
- [ ] A binding with `allowed_paths:["**"]` not signed by the operator is rejected.
- [ ] Reads are constrained by the verified `prohibited_paths` (an out-of-scope read inside the worktree is denied).
- [ ] Legitimate operator-signed bindings still load; existing workspace tests pass.
