---
id: ai-ml-engineering-llmops
version: 1.1.0
status: active
---

# Ai Ml Engineering Llmops

## Trigger
Use when the task involves the LLM/ML production lifecycle: model or provider selection, prompt and inference-parameter tuning, prompt-caching and token-cost optimization, RAG retrieval quality, fine-tune/eval pipelines, model-version migration, latency/throughput tuning, or observability for model outputs (drift, refusals, hallucination rate).

## Inputs
Task contract with target metric (quality, cost, or latency); current model id(s), context and pricing, params (temperature, top_p, max_tokens), and caching config; representative prompts and a labeled eval/golden set; retrieval index config and chunking strategy if RAG; SLOs and budget ceilings; risk level and output format.

## Workflow
1. Confirm identity, mode, scope, and evidence; read prompt templates, inference config, and eval harness to EOF.
2. Define the objective as a measurable metric and lock a golden eval set with labels and an automated scorer (exact/semantic/LLM-judge as appropriate) before tuning.
3. Baseline current quality, p50/p95 latency, and cost-per-request; capture token counts per prompt segment.
4. Change one lever at a time: prompt structure, few-shot examples, params, model tier, or prompt-cache breakpoints on stable prefixes; for RAG, tune chunking, top-k, and reranking. Verify model ids/pricing against authoritative provider references, never memory.
5. For model migration, run old and new side-by-side on the golden set before cutover.
6. Re-run the eval and cost/latency measurement; keep the change only if it beats baseline within the budget.
7. Produce evidence, rollback instructions, and residual-risk verdict.

## Outputs
Tuned prompts/params/retrieval config or a migration plan; golden-set scores and cost/latency deltas vs baseline; the scorer and eval command; token-accounting evidence; residual risks (drift, provider-limit exposure, judge bias).

## Safety limits
No scope expansion, secret/API-key access, credential handling, push, merge, deployment, deletion, external communication, or production model swap without the exact governing grant and approval boundary. Never log raw secrets or PII into eval fixtures. Ambiguous mutation targets fail closed.

## Handoffs
Escalate cross-domain decisions to the owning SST role. Agent-loop and tool-orchestration changes hand to AI Agent Engineering; data-pipeline retraining hand to Data Engineering. Medium, high, and critical work requires an independent verifier. Release actions hand off only to the Push Executor.

## Verification
Success requires a reproducible golden-set score at or above baseline, measured cost and p95 latency within budget, model ids/pricing confirmed against authoritative sources, migration parity evidence when applicable, clean rollback, and exact-head evidence. Unmeasured "it seems better" claims remain RED.

## Failure and rollback
Stop on missing authority, stale receipts, inconsistent SSTs, regressed evals, budget breach, or unverifiable metrics. Restore prior prompts/config/model pin before reporting recovery and never call partial recovery GREEN.
