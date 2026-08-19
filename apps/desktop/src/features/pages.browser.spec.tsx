import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, waitFor, act } from '@testing-library/react';
import {
  settleAnimations, invisibleContent, clobberedMotion, reportInvisible, reportClobbered,
  unstyledClasses, styledClassTokens, reportUnstyled,
  emulateMedia as media,
} from '../test/computedStyle';

/**
 * T-024 — the computed-style sweep. The first test in this repository that loads a stylesheet.
 *
 * `A-01` shipped a fully-populated, completely invisible Security instrument, and every one of the
 * 713 unit tests passed while it did, because `css: false` reduces an assertion about appearance
 * to an assertion about a className string. This file asks Chromium instead, over every routed
 * page, in the states the app is actually used in.
 *
 * The invariants are page-agnostic on purpose. Asserting *"Security's instrument is visible"* would
 * require someone to have already suspected Security — and nobody did, for the whole time `A-01`
 * was on main. What is asserted here is what every page owes a reader:
 *
 *   1. Nothing a reader is meant to SEE computes to `opacity: 0` once motion has settled.
 *   2. An element whose class PROMISES an entrance actually runs it.
 *
 * # Why three states and not one — the mistake this file made first
 *
 * The first version of this sweep mounted every page, waited for its reads to SETTLE, and measured.
 * It was green. It was also green with `A-01` deliberately reintroduced, which is how the hole was
 * found: `Security.tsx` applies `sigbreathe` only while `integrity === 'checking'`, and `checking`
 * exists only while the evidence-chain read is IN FLIGHT. A sweep that waits for the load to finish
 * never visits the state the defect lives in.
 *
 * That is `css: false`'s own shape one level up — a check that only visits the state the person
 * writing it happened to reach. So each page is measured in three states, each pinned rather than
 * raced:
 *
 *   * `pending`     — every command returns a promise that NEVER resolves, so the loading state is
 *                     deterministic rather than a window the test might miss. This is where
 *                     skeletons, spinners and `A-01` live.
 *   * `settled`     — shape-correct empty results; the state a reader spends most time in.
 *   * `unreachable` — every command rejects; the fail-closed state this whole cockpit is designed
 *                     around, and the one a happy-path sweep never sees.
 *
 * # And why every state runs twice
 *
 * `.reveal` starts at `opacity: 0` and arrives at `1` only through `animation: reveal … forwards`;
 * any rule that sets `animation: none` for a reduced-motion reader therefore deletes the thing that
 * makes the element visible, unless something else puts the opacity back. That is `A-01`'s exact
 * mechanism aimed at the readers least able to absorb it, and no static check in this repository
 * can see it — the rule is correct-looking CSS inside a media query.
 */

const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class { onmessage: unknown = null; },
}));

