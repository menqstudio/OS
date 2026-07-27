import { configureAxe } from 'jest-axe';

// Shared axe runner for component-level accessibility tests.
//
// These specs render isolated components (fragments), not whole pages, so the
// page-scoped `region` best-practice rule ("all page content must be inside a
// landmark") is not meaningful here and is disabled. Every WCAG 2.0/2.1 A & AA
// rule stays enabled. Note: axe's `color-contrast` rule cannot run under jsdom
// (no layout/canvas), so it is reported as *incomplete*, never as a violation —
// contrast must be checked in a real-browser/visual pass, not in this unit gate.
export const axe = configureAxe({
  rules: {
    region: { enabled: false },
  },
});
