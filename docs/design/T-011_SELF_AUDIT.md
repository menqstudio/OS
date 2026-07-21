# T-011 — adversarial self-audit (pre-review)

> Done autonomously while the Owner was away, to converge the zero-trust review
> faster. Records what was probed, what was fixed, and the residuals with their
> exploitability. This is a self-review, not a substitute for the Owner's audit.

## Fixed during self-audit

- **Internal enforcement tokens were serialized to the untrusted renderer.**
  `list_approvals` (and any command returning `Approval`) serialized `nonce`,
  `request_digest`, `confirmation_digest`, and `origin_session_id` to the webview.
  These are server-only integrity material; a leaked one-time nonce/digest is needless
  attack surface. Fixed with `#[serde(skip_serializing)]` on those four fields; the
  safe provenance fields (`origin_principal`, `confirmed_at`, `confirmed_by`,
  `confirmation_method`) stay visible for display. Test:
  `t011_internal_tokens_are_not_serialized_to_the_webview`.

## Probed and found NOT exploitable (residuals, documented)

- **TOCTOU between approve and execute.** The digest binds the run/step payload at
  approve time; `stream_run_step` reads the payload at execution time. If the payload
  could be mutated in between, the executed prompt would differ from the confirmed one.
  **Not reachable:** there is **no command** to mutate a run's `intent`/`plan` or a
  step's `title`/`detail` after creation (`create_run`/`add_run_step` set them once;
  no `update_run`/`update_step`). The whole payload is immutable server-side data.
  If a mutate command is ever added, an execution-time digest recheck (recompute the
  scope digest, compare to the confirmed one, before running) must be added with it.

- **Single-window principal check is dormant in production.** With one window, a
  requester is always `webview:main` and the confirmer is always the `native`
  authority, so the durable self-approval check never fires in the normal flow — the
  real gate is the native dialog (renderer cannot forge it). The `origin_principal`
  check remains correct defense-in-depth (a `native`-origin request could not
  self-approve) and is exercised by the tests.

- **Non-run-step approvals show `target` only.** `execution_payload` returns `None`
  for non-run entities and the dialog falls back to the (UI-text) `target`. Only
  run-step approvals are ever created today (`stream_run_step`), so this path is
  unused; if other approval kinds are added they need their own canonical scope.

- **In-memory rate limit / single-active guard reset on restart.** These bound
  automated prompt spam; they are not a security boundary and a restart clearing them
  is acceptable. The `ConfirmationGuard` is held across the dialog `await` (bound as
  `let _guard`, not `let _`) and clears on return/cancel/panic-unwind.

## Invariants re-verified

- `consume_for` is still called on the run-completion paths — one native approval
  unlocks exactly one execution (M-2 intact).
- The request envelope is deterministic (fixed struct field order, no maps, no floats)
  → a stable digest across runs/platforms.
- `decide` refuses `"approved"` at the authority layer; `approved_for` requires the
  native-confirmation markers + consumed nonce — the "native-only approve" invariant
  lives in core, not just the command.
