# BroPS Product Architecture

- **Purpose:** Describe the system structure of BroPS — domains, entities, execution model, and state separation.
- **Scope:** Product architecture only. The AI runtime is in [AI_RUNTIME.md](AI_RUNTIME.md); UX surfaces are in [product/](product/).
- **Owner:** Gev.
- **Related:** [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md), [AI_RUNTIME.md](AI_RUNTIME.md), [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md), [product/NAVIGATION.md](product/NAVIGATION.md).
- **Last updated:** 2026-07-19.

## Core domains

1. Identity and access
2. Conversation and rooms
3. Projects and workspaces
4. Tasks and execution
5. Agents and teams
6. Knowledge and retrieval
7. Memory and preferences
8. Decisions and approvals
9. Files and sources
10. Calendar and scheduling
11. Automations and triggers
12. Integrations and external actions
13. Activity, audit, analytics, and security

## Primary entities

- User
- Agent
- AgentTeam
- Room
- Message
- Thread
- Project
- Task
- Decision
- Approval
- KnowledgeItem
- MemoryItem
- FileAsset
- Automation
- Integration
- ActivityEvent
- EvidenceRecord

These entities define the conceptual data model. The concrete persisted schema (tables, keys, indexes, migrations) is intentionally not specified yet; it is a Phase 3–4 deliverable (see [ROADMAP.md](ROADMAP.md)) and will be recorded in a dedicated `DATA_MODEL.md` when the application foundation begins.

## Execution model

1. Gev states intent.
2. Bro resolves objective, scope, risk, and context.
3. Bro proposes or creates an execution plan.
4. Work is delegated to specialist agents.
5. Approval gates stop actions requiring authority.
6. Agents execute within explicit scope.
7. Results include evidence and status.
8. Bro synthesizes and reports the final state.
9. Canonical project records are updated when required.

The mechanics of steps 2–8 (orchestrator modes, agent contracts, engines, events, tool execution, and the approval model) are canonical in [AI_RUNTIME.md](AI_RUNTIME.md).

## State separation

- Conversation state: temporary dialogue context
- Workspace state: current project and task state
- Canonical state: approved repository or database records
- Evidence state: logs, diffs, checks, outputs, and receipts
- Memory state: durable user and system context

## Product boundary

The first build is a product prototype and application foundation. Debian deployment, local models, background services, and infrastructure are later concerns and must not distort the initial product model.

---

# Ճարտարապետություն

BroPS-ը կառուցվում է առանձին domain-ներով, բայց օգտագործողի համար գործում է որպես մեկ միասնական AI Operating System։ Conversation-ը, canonical state-ը, evidence-ը և memory-ն տարբեր շերտեր են և չեն կարող խառնվել։ AI runtime-ի մեխանիկան canonical է [AI_RUNTIME.md](AI_RUNTIME.md)-ում, իսկ UI մակերեսները՝ [product/](product/)-ում։ Կոնկրետ տվյալների սխեման (`DATA_MODEL.md`) կսահմանվի Phase 3–4-ում, երբ սկսվի application-ի հիմքը։
