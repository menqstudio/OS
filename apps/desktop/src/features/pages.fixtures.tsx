import type React from 'react';

/**
 * The page list and the command fixtures both browser projects mount — extracted 2026-08-29.
 *
 * They lived inside `pages.browser.spec.tsx`, which was fine while it was the only spec that
 * needed them. `pages.axe.browser.spec.tsx` needs the same 23 pages and the same `POPULATED`
 * table, and copying them would have made a THIRD copy of the page list (the jsdom a11y spec
 * carries the second) and a second copy of ~250 lines of fixtures. A fixture set that exists
 * twice is a fixture set that will disagree with itself, which is the failure `T-036` recorded
 * from the other end: *"the fixtures must come from the real command shapes or they measure a
 * page the app never renders."*
 *
 * What did NOT move: `vi.mock('@tauri-apps/api/core', ...)`. Vitest hoists it per file, so each
 * spec installs its own mock and passes it in — which is why {@link arrange} takes the mock as
 * an argument instead of closing over one.
 */

/** The shape `arrange` needs from a spec's `vi.fn()`, without importing vitest into this module. */
export type MockLike = { mockImplementation: (fn: (...args: never[]) => unknown) => unknown };

import type {
  ActivityEvent, Agent, AiStatus, Approval, Automation, AutomationRun, CalendarEvent,
  Conversation, Decision, DirListing, Integration, KnowledgeNote, LibraryItem,
  MemoryEntry, Message, Metric, Notification, Project, ResearchItem, Run,
  SearchResult, SecuritySummary, Task,
} from '../domain/entities';
import type {
  AgentStatus, ApprovalLevel, ApprovalStatus, DecisionStatus, MemoryKind, Priority, ProjectStatus,
  RiskLevel, RunStatus, Severity, TaskStatus,
} from '../domain/enums';
import { INTEGRATION_STATUSES } from '../domain/enums';
import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Home } from './Home';
import { Settings } from './Settings';
import { Approvals } from './Approvals';
import { Decisions } from './Decisions';
import { Security } from './Security';
import { Notifications } from './Notifications';
import { Activity } from './Activity';
import { Agents } from './Agents';
import { Analytics } from './Analytics';
import { Automations } from './Automations';
import { BridgePanel } from './Bridge';
import { Calendar } from './Calendar';
import { Chat } from './Chat';
import { Command } from './Command';
import { Files } from './Files';
import { GroupChat } from './GroupChat';
import { Integrations } from './Integrations';
import { Knowledge } from './Knowledge';
import { Library } from './Library';
import { Memory } from './Memory';
import { Projects } from './Projects';
import { Research } from './Research';
import { Tasks } from './Tasks';

/** Shape-correct empty results — the same table the axe sweep uses, and for the same reason:
 *  `list_dir` returns an object with an `entries` array, and answering `[]` yields
 *  `Array.prototype.entries`, a function, so the page dies on `.filter`. */
export const OBJECT_SHAPED: Record<string, unknown> = {
  get_security_summary: { pendingApprovals: 0, decidedApprovals: 0, auditEvents: 0, sensitiveEvents: [] },
  list_dir: { path: '/', parent: null, entries: [] },
  read_file: { path: '/', content: '', readonly: true },
  get_ai_status: { provider: 'not-configured', governed: false, reason: '' },
};

