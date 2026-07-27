// Setup for the accessibility (axe) test project.
//
// 1. jest-dom matchers (toBeInTheDocument, etc.) so a11y specs can also make
//    ordinary DOM assertions if needed.
// 2. jest-axe's `toHaveNoViolations` matcher, registered on vitest's `expect`.
//    jest-axe is test-runner-agnostic (it only depends on axe-core), so the
//    matcher plugs straight into vitest via `expect.extend`.
import '@testing-library/jest-dom';
import { expect } from 'vitest';
import { toHaveNoViolations } from 'jest-axe';

expect.extend(toHaveNoViolations);
