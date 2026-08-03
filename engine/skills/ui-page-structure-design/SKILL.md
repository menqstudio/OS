---
id: ui-page-structure-design
version: 1.1.0
status: active
---

# Ui Page Structure Design

## Trigger
Use when the task defines a page's or view's structure and information hierarchy: layout regions and grid, content ordering and progressive disclosure, navigation and wayfinding, responsive breakpoints and reflow, the document outline/landmark structure, and the primary-action hierarchy of a screen. Distinct from component-level UX — this is the skeleton the components live in.

## Inputs
Task contract with the page's purpose and its primary user goal; content inventory and priority; the design system's layout primitives, grid, and spacing tokens; target viewports and breakpoints; navigation model and where this page sits in it; accessibility target; risk level and output format.

## Workflow
1. Confirm identity, mode, scope, and evidence; read the existing page/layout definitions and navigation config to EOF.
2. State the single primary goal of the page and rank content by importance; everything secondary is subordinate or progressively disclosed.
3. Define the semantic document structure first — one h1, a correct heading outline, and landmark regions (header/nav/main/aside/footer) — so the page is navigable by structure alone.
4. Lay out on the design system's grid and spacing scale; establish the visual hierarchy (a clear focal region, one dominant call-to-action) and a predictable reading order that matches the DOM order.
5. Design the responsive behavior as deliberate reflow per breakpoint (what stacks, what collapses, what stays pinned), keeping the primary action reachable at every size.
6. Verify the tab/reading order matches visual order, landmarks and headings are correct, and the layout holds with real (long/short/empty) content across breakpoints.
7. Produce evidence, rollback instructions, and a residual-risk verdict.

## Outputs
A page structure with a valid heading outline and landmark regions; a grid-based layout and hierarchy honoring design tokens; per-breakpoint reflow behavior; DOM-order-matches-visual-order verification; screenshots across viewports with real content; residual risks.

## Safety limits
No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. Structure work does not authorize backend/content changes; those require their own grants. Ambiguous mutation targets fail closed.

## Handoffs
Escalate cross-domain decisions to the owning SST role. Component behavior and interaction states hand to Frontend UX & Product Design; navigation/IA that spans the app to the owning architecture role. Medium, high, and critical work requires an independent verifier. Release actions hand off only to the Push Executor.

## Verification
Success requires a valid single-h1 heading outline and correct landmarks, DOM order matching visual/reading order, the primary action reachable at every breakpoint, layout stable under real long/short/empty content, accessibility target met, clean rollback, and exact-head evidence. A layout that only holds with placeholder content remains RED.

## Failure and rollback
Stop on missing authority, stale receipts, inconsistent SSTs, a broken heading/landmark outline, or reflow that hides the primary action. Restore the prior page structure before reporting recovery and never call partial recovery GREEN.
