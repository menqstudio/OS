# Tool Execution / Գործիքների կատարում

## Purpose / Նպատակ
Tool Execution is the controlled boundary between AI reasoning and external side effects.
Գործիքների կատարումը վերահսկվող սահման է AI reasoning-ի և արտաքին փոփոխությունների միջև։

## Execution Classes / Կատարման դասեր
- read-only inspection
- reversible write
- destructive write
- privileged or security-sensitive action
- external communication
- scheduled or repeated action

## Mandatory Contract / Պարտադիր պայմանագիր
Every tool call MUST declare:
- actor
- intent
- target
- scope
- inputs
- expected effect
- risk class
- approval requirement
- timeout and retry policy
- evidence to capture

## Lifecycle / Կյանքի ցիկլ
plan → policy check → approval check → execute → verify → record evidence → report

## Rules / Կանոններ
- A tool result is not success until verified.
- Retries MUST be bounded and idempotency-aware.
- Destructive actions MUST have an explicit target and recovery statement.
- Secrets MUST never be logged in plaintext.
- Partial failure MUST be reported precisely.
- Agents MUST NOT claim an action happened without execution evidence.

## Evidence / Ապացույց
Evidence may include commit SHA, file checksum, API response identifier, test output, screenshot, or verified state readback.
Ապացույցը կարող է լինել commit SHA, ֆայլի checksum, API response ID, թեստի արդյունք, screenshot կամ վիճակի վերահաստատում։
