// The single typed boundary between React and the Tauri (Rust + SQLite) backend.
// Every call is a real `invoke` of a `#[tauri::command]`; there is no mock layer.
// Outside a Tauri runtime (e.g. a plain browser) these reject, and the UI shows
// its error state — that is the honest "backend unavailable" behaviour.

import { invoke, Channel } from '@tauri-apps/api/core';
import type {
  ActivityEvent, Agent, AiStatus, Approval, Automation, CalendarEvent, Conversation, Decision,
  DirListing, FileContent, Integration, KnowledgeNote, MemoryEntry, Message, MessageRole, Metric,
  NewAutomation, NewEvent,
  NewKnowledgeNote, NewMemoryEntry, NewMessage, NewProject, NewTask, Notification, Project, Run,
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
  decideApproval: (id: string, decision: 'approved' | 'rejected', note?: string) =>
    invoke<Approval>('decide_approval', { id, decision, note: note ?? null }),

  // notifications
  listNotifications: () => invoke<Notification[]>('list_notifications'),
  markNotificationRead: (id: string) => invoke<Notification>('mark_notification_read', { id }),

  // decisions
  listDecisions: () => invoke<Decision[]>('list_decisions'),
  createDecision: (title: string, rationale: string) =>
    invoke<Decision>('create_decision', { title, rationale }),

  // activity
  listActivity: () => invoke<ActivityEvent[]>('list_activity'),

  // chat
  listConversations: (kind?: 'direct' | 'group') =>
    invoke<Conversation[]>('list_conversations', { kind: kind ?? null }),
  createConversation: (kind: 'direct' | 'group', title: string) =>
    invoke<Conversation>('create_conversation', { kind, title }),
  listMessages: (conversationId: string) =>
    invoke<Message[]>('list_messages', { conversationId }).then((ms) => ms.map(normalizeMessage)),
  postMessage: (input: NewMessage) =>
    invoke<Message>('post_message', {
      input: { ...input, role: allowedRole(input.role) },
    }).then(normalizeMessage),
  // Agent messages are minted server-side only (P1-6). The webview passes ONLY the
  // opaque one-time resultId from a finished stream_ask (never the answer body); the
  // server pulls the held question+answer and persists the pair.
  saveAskToChat: (resultId: string, title: string) =>
    invoke<Conversation>('save_ask_to_chat', { resultId, title }),
  deleteConversation: (id: string) => invoke<void>('delete_conversation', { id }),
  renameConversation: (id: string, title: string) =>
    invoke<Conversation>('rename_conversation', { id, title }),

  // knowledge
  listKnowledge: () => invoke<KnowledgeNote[]>('list_knowledge'),
  searchKnowledge: (query: string) => invoke<KnowledgeNote[]>('search_knowledge', { query }),
  createKnowledge: (input: NewKnowledgeNote) => invoke<KnowledgeNote>('create_knowledge', { input }),
  deleteKnowledge: (id: string) => invoke<void>('delete_knowledge', { id }),

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
  setRunStepStatus: (id: string, status: string) =>
    invoke<RunStep>('set_run_step_status', { id, status }),
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

  // integrations
  listIntegrations: () => invoke<Integration[]>('list_integrations'),
  setIntegrationStatus: (id: string, status: string) =>
    invoke<Integration>('set_integration_status', { id, status }),

  // global search (across projects, tasks, knowledge, decisions, agents, chats, memory)
  searchAll: (query: string) => invoke<SearchResult[]>('search_all', { query }),

  // analytics / security (computed, read-only)
  getAnalytics: () => invoke<Metric[]>('get_analytics'),
  getSecuritySummary: () => invoke<SecuritySummary>('get_security_summary'),

  // ai (live agent replies)
  aiStatus: () => invoke<AiStatus>('ai_status'),
  replyInConversation: (conversationId: string, agent?: string) =>
    invoke<Message>('reply_in_conversation', { conversationId, agent: agent ?? null })
      .then(normalizeMessage),

  // ai streaming: emits {type:'delta'|'done'|'error'} over a channel while the
  // agent produces text. Resolves when the stream ends.
  streamReply: (conversationId: string, onEvent: (e: StreamEvent) => void, agent?: string) => {
    const channel = new Channel<StreamEvent>();
    channel.onmessage = (e) =>
      onEvent(e.type === 'done' ? { ...e, message: normalizeMessage(e.message) } : e);
    return invoke<void>('stream_reply', { conversationId, agent: agent ?? null, onEvent: channel });
  },

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
  // stream_ask only: the full answer is held server-side under this one-time id.
  | { type: 'ready'; resultId: string };

export type RunStepEvent =
  | { type: 'delta'; text: string }
  | { type: 'done' }
  | { type: 'approvalRequired'; approvalId: string }
  | { type: 'error'; message: string };
