# BroPS — Implementation Execution Handoff

Status: implementation contract for `brops-v1-foundation-implementation`
Target: runnable Windows desktop application built with React, TypeScript, Vite and Tauri.
Owner approval required only for merge/release, destructive migration, secret deletion, or material scope change.

## 1. Mandatory startup

1. Verify a real worktree, git, Node/npm, Rust/Cargo and Tauri prerequisites.
2. Fetch `main` and `brops-v1-foundation-implementation`.
3. Checkout the implementation branch only.
4. Read every tracked Markdown file before changing architecture.
5. Inventory current files, dependencies, incomplete scaffolding and contradictions.
6. Preserve approved product laws: Bro-first orchestration, local-first data, explicit permissions, auditability, HY/EN/RU, dark/light.
7. Never claim GREEN without actual command output.

## 2. Required product surface

Primary navigation:

1. Command
2. Projects
3. Tasks
4. Agents
5. Knowledge
6. Memory
7. Group Chat
8. Notifications
9. Settings

Global surfaces:

- left navigation
- top command/search bar
- command palette
- workspace tabs
- right context drawer
- approval drawer
- notification center
- global toast area
- offline/degraded banner
- first-run onboarding
- lock/PIN screen

## 3. Target repository structure

```text
/
  package.json
  tsconfig.json
  vite.config.ts
  index.html
  src/
    app/
      App.tsx
      router.tsx
      providers.tsx
      error-boundary.tsx
    components/
      primitives/
      layout/
      feedback/
      command/
      approvals/
      agents/
      chat/
    features/
      command/
      projects/
      tasks/
      agents/
      knowledge/
      memory/
      group-chat/
      notifications/
      settings/
    domain/
      entities.ts
      enums.ts
      contracts.ts
      validation.ts
    runtime/
      ai/
      approvals/
      permissions/
      events/
      notifications/
      backup/
    services/
      desktop.ts
      repository.ts
      secure-store.ts
      telemetry.ts
    state/
      app-store.ts
      selectors.ts
    i18n/
      index.ts
      hy.ts
      en.ts
      ru.ts
    theme/
      tokens.css
      global.css
      themes.css
    test/
  src-tauri/
    Cargo.toml
    tauri.conf.json
    capabilities/
      default.json
    migrations/
      0001_initial.sql
    src/
      main.rs
      lib.rs
      state.rs
      error.rs
      commands/
        db.rs
        projects.rs
        tasks.rs
        agents.rs
        chat.rs
        knowledge.rs
        memory.rs
        permissions.rs
        notifications.rs
        secrets.rs
        backup.rs
        ai.rs
      db/
        mod.rs
        migrations.rs
        repositories/
      secure_store/
      backup/
      ai_runtime/
  .github/workflows/
    ci.yml
    desktop-build.yml
```

## 4. Data model and SQLite schema

Use SQLite with foreign keys enabled, WAL mode, migrations and repository interfaces. IDs are UUID strings. Timestamps are UTC ISO-8601. Never expose raw SQL to React.

Core tables:

### workspaces
- id PK
- name
- description nullable
- status: active|archived
- created_at
- updated_at

### projects
- id PK
- workspace_id FK
- name
- description
- status: planned|active|blocked|completed|archived
- priority: low|normal|high|critical
- owner_agent_id nullable
- created_at
- updated_at
- archived_at nullable

### tasks
- id PK
- project_id nullable FK
- parent_task_id nullable FK
- title
- description
- status: inbox|planned|ready|running|blocked|review|done|cancelled
- priority
- assigned_agent_id nullable FK
- due_at nullable
- position integer
- created_at
- updated_at
- completed_at nullable

### agents
- id PK
- slug unique
- display_name
- role
- description
- status: active|paused|disabled
- provider_profile_id nullable FK
- system_prompt_id nullable FK
- capability_json
- budget_json
- created_at
- updated_at

### conversations
- id PK
- type: direct|group|command|agent-run
- title
- project_id nullable FK
- created_at
- updated_at

