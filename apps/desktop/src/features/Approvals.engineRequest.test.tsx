// The one control on this page that talks to the ENGINE, and the three things it must never do.
//
// `T-021d`. Phase 2's row asks for "queue + grant/deny/escalate **request**", and the request half is the
// part that did not exist: the page's grant/deny/escalate drive this app's OWN approval system over local
// SQLite. This section asks the engine to RECORD a request. `docs/OWNER_ACTION_REQUIRED.md` fixed the
// separation of the two as an invariant before either was built, so the section names which system it
// belongs to, and these specs hold it to that.
//
// The three:
//   1. it sends `request_engine_approval` and never a verdict command
//   2. it cannot be used at all unless the ENGINE published the task and the state to ask about
//   3. an outcome claiming a decision is not rendered as one

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (cmd: string, args?: unknown) => invokeMock(cmd, args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Approvals } from './Approvals';

const PENDING = {
  id: 'ap-1',
  actionType: 'Send external email',
  target: 'vendor@example.com',
  level: 'A3',
  riskLevel: 'high',
  status: 'pending',
  requestedBy: 'A3',
  decisionNote: null,
  entityType: null,
  entityId: null,
  requestedAt: '1700000000000',
  decidedAt: null,
};

/** A queue read the engine actually served, with one task and the state it holds it in. */
const QUEUE_OK = {
  state: 'ok',
  surface: 'approvalQueue',
  records: [{ task_id: 'task-0001', state: 'awaiting-owner-approval' }],
  authenticated: false,
  engine: null,
};

const RECORDED = {
  state: 'recorded',
  request_id: 'req-7f2a91c4',
  sequence: 1,
  entry_sha256: 'a'.repeat(64),
  duplicate: false,
  adjudicated: false,
  note: 'recorded, not adjudicated',
};

function setup(queue: unknown, outcome: unknown = RECORDED) {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_approvals') return Promise.resolve([PENDING]);
    if (cmd === 'read_engine_approval_queue') {
      return queue instanceof Error ? Promise.reject(queue) : Promise.resolve(queue);
    }
    if (cmd === 'request_engine_approval') return Promise.resolve(outcome);
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Approvals />
      </ToastProvider>
    </AppProvider>,
  );
}

async function fillAndAsk() {
  await waitFor(() => expect(screen.getByLabelText(/Engine task/i)).toBeTruthy());
  fireEvent.change(screen.getByLabelText(/Your name/i), { target: { value: 'gev' } });
  fireEvent.change(screen.getByLabelText(/^Why$/i), { target: { value: 'the owner should see this' } });
  fireEvent.click(screen.getByRole('button', { name: /Ask: approve/i }));
}

beforeEach(() => invokeMock.mockReset());

describe('the engine REQUEST section', () => {
  it('cannot be used when the engine queue is not readable, and says so', async () => {
    setup(new Error('broker_unavailable'));
    await waitFor(() =>
      expect(screen.getByText(/no task to ask about/i)).toBeTruthy());
    expect(screen.queryByLabelText(/Engine task/i)).toBeNull();
    expect(invokeMock.mock.calls.map((c) => c[0])).not.toContain('request_engine_approval');
  });

  it('sends request_engine_approval with the engine-published task and state', async () => {
    setup(QUEUE_OK);
    await fillAndAsk();
    await waitFor(() =>
      expect(invokeMock.mock.calls.some((c) => c[0] === 'request_engine_approval')).toBe(true));
    const [, args] = invokeMock.mock.calls.find((c) => c[0] === 'request_engine_approval')!;
    expect(args).toMatchObject({
      taskId: 'task-0001',
      requestedCommand: 'approve',
      expectedTaskState: 'awaiting-owner-approval',
      requestedBy: 'gev',
    });
  });

  it('sends no verdict command — the desktop asks and does not decide', async () => {
    setup(QUEUE_OK);
    await fillAndAsk();
    await waitFor(() =>
      expect(invokeMock.mock.calls.some((c) => c[0] === 'request_engine_approval')).toBe(true));
    for (const forbidden of ['confirm_approval', 'reject_approval', 'decide_approval']) {
      expect(invokeMock.mock.calls.map((c) => c[0])).not.toContain(forbidden);
    }
  });

  it('renders a record as recorded-not-adjudicated', async () => {
    setup(QUEUE_OK);
    await fillAndAsk();
    await waitFor(() => expect(screen.getByText(/not adjudicated/i)).toBeTruthy());
  });

  it("renders the engine's refusal as a refusal", async () => {
    setup(QUEUE_OK, { state: 'refused', reason: 'task is in state running' });
    await fillAndAsk();
    await waitFor(() => expect(screen.getByText(/engine refused/i)).toBeTruthy());
    expect(screen.getByText(/state running/i)).toBeTruthy();
  });

  it('DOES NOT render an outcome that claims a decision', async () => {
    setup(QUEUE_OK, { ...RECORDED, granted: true });
    await fillAndAsk();
    await waitFor(() => expect(screen.getByText(/Nothing was established/i)).toBeTruthy());
    expect(screen.queryByText(/not adjudicated/i)).toBeNull();
  });

  it('will not ask until a name and a reason are given', async () => {
    setup(QUEUE_OK);
    await waitFor(() => expect(screen.getByLabelText(/Engine task/i)).toBeTruthy());
    const button = screen.getByRole('button', { name: /Ask: approve/i }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/Your name/i), { target: { value: 'gev' } });
    expect((screen.getByRole('button', { name: /Ask: approve/i }) as HTMLButtonElement).disabled).toBe(true);
  });
});
