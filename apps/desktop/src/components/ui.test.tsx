import { describe, it, expect, vi } from 'vitest';
import { useState } from 'react';
import { act, render, screen, fireEvent, within } from '@testing-library/react';
import {
  Modal,
  ConfirmDialog,
  Badge,
  StatusPill,
  EmptyState,
  Button,
  Avatar,
  Field,
  PageHeader,
  Panel,
  Card,
  Skeleton,
} from './ui';
import { statusTone, type Tone } from '../domain/enums';
import { renderMarkdown } from './markdown';

/**
 * Component tests for the shared, presentational UI primitives.
 *
 * Everything exercised here renders WITHOUT the Tauri IPC layer or the
 * `useApp` context (ErrorState / Async are intentionally excluded because
 * they call `useApp()` / `hasBackend()`).
 */

describe('Badge', () => {
  it('renders its children', () => {
    render(<Badge>Hello</Badge>);
    expect(screen.getByText('Hello')).toBeInTheDocument();
  });

  it('defaults to the neutral tone class', () => {
    const { container } = render(<Badge>x</Badge>);
    const badge = container.querySelector('span.badge');
    expect(badge).not.toBeNull();
    expect(badge).toHaveClass('badge--neutral');
  });

  const tones: Tone[] = ['neutral', 'accent', 'success', 'warning', 'danger', 'info'];
  it.each(tones)('applies the badge--%s class for tone "%s"', (tone) => {
    const { container } = render(<Badge tone={tone}>label</Badge>);
    const badge = container.querySelector('span.badge');
    expect(badge).toHaveClass('badge', `badge--${tone}`);
  });
});

describe('StatusPill', () => {
  it('maps a known status to the tone defined in statusTone', () => {
    const { container } = render(<StatusPill status="done" />);
    const badge = container.querySelector('span.badge');
    expect(badge).toHaveClass('badge--success'); // statusTone.done === 'success'
    expect(badge).toHaveTextContent('Done'); // localized label (no provider → English)
  });

  it('maps "blocked" to the danger tone', () => {
    const { container } = render(<StatusPill status="blocked" />);
    expect(container.querySelector('span.badge')).toHaveClass('badge--danger');
  });

  it('falls back to neutral for an unknown status', () => {
    const { container } = render(<StatusPill status="totally_unknown_status" />);
    expect(container.querySelector('span.badge')).toHaveClass('badge--neutral');
  });

  it('localizes a status label (underscores → spaces, capitalized)', () => {
    render(<StatusPill status="awaiting_approval" />);
    expect(screen.getByText('Awaiting approval')).toBeInTheDocument();
  });

  // Cross-check every entry in the statusTone map renders with its mapped class.
  it.each(Object.entries(statusTone))(
    'renders status "%s" with the badge--%s class',
    (status, tone) => {
      const { container } = render(<StatusPill status={status} />);
      expect(container.querySelector('span.badge')).toHaveClass(`badge--${tone}`);
    },
  );
});

describe('EmptyState', () => {
  it('renders the title', () => {
    render(<EmptyState title="Nothing yet" />);
    expect(screen.getByText('Nothing yet')).toBeInTheDocument();
  });

  it('renders the hint when provided', () => {
    render(<EmptyState title="Nothing yet" hint="Add your first item" />);
    expect(screen.getByText('Add your first item')).toBeInTheDocument();
  });

  it('omits the hint element when no hint is provided', () => {
    render(<EmptyState title="Solo" />);
    expect(screen.queryByText('Add your first item')).not.toBeInTheDocument();
  });

  it('renders the default glyph and a custom glyph', () => {
    const { rerender } = render(<EmptyState title="A" />);
    expect(screen.getByText('◍')).toBeInTheDocument();
    rerender(<EmptyState title="A" glyph="★" />);
    expect(screen.getByText('★')).toBeInTheDocument();
  });
});

