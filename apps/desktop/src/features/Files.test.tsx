import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// Mock the Tauri IPC boundary. Files mirrors a REAL directory (list_dir) and reads
// real bytes on demand (read_file) — it never fabricates a listing or file content.
// This smoke test locks the browser render path against the real list_dir command;
// no read_file is issued until a file is actually opened.
const invokeMock = vi.fn();
vi.mock('@tauri-apps/api/core', () => ({
  invoke: (cmd: string, args?: unknown) => invokeMock(cmd, args),
  Channel: class {},
}));

import { AppProvider } from '../app/store';
import { ToastProvider } from '../components/toast';
import { Files } from './Files';

const LISTING = {
  path: '/home/gev',
  parent: '/home',
  entries: [
    { name: 'notes.txt', path: '/home/gev/notes.txt', isDir: false, sizeBytes: 128, modified: '1700000000000' },
    { name: 'projects', path: '/home/gev/projects', isDir: true, sizeBytes: 0, modified: '1700000000000' },
  ],
};

function setup() {
  invokeMock.mockImplementation((cmd: string) => {
    if (cmd === 'list_dir') return Promise.resolve(LISTING);
    if (cmd === 'read_file') return Promise.resolve({ path: '', content: '', readonly: true });
    return Promise.resolve(null);
  });
  return render(
    <AppProvider>
      <ToastProvider>
        <Files />
      </ToastProvider>
    </AppProvider>,
  );
}

beforeEach(() => invokeMock.mockReset());

describe('Files — mirrors a real directory, never fabricates a listing', () => {
  it('renders the real directory entries from list_dir', async () => {
    setup();
    await waitFor(() => expect(screen.getByText('notes.txt')).toBeInTheDocument());
    expect(screen.getByText('projects')).toBeInTheDocument();
  });

  it('does not read any file bytes until one is opened', async () => {
    setup();
    await waitFor(() => expect(screen.getByText('notes.txt')).toBeInTheDocument());
    // Listing is a pure mirror: no read_file is issued just to browse.
    expect(invokeMock).not.toHaveBeenCalledWith('read_file', expect.anything());
    // …and the directory was read from the real command.
    expect(invokeMock).toHaveBeenCalledWith('list_dir', expect.anything());
  });
});
