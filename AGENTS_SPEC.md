# Agents Specification

## Agent model

Every agent is a scoped specialist. No agent is globally autonomous by default.

## Required agent profile

- Name and domain
- Mission
- Capabilities
- Tools
- Allowed data sources
- Prohibited actions
- Approval requirements
- Project access
- Memory scope
- Output contract
- Success metrics
- Failure and escalation rules

## Core statuses

Offline, Idle, Observing, Thinking, Waiting approval, Working, Blocked, Review, Failed, Completed.

## Delegation contract

Every delegated run must contain:

1. Objective
2. Context
3. Allowed scope
4. Expected output
5. Completion evidence
6. Deadline or stop condition
7. Approval boundary

## Agent teams

Agents may be grouped into persistent teams such as Product, Architecture, Engineering, Security, Operations, and Review. Bro coordinates cross-team work and prevents conflicting execution.

## Initial specialist set

Lens, Lezu, Forge, Tensor, Reviz, Mason, Pixel, Grid, Probe, Ops, Vault, Flow, Archi, Sigma, Steward, Pocket, Shield, Sentry, Hawk, Relay, Compass, Strat, Closer.

## Truth requirement

An agent may report only one of: completed with evidence, partially completed with evidence, blocked with reason, failed with reason, or not started. Vague progress claims are invalid.

---

# Agent-ների կանոններ

Յուրաքանչյուր agent մասնագիտացված և scope-ով սահմանափակ worker է։ Delegation-ը պարտադիր պարունակում է objective, context, allowed scope, expected output, evidence, stop condition և approval boundary։
