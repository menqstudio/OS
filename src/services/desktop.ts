// The single typed boundary between React and the Tauri (Rust + SQLite) backend.
// Every call is a real `invoke` of a `#[tauri::command]`; there is no mock layer.
// Outside a Tauri runtime (e.g. a plain browser) these reject, and the UI shows
// its error state — that is the honest "backend unavailable" behaviour.

import { invoke } from '@tauri-apps/api/core';
import type {
  ActivityEvent, Agent, Approval, Conversation, Decision, Message, NewMessage, NewProject,
  NewTask, Notification, Project, Task,
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
};
