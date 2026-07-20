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

describe('AppProvider — governedEngine preference (Slice 2 settings toggle)', () => {
  beforeEach(() => localStorage.clear());

  it('defaults governedEngine to false (opt-in, default OFF)', () => {
    let api!: Api;
    mount((a) => (api = a));
    expect(api.governedEngine).toBe(false);
  });

  it('persists governedEngine to localStorage when toggled on', () => {
    let api!: Api;
    mount((a) => (api = a));
    act(() => api.setGovernedEngine(true));
    expect(localStorage.getItem('brops.governedEngine')).toBe('true');
  });

  it('reads a persisted governedEngine=true on mount', () => {
    localStorage.setItem('brops.governedEngine', 'true');
    let api!: Api;
    mount((a) => (api = a));
    expect(api.governedEngine).toBe(true);
  });

  it('keeps theme + language working alongside the new preference', () => {
    let api!: Api;
    mount((a) => (api = a));
    expect(api.theme).toBe('dark'); // default theme
    act(() => api.setLang('hy'));
    expect(localStorage.getItem('brops.lang')).toBe('"hy"');
  });
});
