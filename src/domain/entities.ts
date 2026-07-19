// These types mirror the Rust structs returned by the Tauri commands
// (src-tauri/core/src/domain.rs), serialized as camelCase. Optional Rust
// fields (`Option<T>`) serialize as `T | null`.

export interface Project {
  id: string;
  workspaceId: string | null;
  name: string;
  description: string;
  status: string;
  priority: string;
  createdAt: string;
  updatedAt: string;
  archivedAt: string | null;
}

export interface Task {
  id: string;
  projectId: string | null;
  title: string;
  description: string;
  status: string;
  priority: string;
  assignedAgentId: string | null;
  dueAt: string | null;
  position: number;
  createdAt: string;
  updatedAt: string;
  completedAt: string | null;
}

export interface Agent {
  id: string;
  slug: string;
  displayName: string;
  role: string;
  status: string;
  model: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface Approval {
  id: string;
  actionType: string;
  target: string;
  level: string;
  riskLevel: string;
  status: string;
  requestedBy: string;
  decisionNote: string | null;
  requestedAt: string;
  decidedAt: string | null;
}

export interface Notification {
  id: string;
  kind: string;
  severity: string;
  title: string;
  body: string;
  entityType: string | null;
  entityId: string | null;
  readAt: string | null;
  createdAt: string;
}

export interface Decision {
  id: string;
  title: string;
  status: string;
  owner: string;
  rationale: string;
  createdAt: string;
  updatedAt: string;
}

export interface ActivityEvent {
  id: string;
  eventType: string;
  actorId: string | null;
  entityType: string | null;
  entityId: string | null;
  createdAt: string;
}

export interface Conversation {
  id: string;
  kind: string;
  title: string;
  messageCount: number;
  lastMessageAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface Message {
  id: string;
  conversationId: string;
  role: string;
  author: string;
  body: string;
  createdAt: string;
}

export interface NewMessage {
  conversationId: string;
  role: string;
  author: string;
  body: string;
}

export interface KnowledgeNote {
  id: string;
  title: string;
  body: string;
  source: string;
  tags: string;
  createdAt: string;
  updatedAt: string;
}

export interface NewKnowledgeNote {
  title: string;
  body: string;
  source: string;
  tags: string;
}

export interface MemoryEntry {
  id: string;
  scope: string;
  kind: string;
  content: string;
  pinned: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface NewMemoryEntry {
  scope: string;
  kind: string;
  content: string;
}

export interface Run {
  id: string;
  intent: string;
  status: string;
  plan: string;
  createdAt: string;
  updatedAt: string;
}

export interface CalendarEvent {
  id: string;
  title: string;
  kind: string;
  location: string;
  startsAt: string;
  endsAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface NewEvent {
  title: string;
  kind: string;
  location: string;
  startsAt: string;
  endsAt: string | null;
}

export interface Automation {
  id: string;
  name: string;
  trigger: string;
  action: string;
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface NewAutomation {
  name: string;
  trigger: string;
  action: string;
}

export interface Integration {
  id: string;
  name: string;
  provider: string;
  status: string;
  createdAt: string;
  updatedAt: string;
}

export interface Metric {
  key: string;
  label: string;
  value: number;
}

export interface SecuritySummary {
  pendingApprovals: number;
  decidedApprovals: number;
  auditEvents: number;
  sensitiveEvents: ActivityEvent[];
}

export interface DirEntry {
  name: string;
  path: string;
  isDir: boolean;
  sizeBytes: number;
  modified: string | null;
}

export interface DirListing {
  path: string;
  parent: string | null;
  entries: DirEntry[];
}

export interface NewProject {
  name: string;
  description: string;
  priority: string;
  workspaceId: string | null;
}

export interface NewTask {
  projectId: string | null;
  title: string;
  description: string;
  priority: string;
  assignedAgentId: string | null;
}
