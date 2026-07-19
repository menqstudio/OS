// The single typed boundary between React and the Tauri (Rust + SQLite) backend.
// Every call is a real `invoke` of a `#[tauri::command]`; there is no mock layer.
// Outside a Tauri runtime (e.g. a plain browser) these reject, and the UI shows
// its error state — that is the honest "backend unavailable" behaviour.

import { invoke, Channel } from '@tauri-apps/api/core';
import type {
  ActivityEvent, Agent, AiStatus, Approval, Automation, CalendarEvent, Conversation, Decision,
  DirListing, Integration, KnowledgeNote, MemoryEntry, Message, Metric, NewAutomation, NewEvent,
  NewKnowledgeNote, NewMemoryEntry, NewMessage, NewProject, NewTask, Notification, Project, Run,
  RunStep, SearchResult, SecuritySummary, Task,
} from '../domain/entities';

/** True when running inside the Tauri desktop runtime. */
export function hasBackend(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

export const desktop = {
  // projects
  listProjects: () => invoke<Project[]>('list_projects'),
  createProject: (input: NewProject) => invoke<Project>('create_project', { input }),
  setProjectStatus: (id: string, status: string) =>
    invoke<Project>('set_project_status', { id, status }),

  // tasks
  listTasksByProject: (projectId: string) =>
    invoke<Task[]>('list_tasks_by_project', { projectId }),
  listTasksByStatus: (status: string) => invoke<Task[]>('list_tasks_by_status', { status }),
  createTask: (input: NewTask) => invoke<Task>('create_task', { input }),
  setTaskStatus: (id: string, status: string) => invoke<Task>('set_task_status', { id, status }),

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
    invoke<Message[]>('list_messages', { conversationId }),
  postMessage: (input: NewMessage) => invoke<Message>('post_message', { input }),
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

  // files (read-only filesystem browser; path omitted = home dir)
  listDir: (path?: string) => invoke<DirListing>('list_dir', { path: path ?? null }),

  // runs (command)
  listRuns: () => invoke<Run[]>('list_runs'),
  createRun: (intent: string, plan: string) => invoke<Run>('create_run', { intent, plan }),
  setRunStatus: (id: string, status: string) => invoke<Run>('set_run_status', { id, status }),
  listRunSteps: (runId: string) => invoke<RunStep[]>('list_run_steps', { runId }),
  addRunStep: (runId: string, title: string, detail: string) =>
    invoke<RunStep>('add_run_step', { runId, title, detail }),
  setRunStepStatus: (id: string, status: string) =>
    invoke<RunStep>('set_run_step_status', { id, status }),
  advanceRun: (runId: string) => invoke<Run>('advance_run', { runId }),

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
    invoke<Message>('reply_in_conversation', { conversationId, agent: agent ?? null }),

  // ai streaming: emits {type:'delta'|'done'|'error'} over a channel while the
  // agent produces text. Resolves when the stream ends.
  streamReply: (conversationId: string, onEvent: (e: StreamEvent) => void, agent?: string) => {
    const channel = new Channel<StreamEvent>();
    channel.onmessage = onEvent;
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
  | { type: 'error'; message: string };
