// Setup for the accessibility (axe) test project.
//
// 1. THE SAME ENVIRONMENT THE UNIT PROJECT GETS. This imported `@testing-library/jest-dom`
//    directly and stopped there, so the a11y project ran WITHOUT the jsdom stubs `setup.ts`
//    installs — `matchMedia`, `scrollIntoView`, `ResizeObserver`. A page that reads any of them
//    at mount threw before axe could look at it, and several do. That is a large part of why no
//    page had an a11y spec until 2026-08-16: the project they would have to live in could not
//    render them. `setup.ts` imports jest-dom itself, so this is a replacement, not an addition.
// 2. jest-axe's `toHaveNoViolations` matcher, registered on vitest's `expect`.
//    jest-axe is test-runner-agnostic (it only depends on axe-core), so the
//    matcher plugs straight into vitest via `expect.extend`.
import './setup';
import { expect } from 'vitest';
import { toHaveNoViolations } from 'jest-axe';

expect.extend(toHaveNoViolations);
