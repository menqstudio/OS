import type {
  Project, Task, Agent, Conversation, CommandRun, Approval, Decision,
  MemoryItem, KnowledgeItem, Notification, ActivityEvent,
} from '../domain/entities';

export const agents: Agent[] = [
  { id: 'a1', slug: 'forge', name: 'Forge', role: 'Engineering', status: 'working', model: 'claude-opus', capabilities: ['code', 'refactor', 'review'], activeRuns: 2 },
  { id: 'a2', slug: 'mason', name: 'Mason', role: 'Architecture', status: 'thinking', model: 'claude-opus', capabilities: ['design', 'contracts'], activeRuns: 1 },
  { id: 'a3', slug: 'pixel', name: 'Pixel', role: 'Design', status: 'idle', model: 'claude-sonnet', capabilities: ['ui', 'tokens'], activeRuns: 0 },
  { id: 'a4', slug: 'probe', name: 'Probe', role: 'Testing', status: 'review', model: 'claude-sonnet', capabilities: ['tests', 'qa'], activeRuns: 1 },
  { id: 'a5', slug: 'shield', name: 'Shield', role: 'Security', status: 'blocked', model: 'claude-opus', capabilities: ['audit', 'threat-model'], activeRuns: 0 },
  { id: 'a6', slug: 'lezu', name: 'Lezu', role: 'Localization', status: 'idle', model: 'claude-sonnet', capabilities: ['hy', 'en', 'ru'], activeRuns: 0 },
];

export const projects: Project[] = [
  { id: 'p1', name: 'BroPS Desktop Foundation', description: 'React + Tauri app shell and core runtime.', status: 'active', priority: 'high', taskCount: 12, openApprovals: 1, updatedAt: '2026-07-19' },
  { id: 'p2', name: 'Design System Rollout', description: 'MenQ token adoption across all screens.', status: 'active', priority: 'normal', taskCount: 7, openApprovals: 0, updatedAt: '2026-07-18' },
  { id: 'p3', name: 'Localization HY/EN/RU', description: 'Trilingual runtime parity.', status: 'blocked', priority: 'high', taskCount: 5, openApprovals: 2, updatedAt: '2026-07-17' },
  { id: 'p4', name: 'AI Runtime Contracts', description: 'Provider adapters and orchestration.', status: 'planned', priority: 'critical', taskCount: 9, openApprovals: 0, updatedAt: '2026-07-16' },
];

export const tasks: Task[] = [
  { id: 't1', projectId: 'p1', title: 'Implement app shell + routing', status: 'done', priority: 'high', assignee: 'forge', dueAt: '2026-07-18' },
  { id: 't2', projectId: 'p1', title: 'Command palette (Ctrl/Cmd+K)', status: 'active', priority: 'normal', assignee: 'forge', dueAt: '2026-07-20' },
  { id: 't3', projectId: 'p1', title: 'Right context drawer', status: 'review', priority: 'normal', assignee: 'pixel', dueAt: '2026-07-21' },
  { id: 't4', projectId: 'p3', title: 'Russian dictionary parity', status: 'blocked', priority: 'high', assignee: 'lezu', dueAt: '2026-07-22', blockedReason: 'Awaiting terminology approval' },
  { id: 't5', projectId: 'p2', title: 'Dark/light token audit', status: 'active', priority: 'normal', assignee: 'pixel', dueAt: '2026-07-23' },
  { id: 't6', projectId: 'p4', title: 'Provider interface skeleton', status: 'planned', priority: 'critical', assignee: 'mason', dueAt: '2026-07-25' },
  { id: 't7', projectId: null, title: 'Review security threat model', status: 'inbox', priority: 'high', assignee: 'shield', dueAt: null },
];

export const conversations: Conversation[] = [
  {
    id: 'c1', type: 'direct', title: 'Bro', members: ['gev', 'bro'], projectId: null, updatedAt: '2026-07-19',
    messages: [
      { id: 'm1', senderType: 'user', senderId: 'gev', role: 'user', content: 'What needs my approval today?', createdAt: '09:12' },
      { id: 'm2', senderType: 'agent', senderId: 'bro', role: 'assistant', content: 'Two approvals are pending: an external send in Localization, and a destructive migration in Foundation. Both are in the Approvals queue.', createdAt: '09:12' },
    ],
  },
  {
    id: 'c2', type: 'group', title: 'Foundation Room', members: ['gev', 'bro', 'forge', 'mason', 'probe'], projectId: 'p1', updatedAt: '2026-07-19',
    messages: [
      { id: 'm3', senderType: 'user', senderId: 'gev', role: 'user', content: '@Forge status on the shell?', createdAt: '10:01' },
      { id: 'm4', senderType: 'agent', senderId: 'forge', role: 'assistant', content: 'Shell + routing done (evidence: build GREEN). Command palette in progress.', createdAt: '10:02' },
      { id: 'm5', senderType: 'agent', senderId: 'mason', role: 'assistant', content: 'Proposing we lock the router contract before adding features.', createdAt: '10:03' },
    ],
  },
];

