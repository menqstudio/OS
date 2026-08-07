import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';

// Mock the Tauri IPC boundary. The point of this suite is the boundary itself: this
// build registers NO dispatch command, so the composer must say so rather than paint a
// dispatch that did not happen.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Tasks } from './Tasks';
import { STR } from './Tasks.strings';

const en = (k: keyof typeof STR) => STR[k].en;

const TASK = {
  id: 'task-1',
  projectId: null,
  title: 'Draft the specification',
  description: 'first cut of the spec',
  status: 'active',
  priority: 'high',
  assignedAgentId: 'a-1',
  dueAt: null,
  position: 1,
  createdAt: '1700000000000',
  updatedAt: '1700000000000',
  completedAt: null,
};

const AGENTS = [
  { id: 'a-1', slug: 'boundary-auditor', displayName: 'Boundary Auditor', role: 'auditor', status: 'idle', model: null, createdAt: '0', updatedAt: '0' },
  { id: 'a-2', slug: 'evidence-verifier', displayName: 'Evidence Verifier', role: 'verifier', status: 'idle', model: null, createdAt: '0', updatedAt: '0' },
];

function setup(onDispatch?: (args: unknown) => Promise<unknown>) {
  invokeMock.mockImplementation((cmd: string, args: unknown) => {
    if (cmd === 'list_tasks') return Promise.resolve([TASK]);
    if (cmd === 'list_projects') return Promise.resolve([]);
    if (cmd === 'list_agents') return Promise.resolve(AGENTS);
    if (cmd === 'list_task_dependencies') return Promise.resolve([]);
    if (cmd === 'dispatch_task_contract') {
      // The real build has no such command; Tauri rejects an unknown one.
      return onDispatch
        ? onDispatch(args)
        : Promise.reject(new Error('Command dispatch_task_contract not found'));
    }
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Tasks />
      </ToastProvider>
    </AppProvider>,
  );
}

async function openComposer() {
  setup();
  await screen.findByText('Draft the specification');
  fireEvent.click(screen.getByRole('button', { name: `${en('dispatch')}: ${TASK.title}` }));
  return screen.findByRole('dialog');
}

/** Fill the composer with a grant that clears every pre-flight check. */
function fillValidGrant() {
  fireEvent.change(screen.getByLabelText(en('fPack')), { target: { value: 'architecture-audit' } });
  fireEvent.change(screen.getByLabelText(en('fScope')), { target: { value: 'apps/desktop/src/features' } });
  fireEvent.change(screen.getByLabelText(en('fSkills')), { target: { value: 'analysis-primary' } });
  fireEvent.change(screen.getByLabelText(en('fDone')), { target: { value: 'the spec is reviewed' } });
  fireEvent.change(screen.getByLabelText(en('fRollback')), { target: { value: 'discard the branch' } });
}

beforeEach(() => invokeMock.mockReset());

describe('Tasks — a dispatch produces a real contract-shaped assignment', () => {
  it('opens a composer that names the chosen agent definition and its real tool list', async () => {
    const dialog = await openComposer();
    // The capability half: the file that actually decides the tools.
    expect(within(dialog).getByText('.claude/agents/reader.md')).toBeTruthy();
    // The narrowest tier is the default grant, so Bash/Edit must NOT be in it.
    expect(within(dialog).getByText('Read')).toBeTruthy();
    expect(within(dialog).queryByText('Edit')).toBeNull();

    fireEvent.change(screen.getByLabelText(en('fTier')), { target: { value: 'builder' } });
    await waitFor(() => expect(within(dialog).getByText('Edit')).toBeTruthy());
    expect(within(dialog).getByText('.claude/agents/builder.md')).toBeTruthy();
  });

  it('says plainly that the draft is not a sealed contract', async () => {
    const dialog = await openComposer();
    expect(within(dialog).getByText(en('draftWarning'))).toBeTruthy();
    // The draft must never claim a repository binding it cannot observe.
    expect(within(dialog).queryByText(/base_commit: [0-9a-f]{40}/)).toBeNull();
  });

  it('refuses to send an incomplete draft, and says which contract fields are missing', async () => {
    const dialog = await openComposer();
    const problems = within(dialog).getByRole('alert');
    expect(within(problems).getByText('pack_id')).toBeTruthy();
    expect(within(problems).getByText('core_skills')).toBeTruthy();
    expect(within(problems).getByText('scope')).toBeTruthy();

    const send = within(dialog).getByRole('button', { name: en('dispatch') });
    expect((send as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(send);
    expect(invokeMock.mock.calls.some((c) => c[0] === 'dispatch_task_contract')).toBe(false);
  });

  it('reports the missing backend as NOT dispatched, never as accepted', async () => {
    const dialog = await openComposer();
    fillValidGrant();
    await waitFor(() => expect(within(dialog).getByText(en('wellFormed'))).toBeTruthy());

    fireEvent.click(within(dialog).getByRole('button', { name: en('dispatch') }));

    await waitFor(() => expect(within(dialog).getByText(en('outUnreachable'))).toBeTruthy());
    // The honest state, and what it would take to change it.
    expect(within(dialog).getByText(/Command dispatch_task_contract not found/)).toBeTruthy();
    expect(within(dialog).getByText(/dispatch_task_contract` Tauri command/)).toBeTruthy();
    // Nothing may read as accepted.
    expect(within(dialog).queryByText(en('outAccepted'))).toBeNull();
  });

  it('sends the contract-shaped frame the engine would receive', async () => {
    const dialog = await openComposer();
    fillValidGrant();
    await waitFor(() => expect(within(dialog).getByText(en('wellFormed'))).toBeTruthy());
    fireEvent.click(within(dialog).getByRole('button', { name: en('dispatch') }));

    await waitFor(() => expect(
      invokeMock.mock.calls.some((c) => c[0] === 'dispatch_task_contract'),
    ).toBe(true));

    const call = invokeMock.mock.calls.find((c) => c[0] === 'dispatch_task_contract');
    const req = (call?.[1] as { request: Record<string, unknown> }).request;
    const draft = req.contract_draft as Record<string, unknown>;
    expect(req.agent_definition).toBe('reader');
    expect(draft.agent_id).toBe('boundary-auditor');   // the real roster identity
    expect(draft.assignee_role).toBe('auditor');       // the real role
    expect(draft.pack_id).toBe('architecture-audit');
    expect(draft.mode).toBe('review');
    expect(draft.risk).toBe('low');
    expect(draft.scope).toEqual(['apps/desktop/src/features']);
    expect('repository' in draft).toBe(false);
  });

  it('will not render an engine reply as accepted unless it is a complete accepted frame', async () => {
    // A backend that says "accepted" but pins nothing — no lease, no digest, no sealed
    // repository — must not produce a green state.
    setup(async () => ({
      protocol: 'brops.agent-dispatch-result.v1',
      status: 'accepted',
      client_request_id: 'whatever',
    }));
    await screen.findByText('Draft the specification');
    fireEvent.click(screen.getByRole('button', { name: `${en('dispatch')}: ${TASK.title}` }));
    const dialog = await screen.findByRole('dialog');
    fillValidGrant();
    await waitFor(() => expect(within(dialog).getByText(en('wellFormed'))).toBeTruthy());
    fireEvent.click(within(dialog).getByRole('button', { name: en('dispatch') }));

    await waitFor(() => expect(within(dialog).getByText(en('outUnreachable'))).toBeTruthy());
    expect(within(dialog).queryByText(en('outAccepted'))).toBeNull();
  });

  it('renders an accepted dispatch only with the lease, digest and sealed binding', async () => {
    const digest = 'a'.repeat(64);
    const commit = 'b'.repeat(40);
    setup(async (args) => ({
      protocol: 'brops.agent-dispatch-result.v1',
      status: 'accepted',
      client_request_id: (args as { request: { client_request_id: string } }).request.client_request_id,
      assignment_id: 'asg-7',
      contract_digest: digest,
      lease_id: 'lease-7',
      repository: {
        full_name: 'menqstudio/OS', branch: 'wave/phase-push-1', worktree: '/repo',
        base_commit: commit, tree_identity: digest,
      },
    }));
    await screen.findByText('Draft the specification');
    fireEvent.click(screen.getByRole('button', { name: `${en('dispatch')}: ${TASK.title}` }));
    const dialog = await screen.findByRole('dialog');
    fillValidGrant();
    await waitFor(() => expect(within(dialog).getByText(en('wellFormed'))).toBeTruthy());
    fireEvent.click(within(dialog).getByRole('button', { name: en('dispatch') }));

    await waitFor(() => expect(within(dialog).getByText(en('outAccepted'))).toBeTruthy());
    expect(within(dialog).getByText('asg-7')).toBeTruthy();
    expect(within(dialog).getByText('lease-7')).toBeTruthy();
    expect(within(dialog).getByText(commit)).toBeTruthy();
  });
});
