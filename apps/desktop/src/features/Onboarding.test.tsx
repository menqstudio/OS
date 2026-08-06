import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import { AppProvider } from '../app/store';
import { Onboarding } from './Onboarding';

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
