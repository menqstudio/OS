// The single typed boundary between React and the Tauri (Rust + SQLite) backend.
// Every call is a real `invoke` of a `#[tauri::command]`; there is no mock layer.
// Outside a Tauri runtime (e.g. a plain browser) these reject, and the UI shows
// its error state — that is the honest "backend unavailable" behaviour.

import { invoke, Channel } from '@tauri-apps/api/core';
import {
  parseGovernanceRead, type GovernanceRead, type GovernanceSurface,
} from './governance';
import type {
  ActivityEvent, Agent, AiStatus, Approval, Automation, AutomationRun, CalendarEvent, Conversation, Decision,
  DirListing, FileContent, Integration, KnowledgeNote, LibraryItem, MemoryEntry, Message, MessageRole, Metric,
  NewAutomation, NewEvent,
  NewKnowledgeNote, NewLibraryItem, NewMemoryEntry, NewProject, NewResearchItem, NewTask,
  Notification, Project, ResearchItem, Run,
  RunStep, SearchResult, SecuritySummary, Task,
} from '../domain/entities';

/** True when running inside the Tauri desktop runtime. */
export function hasBackend(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

// Message-role allowlist. Only 'agent' messages are ever rendered through the
// markdown (HTML) sink; every other role coming over the IPC boundary — known
// or not — is coerced to 'user', which the UI renders as plain text. This keeps
// an unexpected role from flipping a message into the HTML renderer.
const MARKDOWN_ROLES: ReadonlySet<string> = new Set(['agent']);

function allowedRole(role: string): MessageRole {
  return MARKDOWN_ROLES.has(role) ? 'agent' : 'user';
}

function normalizeMessage(m: Message): Message {
  return { ...m, role: allowedRole(m.role) };
}

// Phase-2 governance mirror: invoke a READ-ONLY governance command and parse its typed
// reply fail-closed. A rejected invoke (no backend, IPC error, engine down) becomes
// `unreachable` rather than a thrown rejection — a governance read is a mirror, so an
// honest state is always returned and never an exception a page must special-case.
async function governanceRead(
  surface: GovernanceSurface,
  command: string,
  args?: Record<string, unknown>,
): Promise<GovernanceRead> {
  try {
    const raw = await invoke<unknown>(command, args);
    return parseGovernanceRead(surface, raw);
  } catch (e) {
    const reason = e instanceof Error ? e.message : String(e);
    return { state: 'unreachable', surface, reason };
  }
}

/**
 * Result of the governed trust-chain self-test. `bound && production_verified` means a
 * Production-CLASS `trusted_verified` receipt was produced by the in-process chain (real
 * ed25519 crypto) — but `demonstration_custody` is ALWAYS true here (the root is the
 * compiled-in demonstration anchor, not an offline-root-verified production manifest), so
 * this must NEVER be shown as real production trust. `custody_note` states the honest
 * posture; `available` is false off Windows.
 */
export interface TrustSelftest {
  available: boolean;
  trust_state: string;
  production_verified: boolean;
  /** True when the trust root is the demonstration anchor, not a real production root.
   *  Always true for this self-test — pair it with `production_verified` so the boolean
   *  can never be read as production trust on its own. */
  demonstration_custody: boolean;
  /**
   * Where `answer` came from. A failed or absent model used to be indistinguishable from a real
   * one: the built-in placeholder was bound by the chain and shown beside `trusted_verified`, so
   * the receipt was honest about custody and the screen was misleading about what answered
   * (remediation audit, honesty finding). Rendering the verdict without this is the defect.
   */
  answer_source:
    | 'model'
    | 'builtin_placeholder_no_model_configured'
    | 'builtin_placeholder_model_failed';
  answer_is_from_a_model: boolean;
  bound: boolean;
  detail: string;
  /** The reply the chain's executor produced INSIDE the governed turn and which the receipt
   *  bound + verified. A real model answer when BROPS_SELFTEST_MODEL_CMD is set, else a fixed
   *  demonstration string. Always demonstration custody. */
  answer: string;
  custody_note: string;
  platform_note: string;
}

export const desktop = {
  // projects
  listProjects: () => invoke<Project[]>('list_projects'),
  createProject: (input: NewProject) => invoke<Project>('create_project', { input }),
  setProjectStatus: (id: string, status: string) =>
    invoke<Project>('set_project_status', { id, status }),
  updateProject: (id: string, name: string, description: string, priority: string) =>
    invoke<Project>('update_project', { id, name, description, priority }),

  // tasks
  listTasksByProject: (projectId: string) =>
    invoke<Task[]>('list_tasks_by_project', { projectId }),
  listTasksByStatus: (status: string) => invoke<Task[]>('list_tasks_by_status', { status }),
  listTasks: () => invoke<Task[]>('list_tasks'),
  createTask: (input: NewTask) => invoke<Task>('create_task', { input }),
  setTaskStatus: (id: string, status: string) => invoke<Task>('set_task_status', { id, status }),
  updateTask: (id: string, title: string, description: string, priority: string) =>
    invoke<Task>('update_task', { id, title, description, priority }),
  // task dependencies (blockers) — each mutating call returns the fresh list
  listTaskDependencies: (taskId: string) =>
    invoke<Task[]>('list_task_dependencies', { taskId }),
  addTaskDependency: (taskId: string, dependsOnId: string) =>
    invoke<Task[]>('add_task_dependency', { taskId, dependsOnId }),
  removeTaskDependency: (taskId: string, dependsOnId: string) =>
    invoke<Task[]>('remove_task_dependency', { taskId, dependsOnId }),

  // agents
  listAgents: () => invoke<Agent[]>('list_agents'),

  // approvals
  listApprovals: () => invoke<Approval[]>('list_approvals'),
  // T-010: the fail-safe reject path — a dedicated command so a compromised renderer
  // cannot flip a decision argument to "approved".
  rejectApproval: (id: string, note?: string) =>
    invoke<Approval>('reject_approval', { id, note: note ?? null }),
  // T-011: approve via renderer-independent native confirmation. This command drives
  // a native OS dialog from Rust; the webview cannot forge it and never sends a
  // "confirmed" flag. Generic decide_approval remains capability-denied.
  confirmApproval: (id: string) =>
    invoke<Approval>('confirm_approval', { id }),
  // A non-verdict sibling of reject: routes a pending approval to higher review (A3) and
  // notifies the owner. It authorizes nothing, so it needs no native confirmation.
  escalateApproval: (id: string) =>
    invoke<Approval>('escalate_approval', { id }),

  // notifications
  listNotifications: () => invoke<Notification[]>('list_notifications'),
  markNotificationRead: (id: string) => invoke<Notification>('mark_notification_read', { id }),

  // decisions
  listDecisions: () => invoke<Decision[]>('list_decisions'),

  // activity
  listActivity: () => invoke<ActivityEvent[]>('list_activity'),

  // chat
  listConversations: (kind?: 'direct' | 'group') =>
    invoke<Conversation[]>('list_conversations', { kind: kind ?? null }),
  createConversation: (kind: 'direct' | 'group', title: string) =>
    invoke<Conversation>('create_conversation', { kind, title }),
  listMessages: (conversationId: string) =>
    invoke<Message[]>('list_messages', { conversationId }).then((ms) => ms.map(normalizeMessage)),
  // Human chat input goes through post_user_message: the renderer sends only the
  // conversation, body and author — the server FIXES the role to `user`, so a
  // compromised renderer can't flip a message into the agent/markdown path (L-4b/P1-6).
  postMessage: (input: { conversationId: string; body: string; author?: string }) =>
    invoke<Message>('post_user_message', {
      conversationId: input.conversationId,
      body: input.body,
      author: input.author ?? null,
    }).then(normalizeMessage),
  // Agent messages are minted server-side only (P1-6). The webview passes ONLY the
  // opaque one-time resultId from a finished stream_ask (never the answer body); the
  // server pulls the held question+answer and persists the pair.
  saveAskToChat: (resultId: string, title: string) =>
    invoke<Conversation>('save_ask_to_chat', { resultId, title }),
  deleteConversation: (id: string) => invoke<void>('delete_conversation', { id }),
  renameConversation: (id: string, title: string) =>
    invoke<Conversation>('rename_conversation', { id, title }),
  // Group-room roster: the create-modal multi-select sets it; the reply fan-out + each
  // agent's prompt use it. Returns the stored roster.
  setConversationParticipants: (conversationId: string, names: string[]) =>
    invoke<string[]>('set_conversation_participants', { conversationId, names }),
  listConversationParticipants: (conversationId: string) =>
    invoke<string[]>('list_conversation_participants', { conversationId }),

  // knowledge
  listKnowledge: () => invoke<KnowledgeNote[]>('list_knowledge'),
  searchKnowledge: (query: string) => invoke<KnowledgeNote[]>('search_knowledge', { query }),
  createKnowledge: (input: NewKnowledgeNote) => invoke<KnowledgeNote>('create_knowledge', { input }),
  deleteKnowledge: (id: string) => invoke<void>('delete_knowledge', { id }),

  // library
  listLibrary: () => invoke<LibraryItem[]>('list_library'),
  createLibraryItem: (input: NewLibraryItem) => invoke<LibraryItem>('create_library_item', { input }),
  deleteLibraryItem: (id: string) => invoke<void>('delete_library_item', { id }),

  // research
  listResearch: () => invoke<ResearchItem[]>('list_research'),
  createResearchItem: (input: NewResearchItem) => invoke<ResearchItem>('create_research_item', { input }),
  deleteResearchItem: (id: string) => invoke<void>('delete_research_item', { id }),

  // memory
  listMemory: (scope?: string) => invoke<MemoryEntry[]>('list_memory', { scope: scope ?? null }),
  createMemory: (input: NewMemoryEntry) => invoke<MemoryEntry>('create_memory', { input }),
  setMemoryPinned: (id: string, pinned: boolean) =>
    invoke<MemoryEntry>('set_memory_pinned', { id, pinned }),
  deleteMemory: (id: string) => invoke<void>('delete_memory', { id }),

  // files (filesystem browser; path omitted = home dir). read/write a text file
  listDir: (path?: string) => invoke<DirListing>('list_dir', { path: path ?? null }),
  readFile: (path: string) => invoke<FileContent>('read_file', { path }),
  writeFile: (path: string, content: string) => invoke<void>('write_file', { path, content }),

  // runs (command)
  listRuns: () => invoke<Run[]>('list_runs'),
  createRun: (intent: string, plan: string) => invoke<Run>('create_run', { intent, plan }),
  setRunStatus: (id: string, status: string) => invoke<Run>('set_run_status', { id, status }),
  listRunSteps: (runId: string) => invoke<RunStep[]>('list_run_steps', { runId }),
  addRunStep: (runId: string, title: string, detail: string, requiresApproval = false) =>
    invoke<RunStep>('add_run_step', { runId, title, detail, requiresApproval }),
  advanceRun: (runId: string) => invoke<Run>('advance_run', { runId }),
  // execute the next runnable step via the AI provider, streaming its result.
  streamRunStep: (runId: string, onEvent: (e: RunStepEvent) => void) => {
    const channel = new Channel<RunStepEvent>();
    channel.onmessage = onEvent;
    return invoke<void>('stream_run_step', { runId, onEvent: channel });
  },

  // events (calendar)
  listEvents: () => invoke<CalendarEvent[]>('list_events'),
  createEvent: (input: NewEvent) => invoke<CalendarEvent>('create_event', { input }),
  deleteEvent: (id: string) => invoke<void>('delete_event', { id }),

  // automations
  listAutomations: () => invoke<Automation[]>('list_automations'),
  createAutomation: (input: NewAutomation) => invoke<Automation>('create_automation', { input }),
  setAutomationEnabled: (id: string, enabled: boolean) =>
    invoke<Automation>('set_automation_enabled', { id, enabled }),
  deleteAutomation: (id: string) => invoke<void>('delete_automation', { id }),
  // Run an automation NOW: performs its local (no-AI) action and returns the recorded run.
  runAutomation: (id: string) => invoke<AutomationRun>('run_automation', { id }),
  listAutomationRuns: (id: string) => invoke<AutomationRun[]>('list_automation_runs', { id }),

  // integrations
  listIntegrations: () => invoke<Integration[]>('list_integrations'),
  setIntegrationStatus: (id: string, status: string) =>
    invoke<Integration>('set_integration_status', { id, status }),

  // global search (across projects, tasks, knowledge, decisions, agents, chats, memory)
  searchAll: (query: string) => invoke<SearchResult[]>('search_all', { query }),

  // analytics / security (computed, read-only)
  getAnalytics: () => invoke<Metric[]>('get_analytics'),
  getSecuritySummary: () => invoke<SecuritySummary>('get_security_summary'),

  // Phase-2 governance mirror (READ-ONLY; mirror, never decide). Each wrapper invokes
  // a read-only Tauri command that asks the engine sidecar and parses the typed reply
  // FAIL-CLOSED: a thrown transport error is mapped to `unreachable`, a refused/malformed
  // reply to `blocked`, and only a well-formed schema-valid reply to `ok`. The renderer
  // supplies no key/lease and never decides — it can only surface engine truth or an
  // honest blocked/unreachable state.
  readEvidenceChain: (taskId?: string) =>
    governanceRead('evidenceChain', 'read_evidence_chain', { taskId: taskId ?? null }),
  readEngineApprovalQueue: () => governanceRead('approvalQueue', 'read_engine_approval_queue'),

  // Governed trust-chain self-test: runs the REAL in-process challenge→sign→verify→
  // trusted_verified chain (Windows) and returns the honest outcome + custody posture.
  // It never flips live AI turns — those stay fail-closed.
  governedTrustSelftest: () => invoke<TrustSelftest>('governed_trust_selftest'),

  // ai (live agent replies)
  aiStatus: () => invoke<AiStatus>('ai_status'),

  // A live DEMONSTRATION-verified reply (Windows): the reply is produced INSIDE the in-process
  // governed chain and verified under the demonstration anchor, so the returned message carries
  // receipt='demonstration_verified' (real crypto, demonstration custody — never production).
  // Requires BROPS_SELFTEST_MODEL_CMD; rejects (fail-closed) otherwise or off Windows.
  demonstrationVerifiedReply: (conversationId: string, agent?: string) =>
    invoke<Message>('demonstration_verified_reply', { conversationId, agent: agent ?? null })
      .then(normalizeMessage),

  // ai streaming: emits {type:'delta'|'done'|'error'} over a channel while the
  // agent produces text. Resolves when the stream ends.
  streamReply: (conversationId: string, onEvent: (e: StreamEvent) => void, agent?: string) => {
    const channel = new Channel<StreamEvent>();
    channel.onmessage = (e) =>
      onEvent(e.type === 'done' ? { ...e, message: normalizeMessage(e.message) } : e);
    return invoke<void>('stream_reply', { conversationId, agent: agent ?? null, onEvent: channel });
  },

  // Stop an in-flight streaming turn for a conversation (the Stop button). The
  // backend breaks the stream at the next delta and keeps whatever streamed so far.
  cancelReply: (conversationId: string) => invoke<void>('cancel_reply', { conversationId }),

  // Open a second app window (right-click → "Open in new window"), optionally at a route.
  openWindow: (route?: string) => invoke<void>('open_window', { route: route ?? null }),

  // one-shot Ask Bro: streams an answer to a single prompt (no persistence).
  streamAsk: (prompt: string, onEvent: (e: StreamEvent) => void) => {
    const channel = new Channel<StreamEvent>();
    channel.onmessage = onEvent;
    return invoke<void>('stream_ask', { prompt, onEvent: channel });
  },
};

export type StreamEvent =
  | { type: 'delta'; text: string }
  | { type: 'done'; message: Message }
  | { type: 'error'; message: string }
  // A governed turn was Blocked by desktop receipt verification: NO agent message was
  // produced (Wave 3a Blocks every governed turn). The UI shows a transient turn-level
  // notice, never a persisted reply. `reason` is the machine verdict.
  | { type: 'blocked'; reason: string }
  // stream_ask only: the full answer is held server-side under this one-time id.
  | { type: 'ready'; resultId: string };

export type RunStepEvent =
  | { type: 'delta'; text: string }
  | { type: 'done' }
  | { type: 'approvalRequired'; approvalId: string }
  | { type: 'error'; message: string };

// --- Wave 3b-1B: governed-turn thin proxy to the trusted broker service -------------------------
// The renderer sends the broker ONLY the closed {conversation_id, agent?, client_request_id} command
// via the `governed_turn_execute` #[tauri::command] (a thin proxy forwarding to the broker service over
// the platform IPC); the committed/blocked reply is parsed + validated read-only. The renderer can never
// forge a `trusted_verified` result — see services/governedTurn.ts.
import {
  runGovernedTurn as runGovernedTurnCore,
  type GovernedTurnRequest, type GovernedTurnResult,
} from './governedTurn';

/** Real broker transport: invoke the thin-proxy `governed_turn_execute` Tauri command. */
async function brokerTransport(request: GovernedTurnRequest): Promise<unknown> {
  return invoke('governed_turn_execute', { request });
}

/** Run a governed turn through the trusted broker service. `agent` is an optional authorized identifier;
 *  the broker resolves system/history/config/IDs itself — the renderer supplies none of them. */
export function governedTurn(conversationId: string, agent?: string): Promise<GovernedTurnResult> {
  return runGovernedTurnCore(conversationId, agent, brokerTransport, () => crypto.randomUUID());
}
