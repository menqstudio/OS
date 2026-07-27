#!/usr/bin/env python3
"""Fail-closed filter over `npm audit --json`.

Stdlib only. Reads an ``npm audit --json`` document (npm v7+ "vulnerabilities"
map, with a v6 "advisories" fallback), applies a high+ severity threshold, and
honours an allowlist of explicitly-waived advisories. Any high or critical
finding that is NOT waived makes this process exit 1 so the CI job fails closed.

Usage:
    npm audit --json > audit.json || true
    python npm_audit_filter.py audit.json --allow npm-audit-allow.txt

`npm audit` itself exits non-zero when vulnerabilities exist, so the workflow
captures its JSON with a trailing `|| true` and lets THIS gate decide pass/fail.
An empty/blank input (npm produced nothing) is treated as a hard error, not a
silent pass, so a broken audit step can never masquerade as "clean".
"""

from __future__ import annotations

import argparse
import json
import re
import sys

# Severity ordering. The gate fails on anything at or above the threshold.
SEVERITY_RANK = {
    "info": 0,
    "low": 1,
    "moderate": 2,
    "high": 3,
    "critical": 4,
}
DEFAULT_THRESHOLD = "high"

_GHSA_RE = re.compile(r"GHSA-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4}", re.IGNORECASE)


def _norm(token: str) -> str:
    return token.strip().lower()


def load_allowlist(path: str | None) -> set[str]:
    """Read an allowlist file: one token per line, `#` comments and blanks ignored.

    A token may be a package name, a numeric advisory source id, a GHSA id, an
    advisory URL, or an advisory title. Matching is case-insensitive.
    """
    if not path:
        return set()
    allowed: set[str] = set()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                # Allow an inline trailing comment: `left-pad  # tracked in JIRA-1`.
                token = line.split("#", 1)[0].strip()
                if token:
                    allowed.add(_norm(token))
    except FileNotFoundError:
        # A missing allowlist means "nothing is waived", not a crash. The file is
        # committed in-repo, so this only happens under misconfiguration; treat it
        # as the strictest possible policy (empty allowlist).
        print(f"[npm-audit-filter] WARNING: allowlist not found: {path} "
              f"(treating as empty; nothing waived)", file=sys.stderr)
        return set()
    return allowed


def _ghsa_ids(text: str) -> set[str]:
    return {m.group(0).lower() for m in _GHSA_RE.finditer(text or "")}


def _identifiers_v7(name: str, node: dict) -> set[str]:
    """Collect every token that could waive this package's vulnerability."""
    ids: set[str] = set()
    if name:
        ids.add(_norm(name))
    node_name = node.get("name")
    if isinstance(node_name, str) and node_name:
        ids.add(_norm(node_name))
    for via in node.get("via", []) or []:
        if isinstance(via, str):
            # Transitive: the name of the dependency that introduces the issue.
            ids.add(_norm(via))
            continue
        if not isinstance(via, dict):
            continue
        source = via.get("source")
        if source is not None:
            ids.add(_norm(str(source)))
        for key in ("url", "title", "name"):
            val = via.get(key)
            if isinstance(val, str) and val:
                ids.add(_norm(val))
                ids |= _ghsa_ids(val)
    return ids


def _worst_severity(node: dict) -> str:
    """Effective severity for a v7 vulnerability node (max over its `via`)."""
    worst = node.get("severity", "info")
    worst_rank = SEVERITY_RANK.get(str(worst).lower(), 0)
    for via in node.get("via", []) or []:
        if isinstance(via, dict):
            sev = str(via.get("severity", "")).lower()
            rank = SEVERITY_RANK.get(sev, -1)
            if rank > worst_rank:
                worst_rank, worst = rank, sev
    return str(worst).lower()


