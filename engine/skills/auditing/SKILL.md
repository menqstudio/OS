---
id: auditing
version: 1.1.0
status: active
---

# Auditing

## Trigger
Use when the task is independent verification against a defined standard — a controls/compliance audit, code or change review for policy conformance, evidence and access review, reconciliation of claimed vs. actual state, or attesting that a control operated. The auditor checks; it never performs or approves the work it audits.

## Inputs
Task contract naming the audit objective and the control framework or policy (SST) to test against; the population/scope and period; the assertions being tested; evidence sources (logs, configs, tickets, commits, access records); sampling rules; and required output format (audit report with findings and ratings).

## Workflow
1. Confirm identity, mode grant, and independence (not the author of the audited work); read the governing standard/policy and prior audit findings to EOF.
2. Define the objective, in-scope population, period, and the specific control assertions to test; fix the sampling method before pulling evidence.
3. Collect evidence read-only; preserve it with source, timestamp, and hash where applicable — never alter the audited system or its records.
4. Test each control for design (is it adequate?) and operating effectiveness (did it actually run over the period?); trace claims to independent, corroborating evidence, not self-attestation.
5. Record every exception with the expected vs. observed state, root cause, severity, and the control/requirement it breaches; distinguish isolated exceptions from systemic gaps.
6. Rate findings by risk, propose remediation owners and required corrective action, and separate audit opinion from management response.
7. Emit the audit report: scope, method, evidence trail, findings with severity, and an overall opinion with residual risk.

## Outputs
An audit report with objective and scope; the tested controls and results (pass/exception); an evidence trail per finding; severity-rated exceptions with root cause and remediation; and an overall opinion with residual risk.

## Safety limits
No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. The auditor must not remediate, approve, or modify the work under audit (segregation of duties), nor alter evidence. Accepting self-attestation as proof, or narrowing scope to avoid a finding, is prohibited. Ambiguity fails closed as a finding, not a pass.

## Handoffs
Escalate material or systemic findings to the control owner and governance; hand remediation to the responsible specialist (never self-remediate). Medium, high, and critical audits require an independent verifier of the evidence and ratings. Any resulting change hands off only to the Push Executor.

## Verification
Success requires every finding backed by preserved, independently-sourced evidence, controls tested for both design and operation over the full period, sampling defensible, and no evidence altered. A pass opinion resting on self-attestation or an untested control stays RED.

## Failure and rollback
Stop on missing authority, compromised independence, altered or incomplete evidence, or an untestable assertion. Mark it an exception rather than a pass, preserve the original evidence and tree, and never issue a clean opinion without a verified evidence trail.
