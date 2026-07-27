# Dependency-safe queue manifest — OS v1

**Purpose.** `main` is temporarily frozen for **PR #31**'s exact-head Architect design re-audit (moving
`main` would invalidate the rev-28 audit candidate `c9680f5`). Dependency-safe work therefore proceeds on
isolated branches and is **queued** here — built, tested, reviewed, pushed, but **NOT merged** until PR #31
lands and `main` is re-synced. This file records each branch: base, owner, tests, conflict surface, and the
merge order. Nothing queued alters the PR #31 audit candidate or prejudges the disputed 3b-1B design.

**Critical path (gated, not stopped):** Architect design re-audit of **PR #31 / rev-28 @ `c9680f5`**
(CI run 30280738223, 9/9 GREEN — CI ≠ design GREEN). Only PR #31's merge + architecture-dependent 3b-1B
implementation are blocked; everything below is independent.

## Merge order (after PR #31 is design-GREEN, merged, and `main` re-synced)
1. `ci/ai-surface-inventory-gate` — no product deps; merge first.
2. `ci/supply-chain-gate` — `.github/` only; independent.
3. `ui/design-system` — theme tokens + contrast gate; base for UI work.
4. `ui/modal-a11y` — depends on nothing but pairs with the design system.
5. `docs/windows-broker-design`, `docs/windows-broker-impl-plan`, `docs/pr32-rebase-map` — docs only; any time.
6. Product-UI page branches — after the design-system + a11y foundations land (correct dependency order).

## Queued branches
| Branch | Base | Area | Owner | Tests / verification | Conflict surface | State |
|---|---|---|---|---|---|---|
| `ci/ai-surface-inventory-gate` | main (b6c6712) | security CI | Claude | 9 unit tests + gate GREEN locally | `tools/`, `apps/desktop/src-tauri/ai-surface-policy.json` | ✅ verified, queued |
| `docs/windows-broker-design` | main (b6c6712) | security design | Claude | adversarial review (6 findings closed) | `docs/design/` only | ✅ verified, queued |
| `backup/pr31-pre-rebase-6ebeca8` | — | safety backup of PR #31 pre-rebase head | Claude | n/a | none | 🔒 backup ref |
| `ci/supply-chain-gate` | main | supply-chain CI | Claude | YAML parse + filter compile + adversarial review | `.github/` only | ⏳ wave-3 building |
| `ui/design-system` | main | theme/tokens/contrast | Claude | `tools/check_contrast.py` + unittest | `apps/desktop/src/theme/`, `tools/` | ⏳ wave-3 building |
| `ui/modal-a11y` | main | accessibility | Claude | vitest + testing-library + axe | `apps/desktop/src/components/ui.tsx` | ⏳ wave-3 building |
| `docs/pr32-rebase-map` | main | analysis (no arch change) | Claude | review | `docs/design/` only | ⏳ wave-3 building |
| `docs/windows-broker-impl-plan` | main | security design | Claude | review | `docs/design/` only | ⏳ wave-3 building |

## Admission rule
A branch is admitted to the queue only after: it builds, its tests/self-verification pass, and an
independent adversarial review returns CLEAN. Flawed/incomplete artifacts are held (not queued) — see the
session log. No branch may modify files that would collide with PR #31 (`config/current_state.json`, the
3b-1B addendum, the coordination checkers) — those move only through PR #31.