/**
 * `T-036` — the `populated` state: pages with data in them.
 *
 * The eighth audit measured this suite at **363 of 2 249 styled class tokens, 16.1%**, and named the
 * cause precisely: it is the mock, not the detector. `arrange('settled')` resolved every command not
 * in a four-entry table to `[]`, so nothing was ever selected, and no detail pane, per-row control,
 * selection-gated panel, empty-vs-populated branch or row-level state ever mounted. §D names five
 * states and the suite covered three of them — `loading`, `error`, `empty`. **`default`, a page with
 * data in it, was not one of them.**
 *
 * WHY THESE FIXTURES ARE TYPED, AND WHY THAT IS THE WHOLE POINT
 *
 * The row's warning is the important half: *"the fixtures must come from the real command shapes or
 * they measure a page the app never renders."* A hand-shaped object literal cannot give that — it
 * gives whatever its author remembered. So every fixture below is declared **against the exported
 * domain interface the command's own `invoke<T>` names**, which `apps/desktop/src/domain/entities.ts`
 * introduces as *"these types mirror the Rust structs returned by the Tauri commands"*. A field that
 * does not exist, is misspelled, has the wrong type or is missing is a **compile error**, not a
 * silently-wrong page. `tsc --noEmit` is the check; there is no second manifest to drift.
 *
 * The `POPULATED` table is deliberately keyed by the command name exactly as `services/desktop.ts`
 * invokes it, so a renamed command drops out of the table and its page falls back to `[]` — visibly,
 * as an empty page in a state called `populated`, rather than invisibly.
 */

/**
 * The vocabulary accessors. `Approval.level` and every `status` field are declared `string` on the
 * domain entities -- they mirror Rust `String` columns -- so a typed fixture is shape-correct and can
 * still carry a value the app has never seen. That is not hypothetical: the first draft of these
 * fixtures used `level: 'L2'` and `status: 'granted'`, and the suite immediately reported
 * `.tier-L2` as an unstyled class. It was not a page defect. It was this file inventing a vocabulary,
 * which is exactly the failure `T-036` warns about -- *"the fixtures must come from the real command
 * shapes or they measure a page the app never renders"* -- arriving one level below shape.
 *
 * Routing every enumerated value through `domain/enums.ts` closes it: the canonical lists are what
 * `src-tauri/core` allows, and a wrong value is now a compile error rather than a false finding.
 */
const lvl = (v: ApprovalLevel) => v;
const risk = (v: RiskLevel) => v;
const prio = (v: Priority) => v;
const sev = (v: Severity) => v;
const taskState = (v: TaskStatus) => v;
const projectState = (v: ProjectStatus) => v;
const agentState = (v: AgentStatus) => v;
const runState = (v: RunStatus) => v;
const approvalState = (v: ApprovalStatus) => v;
const integrationState = (v: (typeof INTEGRATION_STATUSES)[number]) => v;
const memoryKind = (v: MemoryKind) => v;
// `I-11`: `Decision.status` is `string` on the entity, so `'accepted'` used to be shape-correct
// and vocabulary-free. It reaches the page's THIRD branch — the fallback — which is the branch a
// word nobody has seen also reaches, so the fixture proved nothing about a recognised state.
const decisionState = (v: DecisionStatus) => v;

const T0 = '2026-08-19T09:00:00Z';
const T1 = '2026-08-19T10:30:00Z';

const PROJECTS: Project[] = [
  { id: 'pr-1', workspaceId: null, name: 'Bridge hardening', description: 'Close the receipt seam.',
    status: projectState('active'), priority: prio('high'), createdAt: T0, updatedAt: T1,
    archivedAt: null },
  { id: 'pr-2', workspaceId: null, name: 'Cockpit polish', description: 'Design-system sweep.',
    status: projectState('blocked'), priority: prio('normal'), createdAt: T0, updatedAt: T1,
    archivedAt: null },
];

const TASKS: Task[] = [
  { id: 'tk-1', projectId: 'pr-1', title: 'Pin the manifest epoch', description: 'Anti-rollback.',
    status: taskState('active'), priority: prio('high'), assignedAgentId: 'ag-1', dueAt: T1, position: 1,
    createdAt: T0, updatedAt: T1, completedAt: null },
  { id: 'tk-2', projectId: 'pr-1', title: 'Write the negative matrix', description: 'Every binding.',
    status: taskState('planned'), priority: prio('normal'), assignedAgentId: null, dueAt: null, position: 2,
    createdAt: T0, updatedAt: T1, completedAt: null },
];

