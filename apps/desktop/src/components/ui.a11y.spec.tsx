import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { axe } from '../test/axe';
import { Button, PageHeader, Field } from './ui';

/**
 * Accessibility (axe) smoke tests for the shared presentational primitives.
 *
 * Each case renders a component, runs axe over the produced DOM, and asserts
 * there are zero WCAG violations. Components are wrapped in a <main> landmark so
 * the rendered tree is a genuinely accessible fragment (belt-and-suspenders with
 * the `region` rule already disabled in ../test/axe).
 *
 * These render WITHOUT the Tauri IPC layer or the `useApp` context, exactly like
 * ui.test.tsx, so nothing here depends on a backend.
 */
describe('accessibility (axe) — shared UI primitives', () => {
  it('a primary Button (discernible text) has no violations', async () => {
    const { container } = render(
      <main>
        <Button variant="primary">Create task</Button>
      </main>,
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it('a PageHeader + labelled Field composition has no violations', async () => {
    const { container } = render(
      <main>
        <PageHeader title="Tasks" subtitle="All work items" />
        <Field label="Owner">Bro</Field>
      </main>,
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
