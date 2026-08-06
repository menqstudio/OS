---
id: frontend-ux-product-design
version: 1.1.0
status: active
---

# Frontend Ux Product Design

## Trigger
Use when the task builds or changes user-facing web UI and its behavior: component implementation, state and data-fetching wiring, form/validation flows, accessibility, responsive layout, loading/error/empty states, performance (bundle, render, Core Web Vitals), or a UX flow that must reduce friction or error rate.

## Inputs
Task contract with the flow or component and its acceptance criteria; design specs or mockups and design tokens; the component library and framework in use; existing components, state stores, and API contracts; accessibility target (WCAG level) and supported browsers/viewports; risk level and output format.

## Workflow
1. Confirm identity, mode, scope, and evidence; read the affected components, state, and API contracts to EOF.
2. Reproduce the current behavior across the target viewports and a keyboard-only path before changing anything.
3. Model every state the surface can be in — loading, empty, partial, error, success, offline — and design each explicitly rather than only the happy path.
4. Implement with semantic HTML and accessible roles/labels first; reuse existing components and tokens instead of forking; keep client state minimal and derive from server state where possible.
5. Handle errors and slow networks visibly (optimistic vs. pending, retry, and non-blocking validation); guard against layout shift and unbounded re-renders.
6. Verify accessibility (focus order, contrast, screen-reader labels, reduced-motion) and responsive behavior; measure bundle/render impact against baseline.
7. Produce evidence, rollback instructions, and a residual-risk verdict.

## Outputs
Scoped component/flow changes reusing the design system; all UI states handled; accessibility and responsive verification notes; before/after performance (bundle size, key CWV) deltas; reproducible steps and screenshots; residual risks.

## Safety limits
No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. Never embed API keys or tokens in client code or expose them in the bundle. Ambiguous mutation targets fail closed.

## Handoffs
Escalate cross-domain decisions to the owning SST role. Page-level structure and information hierarchy hand to UI Page Structure Design; API/contract changes to the owning backend/architecture role. Medium, high, and critical work requires an independent verifier. Release actions hand off only to the Push Executor.

## Verification
Success requires all interaction states rendered correctly, WCAG target met (keyboard + screen-reader path proven), responsive behavior across target viewports, no performance regression beyond the agreed budget, clean rollback, and exact-head evidence. Happy-path-only changes remain RED.

## Failure and rollback
Stop on missing authority, stale receipts, inconsistent SSTs, failed a11y/responsive checks, or performance regression. Restore the prior component/state before reporting recovery and never call partial recovery GREEN.
