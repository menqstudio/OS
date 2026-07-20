# BroPS — MenQ Studio Design Standard Adoption

Status: canonical design dependency for `brops-v1-foundation-implementation`

## 1. Governing rule

BroPS MUST use **MenQ Studio Design Standards** as its parent visual and interaction foundation.

BroPS is a MenQ Studio product. It MUST NOT invent an unrelated design language, duplicate the parent system, or introduce product-local tokens that conflict with MenQ Studio standards.

The hierarchy is:

1. MenQ Studio Design Standards — parent brand and shared product foundation
2. BroPS product design layer — product-specific extensions
3. Page/component implementation — concrete usage

When a BroPS requirement conflicts with the parent MenQ standard, the conflict MUST be documented and explicitly approved before implementation.

## 2. Required inherited foundations

BroPS MUST inherit or map from MenQ Studio standards:

- brand identity and logo usage
- semantic color system
- dark and light theme contracts
- typography scale and font roles
- spacing scale
- sizing scale
- radius system
- elevation and surface hierarchy
- borders and dividers
- icon rules
- motion principles and timing tokens
- focus, hover, active, disabled and selected states
- accessibility requirements
- localization-safe layout rules
- responsive breakpoints and density rules
- shared primitive component behavior
- content tone and terminology rules where defined

## 3. Token architecture

All visual values MUST be token-driven.

Required layers:

- MenQ foundation tokens
- MenQ semantic tokens
- BroPS semantic aliases
- component tokens
- state tokens

BroPS aliases MAY specialize meaning, but MUST resolve back to MenQ tokens whenever the parent standard defines an equivalent.

Examples:

```css
--menq-color-surface-primary
--menq-color-text-primary
--menq-space-4
--menq-radius-card
--brops-command-surface: var(--menq-color-surface-primary)
--brops-agent-card-radius: var(--menq-radius-card)
```

Forbidden:

- hard-coded hex/rgb colors in components
- arbitrary spacing values
- one-off radii or shadows
- page-local typography scales
- duplicated light/dark values outside theme tokens

## 4. BroPS product-specific layer

BroPS MAY add product-specific patterns only where MenQ Studio standards do not already define them.

Approved BroPS extension domains:

- command composer and execution timeline
- AI agent identity/status presentation
- approval and risk surfaces
- agent group-chat presence and mentions
- memory confidence/provenance presentation
- knowledge provenance and linked-entity UI
- runtime budget/usage displays
- desktop workspace tabs and context drawer
- offline/degraded/secure-mode indicators

Each extension MUST:

1. use MenQ tokens,
2. follow MenQ interaction laws,
3. support HY/EN/RU,
4. support dark/light,
5. define all interaction states,
6. meet accessibility requirements,
7. be reusable rather than page-local.

## 5. Visual direction

BroPS should feel:

- premium and intentional
- AI-driven and technical
- slightly futuristic, not decorative sci-fi
- calm, focused and command-first
- dense enough for professional desktop work
- visually consistent with the MenQ product family

Avoid:

- generic admin-dashboard appearance
- excessive neon/glow
- visual noise
- unsupported glass effects
- decorative gradients without semantic purpose
- inconsistent card styles
- consumer-chat styling that weakens the command-center identity

## 6. Component adoption rule

Before creating a component, implementation MUST check whether MenQ Studio standards already define:

- primitive
- pattern
- token
- variant
- state behavior

If yes, reuse or adapt it. If no, create a BroPS extension and document the reason.

Core shared primitives should include:

- Button
- IconButton
- Input
- Textarea
- Select
- Checkbox
- Radio
- Switch
- Tabs
- Badge
- Tooltip
- Popover
- Dropdown
- Dialog
- Drawer/Sheet
- Toast
- Alert
- Card
- Table/List
- Skeleton
- EmptyState
- ErrorState
- Avatar
- Progress
- CommandMenu

## 7. Required design implementation artifacts

The implementation branch MUST contain:

- imported or mirrored MenQ token source with provenance
- BroPS token alias file
- dark/light theme mappings
- shared primitive component library
- product pattern components
- component state documentation or stories
- responsive behavior documentation
- accessibility checks
- visual regression coverage for critical surfaces

The codebase SHOULD expose tokens through CSS custom properties and typed TypeScript helpers where useful.

## 8. Page design gate

No page is complete until it demonstrates:

- MenQ token usage
- dark and light modes
- HY, EN and RU content resilience
- loading, empty, populated, error, offline and permission-denied states
- keyboard navigation
- visible focus state
- narrow-width behavior
- no hard-coded visual values

Critical pages requiring visual review:

1. Command
2. Projects
3. Tasks
4. Agents
5. Knowledge
6. Memory
7. Group Chat
8. Notifications
9. Settings

## 9. Source-of-truth handling

The implementer MUST locate and read the canonical MenQ Studio Design Standards repository/files before finalizing visual implementation.

If the exact canonical source cannot be accessed, implementation MUST NOT silently guess that it complies. It may proceed with provisional mappings, but must mark them clearly and open a blocking design-source gap before declaring the UI final.

## 10. Acceptance criteria

Design compliance is GREEN only when:

- every visual value resolves through tokens
- MenQ parent standards are explicitly referenced
- BroPS-specific deviations are documented
- dark/light are complete
- HY/EN/RU are complete
- critical components include all states
- responsive behavior is implemented
- keyboard/focus behavior is validated
- accessibility checks pass
- visual regression evidence exists for critical screens

This file is mandatory reading together with `DESIGN_SYSTEM.md`, `DETAILED_UX_UI_SPEC.md`, `LOCALIZATION_AND_THEMES.md`, and `IMPLEMENTATION_EXECUTION_HANDOFF.md`.
