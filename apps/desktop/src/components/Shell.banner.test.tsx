import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';

// The IPC boundary and the app-identity plugin, mocked at the boundary so the Shell's own reads
// (`useAsync`, `readAppIdentity`) are the real ones. Inert unless a test installs a backend.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));
vi.mock('@tauri-apps/api/app', () => ({
  getName: () => invokeMock('plugin:app|name'),
  getVersion: () => invokeMock('plugin:app|version'),
}));

import { dicts } from '../i18n';
import { App } from '../App';
import { AppProvider, useApp } from '../app/store';
import { RouteView, pageFocusTarget } from '../app/routes';
import { Shell } from './Shell';
import { ErrorState } from './ui';
import { ToastProvider } from './toast';

// The no-backend banner used to read "Prototype — mock data, no backend connected."
// That lies in the OTHER direction: there is no mock layer anywhere in this build.
// `services/desktop.ts` maps every IPC name to a registered `#[tauri::command]`, so
// outside the Tauri runtime each call simply rejects and each panel renders its own
// error state. A user told they are looking at mock data would distrust real numbers
// and trust fabricated ones — exactly backwards.
const LANGS = ['en', 'hy', 'ru'] as const;

describe('Shell no-backend banner — the copy matches what the build actually does', () => {
  it('exists in all three languages', () => {
    for (const lang of LANGS) {
      const s = dicts[lang]['state.prototype'];
      expect(typeof s, `${lang} must carry state.prototype`).toBe('string');
      expect(s.trim()).not.toBe('');
    }
  });

  it('never asserts that mock/test data is on screen, in any language', () => {
    // The exact affirmative claims the old copy made, per language.
    const FALSE_CLAIMS: Record<(typeof LANGS)[number], RegExp> = {
      en: /[—-]\s*mock data/i,
      hy: /փորձնական տվյալներ,/,
      ru: /тестовые данные/i,
    };
    for (const lang of LANGS) {
      const s = dicts[lang]['state.prototype'];
      expect(
        FALSE_CLAIMS[lang].test(s),
        `${lang}: banner must not advertise mock data`,
      ).toBe(false);
    }
  });

  it('states the real situation in every language: no backend, and no mock data either', () => {
    expect(dicts.en['state.prototype']).toMatch(/no.*backend.*connected/i);
    // Each language explicitly DENIES the mock data the old copy asserted.
    expect(dicts.en['state.prototype']).toMatch(/there is no mock data/i);
    expect(dicts.hy['state.prototype']).toMatch(/Փորձնական տվյալներ չկան/);
    expect(dicts.ru['state.prototype']).toMatch(/Тестовых данных нет/);
  });

  it('names the state the panels really show, in every language', () => {
    // It said "every panel will show its own error state". They do not: with no backend,
    // `ErrorState` and `Async` (ui.tsx) replace the error with the calm `state.offline` panel.
    for (const lang of LANGS) {
      expect(dicts[lang]['state.prototype'], lang).toContain(dicts[lang]['state.offline']);
    }
    expect(dicts.en['state.prototype']).not.toMatch(/error state/i);
  });
});

// ── the rendered Shell ─────────────────────────────────────────────────────────────────────────
//
// Until this block the Shell had no rendered test at all — the file above reads dictionaries. Each
// case below is a behaviour that was broken in the real frame while every existing test passed,
// because the tests that covered the neighbouring code rendered it WITHOUT the Shell around it.