const AGENTS: Agent[] = [
  { id: 'ag-1', slug: 'ledger-reader', displayName: 'Ledger Reader', role: 'Ledger Reader',
    status: agentState('idle'), model: 'claude-sonnet-5', createdAt: T0, updatedAt: T1 },
  { id: 'ag-2', slug: 'seam-builder', displayName: 'Seam Builder', role: 'Builder',
    status: agentState('working'), model: null, createdAt: T0, updatedAt: T1 },
];

const APPROVALS: Approval[] = [
  { id: 'ap-1', actionType: 'write_file', target: 'engine/config/trusted-keys.json', level: lvl('A2'),
    riskLevel: risk('high'), status: approvalState('pending'), requestedBy: 'seam-builder',
    decisionNote: null,
    entityType: 'task', entityId: 'tk-1', requestedAt: T0, decidedAt: null },
  { id: 'ap-2', actionType: 'run_step', target: 'cargo test -p brops-core', level: lvl('A1'),
    riskLevel: risk('low'), status: approvalState('approved'), requestedBy: 'ledger-reader',
    decisionNote: 'Read-only suite.', entityType: 'run', entityId: 'rn-1', requestedAt: T0,
    decidedAt: T1, originPrincipal: 'owner', confirmedAt: T1, confirmedBy: 'owner',
    confirmationMethod: 'native-dialog' },
];

const NOTIFICATIONS: Notification[] = [
  { id: 'nt-1', kind: 'approval', severity: sev('warning'), title: 'Approval waiting',
    body: 'A write to the trusted-key registry is staged.', entityType: 'approval',
    entityId: 'ap-1', readAt: null, createdAt: T1 },
  { id: 'nt-2', kind: 'run', severity: sev('info'), title: 'Run finished', body: 'The suite is green.',
    entityType: 'run', entityId: 'rn-1', readAt: T1, createdAt: T0 },
];

const DECISIONS: Decision[] = [
  { id: 'de-1', title: 'One palette, and it is --menq-*', status: decisionState('accepted'), owner: 'owner',
    rationale: 'Two palettes with one gate is one contract, two implementations.',
    createdAt: T0, updatedAt: T1 },
];

const ACTIVITY: ActivityEvent[] = [
  { id: 'ev-1', eventType: 'approval.granted', actorType: 'user', actorId: 'owner',
    entityType: 'approval', entityId: 'ap-2', createdAt: T1 },
  { id: 'ev-2', eventType: 'run.created', actorType: 'agent', actorId: 'seam-builder',
    entityType: 'run', entityId: 'rn-1', createdAt: T0 },
];

const CONVERSATIONS: Conversation[] = [
  { id: 'cv-1', kind: 'chat', title: 'Receipt seam', messageCount: 2, lastMessageAt: T1,
    createdAt: T0, updatedAt: T1 },
  { id: 'cv-2', kind: 'group', title: 'Design review', messageCount: 1, lastMessageAt: T1,
    createdAt: T0, updatedAt: T1 },
];

const MESSAGES: Message[] = [
  { id: 'ms-1', conversationId: 'cv-1', role: 'user', author: 'owner',
    body: 'What does the receipt bind?', createdAt: T0 },
  // A governed reply carries a badge. `development_untrusted` is the only one a shipped install can
  // reach, so it is the honest one to render here -- `trusted_verified` would paint a state the
  // production gate forbids.
  { id: 'ms-2', conversationId: 'cv-1', role: 'agent', author: 'Bro',
    body: 'The exact output bytes, the policy bundle and the containment evidence.',
    createdAt: T1, receipt: 'development_untrusted' },
];

const KNOWLEDGE: KnowledgeNote[] = [
  { id: 'kn-1', title: 'JCS canonicalisation', body: 'RFC 8785; byte-equal across languages.',
    source: 'docs/design', tags: 'protocol,receipt', createdAt: T0, updatedAt: T1 },
];

const LIBRARY: LibraryItem[] = [
  { id: 'li-1', title: 'Zero-trust audit, round eight', kind: 'report',
    body: 'RED, no P0; 27 marks promoted.', tags: 'audit', createdAt: T0, updatedAt: T1 },
];

