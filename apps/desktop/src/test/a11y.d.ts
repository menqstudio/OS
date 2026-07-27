// Teach vitest's `expect` about jest-axe's matcher for TypeScript.
//
// @types/jest-axe augments the global `jest` namespace, which vitest does not
// use, so the vitest `Assertion` interface needs its own augmentation here.
// This keeps `tsc --noEmit` (the build/typecheck step) green for the a11y specs.
import 'vitest';

interface A11yMatchers<R = unknown> {
  toHaveNoViolations(): R;
}

declare module 'vitest' {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  interface Assertion<T = any> extends A11yMatchers<T> {}
  interface AsymmetricMatchersContaining extends A11yMatchers {}
}
