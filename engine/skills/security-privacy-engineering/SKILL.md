---
id: security-privacy-engineering
version: 1.1.0
status: active
---

# Security Privacy Engineering

## Trigger
Use when the task assesses or hardens security and privacy posture: authentication/authorization design, input validation and injection surface, secret and key handling, cryptographic choices, data classification and PII minimization, threat modeling, dependency/supply-chain risk, or triaging a suspected vulnerability. Also whenever a change touches auth, untrusted input, or sensitive data.

## Inputs
Task contract with the asset or surface under review and the trust boundary; relevant code, auth/session flow, data schema, and dependency manifest; data-classification and regulatory constraints; the threat model or attacker profile if one exists; risk level and output format.

## Workflow
1. Confirm identity, mode, scope, and evidence; read the affected auth flow, data handling, and trust boundaries to EOF.
2. Threat-model the surface: enumerate entry points, trust boundaries, assets, and attacker capabilities (STRIDE or equivalent) before proposing fixes.
3. Verify authorization on every request at the object level (not just authentication), validate and canonicalize all untrusted input, and use parameterized/escaped queries and safe encoders against injection.
4. Handle secrets and crypto correctly: no secrets in code/logs/bundles, use a managed store, use vetted algorithms and libraries (never hand-rolled crypto), and enforce least privilege on every credential.
5. Minimize data: classify PII, collect and retain the minimum, and apply encryption in transit and at rest per the classification.
6. For a suspected vulnerability, prove it with a minimal reproduction/PoC, then propose the smallest fix and a regression test that fails on the exploit; check dependencies for known CVEs.
7. Produce evidence, rollback instructions, and a residual-risk verdict — never expose live secrets in the report.

## Outputs
A findings report with severity, exploitability, and affected trust boundary; a minimal reproduction for each confirmed issue; proposed least-privilege fixes and an exploit-regression test; dependency/CVE exposure; residual risks and accepted-risk notes. Findings and patches only in review mode.

## Safety limits
No scope expansion, secret access, credential handling, exfiltration, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. Never disclose, log, or transmit real secrets/PII; redact in all evidence. Exploit PoCs run only against in-scope non-production targets. Ambiguous mutation targets fail closed.

## Handoffs
Escalate cross-domain decisions to the owning SST role. Code remediation hands to the relevant engineering skill; infra/secret-store and network controls to DevOps/SRE; data-model changes to Databases & Storage. Medium, high, and critical work requires an independent verifier. Release actions hand off only to the Push Executor.

## Verification
Success requires each confirmed finding backed by a minimal reproduction, the fix proven by an exploit-regression test that fails before and passes after, least privilege and injection safety demonstrated, no secret/PII leaked in evidence, dependency CVEs checked, clean rollback, and exact-head evidence. Unreproduced "potential" findings are labeled as such, and fixes without regression coverage remain RED.

## Failure and rollback
Stop on missing authority, stale receipts, inconsistent SSTs, an unreproduced claimed exploit, or any risk of secret exposure. Restore the original tree before reporting recovery and never call partial recovery GREEN.
