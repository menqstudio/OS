import React from 'react';
import type { RouteId } from '../app/nav';
import { Generic } from './Generic';

// Route-based code splitting: every backend-backed screen is lazy-loaded so the
// initial webview payload carries only the shell + <Generic> fallback, not all 22
// feature pages at once. Each page becomes its own chunk fetched on first navigation
// (instant from local disk in the Tauri webview). Screens are named exports, so the
// dynamic import is remapped to a default for React.lazy.
const lazy = (load: () => Promise<Record<string, React.ComponentType>>, name: string): React.FC =>
  React.lazy(() => load().then((m) => ({ default: m[name] })));

// Screens backed by real Tauri commands (SQLite). Everything else falls through
// to <Generic>, which honestly reports that the workspace has no backend yet.
const screens: Partial<Record<RouteId, React.FC>> = {
  home: lazy(() => import('./Home'), 'Home'),
  command: lazy(() => import('./Command'), 'Command'),
  chat: lazy(() => import('./Chat'), 'Chat'),
  groupChat: lazy(() => import('./GroupChat'), 'GroupChat'),
  projects: lazy(() => import('./Projects'), 'Projects'),
  tasks: lazy(() => import('./Tasks'), 'Tasks'),
  agents: lazy(() => import('./Agents'), 'Agents'),
  knowledge: lazy(() => import('./Knowledge'), 'Knowledge'),
  memory: lazy(() => import('./Memory'), 'Memory'),
  decisions: lazy(() => import('./Decisions'), 'Decisions'),
  research: lazy(() => import('./Research'), 'Research'),
  library: lazy(() => import('./Library'), 'Library'),
  calendar: lazy(() => import('./Calendar'), 'Calendar'),
  automations: lazy(() => import('./Automations'), 'Automations'),
  approvals: lazy(() => import('./Approvals'), 'Approvals'),
  activity: lazy(() => import('./Activity'), 'Activity'),
  notifications: lazy(() => import('./Notifications'), 'Notifications'),
  files: lazy(() => import('./Files'), 'Files'),
  integrations: lazy(() => import('./Integrations'), 'Integrations'),
  analytics: lazy(() => import('./Analytics'), 'Analytics'),
  security: lazy(() => import('./Security'), 'Security'),
  settings: lazy(() => import('./Settings'), 'Settings'),
};

export function Screen({ route }: { route: RouteId }) {
  const C = screens[route];
  return (
    <React.Suspense fallback={<div className="screen-loading" aria-busy="true" />}>
      {C ? <C /> : <Generic route={route} />}
    </React.Suspense>
  );
}
