# BroPS AI Runtime Contracts

## Provider contract
Providers expose model discovery, text/tool streaming, structured output, usage accounting, cancellation and normalized errors. Provider adapters MUST not leak provider-specific response shapes into domain logic.

## Model policy
Each agent has preferred and fallback models, capability requirements, context limit, cost ceiling, latency target and data-sharing classification. Routing considers task type, privacy, availability, budget and quality.

## Prompt contract
Prompts are versioned artifacts with identity, objective, allowed context, tools, output schema, refusal rules and termination criteria. Runtime context is assembled separately and provenance is recorded.

## Agent contract
An agent declares identity, domain, capabilities, tool permissions, provider policy, memory access, approval requirements and measurable completion conditions. Agents cannot self-expand permissions.

## Run lifecycle
The status set is the one the code enforces — `RUN_STATUSES` in `src-tauri/core/src/domain.rs`, mirrored by `RunStatus` in `src/domain/enums.ts` and by the trigger in migration `0011`: `drafted`, `queued`, `planning`, `awaiting_approval`, `running`, `paused`, `succeeded`, `failed`, `cancelled`. (This line ended in `completed`, which is not a status; the handoff's `waiting_approval` is not one either.)
Every transition emits an event. Cancellation is cooperative and tool invocations are idempotent where possible.

## Retries
Retry only transient/provider errors with exponential backoff and jitter. Never retry policy denial, invalid input or destructive action automatically. Default maximum: 3 attempts per step.

## Budgets
Budgets exist per run, agent, project and billing period: tokens, money, wall time, tool calls and retries. Crossing a soft limit warns; crossing a hard limit pauses and requests approval. **Not implemented:** no run, agent, project or billing-period budget exists in the code, and the handoff contract says the opposite about a hard limit ("crossing a budget cancels safely"). Which of the two is intended is an open product decision, not a behaviour.

## Observability
Record provider/model, prompt version, input/output token counts, cost estimate, latency, tool calls, retries, errors and final status without recording secrets.
