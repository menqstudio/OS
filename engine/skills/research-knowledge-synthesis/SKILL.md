---
id: research-knowledge-synthesis
version: 1.1.0
status: active
---

# Research Knowledge Synthesis

## Trigger
Use when the task requires gathering evidence across many sources and producing a defensible, cited synthesis — a literature or landscape review, options/vendor comparison, technology or standards survey, systematic evidence summary, or a decision brief where every claim must trace to a source and conflicting evidence must be reconciled.

## Inputs
Task contract with the research question and decision it informs; inclusion/exclusion criteria; source corpus or allowed source types; recency and authority requirements; the SST of prior accepted findings; conflict-resolution rules; and required output format (brief, matrix, or annotated bibliography).

## Workflow
1. Confirm identity, mode grant, and scope; read prior accepted findings (SST) to EOF so the synthesis extends rather than contradicts the record.
2. Frame the question precisely (PICO-style where applicable) and fix inclusion/exclusion and recency criteria before searching, to avoid cherry-picking.
3. Search systematically across independent sources; log every query, source, date accessed, and why each was included or excluded for reproducibility.
4. Appraise each source for authority, recency, method quality, and bias; grade evidence strength and down-weight low-quality or non-independent corroboration.
5. Extract claims into a structured matrix (claim → source → strength → agree/conflict); never assert a claim without a traceable citation.
6. Reconcile conflicts explicitly: state the disagreement, weigh evidence, and give a calibrated confidence rather than hiding the tension; separate established fact from inference and from open question.
7. Synthesize into the requested artifact with an executive answer, the evidence base, confidence levels, and named gaps for further research.

## Outputs
A cited synthesis answering the question; a claim-source-strength matrix; explicit treatment of conflicting evidence with confidence levels; a search/inclusion log for reproducibility; and a list of knowledge gaps and their impact on the decision.

## Safety limits
No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. No fabricated, hallucinated, or uncited claims; no misrepresenting source strength or omitting contradicting evidence. Where a claim cannot be sourced, mark it unknown rather than assert it. Ambiguous scope fails closed.

## Handoffs
Escalate domain-specific technical judgments to the owning specialist and contested decisions to the decision owner. Medium, high, and critical syntheses require an independent verifier who spot-checks citations. Any published artifact hands off only to the Push Executor.

## Verification
Success requires every material claim traceable to a cited source, the search log reproducing the corpus, conflicting evidence surfaced not suppressed, confidence levels justified, and no uncited assertion. A synthesis with a claim a verifier cannot trace to its source stays RED.

## Failure and rollback
Stop on missing authority, an uncited or unverifiable claim, a failed citation spot-check, or suppressed conflict. Withdraw the affected conclusion, restore the prior accepted record, and never present unsourced or cherry-picked findings as GREEN.
