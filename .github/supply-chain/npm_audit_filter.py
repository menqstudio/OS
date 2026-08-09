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

**An audit that could not run is not an audit that found nothing.** Every way the
audit can fail to produce a real result is a hard error here, never a silent pass:

  * empty/blank input (npm produced nothing);
  * unparseable JSON, or JSON that is not an object;
  * an npm ERROR document (`{"error": {...}}`) -- npm emits this, exit code and
    all, for ENOLOCK / registry failure / EAUDITNOPJSON. It parses fine and has
    neither `vulnerabilities` nor `advisories`, so before this check it produced
    zero findings and a PASS;
  * a document carrying NEITHER an npm v7 `vulnerabilities` map nor a v6
    `advisories` map -- an unrecognised shape cannot be audited, so it is refused
    rather than read as "clean";
  * a document whose own `metadata.vulnerabilities` counts high/critical entries
    that the findings walk did not produce (shape drift / truncation);
  * an `--npm-exit-code` outside {0, 1} (npm uses 1 for "vulnerabilities found";
    anything else is a tool failure, not an audit result).
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


class AuditUnavailable(Exception):
    """The input is not a usable audit result. Always fail closed on this."""


#: npm exit codes that correspond to an audit that actually RAN. `npm audit`
#: exits 0 when nothing is at/above its own level and 1 when it found something;
#: any other code (ENOLOCK, network, EUSAGE, a crash) means no audit happened.
NPM_EXIT_CODES_MEANING_AUDIT_RAN = (0, 1)


def _npm_error_summary(err) -> str:
    if isinstance(err, dict):
        code = err.get("code") or "?"
        summary = err.get("summary") or err.get("detail") or ""
        return f"code={code} {summary}".strip()
    return str(err)


def classify_document(doc: dict) -> str:
    """Return "v7" or "v6" for a usable audit document; raise `AuditUnavailable`
    otherwise.

    This is the gate's fail-closed door. `collect_findings` below answers only
    "which findings are at/above threshold" -- an EMPTY answer from it is
    meaningful ONLY once we know the document really was an audit result. npm's
    error document is the case that made that distinction load-bearing: it is
    valid JSON, it has no `vulnerabilities` and no `advisories`, and it therefore
    used to walk straight through the severity filter to `PASS`.
    """
    if "error" in doc:
        raise AuditUnavailable(
            "npm reported an ERROR instead of an audit result: "
            + _npm_error_summary(doc.get("error"))
        )
    if isinstance(doc.get("vulnerabilities"), dict):
        return "v7"
    if isinstance(doc.get("advisories"), dict):
        return "v6"
    raise AuditUnavailable(
        "document carries neither an npm v7 `vulnerabilities` map nor a v6 "
        "`advisories` map -- this is not an audit result. Keys present: "
        + (", ".join(sorted(map(str, doc))) or "<none>")
    )


def _metadata_high_plus(doc: dict, threshold_rank: int) -> int | None:
    """npm's OWN count of entries at/above the threshold, or None if absent.

    A cross-check against a second field in the same document: if npm says it
    found high/critical entries and our walk produced none, the map we walked was
    not the map npm counted (truncation, shape drift, a future schema), and a
    zero-findings PASS would be a lie.
    """
    meta = doc.get("metadata")
    if not isinstance(meta, dict):
        return None
    counts = meta.get("vulnerabilities")
    if not isinstance(counts, dict):
        return None
    total = 0
    seen = False
    for sev, rank in SEVERITY_RANK.items():
        if rank < threshold_rank:
            continue
        val = counts.get(sev)
        if isinstance(val, bool) or not isinstance(val, int):
            continue
        seen = True
        total += val
    return total if seen else None


def collect_findings(doc: dict, threshold_rank: int,
                     shape: str | None = None) -> list[dict]:
    """Return every finding at/above `threshold_rank`, each with its identifiers.

    `shape` is the verdict of `classify_document` ("v7" / "v6"). It is a REQUIRED
    input in spirit: this function no longer decides for itself whether a document
    is auditable, it only computes severity membership within a shape already
    proven usable. Passing None re-runs the classifier (which raises
    `AuditUnavailable` on a non-audit document) rather than silently returning [].
    The blocking/waived split is decided later by `partition`.
    """
    findings: list[dict] = []

    if shape is None:
        shape = classify_document(doc)

    if shape == "v7":
        vulns = doc.get("vulnerabilities") or {}
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
    parser.add_argument("--npm-exit-code", dest="npm_exit_code", type=int, default=None,
                        help="The exit code `npm audit` itself returned. 0 (nothing at "
                             "npm's level) and 1 (vulnerabilities found) mean the audit "
                             "RAN; any other code is a tool failure and fails closed.")
    args = parser.parse_args(argv)

    threshold_rank = SEVERITY_RANK[args.threshold]

    # The audit process itself must have RUN. npm exits 1 when it finds something and 0
    # when it does not; every other code (ENOLOCK, EUSAGE, network, crash) means there is
    # no audit result to filter, whatever the JSON on stdout looks like.
    if args.npm_exit_code is not None and             args.npm_exit_code not in NPM_EXIT_CODES_MEANING_AUDIT_RAN:
        print(f"[npm-audit-filter] ERROR: `npm audit` exited {args.npm_exit_code} "
              f"(expected one of {list(NPM_EXIT_CODES_MEANING_AUDIT_RAN)}). The audit did "
              f"not run. Failing closed.", file=sys.stderr)
        return 1

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

    # Prove the document IS an audit result before reading "no findings" as "clean".
    try:
        shape = classify_document(doc)
    except AuditUnavailable as exc:
        print(f"[npm-audit-filter] ERROR: {exc} Failing closed.", file=sys.stderr)
        return 1

    allowlist = load_allowlist(args.allow)
    findings = collect_findings(doc, threshold_rank, shape)

    # Cross-check the walk against npm's own count in the same document. If npm counted
    # high/critical entries and the walk produced none, the map we read is not the map npm
    # summarised -- a zero-findings PASS there would be false.
    claimed = _metadata_high_plus(doc, threshold_rank)
    if claimed is not None and claimed > 0 and not findings:
        print(f"[npm-audit-filter] ERROR: metadata reports {claimed} "
              f"{args.threshold}+ vulnerabilit(y/ies) but the {shape} findings walk "
              f"produced none -- the document shape is not what this filter reads. "
              f"Failing closed.", file=sys.stderr)
        return 1

    blocking, waived = partition(findings, allowlist)

    print(f"[npm-audit-filter] shape={shape} threshold={args.threshold} "
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