const RESEARCH: ResearchItem[] = [
  { id: 'rs-1', title: 'Anchor custody on POSIX', question: 'Who may write the head?',
    findings: 'A resident principal that owns the marks directory.', status: 'open',
    createdAt: T0, updatedAt: T1 },
];

const MEMORY: MemoryEntry[] = [
  { id: 'me-1', scope: 'project', kind: memoryKind('fact'), content: 'The gate is shut on purpose.',
    pinned: true, createdAt: T0, updatedAt: T1 },
];

const RUNS: Run[] = [
  { id: 'rn-1', intent: 'Verify the receipt seam', status: runState('running'),
    plan: 'Read the ledger, then the evidence chain.', createdAt: T0, updatedAt: T1 },
];

/**
 * `list_run_steps` and `list_task_dependencies` have NO fixture here, deliberately.
 *
 * Both are selection-gated: nothing invokes them until a run or a task is selected, and this
 * arrangement only mounts pages. The liveness test below measures that from behaviour and refused
 * the first draft, which carried fixtures for both — a fixture for a state the suite cannot reach
 * is a fixture nobody can be wrong about, which is worse than an absence somebody can see.
 *
 * They are the next slice, and they need driving a selection, not another table entry. `T-036`.
 *
 * `read_file` is out for the same reason, and `get_ai_status` for a different one: **no command of
 * that name exists.** `services/desktop.ts` invokes `ai_status`. The liveness test found it in the
 * first draft of this table -- and the four-entry `OBJECT_SHAPED` table above has carried the same
 * phantom key since it was written, answering a command nothing calls. It is left there rather than
 * quietly deleted, because it is a finding about that table and not about this one.
 */

const EVENTS: CalendarEvent[] = [
  { id: 'cal-1', title: 'Audit window', kind: 'review', location: 'remote',
    startsAt: T0, endsAt: T1, createdAt: T0, updatedAt: T1 },
];

const AUTOMATIONS: Automation[] = [
  { id: 'au-1', name: 'Nightly ledger read', trigger: 'schedule:daily',
    action: 'read_decision_ledger', enabled: true, createdAt: T0, updatedAt: T1 },
];

const AUTOMATION_RUNS: AutomationRun[] = [
  { id: 'ar-1', automationId: 'au-1', ranAt: T1, outcome: 'ok', detail: 'Local write recorded.' },
];

const INTEGRATIONS: Integration[] = [
  { id: 'in-1', name: 'GitHub', provider: 'github', status: integrationState('connected'),
    createdAt: T0, updatedAt: T1 },
  { id: 'in-2', name: 'Slack', provider: 'slack', status: integrationState('disconnected'),
    createdAt: T0, updatedAt: T1 },
];

const METRICS: Metric[] = [
  { key: 'runs', label: 'Runs', value: 12 },
  { key: 'approvals', label: 'Approvals', value: 3 },
];

const SEARCH: SearchResult[] = [
  { kind: 'task', id: 'tk-1', title: 'Pin the manifest epoch', subtitle: 'Bridge hardening',
    route: 'tasks' },
];

const SECURITY: SecuritySummary = {
  pendingApprovals: 1, decidedApprovals: 1, auditEvents: 2, sensitiveEvents: [ACTIVITY[0]],
};

const LISTING: DirListing = {
  path: '/', parent: null, truncated: false,
  entries: [
    { name: 'notes.md', path: '/notes.md', isDir: false, sizeBytes: 2048, modified: T1 },
    { name: 'archive', path: '/archive', isDir: true, sizeBytes: 0, modified: null },
  ],
};

const AI: AiStatus = {
  provider: 'claude-cli', model: 'claude-sonnet-5', ready: true,
  detail: 'Contained, not governed.', governed: false,
};