### conversation_members
- conversation_id FK
- member_type: user|agent
- member_id
- joined_at
- composite PK

### messages
- id PK
- conversation_id FK
- sender_type
- sender_id
- role: user|assistant|system|tool
- content_json
- status: pending|streaming|complete|failed|cancelled
- reply_to_id nullable
- created_at
- updated_at

### command_runs
- id PK
- conversation_id nullable FK
- command_text
- objective
- status: drafted|queued|running|waiting_approval|succeeded|failed|cancelled
- orchestrator_plan_json
- result_json nullable
- error_json nullable
- started_at nullable
- finished_at nullable
- created_at

### agent_runs
- id PK
- command_run_id FK
- agent_id FK
- attempt integer
- status
- input_json
- output_json nullable
- usage_json nullable
- error_json nullable
- started_at
- finished_at nullable

### approvals
- id PK
- command_run_id nullable FK
- action_type
- risk_level: low|medium|high|critical
- request_json
- status: pending|approved|denied|expired|cancelled
- decision_note nullable
- requested_at
- decided_at nullable

### permission_grants
- id PK
- subject_type: user|agent|runtime
- subject_id
- capability
- scope_json
- decision: allow|deny|ask
- expires_at nullable
- created_at
- updated_at

### notifications
- id PK
- type
- severity: info|success|warning|error|critical
- title
- body
- entity_type nullable
- entity_id nullable
- read_at nullable
- created_at

### knowledge_items
- id PK
- type: note|document|link|snippet|decision
- title
- content_text
- source_uri nullable
- metadata_json
- created_at
- updated_at

### memory_items
- id PK
- category: preference|fact|decision|lesson|failure|relationship
- subject
- content
- confidence real
- sensitivity: normal|private|secret
- provenance_json
- status: active|superseded|deleted
- created_at
- updated_at

### provider_profiles
- id PK
- provider: openai|anthropic|google|local|custom
- display_name
- endpoint nullable
- default_model
- secret_ref nullable
- settings_json
- enabled boolean
- created_at
- updated_at

### prompt_templates
- id PK
- slug unique
- name
- version integer
- template
- variables_json
- checksum
- active boolean
- created_at

### event_log
- id PK
- event_type
- actor_type
- actor_id nullable
- entity_type nullable
- entity_id nullable
- payload_json
- correlation_id nullable
- created_at

### backups
- id PK
- file_path
- checksum
- encrypted boolean
- schema_version
- status
- created_at

Indexes are mandatory for foreign keys, statuses, timestamps, message conversation order, task project/status and event correlation IDs.

## 5. Frontend state architecture

Use TanStack Query for server/desktop data and Zustand only for ephemeral UI state.

Persistent domain state belongs in SQLite. Do not duplicate database entities into a global mutable store.

Ephemeral state examples:
- active route
- open drawers/modals
- selected workspace tab
- command draft
- streaming state
- language
- theme
- density

Every async surface must implement:
- initial loading
- refreshing
- empty
- populated
- validation error
- recoverable error with retry
- permission denied
- offline/degraded
- destructive confirmation

## 6. UX/UI page contract

### Command
Components: command composer, scope selector, agent recommendation, execution plan preview, live run timeline, approvals, results, artifacts.
States: blank, drafting, validating, planning, awaiting approval, executing, partial result, success, failure, cancelled.

### Projects
Components: list/grid switch, filters, project card, detail panel, activity, linked tasks/knowledge/chat.
Responsive: desktop split view; narrow screens use full-page detail.

### Tasks
Components: inbox, board/list, filters, task editor, dependencies, assignee, run action.
Support keyboard creation, optimistic safe edits and rollback on failure.

### Agents
Components: roster, status, capabilities, provider/model, budget, prompt version, recent runs, pause/resume.
Secrets are never displayed.

### Knowledge
Components: source list, search, reader/editor, tags, provenance, linked entities.
No fake vector search claim; add semantic retrieval only after an actual index exists.