/** A backend for the Shell's own startup reads; every other command answers with an empty list. */
function backend(answers: Record<string, () => unknown>) {
  (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
  invokeMock.mockImplementation((cmd: string) => {
    const answer = answers[cmd];
    // An answer that throws is a command that rejects, as a real `invoke` would.
    return answer ? new Promise((resolve) => resolve(answer())) : Promise.resolve([]);
  });
}

/** The real frame around the real router, the way App.tsx composes them. */
function RoutedInner() {
  const { route } = useApp();
  return <Shell><RouteView route={route} /></Shell>;
}
const Routed = () => <AppProvider><ToastProvider><RoutedInner /></ToastProvider></AppProvider>;
const stageOf = () => document.getElementById('main-content')!;
/** The routed page has arrived: its own text is in the stage (the nav link's is outside it). */
const arrived = (text: string) => within(stageOf()).findByText(text);

const navLink = (id: string) => document.querySelector<HTMLAnchorElement>(`nav a[href="#${id}"]`)!;

beforeEach(() => {
  invokeMock.mockReset();
  invokeMock.mockImplementation(() => Promise.reject(new Error('no backend')));
  window.location.hash = '';
  // The ambient layer asks its <canvas> for a 2d context. jsdom has none and says so on stderr
  // for every render; `null` is the answer Ambient.tsx already handles ("no context, no mesh").
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
});
afterEach(() => {
  delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
  vi.restoreAllMocks();
});

describe('Shell — one no-backend banner', () => {
  it('the app renders exactly one, and it is the Shell\'s', async () => {
    const { container } = render(<App />);
    await screen.findByText(new RegExp(dicts.en['state.offline']));
    expect(container.querySelectorAll('.proto-banner')).toHaveLength(1);
    // App.tsx used to render a second, differently-worded one above the frame.
    expect(container.querySelectorAll('.offline-banner')).toHaveLength(0);
    expect(screen.queryByText(dicts.en['state.offlineBanner'])).toBeNull();
  });
});

describe('Shell — focus follows a navigation', () => {
  it('lands in the page, not on the sidebar link that was clicked', async () => {
    // The Shell keyed its stage wrapper on the route, which remounted RouteView and reset the
    // counter that tells a navigation from first paint: RouteFocus was never enabled, and focus
    // stayed on the link. routes.test.tsx passed throughout — it renders RouteView with no Shell.
    render(<Routed />);
    const link = navLink('bridge');
    act(() => link.focus());
    fireEvent.click(link);
    await arrived('Governed bridge');
    await waitFor(() => expect(stageOf().contains(document.activeElement)).toBe(true));
    expect(document.activeElement).not.toBe(link);
    // The page's first heading, or the stage itself when it has none — RouteFocus's own rule.
    expect(document.activeElement).toBe(pageFocusTarget(stageOf()));
  });

  it('still replays the page-enter wrapper once per route', async () => {
    render(<Routed />);
    const first = document.querySelector('#main-content > .stage-enter');
    expect(first).not.toBeNull();
    fireEvent.click(navLink('bridge'));
    await arrived('Governed bridge');
    const second = document.querySelector('#main-content > .stage-enter');
    expect(second).not.toBeNull();
    // A new element, so the CSS animation on it starts again.
    expect(second).not.toBe(first);
  });
});

describe('Shell — context-menu Paste', () => {
  function Controlled() {
    const [value, setValue] = useState('ab');
    return (
      <>
        <input aria-label="field" value={value} onChange={(e) => setValue(e.target.value)} />
        <output data-testid="state">{value}</output>
      </>
    );
  }

  it('reaches a React-controlled field: the state changes, not just the DOM', async () => {
    // Two defects stacked. The menu blurred to <body> and then looked for the field in
    // `document.activeElement`; and had it found one, `el.value = …` goes through React's own
    // instance setter, so the `input` event that followed was swallowed and onChange never ran.
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { readText: vi.fn().mockResolvedValue('ZZ') },
    });
    render(<AppProvider><Shell><Controlled /></Shell></AppProvider>);
    const field = screen.getByLabelText('field') as HTMLInputElement;
    act(() => { field.focus(); field.setSelectionRange(1, 1); });
    fireEvent.contextMenu(field);
    const paste = await screen.findByRole('menuitem', { name: dicts.en['action.paste'] });
    // What a real click does before the handler runs: the button takes focus from the field.
    act(() => paste.focus());
    fireEvent.click(paste);
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('aZZb'));
    expect(field.value).toBe('aZZb');
    expect(field).toHaveFocus();
    expect(field.selectionStart).toBe(3);
  });

  it('offers no Paste on text that cannot receive it', async () => {
    render(<AppProvider><Shell><p>plain text</p></Shell></AppProvider>);
    fireEvent.contextMenu(screen.getByText('plain text'));
    await screen.findByRole('menu');
    expect(screen.queryByRole('menuitem', { name: dicts.en['action.paste'] })).toBeNull();
  });
});