describe('Button', () => {
  it('renders its children', () => {
    render(<Button>Click me</Button>);
    expect(screen.getByRole('button', { name: 'Click me' })).toBeInTheDocument();
  });

  it('defaults to type="button" and the base btn class without a variant modifier', () => {
    render(<Button>Default</Button>);
    const btn = screen.getByRole('button', { name: 'Default' });
    expect(btn).toHaveClass('btn');
    expect(btn).toHaveAttribute('type', 'button');
    expect(btn.className).not.toMatch(/btn--(primary|danger|ghost)/);
  });

  it('applies the primary variant class', () => {
    render(<Button variant="primary">Go</Button>);
    expect(screen.getByRole('button', { name: 'Go' })).toHaveClass('btn--primary');
  });

  it('applies the danger variant class', () => {
    render(<Button variant="danger">Delete</Button>);
    expect(screen.getByRole('button', { name: 'Delete' })).toHaveClass('btn--danger');
  });

  it('applies the small size class only when small is set', () => {
    const { rerender } = render(<Button>Big</Button>);
    expect(screen.getByRole('button', { name: 'Big' })).not.toHaveClass('btn--sm');
    rerender(<Button small>Small</Button>);
    expect(screen.getByRole('button', { name: 'Small' })).toHaveClass('btn--sm');
  });

  it('fires onClick when clicked', () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Press</Button>);
    fireEvent.click(screen.getByRole('button', { name: 'Press' }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('honours the disabled prop', () => {
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Nope
      </Button>,
    );
    const btn = screen.getByRole('button', { name: 'Nope' });
    expect(btn).toBeDisabled();
    fireEvent.click(btn);
    expect(onClick).not.toHaveBeenCalled();
  });

  it('supports the submit type', () => {
    render(<Button type="submit">Submit</Button>);
    expect(screen.getByRole('button', { name: 'Submit' })).toHaveAttribute('type', 'submit');
  });
});

describe('Avatar', () => {
  it('renders the uppercased first letter of the name', () => {
    render(<Avatar name="gev" />);
    expect(screen.getByText('G')).toBeInTheDocument();
  });
});

describe('Field', () => {
  it('renders the label and its child content', () => {
    render(<Field label="Owner">Bro</Field>);
    expect(screen.getByText('Owner')).toBeInTheDocument();
    expect(screen.getByText('Bro')).toBeInTheDocument();
  });
});

describe('PageHeader', () => {
  it('renders the title and subtitle', () => {
    render(<PageHeader title="Tasks" subtitle="All work items" />);
    expect(screen.getByText('Tasks')).toBeInTheDocument();
    expect(screen.getByText('All work items')).toBeInTheDocument();
  });

  it('renders action nodes', () => {
    render(<PageHeader title="Tasks" actions={<button>New</button>} />);
    expect(screen.getByRole('button', { name: 'New' })).toBeInTheDocument();
  });

  it('omits the subtitle when not provided', () => {
    render(<PageHeader title="Solo" />);
    expect(screen.queryByText('All work items')).not.toBeInTheDocument();
  });
});

describe('Panel', () => {
  it('renders its title and children', () => {
    render(<Panel title="Overview">body content</Panel>);
    expect(screen.getByText('Overview')).toBeInTheDocument();
    expect(screen.getByText('body content')).toBeInTheDocument();
  });

  it('renders children with no head when no title/actions are given', () => {
    const { container } = render(<Panel>just body</Panel>);
    expect(screen.getByText('just body')).toBeInTheDocument();
    expect(container.querySelector('.panel-head')).toBeNull();
  });
});

describe('Card', () => {
  it('renders children and merges an extra className', () => {
    const { container } = render(<Card className="extra">inside</Card>);
    const card = container.querySelector('.card');
    expect(card).toHaveClass('card', 'extra');
    expect(within(card as HTMLElement).getByText('inside')).toBeInTheDocument();
  });
});

describe('Skeleton', () => {
  it('renders the default number of rows and marks the region busy', () => {
    const { container } = render(<Skeleton />);
    const region = container.querySelector('[aria-busy="true"]');
    expect(region).not.toBeNull();
    expect(container.querySelectorAll('.skeleton')).toHaveLength(3);
  });

  it('renders the requested number of rows', () => {
    const { container } = render(<Skeleton rows={5} />);
    expect(container.querySelectorAll('.skeleton')).toHaveLength(5);
  });
});

/**
 * `Modal` declared `aria-modal="true"` and kept none of what that promises: no accessible name, no
 * Escape, no focus move, no trap. Every create/edit form and every destructive `ConfirmDialog` is
 * built on it. The behaviour existed, complete, inside `Drawer` — which nothing renders. These
 * cases hold the contract on the dialog the app actually opens.
 */
describe('Modal — the dialog contract', () => {
  const confirm = (onCancel = () => {}, onConfirm = () => {}) => (
    <ConfirmDialog
      title="Delete note?"
      message="This cannot be undone."
      confirmLabel="Delete"
      cancelLabel="Cancel"
      onConfirm={onConfirm}
      onCancel={onCancel}
    />
  );

  it('is named by its title', () => {
    render(<Modal title="New task" onClose={() => {}}><input aria-label="name" /></Modal>);
    expect(screen.getByRole('dialog', { name: 'New task' })).toHaveAttribute('aria-modal', 'true');
  });

  it('moves focus inside on open — to the SAFE button of a destructive confirm', () => {
    render(confirm());
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus();
  });

  it('takes focus itself when it holds nothing focusable', () => {
    render(<Modal title="Notice" onClose={() => {}}>read only</Modal>);
    expect(screen.getByRole('dialog')).toHaveFocus();
  });

  it('leaves focus on a child that asked for it', () => {
    render(
      <Modal title="Rename" onClose={() => {}}>
        <input aria-label="first" />
        <input aria-label="second" autoFocus />
      </Modal>,
    );
    expect(screen.getByLabelText('second')).toHaveFocus();
  });

  it('closes on Escape', () => {
    const onCancel = vi.fn();
    render(confirm(onCancel));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('traps Tab at both ends, and pulls back focus that already escaped', () => {
    render(<><button type="button">behind</button>{confirm()}</>);
    const cancel = screen.getByRole('button', { name: 'Cancel' });
    const del = screen.getByRole('button', { name: 'Delete' });
    act(() => del.focus());
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(cancel).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(del).toHaveFocus();
    // A click on the scrim's edge, a programmatic blur: focus is on the page behind the modal.
    act(() => screen.getByRole('button', { name: 'behind' }).focus());
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(cancel).toHaveFocus();
  });

  it('hands focus back to the opener on close, and does not chase one that is gone', () => {
    function Harness({ open, showOpener }: { open: boolean; showOpener: boolean }) {
      return (
        <>
          {showOpener && <button type="button">opener</button>}
          {open && confirm()}
        </>
      );
    }
    const first = render(<Harness open={false} showOpener />);
    const opener = screen.getByRole('button', { name: 'opener' });
    act(() => opener.focus());
    first.rerender(<Harness open showOpener />);
    expect(opener).not.toHaveFocus();
    first.rerender(<Harness open={false} showOpener />);
    expect(opener).toHaveFocus();

    // The action removed the row the dialog was opened from: the opener is detached.
    first.rerender(<Harness open showOpener />);
    const chased = vi.spyOn(opener, 'focus');
    first.rerender(<Harness open showOpener={false} />);
    first.rerender(<Harness open={false} showOpener={false} />);
    expect(chased).not.toHaveBeenCalled();
  });

  it('does not move focus when its parent re-renders with a new onClose', () => {
    // Every caller passes an inline arrow. Keyed on `onClose`, the effect re-ran on each keystroke
    // in a form: cleanup sent focus to the opener and setup pulled it to the FIRST field.
    function Form() {
      const [open, setOpen] = useState(false);
      const [text, setText] = useState('');
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>open</button>
          {open && (
            <Modal title="New task" onClose={() => setOpen(false)}>
              <input aria-label="title" />
              <input aria-label="notes" value={text} onChange={(e) => setText(e.target.value)} />
            </Modal>
          )}
        </>
      );
    }
    render(<Form />);
    // Opened from a real control, as in the app: that control is what a re-run would refocus.
    const opener = screen.getByRole('button', { name: 'open' });
    act(() => opener.focus());
    fireEvent.click(opener);
    expect(screen.getByLabelText('title')).toHaveFocus();
    const notes = screen.getByLabelText('notes');
    act(() => notes.focus());
    fireEvent.change(notes, { target: { value: 'typed' } });
    expect(notes).toHaveValue('typed');
    expect(notes).toHaveFocus();
  });

  it('only the topmost dialog answers Escape', () => {
    const closeForm = vi.fn();
    const closeConfirm = vi.fn();
    render(
      <Modal title="Edit" onClose={closeForm}>
        <input aria-label="title" />
        {confirm(closeConfirm)}
      </Modal>,
    );
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(closeConfirm).toHaveBeenCalledTimes(1);
    expect(closeForm).not.toHaveBeenCalled();
  });

  it('still closes on a scrim click and not on an inner one', () => {
    const onClose = vi.fn();
    const { container } = render(<Modal title="M" onClose={onClose}><span>inner</span></Modal>);
    fireEvent.click(screen.getByText('inner'));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(container.querySelector('.modal-scrim') as HTMLElement);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

/**
 * The agent-reply renderer. Its output goes to `dangerouslySetInnerHTML`, and it had no test.
 */
describe('renderMarkdown — code spans and links do not swallow each other', () => {
  const NUL = String.fromCharCode(0);

  it('shows a link written inside a code span literally', () => {
    // Was: `<p>Use <code>\u00000\u0000</code> to link.</p>` — the link was stashed first, the code
    // rule stashed its placeholder, and one substitution pass left the placeholder on screen.
    const html = renderMarkdown('Use `[docs](https://example.com/a)` to link.');
    expect(html).toBe('<p>Use <code>[docs](https://example.com/a)</code> to link.</p>');
  });

  it('renders a code span inside link text', () => {
    const html = renderMarkdown('See [`run()`](https://example.com/run).');
    expect(html).toContain('<a href="https://example.com/run" target="_blank" rel="noopener noreferrer"><code>run()</code></a>');
    expect(html).not.toContain(NUL);
  });

  it('never lets a placeholder reach the output, whatever the nesting', () => {
    for (const src of [
      '`[a](https://x.example/1)` and [b](https://x.example/2) and `c`',
      '[`a` and `b`](https://x.example/3)',
      '**`[a](https://x.example/4)`**',
      '[a](https://x.example/`b`)',
    ]) {
      const html = renderMarkdown(src);
      expect(html, src).not.toContain(NUL);
      expect(html, src).not.toMatch(/href="[^"]*</);
    }
  });

  it('still escapes source HTML and still limits hrefs to http(s)', () => {
    expect(renderMarkdown('<img src=x onerror=alert(1)>')).toBe('<p>&lt;img src=x onerror=alert(1)&gt;</p>');
    expect(renderMarkdown('[x](javascript:alert(1))')).not.toContain('<a ');
  });
});
