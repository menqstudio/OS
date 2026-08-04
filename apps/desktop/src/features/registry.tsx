import React from 'react';
import type { RouteId } from '../app/nav';
import { Generic } from './Generic';
import { useApp } from '../app/store';
import { ErrorState } from '../components/ui';

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

/** Honest fallback when a route's chunk fails to load or its page throws on mount —
 *  the §D route `error` state, instead of a blank webview. */
function RouteMountError({ route, onRetry }: { route: RouteId; onRetry: () => void }) {
  const { lang } = useApp();
  const msg =
    ({ en: `The "${route}" page failed to load.`, hy: `«${route}» էջը չբեռնվեց։`, ru: `Страница «${route}» не загрузилась.` } as const)[lang] ??
    `The "${route}" page failed to load.`;
  const retry = ({ en: 'Retry', hy: 'Կրկնել', ru: 'Повторить' } as const)[lang] ?? 'Retry';
  return (
    <div className="screen-error" role="alert">
      <ErrorState message={msg} onRetry={onRetry} retryLabel={retry} />
    </div>
  );
}

interface BoundaryProps {
  route: RouteId;
  children: React.ReactNode;
}
/** Route-level error boundary: catches a lazy-chunk load failure or a page mount/render
 *  throw so one broken page can't blank the whole app. Navigating to a different route
 *  clears a prior error automatically; the fallback also offers a Retry. */
class RouteErrorBoundary extends React.Component<BoundaryProps, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidUpdate(prev: BoundaryProps) {
    if (prev.route !== this.props.route && this.state.failed) this.setState({ failed: false });
  }
  render() {
    if (this.state.failed) {
      return <RouteMountError route={this.props.route} onRetry={() => this.setState({ failed: false })} />;
    }
    return this.props.children;
  }
}

export function Screen({ route }: { route: RouteId }) {
  const C = screens[route];
  return (
    <RouteErrorBoundary route={route}>
      <React.Suspense fallback={<div className="screen-loading" aria-busy="true" />}>
        {C ? <C /> : <Generic route={route} />}
      </React.Suspense>
    </RouteErrorBoundary>
  );
}
