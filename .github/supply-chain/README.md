# Supply-chain scan gate

Companion files for [`.github/workflows/supply-chain.yml`](../workflows/supply-chain.yml).
The workflow runs **independent** jobs (a failure in one never masks the others), each
failing **closed**. These are the scanners, and the file each one reads from this
directory:

| Job | Tool | Ecosystem | Config in this dir |
|-----|------|-----------|--------------------|
| `cargo-audit` | [cargo-audit](https://github.com/rustsec/rustsec) | Rust | `cargo-audit-ignore.txt` |
| `cargo-deny`  | [cargo-deny](https://github.com/EmbarkStudios/cargo-deny) | Rust | `deny.toml` |
| `pip-audit`   | [pip-audit](https://github.com/pypa/pip-audit) | Python | `pip-audit-ignore.txt` |
| `npm-audit`   | `npm audit` + `npm_audit_filter.py` | Node | `npm-audit-allow.txt`, `npm_audit_filter.py` |
| `sbom`        | CycloneDX (rust/npm/python) | all | - (emits `sbom/` artifact) |
| `gitleaks`    | [gitleaks](https://github.com/gitleaks/gitleaks) | secrets | `gitleaks.toml` |

The same workflow carries five more jobs that are repository gates rather than scanners
and read nothing from this directory: `action-pins`, `release-signing`, `residual-items`,
`reachability` and `runbook-snippets`. This page said "six jobs" while the workflow had
eleven; the count is not kept here any more, and the `jobs:` block of the workflow is the
list.

`gitleaks` scans the **working tree**. Its pull-request step passes `--no-git`, so it does
not walk the commit range: a secret added and then removed inside one pull request is not
seen (audit F-20, recorded in the step).

**Triggers:** `pull_request` (opened/reopened/synchronize), `push` to `main`, and a
weekly `schedule` (Mondays 07:17 UTC) so newly-published advisories against an
unchanged dependency graph still turn the repository red.

All third-party actions are pinned by full commit SHA (the shared SHAs match
`.github/workflows/ci.yml`). `gitleaks` is installed from a version-pinned release
tarball verified against the release's own `checksums.txt`.

## Waiver / allowlist files

Every waiver is a **consciously accepted risk**. Each entry must carry a
justification comment and, ideally, a tracking issue link.

The files were created empty, and this page went on saying "all four files start empty:
the default posture waives nothing" after that stopped being true. **They waive things
now** — RustSec warnings in `cargo-audit-ignore.txt` and `deny.toml`, `cryptography`
advisories in `pip-audit-ignore.txt`. Read the files for what and why; the numbers are
not repeated here, because a count on this page is checked by nothing. What IS checked,
by `tools/check_crypto_surface.py` in the `pip-audit` job:

- every `pip-audit-ignore.txt` entry records the release that fixes it and has not been
  outgrown by the pin;
- `cargo-audit-ignore.txt` and `deny.toml`'s `[advisories].ignore` are the **same set**.
  They are one waiver list read by two scanners, and until this check each carried only a
  comment asking to be kept in sync with the other.

- **`cargo-audit-ignore.txt`** - RustSec IDs (`RUSTSEC-YYYY-NNNN`), one per line,
  passed to cargo-audit as `--ignore`. Every id here must also be in
  `deny.toml`'s `[advisories].ignore`, and the reverse (gate-enforced, see above).
- **`pip-audit-ignore.txt`** - advisory IDs (`GHSA-...` / `PYSEC-...` / `CVE-...`), one
  per line, passed to pip-audit as `--ignore-vuln`.
- **`npm-audit-allow.txt`** - tokens matched (case-insensitively) against each
  finding's package name, npm source id, GHSA id, advisory URL, or title. Prefer the
  GHSA id; a bare package name waives *all* advisories for that package.
- **`deny.toml`** - cargo-deny policy: advisories (`vulnerability = deny`, fail
  closed), an SPDX license allowlist, bans (wildcards denied), and source pinning
  (only crates.io permitted).
- **`gitleaks.toml`** - extends the built-in gitleaks ruleset and allowlists
  lockfiles, test fixtures, and documentation placeholders.

## `npm_audit_filter.py`

Stdlib-only, no third-party imports. Reads `npm audit --json` (npm v7+
`vulnerabilities` map, with a v6 `advisories` fallback), applies a `--threshold`
(default `high`), and honours `npm-audit-allow.txt`. It **fails closed**:

- any un-waived finding at/above the threshold -> exit `1` (job red);
- empty/blank input or unparseable JSON -> exit `1` (a broken audit step can never
  masquerade as clean);
- a missing allowlist file -> treated as *empty* (strictest policy), with a warning.

```bash
# Local reproduction of the CI job:
cd apps/desktop
npm audit --json > npm-audit.json || true
python ../../.github/supply-chain/npm_audit_filter.py \
    npm-audit.json \
    --allow ../../.github/supply-chain/npm-audit-allow.txt \
    --threshold high
```

## Verification performed

- `supply-chain.yml` parses under PyYAML `safe_load`.
- `npm_audit_filter.py` compiles under `python -m py_compile`.
