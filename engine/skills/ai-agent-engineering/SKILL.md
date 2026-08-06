---
id: ai-agent-engineering
version: 1.1.0
status: active
---

# Ai Agent Engineering

## Trigger
Use when the task designs, builds, or debugs an autonomous or multi-agent system: tool/function-calling loops, agent orchestration and handoffs, planner/executor splits, memory and context management, retries and loop-termination, or agent evaluation harnesses. Also when diagnosing runaway loops, tool-call malformation, context-window overflow, or non-deterministic agent behavior.

## Inputs
Task contract with the target agent's role boundary; existing agent/graph definitions, tool schemas (JSON Schema), system prompts, and orchestration config; trace logs or transcripts of the failing run; the model id, temperature, and max-turn/budget limits; risk level and required output format.

## Workflow
1. Confirm identity, mode grant, scope, and the agent's authority boundary; read every affected tool schema, prompt, and graph node to EOF.
2. Reconstruct the failing trace turn-by-turn: map each tool call, its arguments, the observation returned, and the state mutation, before changing anything.
3. Establish a baseline eval set (golden tasks + adversarial/loop-bait cases) and record pass rate and token/turn cost.
4. Fix at the correct layer: tighten tool schemas and descriptions to remove ambiguity; make tools idempotent and error-returning (never throwing) so the loop can recover; add explicit termination conditions and turn/token budgets; scope memory writes as append-only with stable ids.
5. Keep the agent's granted authority unchanged — never widen tool access or bypass approval gates to "make it work".
6. Re-run the eval set plus negative tests (injection, malformed args, infinite-loop bait); compare against baseline.
7. Produce evidence, rollback instructions, and a residual-risk verdict.

## Outputs
Scoped changes to prompts/tool schemas/orchestration; updated or added eval cases; before/after eval pass rate and cost delta; reproducible run commands; trace excerpts as evidence; residual risks (non-determinism, prompt-injection surface, unbounded cost).

## Safety limits
No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. Never grant an agent new tools, network egress, or write authority beyond its contract. Ambiguous mutation targets and unbounded loops fail closed.

## Handoffs
Escalate cross-domain decisions to the owning SST role. Model/provider selection and cost-budget changes escalate to LLMOps. Medium, high, and critical work requires an independent verifier. Release actions hand off only to the Push Executor.

## Verification
Success requires schema-valid tool definitions, an eval set that passes at or above baseline with adversarial/injection cases covered, deterministic termination proven (no run exceeds the turn/token budget), clean rollback, and exact-head evidence. Claims of "fixed" without a re-run trace remain RED.

## Failure and rollback
Stop on missing authority, stale receipts, inconsistent SSTs, failing evals, non-terminating loops, or unverifiable traces. Restore the original prompts/schemas/config before reporting recovery and never call partial recovery GREEN.
