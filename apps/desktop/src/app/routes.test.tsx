/// <reference types="vite/client" />
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AppProvider } from './store';
import { ALL_ITEMS, type RouteId } from './nav';
import { ROUTED_IDS, RouteErrorBoundary, RouteFocus, RouteView, describeRouteError, pageFocusTarget } from './routes';

/**
 * The shell's routing contract.
 *
 * Every defect these lock was real in this tree:
 *   - `Bridge.tsx` was fully implemented and reachable from no route at all — the same
 *     "it exists but nothing can get to it" class as the unreachable backend commands.
 *   - the route boundary caught page crashes and then reported a fixed sentence, so the
 *     thrown error never reached the person who had to fix it.
 *   - a route change left keyboard focus on the sidebar link: the stage swapped and the
 *     keyboard user was not told and was not moved.
 */

const wrap = (ui: React.ReactNode) => <AppProvider>{ui}</AppProvider>;

describe('route table — every nav entry resolves to a page', () => {
  it('routes every id the sidebar and the command palette offer', () => {
    const unreachable = ALL_ITEMS.map((i) => i.id).filter((id) => !ROUTED_IDS.includes(id));
    expect(unreachable, 'these nav entries would land on the Generic placeholder').toEqual([]);
  });

  it('offers every routed id in the nav — no route reachable only by typing a URL hash', () => {
    const navIds = new Set(ALL_ITEMS.map((i) => i.id));
    const hidden = ROUTED_IDS.filter((id) => !navIds.has(id));
    expect(hidden, 'these routes have a page but no way to reach it from the UI').toEqual([]);
  });

  it('routes the governed bridge, which previously had no route of its own', () => {
    expect(ROUTED_IDS).toContain('bridge');
    expect(ALL_ITEMS.map((i) => i.id)).toContain('bridge');
  });
});

/**
 * The audit sweep, mechanised: every page file under `features/` must either be routed
 * or be a named, deliberate sub-component. A new page added without a route fails here
 * instead of shipping invisible.
 */
describe('no page under features/ is unreachable', () => {
  const pages = import.meta.glob('../features/*.tsx', { eager: false });

  /** `groupChat` -> `GroupChat`, `bridge` -> `Bridge`: the route id IS the file stem. */
  const routedFiles = new Set(ROUTED_IDS.map((id) => id[0]!.toUpperCase() + id.slice(1)));

  /**
   * Deliberate sub-components — each mounted by a routed page (or by the app frame),
   * reviewed one by one:
   *   Generic        — the honest placeholder the router falls back to for an unknown id.
   *   Conversations  — the shared thread workspace Chat and GroupChat both render.
   *   delegationView — the delegation ledger Chat renders beside the thread.
   *   Onboarding     — the first-run overlay, mounted by App.tsx outside the stage.
   *   registry       — the OLD route table, superseded by app/routes.tsx. It has since
   *                    been DELETED, so the glob never yields it and this entry is inert;
   *                    it is kept only so a stray re-add is caught by review, not by a
   *                    surprise failure here.
   *   writeRecord    — the shared local-write-record reader (badge + panel + notice)
   *                    that Memory and Knowledge both render, so the two surfaces cannot
   *                    drift into saying different things about the same records. Not a
   *                    page: it has no route and mounts nothing on its own.
   */
  const SUB_COMPONENTS = new Set([
    'Generic', 'Conversations', 'delegationView', 'Onboarding', 'registry', 'writeRecord',
  ]);

  const stems = Object.keys(pages)
    .map((p) => p.slice(p.lastIndexOf('/') + 1).replace(/\.tsx$/, ''))
    .filter((s) => !s.includes('.')); // drop *.test.tsx / *.spec.tsx

  it('discovers the feature page files', () => {
    expect(stems.length).toBeGreaterThan(20);
  });

  it('every page is either routed or a declared sub-component', () => {
    const orphans = stems.filter((s) => !routedFiles.has(s) && !SUB_COMPONENTS.has(s));
    expect(orphans, 'give these a route in app/routes.tsx, or declare them as sub-components').toEqual([]);
  });

  it('every routed id has a page file behind it', () => {
    const missing = [...routedFiles].filter((f) => !stems.includes(f));
    expect(missing, 'these routes point at a file that does not exist').toEqual([]);
  });
});

