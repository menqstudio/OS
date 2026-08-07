import React from 'react';
import type { RouteId } from './nav';
import { useApp } from './store';
import { Generic } from '../features/Generic';

/**
 * The app's route table — the one place a `RouteId` becomes a page.
 *
 * It lives in `app/` because routing is a shell concern: the sidebar, the URL hash
 * (`app/store.tsx`), the command palette and this table all read the same `RouteId`
 * union, and a page that is not listed here is a page no user can reach. It was
 * previously in `features/registry.tsx`, where `Bridge.tsx` — a fully implemented
 * panel — ended up with no route at all and was reachable only by being mounted
 * inside another page.
 *
 * Three properties this file is responsible for:
 *
 *  1. COMPLETENESS. `SCREENS` is a total `Record<RouteId, …>`, not a `Partial`. Adding
 *     a route id without giving it a page is a compile error here, so "the page exists
 *     but nothing routes to it" cannot recur silently.
 *  2. HONEST FAILURE. When a page throws or its chunk fails to load, the boundary shows
 *     the REAL error, not a generic apology. A boundary that hides the cause turns a
 *     one-line fix into a debugging session.
 *  3. FOCUS. A route change moves keyboard focus into the new page's heading. Without
 *     this, activating a nav link leaves focus on the link: the screen changed and the
 *     keyboard user was told nothing and is still parked in the sidebar.
 */

// Route-based code splitting: every screen is lazy-loaded so the initial webview
// payload carries only the shell, not all 23 feature pages at once. Screens are named
// exports, so the dynamic import is remapped to a default for React.lazy.
const lazy = (load: () => Promise<Record<string, React.ComponentType>>, name: string): React.FC =>
  React.lazy(() => load().then((m) => ({ default: m[name] })));

/** Every `RouteId` to the page it renders. Total by construction (see point 1 above). */
const SCREENS: Record<RouteId, React.FC> = {
  home: lazy(() => import('../features/Home'), 'Home'),
  command: lazy(() => import('../features/Command'), 'Command'),
  chat: lazy(() => import('../features/Chat'), 'Chat'),
  groupChat: lazy(() => import('../features/GroupChat'), 'GroupChat'),
  projects: lazy(() => import('../features/Projects'), 'Projects'),
  tasks: lazy(() => import('../features/Tasks'), 'Tasks'),
  agents: lazy(() => import('../features/Agents'), 'Agents'),
  knowledge: lazy(() => import('../features/Knowledge'), 'Knowledge'),
  memory: lazy(() => import('../features/Memory'), 'Memory'),
  decisions: lazy(() => import('../features/Decisions'), 'Decisions'),
  // The governed bridge. Previously reachable only as a panel inside Decisions; it is
  // its own surface, and the unfiltered read (no decision selected) exists only here.
  bridge: lazy(() => import('../features/Bridge'), 'BridgePanel'),
  research: lazy(() => import('../features/Research'), 'Research'),
  library: lazy(() => import('../features/Library'), 'Library'),
  calendar: lazy(() => import('../features/Calendar'), 'Calendar'),
  automations: lazy(() => import('../features/Automations'), 'Automations'),
  approvals: lazy(() => import('../features/Approvals'), 'Approvals'),
  activity: lazy(() => import('../features/Activity'), 'Activity'),
  notifications: lazy(() => import('../features/Notifications'), 'Notifications'),
  files: lazy(() => import('../features/Files'), 'Files'),
  integrations: lazy(() => import('../features/Integrations'), 'Integrations'),
  analytics: lazy(() => import('../features/Analytics'), 'Analytics'),
  security: lazy(() => import('../features/Security'), 'Security'),
  settings: lazy(() => import('../features/Settings'), 'Settings'),
};

/** Route ids that resolve to a real page. Exported so a test can assert the table
 *  covers the nav rather than trusting that it does. */
export const ROUTED_IDS = Object.keys(SCREENS) as RouteId[];

/** Trilingual copy for the crash panel. Authored here, next to the only thing that
 *  renders it, rather than in the shared dictionaries — the same per-surface pattern
 *  the feature pages use. */
const CRASH = {
  title: {
    en: 'This page could not be shown',
    hy: 'Այս էջը չհաջողվեց ցույց տալ',
    ru: 'Эту страницу не удалось показать',
  },
  // Deliberately does NOT guess a cause. The real error is printed verbatim below it.
  body: {
    en: 'The page stopped while rendering. The error it raised is shown exactly as it '
      + 'arrived — nothing here is a diagnosis.',
    hy: 'Էջը կանգնեց render-ի ժամանակ։ Իր տված սխալը ցույց ա տրված ուղիղ այնպես, ինչպես եկել ա — '
      + 'այստեղ ոչինչ ախտորոշում չի։',
    ru: 'Страница остановилась во время рендеринга. Ошибка показана ровно так, как пришла — '
      + 'ничто здесь не является диагнозом.',
  },
  routeLabel: { en: 'route: ', hy: 'route՝ ', ru: 'маршрут: ' },
  retry: { en: 'Try this page again', hy: 'Կրկին փորձել այս էջը', ru: 'Попробовать страницу снова' },
  // Used when the thrown value carried no message at all — an absence, stated as one.
  noMessage: {
    en: 'The failure carried no message.',
    hy: 'Ձախողումը հաղորդագրություն չէր կրում։',
    ru: 'Сбой не содержал сообщения.',
  },
} as const;

