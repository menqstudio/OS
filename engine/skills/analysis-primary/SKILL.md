---
id: analysis-primary
version: 1.1.0
status: active
---

# Analysis Primary

## Trigger
Use as the first-pass structured analysis of a problem, dataset, incident, or decision before deeper specialist work — decomposing an ambiguous ask, root-causing a failure, sizing an impact, or framing options and trade-offs so downstream specialists receive a sharp, evidence-anchored problem statement.

## Inputs
Task contract with the question or symptom; available evidence (logs, data, docs, tickets); constraints and the decision to be informed; the canonical SST for the affected domain; known prior findings; and required output format (analysis note, options matrix, or root-cause report).

## Workflow
1. Confirm identity, mode grant, and scope; read the relevant SST and prior findings to EOF before forming any hypothesis.
2. Restate the problem in one sentence and separate the observed symptom from assumed cause; list what is known, unknown, and assumed.
3. Decompose using an explicit frame (MECE breakdown, first principles, or a 5-whys / fishbone for root cause) so no major branch is silently dropped.
4. Gather and cite evidence for each branch; distinguish correlation from causation and quantify magnitude where possible rather than asserting significance.
5. Form competing hypotheses and actively seek disconfirming evidence for each; do not stop at the first plausible explanation.
6. Rank findings/options by impact and confidence, state assumptions and their fragility, and identify the smallest next action or experiment that would resolve the biggest uncertainty.
7. Emit a tight analysis with the answer, the reasoning chain, evidence, confidence, and a clear handoff to the owning specialist.

## Outputs
A concise problem statement; a structured decomposition; evidence-backed findings or ranked options with impact and confidence; stated assumptions and open questions; and a recommended next action or specialist handoff.

## Safety limits
No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. This skill analyzes and recommends; it does not execute mutations. No unstated assumption presented as fact and no conclusion beyond what the evidence supports. Ambiguous scope fails closed.

## Handoffs
Escalate domain execution to the owning specialist (data, security, telecom, regulatory) with the framed problem attached. Medium, high, and critical analyses require an independent verifier of the reasoning and evidence. Any resulting change hands off only to the Push Executor.

## Verification
Success requires each conclusion tied to cited evidence, the decomposition covering the problem without gaps, disconfirming evidence considered, assumptions made explicit, and confidence calibrated. A conclusion that outruns its evidence or hides an assumption stays RED.

## Failure and rollback
Stop on missing authority, insufficient evidence, or a decomposition that omits a material branch. Withdraw the affected conclusion, mark the gap, restore the prior record, and never present an under-evidenced analysis as GREEN.