### Memory
Components: categories, confidence, provenance, sensitivity, edit/supersede/delete flows.
Deletion of sensitive memory requires explicit confirmation and audit event.

### Group Chat
Components: conversation list, member panel, timeline, composer, mentions, agent status, artifacts.
Agents must not silently execute tools merely because they were mentioned.

### Notifications
Components: unread/read tabs, severity filters, entity links, mark read, settings shortcut.

### Settings
Sections: profile, appearance, language, AI providers, permissions, notifications, storage, backup/restore, security, diagnostics, about.

Responsive breakpoints must be tokenized. At narrow width collapse navigation, drawers become sheets, data tables become cards, but desktop remains the primary target.

## 7. Localization and themes

Languages: Armenian (`hy`), English (`en`), Russian (`ru`).

Rules:
- no user-facing literal strings outside dictionaries
- stable translation keys
- fallback language English
- language persisted locally
- date/number formatting through `Intl`
- Armenian and Russian must be complete, not partial placeholders

Themes:
- `light` and `dark`, plus optional `system` preference resolving to one of them
- semantic tokens only: background, surface, elevated, text, muted, border, accent, success, warning, danger, focus
- meet WCAG AA for core text and controls
- no hard-coded component colors

## 8. Tauri desktop boundary

React may call only typed Tauri commands through `services/desktop.ts`.

Required command groups:
- database initialization and health
- CRUD repositories
- secure secret save/delete/status
- file picker/import/export
- backup create/list/verify/restore
- notification permission/status/send
- AI run start/cancel/status
- diagnostics export

Security:
- minimal capabilities
- deny arbitrary shell execution
- no unrestricted filesystem access
- validate all command inputs in Rust
- normalize/canonicalize paths
- never log secret values
- secrets stored through OS credential/keyring integration; DB stores references only

## 9. Backup and restore

Backup package includes:
- SQLite consistent snapshot
- manifest with app version/schema version/timestamp
- SHA-256 checksums
- optional user-selected attachments

Default backup excludes provider secrets. Restore flow:
1. select backup
2. verify package/checksum/version
3. show impact preview
4. create automatic pre-restore backup
5. close DB handles
6. restore atomically
7. run migrations
8. run integrity check
9. record event
10. report exact success/failure

Failed restore must roll back to the pre-restore snapshot.

## 10. Permissions and notifications

Permission decisions: `allow`, `deny`, `ask`.

Capabilities include:
- read/write project data
- read/write files within selected scope
- external network/provider call
- send desktop notification
- access secret reference
- create backup
- destructive delete

High-risk and destructive operations always require current explicit approval. Persistent grants must have visible scope and revocation.

Desktop notifications:
- request OS permission intentionally
- in-app notification is always written first
- deduplicate repeated events
- clicking a notification deep-links to the relevant entity
- quiet hours and per-category settings

## 11. AI runtime contracts

### Provider interface

```ts
interface AiProvider {
  id: string;
  listModels(): Promise<ModelInfo[]>;
  validateConfiguration(): Promise<ProviderHealth>;
  generate(request: GenerateRequest, signal: AbortSignal): AsyncIterable<ProviderEvent>;
}
```

### Orchestrator stages
1. normalize user objective
2. load authorized context
3. classify risk
4. build explicit plan
5. select agents/providers
6. estimate budget
7. request approval when required
8. execute bounded runs
9. verify outputs
10. persist result/events
11. present provenance and unresolved uncertainty

### Retry policy
- retry only transient failures: timeout, 429, selected 5xx
- exponential backoff with jitter
- maximum three attempts by default
- no automatic retry for invalid credentials, policy denial or malformed deterministic input
- every attempt recorded

### Budgets
Enforce per-run:
- token limit
- monetary limit where pricing is known
- wall-clock timeout
- max tool calls
- max agent fan-out
- max retry count

Crossing a budget cancels safely and produces a partial-result state, never a fabricated success.

### Prompt management
- versioned prompt templates
- checksum stored with each run
- variables validated
- system instructions separated from user content
- no secret interpolation into prompts unless explicitly required and authorized

