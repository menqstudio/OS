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
