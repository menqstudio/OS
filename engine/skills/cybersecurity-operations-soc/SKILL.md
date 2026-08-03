---
id: cybersecurity-operations-soc
version: 1.1.0
status: active
---

# Cybersecurity Operations Soc

## Trigger
Use when the task is defensive security operations — triaging an alert or suspected incident, threat hunting, tuning detections, writing/reviewing SIEM or EDR rules, doing DFIR on a host or log set, mapping activity to MITRE ATT&CK, or assessing indicators of compromise. Not for authorized attack simulation (see offensive-security-pentesting).

## Inputs
Task contract with the alert/incident scope and severity; log and telemetry sources (EDR, SIEM, netflow, cloud audit, auth); detection rules or hunt hypothesis; asset/identity inventory and known-good baselines; IOC/TI feeds; the incident-response runbook (SST); and required output format (triage note, detection rule, or IR report).

## Workflow
1. Confirm identity, mode grant, scope, and read the IR runbook and detection inventory to EOF; establish the incident timeline anchor.
2. Scope and classify: what assets/identities/data are implicated, severity, and whether this is active. Preserve evidence read-only — never alter source logs or the affected host outside a granted containment action.
3. Build a chronological timeline from correlated telemetry; pivot on IOCs (hashes, IPs, domains, user agents, parent-child process trees) and map each step to MITRE ATT&CK tactics/techniques.
4. Separate true from false positive against the known-good baseline; identify the detection gap that missed or over-fired.
5. Author or tune detections as code (Sigma/KQL/SPL/EQL): specify logic, data source, false-positive profile, and test against historical data before proposing enablement.
6. Recommend containment/eradication/recovery steps per the runbook; flag any action requiring an explicit grant (isolation, credential reset, blocklist) for approval rather than executing.
7. Emit the triage/IR artifact with IOCs, ATT&CK mapping, confidence, and lessons-learned detection improvements.

## Outputs
A verdict (true/false positive) with confidence and evidence timeline; IOC list; ATT&CK technique mapping; tested detection rules with false-positive profile; recommended containment steps gated on approval; and residual-risk statement.

## Safety limits
No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. No host isolation, account disable, blocklisting, log deletion, or attacker-notification without the exact grant; never modify or destroy forensic evidence. Ambiguous containment targets fail closed.

## Handoffs
Escalate confirmed active/critical incidents to the incident commander, legal-hold and breach-notification questions to Regulatory/legal, and offensive validation to offensive-security-pentesting. Medium, high, and critical work requires an independent verifier. Containment/rule deployment hands off only to the Push Executor.

## Verification
Success requires a reproducible timeline from cited raw telemetry, IOCs validated against multiple sources, ATT&CK mapping justified per step, detection rules tested to a documented false-positive rate, and no evidence altered. An IOC or verdict without corroborating telemetry stays RED.

## Failure and rollback
Stop on missing authority, broken chain of custody, unreproducible timeline, or an untested rule. Revert any tuning change, preserve original evidence, restore the tree, and never declare an incident contained or a detection safe without verified evidence.
