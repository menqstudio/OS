# Phase 2 — Govern the remaining AI surfaces · design proposal (Architect audit requested)

> **STATUS: DESIGN PROPOSAL — NOT IMPLEMENTED. §I change-control (propose → Architect audit → Owner
> approve → implement).** This closes the honest security gap tracked in `ai-surface-policy.json`: three of
> the four model-provider entry points bypass the governance wall entirely. It does **NOT** change the gate
> logic, does **NOT** expose production "Verified", and preserves fail-closed. No code is routed until this
> is Architect design-GREEN.

## 0. Objective + honest current state

The whole product is a **governed** AI-operations desktop: every model call should pass through the wall
(challenge → prepare → execute behind the boundary → signed receipt → desktop verify → trust state). Today
only one of four AI surfaces even attempts that. Per `apps/desktop/src-tauri/ai-surface-policy.json` and
`commands.rs`:

| Surface (`#[tauri::command]`) | commands.rs | Provider reached today | Governed? |
|---|---|---|---|
| `stream_reply` | `834` | `ai::governed_turn` (923) **+** `ai::generate_stream` fallthrough (1016) | partial — governed primary, **ungoverned fallthrough** |
| `stream_run_step` | `1075` | `ai::generate_stream` (1211) | **NO** — direct generic provider |
| `stream_ask` | `1273` | `ai::generate_stream` (1282) | **NO** — direct generic provider |
| `reply_in_conversation` | `1305` | `ai::generate` (1329) | **NO** — direct generic provider |

`generic_provider_entrypoints = [ai::generate, ai::generate_stream]`; `governed_entrypoint =
ai::governed_turn`. Three surfaces call the generic entrypoints directly with no challenge, no receipt, no
verify — a governed AI desktop with three ungoverned back doors.

**This proposal:** route all four surfaces through the single governed authority path, and make the generic
provider entrypoints unreachable from any production surface. Reclassify all four to `governed` in the
policy. Preserve the existing fail-closed contract exactly.

## 1. Non-goals / invariants preserved (do not change)

- **No gate-logic change.** `NoTrustedManifest` stays fail-closed; production still **Blocks** every
  governed turn until the live trust chain is wired into the shipped runtime (a separate, code-audit-gated
  step — the broker `main()` keeps `UpstreamBlockedExecutor`). This proposal governs the surfaces; it does
  **not** enable `trusted_verified`.
- **No new provider path.** The generic `ai::generate` / `ai::generate_stream` remain the ONLY low-level
  provider calls; after this change they are reached **only** through `ai::governed_turn` (and the same
  `BROPS_ALLOW_UNGOVERNED` dev-opt-in fallthrough that `stream_reply` already has), never directly from a
  production surface.
- **Buffered, never streamed under governance** (design §3/§7): a governed turn is buffered + desktop-
  verified before any agent message is shown, exactly as `stream_reply` does today. Streaming stays only on
  the explicit `BROPS_ALLOW_UNGOVERNED` dev path.
- **The `ai-surface-policy.json` drift gate stays fail-closed** (`tools/check_ai_surfaces.py`).

## 2. The governed pattern to adopt (already proven in `stream_reply`)

`stream_reply` (commands.rs `861–…`) is the reference implementation and MUST be the shared shape:

1. `crate::ai::provider_is_governed()` — a **resolution error is fail-closed** (never silently ungoverned).
2. `Ok(true)` → `crate::ai::prepare_governed_turn(system, history, started_ms, workspace, install, gen_cfg)`
   (trim + hash the canonical context **once**), issue the one-time nonce challenge, run
   `crate::ai::governed_turn(&prepared)`, verify the signed receipt via `brops-core::receipt_store`, render
   the tri-state result (`trusted_verified` / `development_untrusted` / `blocked`). The accepted path
   persists itself (no double-post).
3. `Ok(false)` → the existing `BROPS_ALLOW_UNGOVERNED` streaming fallthrough (dev-only, fail-closed default).

The three ungoverned surfaces differ only in **how they assemble `(system, history)`** and **how they
surface the result** (streamed vs. buffered, run-step vs. chat vs. ask). The governed core is identical.

