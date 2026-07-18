"""Content secret scanner and redactor (Execution Surface kind=recorder/validator).

Audit gap remediated: the runtime had only filename-based prohibition, no content
inspection, so a secret embedded in an error string, stderr tail or free-text
reason could be persisted verbatim into recovery / quarantine / supervisor records.
This module detects known secret formats and redacts them before any such text is
written to a log, evidence record or incident.

Precision over recall by design: detection is pattern-based on well-known secret
shapes only. It deliberately does NOT flag bare hex/sha256 digests or git hashes,
which are ubiquitous and legitimate in this repository, to avoid destroying
non-secret evidence through over-redaction.

Pure standard library, so this control has no unresolved runtime prerequisite.
"""
from __future__ import annotations

import re

# (type, compiled pattern). The value that must be hidden is either the whole
# match or, where a key name is legitimately visible, capture group "secret".
_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    ("aws-access-key-id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9._-]{20,}")),
    ("openai-key", re.compile(r"sk-[A-Za-z0-9]{32,}")),
    ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("slack-token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("google-api-key", re.compile(r"AIza[0-9A-Za-z._-]{35}")),
    ("private-key-block", re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("bearer-token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{20,}=*")),
]

# key=value / key: value with a plausibly-secret key name. Only the value is hidden.
_ASSIGNMENT = re.compile(
    r"(?i)\b(secret|password|passwd|passphrase|token|api[_-]?key|access[_-]?key|client[_-]?secret)"
    r"(\s*[=:]\s*)"
    r"(['\"]?)([^\s'\"]{6,})(\3)"
)

REDACTION = "[REDACTED:{kind}]"


def scan(text: str) -> list[dict]:
    """Return a list of {kind, start, end} findings, sorted by position."""
    if not isinstance(text, str) or not text:
        return []
    findings: list[dict] = []
    for kind, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            findings.append({"kind": kind, "start": m.start(), "end": m.end()})
    for m in _ASSIGNMENT.finditer(text):
        findings.append({"kind": "keyed-secret", "start": m.start(4), "end": m.end(4)})
    findings.sort(key=lambda f: (f["start"], f["end"]))
    return findings


def contains_secret(text: str) -> bool:
    return bool(scan(text))


def redact(text: str) -> str:
    """Replace every detected secret span with a typed redaction marker.

    Overlapping matches are resolved by taking the earliest, longest span first so
    the output never leaks a partial secret.
    """
    if not isinstance(text, str) or not text:
        return text
    findings = scan(text)
    if not findings:
        return text
    # Merge/skip overlaps: keep earliest start, longest end.
    chosen: list[dict] = []
    last_end = -1
    for f in sorted(findings, key=lambda f: (f["start"], -(f["end"]))):
        if f["start"] >= last_end:
            chosen.append(f)
            last_end = f["end"]
    out = []
    cursor = 0
    for f in chosen:
        out.append(text[cursor:f["start"]])
        out.append(REDACTION.format(kind=f["kind"]))
        cursor = f["end"]
    out.append(text[cursor:])
    return "".join(out)


def redact_mapping(value):
    """Recursively redact all strings inside a JSON-like structure."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_mapping(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_mapping(v) for v in value]
    return value
