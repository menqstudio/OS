# Brand assets · բրենդի ֆայլերը

The MenQ wordmark and the BroPS logo live here because until 2026-08-30 they lived nowhere
that survives. Neither had ever been committed: `git log --all --diff-filter=ADR` over every
image extension in this repository returns no `menq*` image at any point in its history. The
only brand artwork in the tree was the BroPS *application icon* set under
[`apps/desktop/src-tauri/icons/`](../../apps/desktop/src-tauri/icons/), which is the product
mark, not the parent wordmark.

The wordmark survived only as `~/menq-logo-power-flipped (1).png` on one machine, and on
2026-08-30 a disk-cleanup moved it into a root-owned archive the account itself could not
read. It was recovered with `sudo` and committed here. **A file that exists on exactly one
disk, outside version control, is one `mv` away from not existing** — that is what this
directory is for, and it is the same failure mode the repository's canon rules exist to stop:
required state living somewhere that is not the repository.

## What is here

| file | what it is | size |
|---|---|---|
| `menq-logo.png` | the MenQ wordmark, unmodified original | 2880×2160 RGBA, transparent ground |
| `menq-avatar.png` | square derivative of the wordmark, generated from it | 1024×1024 RGBA, ground `#0B0F14` |
| `brops-logo.png` | the BroPS wordmark, unmodified original | 2880×2160 RGBA, transparent ground |

`menq-avatar.png` is **generated, not drawn**: the wordmark is cropped to its alpha bounding
box (`580, 818 → 2413, 1458`, giving 1833×640), scaled to 84% of the canvas width, and centred
on a dark ground. Regenerating it from `menq-logo.png` reproduces it; it carries no artwork of
its own.

## Why the square variant exists

Two measured reasons, not preferences.

**The original is 4:3, and an avatar is square.** GitHub crops to a square and then, for a
`User` account — `gh api users/menqstudio -q .type` prints `User`, not `Organization` — renders
that square as a **circle**. A 2880×2160 image cropped square loses the ends of the wordmark.

**The wordmark is near-white on a transparent ground**, so on any light surface the "Men" half
disappears and only the cyan power mark survives. The dark ground fixes that in both themes.

The wordmark in `menq-avatar.png` is 860 px wide. At its height, the chord available inside the
inscribed circle is √(512² − 150²) ≈ 979 px, so the circular crop clips nothing.

## Using it as the GitHub profile picture

There is no REST endpoint for setting a user avatar — it cannot be scripted, and `gh api` can
only read `avatar_url`. Upload it by hand: **github.com/settings/profile → Edit → Upload a
photo → `docs/brand/menq-avatar.png`**.