describe('route error boundary — shows the real error, not an apology', () => {
  let spy: ReturnType<typeof vi.spyOn>;
  beforeEach(() => {
    // React re-logs every caught error; keep the suite output readable.
    spy = vi.spyOn(console, 'error').mockImplementation(() => {});
  });
  afterEach(() => spy.mockRestore());

  const Boom = ({ throwing }: { throwing: unknown }) => {
    throw throwing;
  };

  it('renders the thrown message verbatim', () => {
    render(wrap(
      <RouteErrorBoundary route="chat">
        <Boom throwing={new Error('read_conversations: no such table: conversation')} />
      </RouteErrorBoundary>,
    ));
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('read_conversations: no such table: conversation');
    expect(alert).toHaveTextContent('Error');
  });

  it('does not replace the cause with a calm offline state when there is no backend', () => {
    // `hasBackend()` is false in jsdom. The previous boundary routed through ErrorState,
    // which swallows its message entirely in that case — a crash rendered as "offline".
    render(wrap(
      <RouteErrorBoundary route="tasks">
        <Boom throwing={new TypeError('cannot read properties of undefined')} />
      </RouteErrorBoundary>,
    ));
    expect(screen.getByRole('alert')).toHaveTextContent('cannot read properties of undefined');
  });

  it('names the route that failed', () => {
    render(wrap(
      <RouteErrorBoundary route="analytics">
        <Boom throwing={new Error('boom')} />
      </RouteErrorBoundary>,
    ));
    expect(screen.getByRole('alert')).toHaveTextContent('analytics');
  });

  it('renders the healthy child when nothing throws', () => {
    render(wrap(<RouteErrorBoundary route="home"><p>the page</p></RouteErrorBoundary>));
    expect(screen.getByText('the page')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('clears itself when the user navigates to a different route', () => {
    const { rerender } = render(wrap(
      <RouteErrorBoundary route="chat">
        <Boom throwing={new Error('kaput')} />
      </RouteErrorBoundary>,
    ));
    expect(screen.getByRole('alert')).toBeInTheDocument();
    rerender(wrap(<RouteErrorBoundary route="home"><p>next page</p></RouteErrorBoundary>));
    expect(screen.getByText('next page')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

describe('describeRouteError', () => {
  it('keeps the error name and message', () => {
    expect(describeRouteError(new TypeError('x is not a function'))).toBe('TypeError: x is not a function');
  });
  it('falls back to the name when the message is empty', () => {
    expect(describeRouteError(new RangeError(''))).toBe('RangeError');
  });
  it('passes a thrown string through unchanged', () => {
    expect(describeRouteError('chunk 42 failed to load')).toBe('chunk 42 failed to load');
  });
  it('reports an absence as an absence, never as a sentence it invented', () => {
    expect(describeRouteError(undefined)).toBe('');
    expect(describeRouteError(null)).toBe('');
  });
  it('stringifies a non-Error object rather than dropping it', () => {
    expect(describeRouteError({ toString: () => 'weird throw' })).toBe('weird throw');
  });
});

describe('pageFocusTarget', () => {
  it('picks the page heading', () => {
    const root = document.createElement('div');
    root.innerHTML = '<p>lead</p><h1 id="want">Tasks</h1><h2>Later</h2>';
    expect(pageFocusTarget(root)?.id).toBe('want');
  });
  it('falls back to the stage when the page has no heading at all', () => {
    const root = document.createElement('div');
    root.id = 'stage';
    root.innerHTML = '<p>no heading here</p>';
    expect(pageFocusTarget(root)?.id).toBe('stage');
  });
  it('returns nothing when there is no stage', () => {
    expect(pageFocusTarget(null)).toBeNull();
  });
});

describe('route change moves keyboard focus into the new page', () => {
  function Stage({ route, enabled }: { route: RouteId; enabled: boolean }) {
    return (
      <AppProvider>
        <main id="main-content">
          <h1>{route}</h1>
          <RouteFocus route={route} enabled={enabled} />
        </main>
      </AppProvider>
    );
  }

  it('focuses the heading of the page that was navigated to', () => {
    const { rerender } = render(<Stage route="home" enabled={false} />);
    expect(document.activeElement).toBe(document.body);
    rerender(<Stage route="tasks" enabled />);
    expect(document.activeElement?.tagName).toBe('H1');
    expect(document.activeElement).toHaveTextContent('tasks');
  });

  it('makes the heading programmatically focusable without putting it in the Tab order', () => {
    render(<Stage route="agents" enabled />);
    expect(document.activeElement).toHaveAttribute('tabindex', '-1');
  });

  it('leaves focus alone on the first page — opening the app is not a navigation', () => {
    render(<Stage route="home" enabled={false} />);
    expect(document.activeElement).toBe(document.body);
  });

  it('falls back to the stage when the page renders no heading', () => {
    render(
      <AppProvider>
        <main id="main-content">
          <p>a page with no heading</p>
          <RouteFocus route="files" enabled />
        </main>
      </AppProvider>,
    );
    expect(document.activeElement?.id).toBe('main-content');
  });
});

describe('RouteView', () => {
  const stage = (route: RouteId) => (
    <AppProvider>
      <main id="main-content">
        <RouteView route={route} />
      </main>
    </AppProvider>
  );

  // An id outside the union exercises the runtime fallback: a stale hash or a route the
  // table does not know must render the honest placeholder, never a blank frame.
  const unknownA = 'not-a-route-a' as RouteId;
  const unknownB = 'not-a-route-b' as RouteId;

  it('renders the honest placeholder for a route it does not know', () => {
    render(stage(unknownA));
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(unknownA);
  });

  /** The lazy import + export name are only exercised on real navigation, so a typo in
   *  either would surface as a crash the first time a user clicked the link. */
  it('mounts the real bridge page on the bridge route', async () => {
    render(stage('bridge'));
    expect(await screen.findByText('Governed bridge')).toBeInTheDocument();
  });

  it('does not steal focus on first paint, and moves it on the next navigation', () => {
    const { rerender } = render(stage(unknownA));
    expect(document.activeElement).toBe(document.body);
    rerender(stage(unknownB));
    expect(document.activeElement?.tagName).toBe('H1');
    expect(document.activeElement).toHaveTextContent(unknownB);
  });
});
