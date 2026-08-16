// Setup for the browser (computed-style) project.
//
// The one thing that must not be got wrong here is the STYLESHEET GRAPH, and the first version of
// this file got it wrong in the direction that produces FALSE FINDINGS.
//
// It imported only `../styles.css` — the app's entry graph (tokens → global → aios → aios-shell) —
// and argued that `ui.css` and `layout.css` should arrive the way they arrive in the app, through
// `ui.tsx` and `Shell.tsx`. That reasoning is wrong for a spec that mounts a component in
// isolation: `CommandPalette` does not import `Shell`, so `layout.css` was absent, and the
// unstyled-class detector reported `.nav-ico` and `.top-spacer` as defined by no rule. They are
// defined — `layout.css:19` and `:27` — and have been all along.
//
// In the running app there is no such thing as a page without `layout.css`: `main.tsx` mounts the
// whole tree and `Shell` is always present. So the faithful thing to load is EVERYTHING the app
// loads, and let each spec mount whichever component it is measuring.
//
// The failure mode this file must avoid is not "too much CSS" — it is measuring a page the app
// never renders. Loading less than the app loads is exactly that, and it reported a defect in
// working code.
import '../styles.css';
import '../components/ui.css';
import '../components/layout.css';

import '@testing-library/jest-dom';

// No matchMedia / ResizeObserver / scrollIntoView stubs. Those exist in `src/test/setup.ts`
// because jsdom implements none of them; here they are real, and stubbing them would be the same
// mistake as `css: false` — substituting a fixture for the thing being measured.
