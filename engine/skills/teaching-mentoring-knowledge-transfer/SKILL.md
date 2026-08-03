---
id: teaching-mentoring-knowledge-transfer
version: 1.1.0
status: active
---

# Teaching Mentoring Knowledge Transfer

## Trigger
Use when the task is to design learning: curriculum/course structure, onboarding paths, runbooks and how-to documentation, tutorials, mentoring plans, skill-gap assessment, or capturing tribal/expert knowledge before it's lost. Also for explaining a complex concept for a specific audience. Do NOT use for performance management (route to people-org-leadership) or brand content (route to marketing-brand).

## Inputs
- Learner profile: current level, prior knowledge, and role context.
- The concrete capability the learner must be able to DO afterward (not just "know").
- Source material or the expert/SME whose knowledge is being captured.
- Constraints: time budget, format (self-serve doc, live, video), and how mastery will be checked.

## Workflow
1. Define learning objectives as observable behaviors: "learner can X" (do, decide, diagnose) — not "understands X"; work backward from that.
2. Assess the gap between current and target level; skip what they already know and target the actual delta.
3. Sequence for cognitive load: prerequisites first, one new concept at a time, concrete-before-abstract, and scaffold from worked example → guided practice → independent practice.
4. Anchor each concept to a real task the learner faces; use worked examples and the "why," not just steps, so knowledge transfers to new situations.
5. For knowledge capture: extract the SME's decision rules, failure modes, and heuristics — the judgment, not just the procedure; write it so a non-expert can act.
6. Build retrieval and feedback: check-for-understanding questions, a hands-on exercise per objective, and spaced reinforcement — passive reading does not build capability.
7. Make it maintainable: date it, name an owner, and note what invalidates it, so the doc/runbook doesn't rot.

## Outputs
- Learning objectives as observable capabilities.
- Sequenced curriculum/onboarding path or runbook, with worked examples and rationale.
- Practice exercises and knowledge checks mapped to each objective.
- Captured SME heuristics/failure modes, with owner and review date.

## Safety limits
No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. Never publish to shared knowledge bases or send training without grant. Do not present unverified procedures as authoritative; flag steps needing SME confirmation. Ambiguous mutation targets fail closed.

## Handoffs
Skill decisions tied to performance/promotion to people-org-leadership. Regulated/compliance training content to legal-compliance-contracts for accuracy sign-off. Localization to language-mastery. Escalate cross-domain decisions to the owning SST role; medium, high, and critical work requires an independent verifier (ideally the SME); publish actions hand off only to the authorized executor.

## Verification
Confirm every objective is an observable capability with a matching practice/check; content is sequenced by cognitive load; procedures are SME-verified or explicitly flagged; runbooks carry owner and review date. Any step presented as authoritative without SME confirmation remains RED.

## Failure and rollback
Stop on vague objectives, unverified procedures, missing learner profile, or a request to publish without grant. Discard the draft, restore prior material, and report the missing input. Never mark unverified or objective-less learning content GREEN.