def collect_findings(doc: dict, threshold_rank: int) -> list[dict]:
    """Return every finding at/above `threshold_rank`, each with its identifiers.

    Handles npm v7+ (`vulnerabilities` map) and falls back to v6 (`advisories`).
    The blocking/waived split is decided later by `partition` against the
    allowlist; this function only computes severity membership.
    """
    findings: list[dict] = []

    vulns = doc.get("vulnerabilities")
    if isinstance(vulns, dict) and vulns:
        for name, node in vulns.items():
            if not isinstance(node, dict):
                continue
            sev = _worst_severity(node)
            if SEVERITY_RANK.get(sev, -1) < threshold_rank:
                continue
            findings.append({
                "package": name,
                "severity": sev,
                "identifiers": _identifiers_v7(name, node),
            })
    else:
        # npm v6 shape: {"advisories": {"<id>": {module_name, severity, ...}}}
        advisories = doc.get("advisories")
        if isinstance(advisories, dict):
            for adv_id, adv in advisories.items():
                if not isinstance(adv, dict):
                    continue
                sev = str(adv.get("severity", "info")).lower()
                if SEVERITY_RANK.get(sev, -1) < threshold_rank:
                    continue
                ids = {_norm(str(adv_id))}
                module = adv.get("module_name")
                if isinstance(module, str):
                    ids.add(_norm(module))
                url = adv.get("url")
                if isinstance(url, str):
                    ids.add(_norm(url))
                    ids |= _ghsa_ids(url)
                title = adv.get("title")
                if isinstance(title, str):
                    ids.add(_norm(title))
                findings.append({
                    "package": adv.get("module_name", str(adv_id)),
                    "severity": sev,
                    "identifiers": ids,
                })

    return findings


def partition(findings: list[dict], allowlist: set[str]) -> tuple[list[dict], list[dict]]:
    blocking, waived = [], []
    for f in findings:
        if f["identifiers"] & allowlist:
            waived.append(f)
        else:
            blocking.append(f)
    return blocking, waived


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed gate over `npm audit --json`.")
    parser.add_argument("audit_json",
                        help="Path to a file containing `npm audit --json` output, "
                             "or '-' to read stdin.")
    parser.add_argument("--allow", dest="allow", default=None,
                        help="Path to the newline-delimited allowlist file.")
    parser.add_argument("--threshold", default=DEFAULT_THRESHOLD,
                        choices=sorted(SEVERITY_RANK, key=SEVERITY_RANK.get),
                        help="Minimum severity that blocks (default: high).")
    args = parser.parse_args(argv)

    threshold_rank = SEVERITY_RANK[args.threshold]

    if args.audit_json == "-":
        raw = sys.stdin.read()
    else:
        try:
            with open(args.audit_json, "r", encoding="utf-8") as fh:
                raw = fh.read()
        except OSError as exc:
            print(f"[npm-audit-filter] ERROR: cannot read {args.audit_json}: {exc}",
                  file=sys.stderr)
            return 1

    if not raw.strip():
        print("[npm-audit-filter] ERROR: empty audit input -- `npm audit` produced "
              "no JSON. Failing closed.", file=sys.stderr)
        return 1

    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[npm-audit-filter] ERROR: could not parse audit JSON: {exc}. "
              f"Failing closed.", file=sys.stderr)
        return 1

    if not isinstance(doc, dict):
        print("[npm-audit-filter] ERROR: audit JSON is not an object. Failing closed.",
              file=sys.stderr)
        return 1

    allowlist = load_allowlist(args.allow)
    findings = collect_findings(doc, threshold_rank)
    blocking, waived = partition(findings, allowlist)

    print(f"[npm-audit-filter] threshold={args.threshold} "
          f"findings>=threshold={len(findings)} "
          f"waived={len(waived)} blocking={len(blocking)}")

    for f in sorted(waived, key=lambda x: x["package"]):
        print(f"  [waived]   {f['severity']:>8}  {f['package']}")
    for f in sorted(blocking, key=lambda x: (-SEVERITY_RANK.get(x['severity'], 0),
                                             x["package"])):
        print(f"  [BLOCKING] {f['severity']:>8}  {f['package']}")

    if blocking:
        print(f"[npm-audit-filter] FAIL: {len(blocking)} un-waived "
              f"{args.threshold}+ vulnerabilit(y/ies).", file=sys.stderr)
        return 1

    print("[npm-audit-filter] PASS: no un-waived high/critical vulnerabilities.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