describe('Shell — nav badges follow the backend', () => {
  it('re-reads the counts on navigation instead of keeping the startup value', async () => {
    let approvals: Array<{ id: string; status: string }> = [{ id: 'a1', status: 'pending' }];
    backend({ list_approvals: () => approvals });
    render(<AppProvider><Shell><p>stage</p></Shell></AppProvider>);
    await waitFor(() => expect(navLink('approvals').querySelector('.nav-badge')?.textContent).toBe('1'));
    // Decided elsewhere in the app. The Shell is never remounted, so with `[]` deps this stayed 1.
    approvals = [{ id: 'a1', status: 'approved' }];
    fireEvent.click(navLink('tasks'));
    await waitFor(() => expect(navLink('approvals').querySelector('.nav-badge')).toBeNull());
    expect(navLink('approvals').getAttribute('aria-label')).toBeNull();
  });
});

describe('Shell — the footer names the build that is running', () => {
  it('prints what the build reports about itself', async () => {
    backend({ 'plugin:app|name': () => 'BroPS', 'plugin:app|version': () => '0.1.0' });
    render(<AppProvider><Shell><p>stage</p></Shell></AppProvider>);
    expect(await screen.findByText('BroPS · v0.1.0')).toHaveClass('side-ver');
    expect(document.body.textContent).not.toMatch(/MENQ OS|v0\.9/);
  });

  it('prints nothing when the build does not answer', async () => {
    const { container } = render(<AppProvider><Shell><p>stage</p></Shell></AppProvider>);
    await waitFor(() => expect(invokeMock).toHaveBeenCalled());
    expect(container.querySelector('.side-ver')).toBeNull();
    expect(container.textContent).not.toMatch(/MENQ OS|v0\.9/);
  });
});

describe('Shell — a refused second window is reported in a tone the stylesheet defines', () => {
  it('uses the danger alert, not a modifier ui.css never declared', async () => {
    backend({ open_window: () => { throw new Error('window cap reached'); } });
    render(<AppProvider><Shell><p>stage</p></Shell></AppProvider>);
    fireEvent.contextMenu(screen.getByText('stage'));
    fireEvent.click(await screen.findByRole('menuitem', { name: dicts.en['action.openNewWindow'] }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('window cap reached');
    expect(alert).toHaveClass('inline-alert--danger');
    expect(alert).not.toHaveClass('inline-alert--error');
  });
});

// Two strings a reader of Armenian or Russian met in English: the dismiss button of the alert above
// was `aria-label="Dismiss"`, and `ErrorState` — every page's "the read failed" — was headed
// "Couldn’t load from the backend" with `t` in scope.
describe('Shell and ErrorState — no English left in a translated page', () => {
  it('names the window-error dismiss button in the page language', async () => {
    localStorage.setItem('brops.lang', JSON.stringify('hy'));
    try {
      backend({ open_window: () => { throw new Error('window cap reached'); } });
      render(<AppProvider><Shell><p>stage</p></Shell></AppProvider>);
      fireEvent.contextMenu(screen.getByText('stage'));
      fireEvent.click(await screen.findByRole('menuitem', { name: dicts.hy['action.openNewWindow'] }));
      const alert = await screen.findByRole('alert');
      const dismiss = alert.querySelector('button')!;
      expect(dismiss.getAttribute('aria-label')).toBe(dicts.hy['action.close']);
      expect(dicts.hy['action.close']).not.toBe(dicts.en['action.close']);
    } finally {
      localStorage.removeItem('brops.lang');
    }
  });

  it.each(['en', 'hy', 'ru'] as const)('heads a failed read from the dictionary (%s)', (lang) => {
    localStorage.setItem('brops.lang', JSON.stringify(lang));
    try {
      (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
      render(<AppProvider><ErrorState message="disk I/O error" /></AppProvider>);
      const title = document.querySelector('.empty-title')!;
      expect(title.textContent).toBe(dicts[lang]['state.loadFailed']);
      if (lang !== 'en') expect(title.textContent).not.toMatch(/Couldn.t load from the backend/);
    } finally {
      localStorage.removeItem('brops.lang');
    }
  });
});
