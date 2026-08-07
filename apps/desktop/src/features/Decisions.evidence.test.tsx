import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// The engine evidence-chain read ANSWERS here (state: 'ok') — the case the
// unreachable-path spec (Decisions.governance.test.tsx) does not cover. Two honesty
// defects lived in this branch:
//
//   * `records: []` was rendered with the "mirrored read-only" copy and painted the
//     evidence node with class `done` (mint/satisfied). Zero evidence read as
//     satisfied evidence.
//   * records are schema-shape-checked only, from whatever process the governed-
//     sidecar setting names, with no signature to verify — yet nothing on screen said
//     the mirror was unauthenticated.
//
// The reply shape is what the Rust mirror serializes, including `authenticated`.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { Decisions } from './Decisions';

const DECISION = {
  id: 'd-1',
  title: 'Ship the mirror',
  status: 'accepted',
  owner: 'gev',
  rationale: 'because',
  createdAt: '1000',
  updatedAt: '1000',
};

function mountWithChain(reply: unknown) {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_decisions') return Promise.resolve([DECISION]);
    if (cmd === 'read_evidence_chain') return Promise.resolve(reply);
    return Promise.resolve(null);
  });
  return render(<AppProvider><Decisions /></AppProvider>);
}

/** The three lifecycle nodes of the evidence-chain strip, as [label, className]. */
function chainNodes(): [string, string][] {
  const chain = document.querySelector('.dec-chain-strip .chain');
  return Array.from(chain?.querySelectorAll('b') ?? []).map(
    (b) => [b.textContent ?? '', b.className] as [string, string],
  );
}

async function openEvidence() {
  await waitFor(() => expect(screen.getAllByText('Ship the mirror').length).toBeGreaterThan(0));
  fireEvent.click(screen.getByText('Open evidence'));
}

beforeEach(() => invokeMock.mockReset());

describe('Decisions — an EMPTY engine evidence chain is not satisfied evidence', () => {
  it('renders "no evidence" and never marks the evidence node done', async () => {
    mountWithChain({ state: 'ok', surface: 'evidenceChain', records: [], authenticated: false });
    await openEvidence();

    await waitFor(() => expect(screen.getByText('No evidence')).toBeInTheDocument());
    // The honest wording, not the "mirrored read-only" copy that implies evidence arrived.
    expect(screen.getByText(/empty chain is not a verified chain/i)).toBeInTheDocument();
    expect(screen.queryByText(/Mirrored read-only from the engine chain/i)).not.toBeInTheDocument();

    // The lifecycle node reads "no evidence" and carries NO `done` (mint/satisfied) class.
    const nodes = chainNodes();
    expect(nodes).toHaveLength(3);
    const [label, cls] = nodes[2];
    expect(label).toBe('no evidence');
    expect(cls).not.toContain('done');
    expect(cls).not.toContain('now');
  });
});

describe('Decisions — mirrored records are labelled unauthenticated', () => {
  it('shows the records but states the mirror is unauthenticated, and keeps the node un-lit', async () => {
    mountWithChain({
      state: 'ok',
      surface: 'evidenceChain',
      records: [{ event_id: 'ev-1' }, { event_id: 'ev-2' }],
      authenticated: false,
    });
    await openEvidence();

    // The real count is shown...
    await waitFor(() => expect(screen.getByText(/ENGINE EVIDENCE · 2/)).toBeInTheDocument());
    // ...alongside an explicit statement that nothing here was authenticated.
    expect(screen.getByText('UNAUTHENTICATED MIRROR')).toBeInTheDocument();
    expect(screen.getByText(/carry no signature/i)).toBeInTheDocument();

    // A green/satisfied node must not rest on an unauthenticated source.
    const [label, cls] = chainNodes()[2];
    expect(label).toBe('evidence · unverified');
    expect(cls).not.toContain('done');
  });

  it('lights the evidence node only when the backend reports authenticated records', async () => {
    // Not reachable today (the mirror always reports authenticated:false); this locks
    // the mapping so the UI follows the backend if a signature check ever lands.
    mountWithChain({
      state: 'ok',
      surface: 'evidenceChain',
      records: [{ event_id: 'ev-1' }],
      authenticated: true,
    });
    await openEvidence();

    await waitFor(() => expect(screen.getByText(/ENGINE EVIDENCE · 1/)).toBeInTheDocument());
    expect(screen.queryByText('UNAUTHENTICATED MIRROR')).not.toBeInTheDocument();
    const [label, cls] = chainNodes()[2];
    expect(label).toBe('evidence');
    expect(cls).toContain('done');
  });
});
