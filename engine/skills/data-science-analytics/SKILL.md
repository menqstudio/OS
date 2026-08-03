---
id: data-science-analytics
version: 1.1.0
status: active
---

# Data Science Analytics

## Trigger
Use when the task requires statistical inference, experiment design, predictive modeling, or metric definition — e.g. an A/B test readout, cohort/funnel analysis, a forecast, a churn/propensity model, anomaly detection, or a disputed KPI whose definition or math must be settled with reproducible evidence.

## Inputs
Task contract with the decision the analysis must inform; dataset locations and grain; column/event dictionaries; canonical metric definitions (SST); population and time window; confidence/power requirements; risk level; and required output format (notebook, report, or model artifact).

## Workflow
1. Confirm identity, mode grant, scope, and that every referenced dataset and metric definition exists; read the SST metric layer to EOF.
2. Profile the data: row counts, null rates, cardinality, duplicate keys, grain, and the join fan-out risk before any aggregation.
3. State the hypothesis or estimand, the unit of analysis, and the pre-registered success/stopping criteria; avoid choosing the metric after seeing results.
4. For experiments: verify randomization balance and Sample Ratio Mismatch, pick the test (t/Mann-Whitney/CUPED/proportion) matching the distribution, compute power, and correct for multiple comparisons.
5. For models: hold out a temporal or grouped split (no leakage), establish a naive baseline, tune, and report calibration plus a fairness/slice breakdown, not just aggregate accuracy.
6. Quantify uncertainty (CI or bootstrap), run sensitivity to outliers and window choice, and set every seed for determinism.
7. Emit a reproducible notebook/script with pinned versions, the decision recommendation, and named threats to validity.

## Outputs
A seeded, re-runnable analysis; effect sizes with confidence intervals and p-values (or model metrics with calibration and slices); the metric SQL/definition used; data-quality caveats; and an explicit decision recommendation with residual risks.

## Safety limits
No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. Never query or move PII beyond the granted dataset; no p-hacking, peeking-based early stops, or metric redefinition after results. Ambiguous data targets fail closed.

## Handoffs
Escalate schema/pipeline changes to Data Architecture Leadership and metric-of-record changes to the metric owner. Medium, high, and critical work requires an independent verifier who re-runs the notebook. Release actions hand off only to the Push Executor.

## Verification
Success requires a clean re-run from a fresh kernel producing identical numbers, seeds fixed, no train/test leakage, SRM within tolerance for experiments, CIs reported, and the metric matching the SST definition. A result that does not reproduce byte-for-byte on re-run stays RED.

## Failure and rollback
Stop on missing authority, stale receipts, undefined metrics, failed reproduction, SRM failure, or detected leakage. Discard the tainted analysis, restore the original tree/notebook state, and never report a non-reproducing or peeked result as GREEN.
