# Agent Flows

- **Purpose:** Define the agent profile, team, permission, and execution flows.
- **Scope:** Agent-facing UX. The agent model itself is canonical in [../AI_RUNTIME.md](../AI_RUNTIME.md).
- **Owner:** Gev.
- **Related:** [../AI_RUNTIME.md](../AI_RUNTIME.md), [DECISION_APPROVAL_FLOWS.md](DECISION_APPROVAL_FLOWS.md), [WORKSPACES.md](WORKSPACES.md), [STATES.md](STATES.md).
- **Last updated:** 2026-07-19.

## Gallery → profile

1. The Agents workspace shows a gallery of agent cards: name, role, live status, provider/model, capabilities, and active-run count.
2. Selecting a card opens the profile: identity and domain, capabilities, allowed tools, provider/model policy, permission scope, budget, memory scope, output contract, and run history. Secrets are never displayed.

## Create / configure

1. **New agent** captures name, domain, mission, capabilities, tools, allowed data sources, prohibited actions, approval requirements, project access, memory scope, and success metrics.
2. Configuration changes are drafts until saved; a saved change records an audit event.

## Assign and delegate

1. An agent is assigned from a task, a room mention, or the Command workspace.
2. Delegation binds the seven-field contract from [../AI_RUNTIME.md](../AI_RUNTIME.md): objective, context, allowed scope, expected output, completion evidence, deadline/stop condition, and approval boundary.
3. An agent cannot self-expand permissions; scope growth requires visible justification and, where needed, approval.

## Status lifecycle

Live status follows the canonical set: `offline → idle → observing → thinking → working → blocked → review → failed | completed`. Every transition is observable in the profile and in any room the agent participates in. `blocked` and `failed` always surface a reason.

## Pause / resume / escalate

- **Pause** halts new work while preserving state; **resume** continues. An emergency stop overrides active runs.
- On reaching a boundary the agent **escalates** with a precise reason rather than proceeding.

## Teams

Agents group into persistent teams — Product, Architecture, Engineering, Security, Operations, Review. Bro coordinates cross-team work and prevents conflicting execution.

## States

Every agent surface implements the patterns in [STATES.md](STATES.md): loading, empty (no agents / no runs), populated, error, offline, permission-denied, and awaiting-approval.

---

# Հայերեն

Ագենտների գործընթացները՝ gallery → profile (ինքնություն, capabilities, tools, provider/model, permissions, budget, memory scope, run history — secrets երբեք չեն ցուցադրվում), ագենտի ստեղծում/կարգավորում (draft-first, audit event), assign ու delegation (յոթ-դաշտանոց contract [../AI_RUNTIME.md](../AI_RUNTIME.md)-ից), status lifecycle (`offline→idle→observing→thinking→working→blocked→review→failed|completed`), pause/resume/escalate (emergency stop-ը գերակա է), և թիմեր (Product/Architecture/Engineering/Security/Operations/Review, համակարգում է Bro-ն)։ Ագենտը չի ընդլայնում իր permission-ները ինքնուրույն։ Բոլոր surface-ները կիրառում են [STATES.md](STATES.md)-ի վիճակները։
