# Wave 3b-1B — implementation status (RC branch `impl/wave-3b1b-execution-binding`)

> **STATUS:** Release-candidate for the 3b-1B **execution→receipt binding** trust chain, built on
> the ChatGPT partial (`OS_PARTIAL_HANDOFF_2026-07-26`, sha256 `b043ae3b…`) applied onto the exact
> rev-26 canonical base `6ebeca88627640eef8effe576b3d388417cb4949`. **NOT design-GREEN, NOT merged.**
> The five rev-26 canonical documentation files are **unchanged** — this file is an additive
> design→code status map, not a design edit. The normative source of truth remains
> [`WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md`](./WAVE_3B1B_EXECUTION_BINDING_ADDENDUM.md).

## Provenance + scope

The partial was authored against the rev-26 constants/closures but on the rev-25 *code* tree. It was
applied here with `git apply --3way` onto live rev-26; the canonical docs were preserved. This RC is
**3b-1B trust-chain only** — it is explicitly NOT 3b-2, NOT 3b-3, and NOT the Phase 0–10 application
completion. Per the repo ordering law (`WAVE_3B1_EXECUTION_BINDING_MAP.md`: "3b-2 does not start
until 3b-1 is exact-head zero-trust GREEN and merged"), 3b-2/3b-3 remain **held** until the Owner
merges 3b-1 and the Architect returns design-GREEN.

## Zero-trust audit → remediation (this RC)

A fresh 4-track zero-trust audit (challenge-authority · governed supervisor/signer · desktop Rust
trust chain · bridge/schemas) was run against the full rev-26 §0–§9 and the real code. The desktop
verifier was found **cryptographically sound and fail-closed** (production `trusted_verified` is
gated behind the complete signature→manifest-root→attestation→§7.1-binding→nonce→uniqueness→freshness
chain; `NoTrustedManifest` stays fail-closed; `receipt.rs` and its frozen fixtures are byte-identical;
strict-JCS and manifest anti-rollback are genuine; the `cfg-sha256:` identity formula and pinned
`generation_config_sha256 = 732b5863…` are correct, no registry-as-identity). The audit found
**4 BLOCKER + 9 MAJOR + minors**, split into two tiers.

### Tier-1 — CLOSED in this RC (contained, locally verified where the platform allows)

| # | Area | Fix |
|---|---|---|
| B | challenge-authority §2.1.1(d) | a physically-present but retention-expired ISSUED row now refuses `pending_expired` (was the swept-case `no_pending_row`); inline DELETE removed, cleanup left to `sweep()`. Both main + CAS-loser paths. New test. |
| M | challenge-authority §2.1(B) | an oversize ISSUE frame now refuses in-set `malformed` (was out-of-set `oversize`). New test. |
| B | bridge diagnostic §4.10(h) | the diagnostic `stage` vocabulary is now exactly the 5 locked sidecar hops (`governed-turn-open`/`staging-open`/`staging-chunk`/`staging-final`/`evidence-request`) across schema + `brops_governed_common.py` + `governed_v1b.py` + the `ai.rs` classifier; transport/local failures now use a distinct signature-free `bridge.governed-turn-transport-failure.v1` frame that the desktop rule-4 catch-all maps to `governed_transport_failure`. New pure tests. |
| B | bridge result §4.5/§4.6 | the refused arm `reason` is now a CLOSED enum (the enforced 22-member `GOVERNED_REFUSAL_REASONS`), not an open `string`. |
| M | bridge result §4.6/§4.10(f) | the success-arm receipt schema now carries `key_id` + `receipt_id` (the producer emits them; the desktop pull binding requires `receipt_id`). |
| M | desktop routing §4.10(f) | an output-read refusal now uses the disjoint 4th prefix `governed_output_read_refused:{reason}` (was mislabeled `governed_verdict_refused:`). |
| M | supervisor output-stream §4.10(f) | quota is now **FIFO-evict** (oldest by `created_at_ms`) with `MAX_OUTPUT_STREAM_ROWS_PER_INSTALL = 64` + a `MAX_OUTPUT_STREAM_BYTES_PER_INSTALL = 512 MiB` byte quota; a completing/signed turn's stream is **always** created (was refusing it with `stream_unknown`). Row eviction never unlinks the content-addressed output bytes. |
| M | supervisor §4.10(d) | pre-acceptance "no INPUTS_READY row" failures now return the disjoint `brops.governed-evidence-request-result.v1 {refused, no_inputs_ready}` (was leaking `challenge_replay`/`lease_not_ready`, which are `GOVERNED_REFUSAL_REASONS` verdict members); the bridge routes it to a stage-`evidence-request` diagnostic. |
| m | desktop hardening | `record_handle` is now type-validated (64-hex) in `prepare_with_snapshot` so a malformed signed envelope refuses rather than panics; removed an unused `manifest.rs` import. |

### Tier-2 — DEFERRED (tracked; not in this RC)

These are large, security-critical mechanisms that are **absent or reduced** in the partial. They are
deferred deliberately: each is provable only on the Linux CI harness (AF_UNIX + `SO_PEERCRED` +
dedicated principals — unrunnable on the Windows dev box), and several touch design that the Architect
has not yet design-GREENed, so implementing them now risks rework against a moving rev-26 closure
review. **Independently verified as genuinely absent** (not audit artifacts):

1. **§7 durable evidence-head anti-rollback floor** — no `governed_evidence_head_floor` table, no
   `validate_chain_detailed`, no A–E CAS matrix; the supervisor mints a degenerate inline evidence
   event (`evidence_head_sequence: 0`, `evidence_event_count: 1`). A rolled-back/forked/stale head is
   not detectable, and the §9 "replayed old evidence head" negative test cannot pass.
2. **§5 durable acceptance ledger + outbox + crash-recovery** — no separate `governed_turn_acceptance`
   table; the `ACCEPTED_PREPARED`/`LEASE_READY`/`EXECUTION_STARTING` states are folded into the single
   synchronous `governed_turn_staging` table with no persisted `lease_payload_bytes` and no restart
   re-evaluation of the launch gate.
3. **§8 dual-key authority separation** — a single `recorder_key` signs BOTH the execution receipt and
   the terminal record; §8 requires a distinct evidence-recorder principal vs the governed-turn-recorder.
   A faithful fix spans the engine signer + supervisor + desktop verifier + signed manifest + pinned
   roots + the Linux-only isolation proof.
4. **Desktop `governed_turn_execute` command (§4.10(g))** — the design mandates exactly one new
   frontend-exposed governed command; the partial folded the flow into the frozen Wave-3a `stream_reply`
   branch instead. Security is contained (all inputs backend-resolved, already capability-gated, 66-command
   gate intact), but it is a frozen-path / design-conformance deviation to reconcile.

Lower-severity deferrals (defense-in-depth / completeness, current behavior is safe): `load_snapshot`
root-signature re-verification on use; the `BROPS_GOVERNED_*` override resolver; `PreparedGovernedTurnV1B`
field encapsulation; the code(22)-vs-addendum(27) `GOVERNED_REFUSAL_REASONS` reconciliation; the
looser-than-code submit `max_output_tokens` schema pattern.

## STOP gates (unchanged, in force)

`NoTrustedManifest` unchanged and fail-closed · no production "Verified" without the complete real
chain · 3b-2/3b-3 not started · **not merged** · rev-26 not Architect-GREEN · frozen Wave-3a / 3b-1A
protocols + fixtures byte-for-byte preserved.
