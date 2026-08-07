import type { DictKey } from '../i18n/en';
import type { Lang } from '../domain/enums';
import { STR as BRIDGE_STR } from '../features/Bridge.strings';

export type RouteId =
  | 'home' | 'command' | 'chat' | 'groupChat' | 'projects' | 'tasks' | 'agents'
  | 'knowledge' | 'memory' | 'decisions' | 'bridge' | 'research' | 'library'
  | 'calendar' | 'automations' | 'approvals' | 'activity' | 'notifications'
  | 'files' | 'integrations' | 'analytics' | 'security' | 'settings';

/** A trilingual string authored next to the page that owns it, rather than in the
 *  shared `i18n/*.ts` dictionaries. Same shape as a `*.strings.ts` entry. */
export type NavCopy = Readonly<Record<Lang, string>>;

export interface NavItem {
  id: RouteId;
  labelKey: DictKey;
  subtitleKey: DictKey;
  icon: string;
  /** Inline trilingual copy owned by the page itself. When present it WINS over
   *  `labelKey` — see `navLabel`. Used by pages that keep all of their copy in a
   *  co-located `*.strings.ts` catalog instead of the shared dictionaries. */
  labelCopy?: NavCopy;
  /** Inline trilingual subtitle; wins over `subtitleKey`. See `navSubtitle`. */
  subtitleCopy?: NavCopy;
}

export interface NavGroup {
  labelKey: DictKey;
  items: NavItem[];
}

/**
 * Bridge keeps ALL of its copy in `features/Bridge.strings.ts` — the per-feature
 * pattern every other page follows — so it has no entry in the shared dictionaries
 * and `i18n/en.ts|hy.ts|ru.ts` stay untouched. These two ids are the slots it would
 * occupy if its copy ever moved there; nothing resolves them today, because
 * `labelCopy`/`subtitleCopy` below are the real source and `navLabel`/`navSubtitle`
 * prefer them. The cast exists only so `NavItem` can keep `labelKey` REQUIRED —
 * `features/Generic.tsx` (owned elsewhere) passes it straight to `t()`.
 */
const BRIDGE_LABEL_KEY = 'nav.bridge' as DictKey;
const BRIDGE_SUBTITLE_KEY = 'bridge.subtitle' as DictKey;

/** The nav label for `item`, in `lang`: the page's own copy when it carries one,
 *  otherwise the shared dictionary via `t`. */
export function navLabel(item: NavItem, lang: Lang, t: (k: DictKey) => string): string {
  return item.labelCopy ? item.labelCopy[lang] || item.labelCopy.en : t(item.labelKey);
}

/** The nav subtitle for `item`, in `lang`. Same precedence as `navLabel`. */
export function navSubtitle(item: NavItem, lang: Lang, t: (k: DictKey) => string): string {
  return item.subtitleCopy ? item.subtitleCopy[lang] || item.subtitleCopy.en : t(item.subtitleKey);
}

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
      {
        id: 'bridge',
        labelKey: BRIDGE_LABEL_KEY,
        subtitleKey: BRIDGE_SUBTITLE_KEY,
        icon: '🔗',
        labelCopy: BRIDGE_STR.panelTitle,
        subtitleCopy: BRIDGE_STR.panelEyebrow,
      },
      { id: 'research', labelKey: 'nav.research', subtitleKey: 'research.subtitle', icon: '⌖' },
      { id: 'library', labelKey: 'nav.library', subtitleKey: 'library.subtitle', icon: '❑' },
    ],
  },
  {
    labelKey: 'nav.group.operations',
    items: [
      { id: 'calendar', labelKey: 'nav.calendar', subtitleKey: 'calendar.subtitle', icon: '📅' },
      { id: 'automations', labelKey: 'nav.automations', subtitleKey: 'automations.subtitle', icon: '⚙' },
      { id: 'approvals', labelKey: 'nav.approvals', subtitleKey: 'approvals.subtitle', icon: '🛡' },
      { id: 'activity', labelKey: 'nav.activity', subtitleKey: 'activity.subtitle', icon: '📈' },
      { id: 'notifications', labelKey: 'nav.notifications', subtitleKey: 'notifications.subtitle', icon: '🔔' },
    ],
  },
  {
    labelKey: 'nav.group.system',
    items: [
      { id: 'files', labelKey: 'nav.files', subtitleKey: 'files.subtitle', icon: '📁' },
      { id: 'integrations', labelKey: 'nav.integrations', subtitleKey: 'integrations.subtitle', icon: '🔌' },
      { id: 'analytics', labelKey: 'nav.analytics', subtitleKey: 'analytics.subtitle', icon: '📊' },
      { id: 'security', labelKey: 'nav.security', subtitleKey: 'security.subtitle', icon: '🔒' },
      { id: 'settings', labelKey: 'nav.settings', subtitleKey: 'settings.subtitle', icon: '⚙' },
    ],
  },
];

export const ALL_ITEMS: NavItem[] = NAV.flatMap((g) => g.items);