/**
 * A governed READ that answered. `blocked` is the state every governance surface permanently ships
 * in, so it is the one worth mounting: the engine was REACHED and refused, which is a first-class
 * answer here and not an error. `authenticated:false` is not decoration -- a mirrored record is never
 * an authenticated record, and a page that paints it as one is the defect these surfaces exist
 * to avoid.
 */
export const GOVERNANCE_BLOCKED = {
  state: 'blocked', reason: 'governance state directory is not provisioned',
  records: [], authenticated: false, recordCount: 0, store: null,
};

export const POPULATED: Record<string, unknown> = {
  list_projects: PROJECTS,
  list_tasks: TASKS,
  list_agents: AGENTS,
  list_approvals: APPROVALS,
  list_notifications: NOTIFICATIONS,
  list_decisions: DECISIONS,
  list_activity: ACTIVITY,
  list_conversations: CONVERSATIONS,
  list_messages: MESSAGES,
  list_knowledge: KNOWLEDGE,
  search_knowledge: KNOWLEDGE,
  list_library: LIBRARY,
  list_research: RESEARCH,
  list_memory: MEMORY,
  list_runs: RUNS,
  list_events: EVENTS,
  list_automations: AUTOMATIONS,
  list_automation_runs: AUTOMATION_RUNS,
  list_integrations: INTEGRATIONS,
  get_analytics: METRICS,
  search_all: SEARCH,
  get_security_summary: SECURITY,
  list_dir: LISTING,
  ai_status: AI,
  read_decision_ledger: GOVERNANCE_BLOCKED,
  read_evidence_chain: GOVERNANCE_BLOCKED,
  read_verifier_verdicts: GOVERNANCE_BLOCKED,
  read_engine_approval_queue: GOVERNANCE_BLOCKED,
};

export type State = 'pending' | 'settled' | 'unreachable' | 'populated';

export function arrange(invokeMock: MockLike, state: State) {
  if (state === 'pending') {
    // A promise that never settles. Deterministic where a timing window would be flaky, and the
    // only way to hold a page in its loading state long enough to measure it.
    invokeMock.mockImplementation(() => new Promise(() => {}));
    return;
  }
  if (state === 'unreachable') {
    invokeMock.mockImplementation(() => {
      const rejected = Promise.reject(new Error('broker_unavailable'));
      rejected.catch(() => {});   // marks it handled without changing what the caller receives
      return rejected;
    });
    return;
  }
  if (state === 'populated') {
    // The `default` state of §D: a page with data in it. Falls back to the object-shaped
    // table, then to `[]`, so a command with no fixture behaves exactly as `settled` does
    // rather than throwing -- a missing fixture must show as an empty page, never as a crash
    // that reads like a page defect.
    invokeMock.mockImplementation((cmd: string) =>
      Promise.resolve(cmd in POPULATED ? POPULATED[cmd]
        : cmd in OBJECT_SHAPED ? OBJECT_SHAPED[cmd] : []));
    return;
  }
  invokeMock.mockImplementation((cmd: string) =>
    Promise.resolve(cmd in OBJECT_SHAPED ? OBJECT_SHAPED[cmd] : []));
}


export const PAGES: Array<[string, () => React.ReactElement]> = [
  ['home', () => <Home />],
  ['settings', () => <Settings />],
  ['approvals', () => <Approvals />],
  ['decisions', () => <Decisions />],
  ['security', () => <Security />],
  ['notifications', () => <Notifications />],
  ['activity', () => <Activity />],
  ['agents', () => <Agents />],
  ['analytics', () => <Analytics />],
  ['automations', () => <Automations />],
  ['bridge', () => <BridgePanel />],
  ['calendar', () => <Calendar />],
  ['chat', () => <Chat />],
  ['command', () => <Command />],
  ['files', () => <Files />],
  ['groupChat', () => <GroupChat />],
  ['integrations', () => <Integrations />],
  ['knowledge', () => <Knowledge />],
  ['library', () => <Library />],
  ['memory', () => <Memory />],
  ['projects', () => <Projects />],
  ['research', () => <Research />],
  ['tasks', () => <Tasks />],
];