## 3. Per-surface plan

### 3.1 `reply_in_conversation` (1305) — the cleanest first slice
Non-streaming; already builds `(system, history)` then calls `ai::generate` (1329). Replace the direct
`generate` with the §2 governed pattern (buffered). On `Ok(true)` it runs the governed turn and persists the
verified reply through the receipt store; on production `NoTrustedManifest` it Blocks (a turn-level notice,
no agent message) — identical semantics to `stream_reply`. `Ok(false)` keeps the dev fallthrough.

### 3.2 `stream_ask` (1273) — one-shot "Ask Bro"
Builds an ephemeral `(system, history)` from `prompt`, calls `ai::generate_stream` (1282). Under governance
the answer is **buffered** (not streamed) then verified; the held answer is persisted by `save_ask_to_chat`
via its existing server-owned one-time `result_id` (T-013), which stays the provenance guard. The
`StreamEvent` channel still delivers a single buffered result + trust state instead of token deltas when
governed; token streaming remains only on the dev fallthrough.

### 3.3 `stream_run_step` (1075) — run-step execution
Routes through the **single governed authority entry** the policy already names —
`governed_turn_execute` — so a run step is a first-class governed turn (its `(system, history)` derives from
the step's inputs). NOTE: `governed_turn_execute` today is a thin stub (per the AI-surface inventory); this
surface's governance depends on that entry being completed to the same `prepare → governed_turn → verify`
contract. If completing `governed_turn_execute` requires an **engine schema change**, that is a separate
**audited engine task**, flagged here, not bundled.

### 3.4 `stream_reply` (834) — remove the ungoverned fallthrough for production
Once the three above are governed, tighten `stream_reply`: the `Ok(false)` branch reaching
`ai::generate_stream` (1016) is retained **only** under `BROPS_ALLOW_UNGOVERNED` (dev), never in a
production build. Reclassify to `governed`.

## 4. Policy reclassification + drift gate

After each surface routes only through `ai::governed_turn` / `governed_turn_execute`, update its
`ai-surface-policy.json` entry `governance: ungoverned_tracked → governed`, and `check_ai_surfaces.py` will
then **enforce** (fail CI closed) that the surface never reaches a generic entrypoint again — the gate flips
from *tracking* an ungoverned surface to *forbidding* one. `save_ask_to_chat` stays a persistence surface
(invokes no provider).

## 5. Tests (per surface)

- **Routing:** each governed surface reaches `ai::governed_turn` (or `governed_turn_execute`) and NEVER
  `ai::generate` / `ai::generate_stream` in a production build (unit + the `check_ai_surfaces.py` gate).
- **Fail-closed:** with `NoTrustedManifest`, each surface **Blocks** (turn-level notice, no agent message,
  no persisted reply) — byte-for-byte the `stream_reply` blocked behavior.
- **No double-post:** the accepted path persists exactly once (receipt store owns persistence).
- **Provenance:** `stream_ask` → `save_ask_to_chat` still requires the server-owned one-time `result_id`.
- **Dev fallthrough:** the ungoverned streaming path is reachable ONLY with `BROPS_ALLOW_UNGOVERNED`.

## 6. What this closes / threat model

Closes the three ungoverned provider back doors: after this, **no production Tauri command can reach the
model provider except through the governance wall**. It does not, by itself, produce `trusted_verified`
(that still needs the live chain wired into the shipped runtime + the Architect CODE-audit) — but it means
that when trust IS wired, every AI surface is already inside the wall, and until then every AI surface
honestly **Blocks** in production rather than silently calling the provider ungoverned.

## 7. Slicing (implement only after design-GREEN)

`reply_in_conversation` (3.1, simplest) → `stream_ask` (3.2) → `stream_run_step` (3.3, may surface an
audited engine task for `governed_turn_execute`) → tighten `stream_reply` (3.4) + policy reclassification.
Each slice keeps CI green and the AI-surface gate consistent; production stays fail-closed throughout.

---
**Requested:** Architect design audit of this proposal (RED/GREEN). No surface is routed until GREEN.
