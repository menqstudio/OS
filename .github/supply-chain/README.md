# Supply-chain scan gate

Companion files for [`.github/workflows/supply-chain.yml`](../workflows/supply-chain.yml).
The workflow runs six **independent** jobs (a failure in one never masks the others),
each failing **closed** on high/critical severity:

| Job | Tool | Ecosystem | Config in this dir |
|-----|------|-----------|--------------------|
| `cargo-audit` | [cargo-audit](https://github.com/rustsec/rustsec) | Rust | `cargo-audit-ignore.txt` |
| `cargo-deny`  | [cargo-deny](https://github.com/EmbarkStudios/cargo-deny) | Rust | `deny.toml` |
| `pip-audit`   | [pip-audit](https://github.com/pypa/pip-audit) | Python | `pip-audit-ignore.txt` |
| `npm-audit`   | `npm audit` + `npm_audit_filter.py` | Node | `npm-audit-allow.txt`, `npm_audit_filter.py` |
| `sbom`        | CycloneDX (rust/npm/python) | all | - (emits `sbom/` artifact) |
| `gitleaks`    | [gitleaks](https://github.com/gitleaks/gitleaks) | secrets | `gitleaks.toml` |

**Triggers:** `pull_request` (opened/reopened/synchronize), `push` to `main`, and a
weekly `schedule` (Mondays 07:17 UTC) so newly-published advisories against an
unchanged dependency graph still turn the repository red.

All third-party actions are pinned by full commit SHA (the shared SHAs match
`.github/workflows/ci.yml`). `gitleaks` is installed from a version-pinned release
tarball verified against the release's own `checksums.txt`.

## Waiver / allowlist files

Every waiver is a **consciously accepted risk**. Each entry must carry a
justification comment and, ideally, a tracking issue link. All four files start
empty (comments only): the default posture waives nothing.

- **`cargo-audit-ignore.txt`** - RustSec IDs (`RUSTSEC-YYYY-NNNN`), one per line,
  passed to cargo-audit as `--ignore`. Mirror any long-lived waiver into
  `deny.toml`'s `[advisories].ignore`.
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
