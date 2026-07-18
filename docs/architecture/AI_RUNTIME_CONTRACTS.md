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
queued -> planning -> awaiting_approval -> running -> paused -> completed | failed | cancelled.
Every transition emits an event. Cancellation is cooperative and tool invocations are idempotent where possible.

## Retries
Retry only transient/provider errors with exponential backoff and jitter. Never retry policy denial, invalid input or destructive action automatically. Default maximum: 3 attempts per step.

## Budgets
Budgets exist per run, agent, project and billing period: tokens, money, wall time, tool calls and retries. Crossing a soft limit warns; crossing a hard limit pauses and requests approval.

## Observability
Record provider/model, prompt version, input/output token counts, cost estimate, latency, tool calls, retries, errors and final status without recording secrets.
