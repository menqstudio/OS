// jest-dom matchers (toBeInTheDocument, etc.) for all tests.
import '@testing-library/jest-dom';

// jsdom does not implement matchMedia; several views read it at mount for
// reduced-motion / responsive breakpoints. Provide an inert, non-matching stub so
// component tests can render those views. Tests that need a specific match can
// override window.matchMedia locally.
if (typeof window !== 'undefined' && typeof window.matchMedia !== 'function') {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
}

// jsdom does not implement scrollIntoView; keyboard-navigable lists (Files, etc.)
// call it to keep the cursor row visible. Stub it as a no-op so those effects don't
// throw during render.
if (typeof Element !== 'undefined' && typeof Element.prototype.scrollIntoView !== 'function') {
  Element.prototype.scrollIntoView = () => {};
}
