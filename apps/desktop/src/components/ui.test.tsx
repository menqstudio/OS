import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import {
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
    expect(badge).toHaveTextContent('done');
  });

  it('maps "blocked" to the danger tone', () => {
    const { container } = render(<StatusPill status="blocked" />);
    expect(container.querySelector('span.badge')).toHaveClass('badge--danger');
  });

  it('falls back to neutral for an unknown status', () => {
    const { container } = render(<StatusPill status="totally_unknown_status" />);
    expect(container.querySelector('span.badge')).toHaveClass('badge--neutral');
  });

  it('replaces underscores with spaces in the label', () => {
    render(<StatusPill status="awaiting_approval" />);
    expect(screen.getByText('awaiting approval')).toBeInTheDocument();
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