## 12. Minimum runnable implementation

The first GREEN candidate must include real, working implementations for:

- app boot and error boundary
- navigation for all primary pages
- language switch HY/EN/RU
- dark/light switch
- SQLite initialization and migrations
- projects CRUD
- tasks CRUD
- agents CRUD/status
- direct and group conversations persisted locally
- message composer and history
- in-app notifications
- permission request/decision UI
- provider configuration without exposing keys
- one real provider adapter behind the common interface
- command run lifecycle with cancellation, bounded retry and event log
- backup create, verify and restore
- diagnostic screen

Features not implemented must be visibly marked unavailable; never use fake-success UI.

## 13. Testing contract

Frontend:
- Vitest + Testing Library
- unit tests for reducers/stores/validators/i18n
- component tests for loading/empty/error/permission states
- integration tests for primary flows with mocked typed desktop service

Rust:
- repository tests against temporary SQLite DB
- migration idempotency and upgrade tests
- permission enforcement tests
- backup checksum/restore/rollback tests
- secret redaction tests
- AI retry/budget/cancellation tests

End-to-end:
- app starts
- onboarding completes
- language/theme persists
- project/task created and survives restart
- group conversation persists
- denied permission blocks operation
- approved operation records event
- backup and restore recover data

## 14. Commands that must be run

```bash
npm ci
npm run lint
npm run typecheck
npm test -- --run
npm run build
cargo fmt --all -- --check
cargo clippy --manifest-path src-tauri/Cargo.toml --all-targets --all-features -- -D warnings
cargo test --manifest-path src-tauri/Cargo.toml
cargo check --manifest-path src-tauri/Cargo.toml
npm run tauri build
```

Do not substitute `npm install` for CI validation once a lockfile exists.

## 15. CI requirements

`ci.yml` on Ubuntu:
- npm ci
- lint
- typecheck
- frontend tests
- frontend build
- cargo fmt/clippy/test/check

`desktop-build.yml` on Windows:
- install Node and stable Rust
- npm ci
- full frontend validation
- cargo validation
- Tauri build
- upload installer/bundle artifact

Branch is not GREEN until required Ubuntu and Windows checks pass on the exact candidate HEAD.

## 16. Commit strategy

Use small reviewable commits:

1. `chore: establish validated React and Tauri workspace`
2. `feat: implement localization and theme runtime`
3. `feat: add SQLite schema and repositories`
4. `feat: implement core project and task workflows`
5. `feat: implement agents and group chat`
6. `feat: add permissions and notifications`
7. `feat: implement secure provider configuration and AI runtime`
8. `feat: add backup restore and diagnostics`
9. `test: cover desktop runtime and critical flows`
10. `ci: validate Ubuntu and Windows desktop builds`
11. `docs: synchronize implementation status and handoff`

Never combine generated artifacts, unrelated refactors and functional changes in one opaque commit.

## 17. Definition of done

The work is complete only when:

- requested functionality is implemented, not merely documented
- all primary pages have complete states
- HY/EN/RU and dark/light work at runtime and persist
- local DB migrations and integrity checks pass
- secrets are outside plaintext DB/logs
- backup verification and rollback are tested
- permissions block unauthorized actions
- AI runs expose provider/model/prompt version/usage/status
- cancellation, retry and budgets work
- no placeholder success paths exist
- lint, typecheck, tests, build, cargo checks and Tauri build pass
- Windows and Ubuntu CI are GREEN on exact HEAD
- draft PR contains validation evidence and known limitations

## 18. Stop conditions

Continue autonomously for normal implementation and defect fixes. Stop only for:

- explicit Owner approval of the exact final merge candidate
- destructive migration affecting existing user data without a tested rollback
- deletion/rotation of real secrets
- material product scope contradiction not resolved by canonical docs
- unavailable external credentials needed to validate a real provider

When blocked, report the exact failing command, error and smallest required Owner action. Never report work as complete when it is not.