/** The real text of a thrown value. Never collapsed to a friendly sentence: an
 *  `Error` keeps its name, and a non-Error throw is stringified as-is. */
export function describeRouteError(error: unknown): string {
  if (error instanceof Error) {
    const msg = error.message.trim();
    return msg ? `${error.name}: ${msg}` : error.name;
  }
  if (typeof error === 'string' && error.trim()) return error;
  if (error === null || error === undefined) return '';
  try {
    return String(error);
  } catch {
    return '';
  }
}

/** The route `error` state: an honest report of what actually threw, instead of a
 *  blank frame or a generic apology. */
function RouteCrash({ route, error, onRetry }: { route: RouteId; error: unknown; onRetry: () => void }) {
  const { lang } = useApp();
  const detail = describeRouteError(error);
  return (
    <div className="screen-error" role="alert">
      <h1 className="page-title">{CRASH.title[lang] ?? CRASH.title.en}</h1>
      <p className="muted">{CRASH.body[lang] ?? CRASH.body.en}</p>
      <pre className="route-error-detail">{detail || (CRASH.noMessage[lang] ?? CRASH.noMessage.en)}</pre>
      <p className="micro muted">{(CRASH.routeLabel[lang] ?? CRASH.routeLabel.en) + route}</p>
      <button type="button" className="btn btn--sm" onClick={onRetry}>
        {CRASH.retry[lang] ?? CRASH.retry.en}
      </button>
    </div>
  );
}

interface BoundaryProps {
  route: RouteId;
  children: React.ReactNode;
}
interface BoundaryState {
  /** The thrown value itself, kept so the cause can be rendered. A boolean `failed`
   *  flag would discard exactly the information the reader needs. */
  error: unknown;
  caught: boolean;
}

/** Route-level error boundary. Catches a lazy-chunk load failure or a page
 *  mount/render throw so one broken page cannot blank the whole app — and keeps the
 *  thrown value so `RouteCrash` can show it. Navigating elsewhere clears it. */
export class RouteErrorBoundary extends React.Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { error: null, caught: false };

  static getDerivedStateFromError(error: unknown): BoundaryState {
    return { error, caught: true };
  }

  componentDidCatch(error: unknown, info: React.ErrorInfo) {
    // The panel shows the message; the console keeps the stack and component trace.
    console.error(`[route:${this.props.route}] page failed to render:`, error, info.componentStack);
  }

  componentDidUpdate(prev: BoundaryProps) {
    if (prev.route !== this.props.route && this.state.caught) this.setState({ error: null, caught: false });
  }

  render() {
    if (this.state.caught) {
      return (
        <RouteCrash
          route={this.props.route}
          error={this.state.error}
          onRetry={() => this.setState({ error: null, caught: false })}
        />
      );
    }
    return this.props.children;
  }
}

/** The first heading of the routed page, or the stage itself when the page has none. */
export function pageFocusTarget(root: Element | null): HTMLElement | null {
  if (!root) return null;
  const heading = root.querySelector<HTMLElement>('h1, h2, h3, [role="heading"]');
  return heading ?? (root as HTMLElement);
}

/**
 * Moves focus into the routed page whenever the route changes.
 *
 * Rendered INSIDE `<Suspense>` on purpose: while a route's chunk is still loading the
 * subtree is not live, so the effect runs only once the real page has committed — not
 * against the loading placeholder.
 */
export function RouteFocus({ route, enabled }: { route: RouteId; enabled: boolean }) {
  React.useEffect(() => {
    if (!enabled) return;
    if (typeof document === 'undefined') return;
    const stage = document.getElementById('main-content');
    const target = pageFocusTarget(stage);
    if (!target) return;
    // Headings are not focusable by default. -1 keeps them out of the Tab order while
    // allowing this programmatic focus, which is what moves the screen reader's cursor.
    if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
    target.focus();
    stage?.scrollTo?.({ top: 0 });
  }, [route, enabled]);
  return null;
}

/** The routed page, with its error boundary, suspense fallback and focus handoff. */
export function RouteView({ route }: { route: RouteId }) {
  const Page = SCREENS[route];
  // Tells the very first page (the app just opened — leave focus alone) apart from a
  // real navigation (focus must follow the change). Compare-and-set, so a repeated
  // render for the same route never counts twice.
  const seen = React.useRef<RouteId>(route);
  const navigations = React.useRef(0);
  if (seen.current !== route) {
    seen.current = route;
    navigations.current += 1;
  }
  return (
    <RouteErrorBoundary route={route}>
      <React.Suspense fallback={<div className="screen-loading" aria-busy="true" />}>
        {Page ? <Page /> : <Generic route={route} />}
        <RouteFocus route={route} enabled={navigations.current > 0} />
      </React.Suspense>
    </RouteErrorBoundary>
  );
}