export const commandRuns: CommandRun[] = [
  { id: 'r1', commandText: 'Draft the Q3 localization plan', objective: 'Plan trilingual coverage', status: 'awaiting_approval', plan: ['Load knowledge', 'Draft plan', 'Request approval to publish'], createdAt: '08:40' },
  { id: 'r2', commandText: 'Summarize open blockers', objective: 'Blocker digest', status: 'succeeded', plan: ['Scan tasks', 'Group by project', 'Summarize'], createdAt: '08:10' },
];

export const approvals: Approval[] = [
  { id: 'ap1', action: 'Send external email', target: 'localization-vendor@example.com', level: 'A2', risk: 'medium', status: 'pending', requestedBy: 'lezu', reversible: false, expiresAt: '2026-07-19 18:00' },
  { id: 'ap2', action: 'Destructive DB migration', target: 'local database', level: 'A3', risk: 'critical', status: 'pending', requestedBy: 'forge', reversible: false, expiresAt: '2026-07-19 20:00' },
  { id: 'ap3', action: 'Enable automation', target: 'daily-digest', level: 'A1', risk: 'low', status: 'approved', requestedBy: 'flow', reversible: true, expiresAt: '2026-07-18 12:00' },
];

export const decisions: Decision[] = [
  { id: 'd1', title: 'Trilingual product scope (HY/EN/RU)', status: 'approved', owner: 'gev', rationale: 'Newest explicit decision supersedes bilingual wording (D-009).', updatedAt: '2026-07-19' },
  { id: 'd2', title: 'Foundation v1 is Locked', status: 'approved', owner: 'gev', rationale: 'Reviewed, canonicalized, Phase 1 UX added (D-010).', updatedAt: '2026-07-19' },
  { id: 'd3', title: 'TanStack Query + Zustand split', status: 'under_review', owner: 'mason', rationale: 'Server state vs ephemeral UI state separation.', updatedAt: '2026-07-18' },
];

export const memory: MemoryItem[] = [
  { id: 'me1', category: 'preference', subject: 'Language', content: 'Owner prefers Armenian in conversation.', confidence: 0.95, sensitivity: 'normal', status: 'active' },
  { id: 'me2', category: 'decision', subject: 'Design', content: 'MenQ tokens are the parent design foundation.', confidence: 0.9, sensitivity: 'normal', status: 'active' },
  { id: 'me3', category: 'failure', subject: 'Process', content: 'Do not commit to the wrong repository.', confidence: 0.8, sensitivity: 'normal', status: 'active' },
];

export const knowledge: KnowledgeItem[] = [
  { id: 'k1', type: 'document', title: 'DESIGN_SYSTEM.md', source: 'repo', updatedAt: '2026-07-19' },
  { id: 'k2', type: 'document', title: 'AI_RUNTIME.md', source: 'repo', updatedAt: '2026-07-19' },
  { id: 'k3', type: 'link', title: 'MenQ Studio Design Standards', source: 'menq://standards', updatedAt: '2026-07-18' },
];

export const notifications: Notification[] = [
  { id: 'n1', type: 'approval_required', severity: 'warning', title: 'Approval required', body: 'Destructive DB migration awaits your decision.', entity: 'ap2', read: false, createdAt: '11:20' },
  { id: 'n2', type: 'run_completed', severity: 'success', title: 'Run completed', body: 'Blocker digest finished with evidence.', entity: 'r2', read: false, createdAt: '08:11' },
  { id: 'n3', type: 'task_due', severity: 'info', title: 'Task due soon', body: 'Command palette due 2026-07-20.', entity: 't2', read: true, createdAt: '07:00' },
  { id: 'n4', type: 'security_warning', severity: 'critical', title: 'Security warning', body: 'Shield flagged a blocked task in threat model.', entity: 't7', read: true, createdAt: 'Yesterday' },
];

export const activity: ActivityEvent[] = [
  { id: 'e1', eventType: 'task.completed', actor: 'forge', entity: 'Implement app shell + routing', createdAt: '2026-07-18 17:40' },
  { id: 'e2', eventType: 'decision.approved', actor: 'gev', entity: 'Foundation v1 is Locked', createdAt: '2026-07-19 02:30' },
  { id: 'e3', eventType: 'approval.requested', actor: 'forge', entity: 'Destructive DB migration', createdAt: '2026-07-19 11:20' },
  { id: 'e4', eventType: 'run.succeeded', actor: 'bro', entity: 'Summarize open blockers', createdAt: '2026-07-19 08:11' },
];
