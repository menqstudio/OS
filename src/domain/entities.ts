import type {
  TaskStatus, ProjectStatus, AgentStatus, RunStatus, ApprovalStatus,
  ApprovalLevel, RiskLevel, Priority, Severity,
} from './enums';

export interface Project {
  id: string;
  name: string;
  description: string;
  status: ProjectStatus;
  priority: Priority;
  taskCount: number;
  openApprovals: number;
  updatedAt: string;
}

export interface Task {
  id: string;
  projectId: string | null;
  title: string;
  status: TaskStatus;
  priority: Priority;
  assignee: string; // agent slug or "gev"
  dueAt: string | null;
  blockedReason?: string;
}

export interface Agent {
  id: string;
  slug: string;
  name: string;
  role: string;
  status: AgentStatus;
  model: string;
  capabilities: string[];
  activeRuns: number;
}

export interface Message {
  id: string;
  senderType: 'user' | 'agent' | 'system';
  senderId: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  createdAt: string;
}

export interface Conversation {
  id: string;
  type: 'direct' | 'group' | 'command' | 'agent-run';
  title: string;
  members: string[]; // slugs or "gev"
  projectId: string | null;
  messages: Message[];
  updatedAt: string;
}

export interface CommandRun {
  id: string;
  commandText: string;
  objective: string;
  status: RunStatus;
  plan: string[];
  createdAt: string;
}

export interface Approval {
  id: string;
  action: string;
  target: string;
  level: ApprovalLevel;
  risk: RiskLevel;
  status: ApprovalStatus;
  requestedBy: string;
  reversible: boolean;
  expiresAt: string;
}

export interface Decision {
  id: string;
  title: string;
  status: 'proposed' | 'under_review' | 'approved' | 'rejected' | 'deferred' | 'superseded';
  owner: string;
  rationale: string;
  updatedAt: string;
}

export interface MemoryItem {
  id: string;
  category: 'preference' | 'fact' | 'decision' | 'lesson' | 'failure' | 'relationship';
  subject: string;
  content: string;
  confidence: number;
  sensitivity: 'normal' | 'private' | 'secret';
  status: 'active' | 'superseded' | 'deleted';
}

export interface KnowledgeItem {
  id: string;
  type: 'note' | 'document' | 'link' | 'snippet' | 'decision';
  title: string;
  source: string;
  updatedAt: string;
}

export interface Notification {
  id: string;
  type: string;
  severity: Severity;
  title: string;
  body: string;
  entity?: string;
  read: boolean;
  createdAt: string;
}

export interface ActivityEvent {
  id: string;
  eventType: string;
  actor: string;
  entity: string;
  createdAt: string;
}