import type {
  ActivityEvent, Agent, AiStatus, Approval, Automation, AutomationRun, CalendarEvent,
  Conversation, Decision, DirListing, Integration, KnowledgeNote, LibraryItem,
  MemoryEntry, Message, Metric, Notification, Project, ResearchItem, Run,
  SearchResult, SecuritySummary, Task,
} from '../domain/entities';
import type {
  AgentStatus, ApprovalLevel, ApprovalStatus, MemoryKind, Priority, ProjectStatus, RiskLevel,
  RunStatus, Severity, TaskStatus,
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
const OBJECT_SHAPED: Record<string, unknown> = {
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
  { id: 'de-1', title: 'One palette, and it is --menq-*', status: 'accepted', owner: 'owner',
    rationale: 'Two palettes with one gate is one contract, two implementations.',
    createdAt: T0, updatedAt: T1 },
];

const ACTIVITY: ActivityEvent[] = [
  { id: 'ev-1', eventType: 'approval.granted', actorId: 'owner', entityType: 'approval',
    entityId: 'ap-2', createdAt: T1 },
  { id: 'ev-2', eventType: 'run.created', actorId: 'seam-builder', entityType: 'run',
    entityId: 'rn-1', createdAt: T0 },
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
const GOVERNANCE_BLOCKED = {
  state: 'blocked', reason: 'governance state directory is not provisioned',
  records: [], authenticated: false, recordCount: 0, store: null,
};

const POPULATED: Record<string, unknown> = {
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

type State = 'pending' | 'settled' | 'unreachable' | 'populated';

function arrange(state: State) {
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


const PAGES: Array<[string, () => React.ReactElement]> = [
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

const STATES: State[] = ['pending', 'settled', 'unreachable'];

/**
 * `mockReset()` clears the implementation as well as the calls, so a bare reset leaves `invoke`
 * returning `undefined`. React runs a component's unmount cleanup AFTER `afterEach`, and
 * `Conversations.tsx` cancels its in-flight reply there — `desktop.cancelReply(id).catch(…)` — so an
 * unimplemented mock turns teardown into `Cannot read properties of undefined (reading 'catch')` and
 * fails the NEXT test with a stack trace pointing at product code that is behaving correctly.
 *
 * It only surfaced with `populated`, because that is the first state in which a conversation is ever
 * selected and `MessageThread` therefore ever mounts. Resetting to a resolved promise keeps the reset
 * (no call history, no leaked implementation) without making teardown throw.
 */
const inert = () => invokeMock.mockReset().mockImplementation(() => Promise.resolve(null));

beforeEach(inert);
afterEach(async () => {
  inert();
  await media([]);           // never leak an emulated feature into the next test
});

async function mount(node: React.ReactElement) {
  const view = render(<AppProvider><ToastProvider>{node}</ToastProvider></AppProvider>);
  await waitFor(() => expect(invokeMock).toHaveBeenCalled());
  await act(async () => { await Promise.resolve(); });
  return view;
}

describe('computed style — nothing a reader should see renders invisible', () => {
  for (const [name, page] of PAGES) {
    for (const state of STATES) {
      it(`${name} · ${state} paints everything it renders`, async () => {
        arrange(state);
        const { container } = await mount(page());
        await settleAnimations();
        const findings = invisibleContent(container);
        expect(findings, `\n${name} (${state}): content present in the DOM and invisible on `
          + `screen —\n${reportInvisible(findings)}\n`).toEqual([]);
      });

      it(`${name} · ${state} paints everything under prefers-reduced-motion`, async () => {
        // The state where `animation: none` is a correct-looking instruction that can silently
        // delete an element's only path to `opacity: 1`.
        await media([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
        arrange(state);
        const { container } = await mount(page());
        await settleAnimations();
        const findings = invisibleContent(container);
        expect(findings, `\n${name} (${state}, reduced motion): content present in the DOM and `
          + `invisible on screen —\n${reportInvisible(findings)}\n`).toEqual([]);
      });
    }
  }
});

/**
 * Class tokens carried for a reason other than styling. Empty, and it must stay empty.
 *
 * The seventh audit's `G-15` names the shape to avoid: a baseline list is where defects hide, and
 * a 785-entry one would make this check theatre. If a genuine JS-hook class ever needs an entry,
 * it gets a written reason beside it — not a quiet widening.
 */
const EXEMPT = new Set<string>([]);

describe('computed style — every class a page applies is styled by something', () => {
  /**
   * `unstyledClasses` was built for the sixth audit's `A-01` and pointed at **two** surfaces: the
   * palette (already known broken) and a hand-written list of seven pill tones. Not at any of the
   * 23 routed pages.
   *
   * The seventh audit ran it across all 69 page/state pairs and found four classes applied by
   * shipped pages that no rule selects — `set-theme`, `sec-page`, `rsx-rail-card`, `cal-runs`.
   * Its sentence is the one worth keeping: *"the repository built the detector for this exact
   * defect class and pointed it at one modal and one hand-written list."* The sixth round's §E had
   * said *"nothing checks that a class the app applies is styled by anything"*; the fix built the
   * check and aimed it at the finding rather than at the class of finding.
   *
   * `styledClassTokens()` is computed AFTER mount, deliberately: 28 of these pages inject their
   * CSS as a `<style>` block when they render, so reading the stylesheet list before mounting
   * would report every one of their classes as unstyled.
   */
  for (const [name, page] of PAGES) {
    for (const state of STATES) {
      it(`${name} · ${state} applies no class that nothing selects`, async () => {
        arrange(state);
        const { container } = await mount(page());
        const findings = unstyledClasses(container, styledClassTokens(), EXEMPT);
        expect(findings, `\n${name} (${state}): classes applied and defined by no rule —\n`
          + `${reportUnstyled(findings)}\n`).toEqual([]);
      });
    }
  }
});

describe('computed style — an element that promises an entrance runs it', () => {
  for (const [name, page] of PAGES) {
    for (const state of STATES) {
      it(`${name} · ${state} runs every animation its classes declare`, async () => {
        arrange(state);
        const { container } = await mount(page());
        // Deliberately NOT settled: this check is about the DECLARATION reaching the element, and
        // `animation-name` says so whether or not the animation has been seeked.
        const findings = clobberedMotion(container);
        expect(findings, `\n${name} (${state}): a class promises a keyframe animation the cascade `
          + `does not run —\n${reportClobbered(findings)}\n`).toEqual([]);
      });
    }
  }
});

describe('populated — every page renders real rows without crashing', () => {
  /**
   * `populated` is NOT in `STATES` yet, and the reason is written here rather than left to be
   * inferred. Running the three sweeps above over it turns **13 of them red**: 24 class tokens that
   * no rule selects, on 12 pages, plus one entrance the `decisions` ledger substitutes rather than
   * runs. Every one is a real finding — they are exactly the 1 886 tokens the eighth audit measured
   * as never shown — and none of them is a defect in these fixtures.
   *
   * Three ways to make the suite green were available and all three are refused:
   *   - add the 24 to `EXEMPT` — this file's own header says a baseline list is where defects hide;
   *   - relax `clobberedMotion` so a substituted entrance passes — that is weakening an assertion to
   *     quiet CI, and the substitution deserves its own decision;
   *   - write 24 CSS rules for surfaces nobody has looked at — inventing a design from a test log.
   *
   * So the fixtures land with the finding, and adding `'populated'` to `STATES` is one line once the
   * 24 are decided. See `T-036`.
   *
   * What this describe DOES assert is the half that is ready and is not vacuous: every page mounts
   * against real rows and renders something. A page that throws on populated data, or renders empty
   * when given rows, fails here — and both were unreachable before, because `arrange('settled')`
   * answered `[]` to everything.
   */
  for (const [name, page] of PAGES) {
    it(`${name} puts its own fixture rows on the screen`, async () => {
      // "It rendered something" is vacuous -- an empty page renders its empty state, and that is
      // text too. "It rendered MORE" was tried and is wrong in three different legitimate ways
      // (`settings` is answered with an object, `security` and `files` fold rows into counts). The
      // property that actually says the fixtures reached the page is that a VALUE from them is
      // readable on it. That cannot be satisfied by an empty state, and it fails on the real ways a
      // fixture table goes wrong: a mistyped command key, a shape the page discards, a row filtered
      // out by a status the page does not recognise.
      arrange('populated');
      const { container } = await mount(page());
      const asked = new Set(invokeMock.mock.calls.map((c) => String(c[0])));
      const wanted: string[] = [];
      for (const cmd of asked) {
        const rows = POPULATED[cmd];
        if (!Array.isArray(rows) || rows.length === 0) continue;
        for (const value of Object.values(rows[0] as Record<string, unknown>)) {
          // Long enough to be this fixture's own words rather than a status token every page shows.
          if (typeof value === 'string' && value.length >= 8 && !value.includes('T0')) {
            wanted.push(value);
          }
        }
      }
      if (wanted.length === 0) return;      // no row-shaped fixture reaches this page; nothing to prove
      const shown = container.textContent ?? '';
      expect(wanted.some((v) => shown.includes(v)),
        `${name} asked for rows and none of their values is on the screen. Looked for any of: `
        + `${wanted.slice(0, 6).join(' | ')}`).toBe(true);
      // WHAT THIS DOES NOT PROVE, written down rather than left to be assumed.
      //
      // `some`, not `every`: a page whose fixtures are ALL wrong fails here, a page where one of
      // three is wrong does not. That was measured, not guessed -- emptying `list_projects` AND
      // `list_agents` left this green, because `projects` also asks for tasks and one surviving
      // fixture satisfied the whole assertion.
      //
      // The per-command version was built and turns FIVE pages red: `home`, `security`, `analytics`,
      // `calendar` and `tasks` each ask for a row command and display no value from it. Some of
      // those are pages folding rows into counts, which is correct and would want a written reason;
      // at least one -- `tasks` not showing a task title -- looks like a real filter the fixtures do
      // not satisfy. Shipping the stronger form would mean either five investigations or a
      // reason-list written to make it green, and a reason-list written that way is the baseline
      // this file's own header refuses. So the weaker form ships with its limit stated, and the five
      // are recorded in `T-036` as the next slice rather than left for someone to rediscover.
    });
  }

  it('no fixture in the table is dead — every key is a command some page actually asks for', async () => {
    // Measured from behaviour, not from a second list: mount all 23 pages, collect the command names
    // they really invoke, and require every fixture key to appear. A renamed or deleted command
    // leaves its fixture behind, and this is what notices — the alternative is a table that grows
    // entries for commands nothing calls, which is the shape `check_reachability` exists to refuse
    // one layer down.
    const asked = new Set<string>();
    for (const [, page] of PAGES) {
      arrange('populated');
      const view = await mount(page());
      for (const call of invokeMock.mock.calls) asked.add(String(call[0]));
      view.unmount();
    }
    const dead = Object.keys(POPULATED).filter((cmd) => !asked.has(cmd));
    expect(dead, 'these fixtures are keyed to commands no page invokes').toEqual([]);
  });
});
