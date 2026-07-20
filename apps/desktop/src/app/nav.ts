import type { DictKey } from '../i18n/en';

export type RouteId =
  | 'home' | 'command' | 'chat' | 'groupChat' | 'projects' | 'tasks' | 'agents'
  | 'knowledge' | 'memory' | 'decisions' | 'research' | 'library'
  | 'calendar' | 'automations' | 'approvals' | 'activity' | 'notifications'
  | 'files' | 'integrations' | 'analytics' | 'security' | 'settings';

export interface NavItem {
  id: RouteId;
  labelKey: DictKey;
  subtitleKey: DictKey;
  icon: string;
}

export interface NavGroup {
  labelKey: DictKey;
  items: NavItem[];
}

const sub = (k: DictKey): DictKey => k;

export const NAV: NavGroup[] = [
  {
    labelKey: 'nav.group.core',
    items: [
      { id: 'home', labelKey: 'nav.home', subtitleKey: 'home.subtitle', icon: '◎' },
      { id: 'command', labelKey: 'nav.command', subtitleKey: 'command.subtitle', icon: '⌘' },
      { id: 'chat', labelKey: 'nav.chat', subtitleKey: 'chat.subtitle', icon: '💬' },
      { id: 'groupChat', labelKey: 'nav.groupChat', subtitleKey: 'groupChat.subtitle', icon: '👥' },
      { id: 'projects', labelKey: 'nav.projects', subtitleKey: 'projects.subtitle', icon: '🗂' },
      { id: 'tasks', labelKey: 'nav.tasks', subtitleKey: 'tasks.subtitle', icon: '✓' },
      { id: 'agents', labelKey: 'nav.agents', subtitleKey: 'agents.subtitle', icon: '🤖' },
    ],
  },
  {
    labelKey: 'nav.group.intelligence',
    items: [
      { id: 'knowledge', labelKey: 'nav.knowledge', subtitleKey: 'knowledge.subtitle', icon: '📚' },
      { id: 'memory', labelKey: 'nav.memory', subtitleKey: 'memory.subtitle', icon: '🧠' },
      { id: 'decisions', labelKey: 'nav.decisions', subtitleKey: 'decisions.subtitle', icon: '⚖' },
      { id: 'research', labelKey: 'nav.research', subtitleKey: 'generic.subtitle', icon: '🔬' },
      { id: 'library', labelKey: 'nav.library', subtitleKey: 'generic.subtitle', icon: '📓' },
    ],
  },
  {
    labelKey: 'nav.group.operations',
    items: [
      { id: 'calendar', labelKey: 'nav.calendar', subtitleKey: 'generic.subtitle', icon: '📅' },
      { id: 'automations', labelKey: 'nav.automations', subtitleKey: 'generic.subtitle', icon: '⚙' },
      { id: 'approvals', labelKey: 'nav.approvals', subtitleKey: 'approvals.subtitle', icon: '🛡' },
      { id: 'activity', labelKey: 'nav.activity', subtitleKey: 'activity.subtitle', icon: '📈' },
      { id: 'notifications', labelKey: 'nav.notifications', subtitleKey: 'notifications.subtitle', icon: '🔔' },
    ],
  },
  {
    labelKey: 'nav.group.system',
    items: [
      { id: 'files', labelKey: 'nav.files', subtitleKey: 'generic.subtitle', icon: '📁' },
      { id: 'integrations', labelKey: 'nav.integrations', subtitleKey: 'generic.subtitle', icon: '🔌' },
      { id: 'analytics', labelKey: 'nav.analytics', subtitleKey: 'generic.subtitle', icon: '📊' },
      { id: 'security', labelKey: 'nav.security', subtitleKey: 'generic.subtitle', icon: '🔒' },
      { id: 'settings', labelKey: 'nav.settings', subtitleKey: 'settings.subtitle', icon: '⚙' },
    ],
  },
];

export const ALL_ITEMS: NavItem[] = NAV.flatMap((g) => g.items);
void sub;
