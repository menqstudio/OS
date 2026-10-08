import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import { AppProvider } from '../app/store';
import { Onboarding } from './Onboarding';
import { STR as ONB_STR } from './Onboarding.strings';

// Empty localStorage => default lang 'en' and onboarding NOT yet seen.
function setup() {
  return render(
    <AppProvider>
      <Onboarding />
    </AppProvider>,
  );
}

describe('Onboarding — first-run intro (shown once, honest)', () => {
  beforeEach(() => {
    try {
      window.localStorage.clear();
    } catch {
      /* jsdom always has storage */
    }
  });

  it('shows on first run, steps through, and marks itself seen on finish', () => {
    setup();
    expect(screen.getByText('Welcome to BroPS')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByText('How it works')).toBeInTheDocument();
    // This step must NOT promise that every model call runs through a lease and a
    // verified receipt: that only holds when the backend resolves the governed engine,
    // and the default configuration streams replies on the ungoverned path.
    expect(screen.getByText(/only governed when this install is configured/i)).toBeInTheDocument();
    expect(screen.getByText(/That is NOT the default/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    // The honesty step must be present — the intro never overstates the trust state.
    expect(screen.getByText('Honest by design')).toBeInTheDocument();
    expect(screen.getByText(/not enabled yet/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Get started' }));
    expect(window.localStorage.getItem('brops.onboarded')).toBe('1');
    expect(screen.queryByText('Welcome to BroPS')).not.toBeInTheDocument();
  });

  it('does not render once already onboarded', () => {
    window.localStorage.setItem('brops.onboarded', '1');
    setup();
    expect(screen.queryByText('Welcome to BroPS')).not.toBeInTheDocument();
  });
});

// The first thing a new user reads said local actions "run directly and reversibly". Marking a
// notification read has no inverse command, and deleting a note, a memory entry or a research
// record is a hard DELETE. The sentence was false in all three languages.
describe('Onboarding — it does not promise that local actions can be undone', () => {
  it.each([
    ['en', /reversibl/i],
    ['hy', /հետշրջելի/],
    ['ru', /обратим/i],
  ] as const)('%s copy does not say local actions are reversible', (lang, claim) => {
    const body = ONB_STR.howBody[lang];
    // It may SAY that some cannot be undone; it may not say that they can.
    const withoutDenial = body.replace(/cannot be undone|not all[^.]*undone|չեն հետարկվում|չի հետարկվում|нельзя отменить|не все[^.]*отменить/gi, '');
    expect(withoutDenial).not.toMatch(claim);
  });

  it('every language says that some local actions cannot be undone', () => {
    expect(ONB_STR.howBody.en).toMatch(/cannot be undone/i);
    expect(ONB_STR.howBody.hy).toMatch(/չեն հետարկվում/);
    expect(ONB_STR.howBody.ru).toMatch(/нельзя отменить/i);
  });
});
