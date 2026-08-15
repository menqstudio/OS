import { describe, it, expect, beforeEach } from 'vitest';
import { render, act } from '@testing-library/react';
import { AppProvider, useApp } from './store';

type Api = ReturnType<typeof useApp>;

/** Render AppProvider and hand the live context back to the test. */
function mount(onApi: (api: Api) => void) {
  function Probe() {
    onApi(useApp());
    return null;
  }
  render(
    <AppProvider>
      <Probe />
    </AppProvider>,
  );
}

describe('AppProvider — theme & language preferences', () => {
  beforeEach(() => localStorage.clear());

  it('defaults theme to dark', () => {
    let api!: Api;
    mount((a) => (api = a));
    expect(api.theme).toBe('dark');
  });

  it('persists language selection to localStorage', () => {
    let api!: Api;
    mount((a) => (api = a));
    act(() => api.setLang('hy'));
    expect(localStorage.getItem('brops.lang')).toBe('"hy"');
  });

  it('does not expose a governedEngine preference (provider is backend-resolved, fail-closed)', () => {
    let api!: Api;
    mount((a) => (api = a));
    expect('governedEngine' in api).toBe(false);
    expect('setGovernedEngine' in api).toBe(false);
  });
});

// fifth audit, A-08. `routeFromHash` validated the URL, so it looked as though nothing could
// reach the Generic placeholder — and the roadmap claimed exactly that. But `openEntity` is
// called from the command palette as `ent.route as RouteId`: a cast over a string the BACKEND
// supplies. A cast is a promise to the compiler, not a check on the value.
describe('AppProvider — a route that crosses the IPC boundary is validated, not cast', () => {
  beforeEach(() => localStorage.clear());

  it('keeps a known route', () => {
    let api!: Api;
    mount((a) => (api = a));
    act(() => api.setRoute('security'));
    expect(api.route).toBe('security');
  });

  it('refuses an unknown route from setRoute and falls back to home', () => {
    let api!: Api;
    mount((a) => (api = a));
    act(() => api.setRoute('not-a-page' as never));
    expect(api.route).toBe('home');
  });

  it('refuses an unknown route from openEntity — the path the palette actually uses', () => {
    let api!: Api;
    mount((a) => (api = a));
    act(() => api.openEntity('whatever-the-backend-said' as never, 'task', 't-1'));
    expect(api.route).toBe('home');
    // The deep-link intent is still carried: the focus target is not the thing that was wrong.
    expect(api.focus).toEqual({ kind: 'task', id: 't-1' });
  });

  it('still deep-links a KNOWN route through openEntity', () => {
    let api!: Api;
    mount((a) => (api = a));
    act(() => api.openEntity('tasks', 'task', 't-9'));
    expect(api.route).toBe('tasks');
    expect(api.focus).toEqual({ kind: 'task', id: 't-9' });
  });
});
