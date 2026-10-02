# T-165 — cryptography 46.0.7 → 50.0.2: CODE-AUDIT request

> **For the Architect.** This changes two audit-required engine paths — the runtime lock and the
> runtime dependency bound — so roadmap §G.2 needs your audit before merge. It is **not merged**.
> The Owner said "go non-stop" on the Builder's proposal to look at the open Dependabot alerts;
> he did not approve this specific change by name before it was written, and that is said here
> rather than left to be noticed.
>
> File the report at `apps/desktop/AUDIT/changes/pr-336-cryptography-50.md` with the two lines
> `Audited-PR: #336` and `Audited-Head: <40-hex>`, then a `VERDICT:` line. Take the head from
> `gh pr view 336 --json headRefOid`; CI stamps the body. Everything marked ◑ is the Builder's claim.

## 1. Why

GitHub showed five open Dependabot alerts on `main`. All five were already recorded waivers:
`GHSA-537c-gmf6-5ccf`, `GHSA-m2h6-j472-rp4c`, `GHSA-g6cj-pr64-35w5` and `GHSA-jwv3-5hgf-82ww` in
`.github/supply-chain/pip-audit-ignore.txt` against `cryptography`, and `RUSTSEC-2024-0429`
(glib) in the RustSec lists. The cryptography waivers rested on two things: the surface premise
(Ed25519 raw only, which `tools/check_crypto_surface.py` enforces) and the sentence
*"cryptography 49.0.0 and 50.0.0 were both tried; the bump broke the engine's governance
runtime."*

## 2. What the Builder measured ◑

- Engine suite against `cryptography 50.0.2`, everything else as locked: **2729 of 2730 passed**.
  The one failure was `test_env_health`: `engine/config/runtime-dependencies.json` declared
  `cryptography >=41,<47`, so the health check refused a version its own bound excluded. That
  check runs in the hook, which is how a bound reads as "the runtime broke".
- `pip-audit --strict` over the candidate lock with **no waiver at all**: `No known
  vulnerabilities found`.
- After the change: the engine suite passes 2731 in a fresh venv built from both locks with
  `--require-hashes` (cryptography 50.0.2, cffi 2.1.0) and 2731 under the system interpreter
  (cryptography 43); the bridge suite, `check_runbook_snippets.py`, `bro_validate.py` and
  `check_crypto_surface.py` are GREEN.

## 3. What changed

| File | What |
|---|---|
| `engine/requirements-ci.txt` | `cryptography==50.0.2`, PyPI's published hashes for the same eight wheel shapes as before (cp39/cp311 abi3; manylinux2014, 2_28, 2_34 x86_64; win_amd64) |
| `engine/config/runtime-dependencies.json` | the bound `>=41,<47` becomes `>=41,<51` |
| `.github/supply-chain/pip-audit-ignore.txt` | the four waivers are deleted; the file says why, and keeps its rules |
| `engine/tests/test_env_health.py` | a test that every pinned runtime library satisfies its declared bound; with `<47` put back it fails |

## 4. What to attack

1. Whether `<51` is the right ceiling, or the bound should follow the pin exactly.
2. Whether anything the engine calls changed behaviour between 46 and 50 in a way the suite would
   not see. The Builder relied on the suite and on `check_crypto_surface.py`'s premise that only
   raw Ed25519 is used; the changelogs were not read line by line.
3. Whether keeping `cffi==2.1.0` is right: 50.0.2 requires `cffi>=2.0.0`.

## 5. What was NOT done

- Nothing on Windows here; the `windows-latest` jobs on this pull request are the proof.
- The cryptography changelogs between 46.0.7 and 50.0.2 were not read in full.
- `docs/DEBIAN_DEPLOYMENT.md` installs the new lock; no deployment was re-run.
- The glib alert (`RUSTSEC-2024-0429`) is unchanged: it is a Rust dependency of the Tauri stack
  and its waiver is outside this change.
- No alert on GitHub was dismissed by hand; they should close when `main` no longer pins the
  vulnerable release.
