#!/usr/bin/env python3
"""Fail-closed CI gate: the pip-audit waivers rest on two facts, and both are checked here.

**Why this exists.** `.github/supply-chain/pip-audit-ignore.txt` waives seven `cryptography`
advisories so the `Python - pip-audit (PyPI advisories)` job stays green. Every waiver is an
accepted HIGH, and each one rested on two claims that nothing in this repository checked:

  1. *"the engine uses ONLY the Ed25519 signing API; it never touches X.509 verification or
     PKCS#7, which is the affected surface of every advisory below."* True when written —
     measured on 2026-09-19: zero `x509` / `pkcs7` / `pkcs12` imports, zero `load_pem_*` /
     `load_der_*` / `load_ssh_*` calls, every `serialization` use `Raw` + `NoEncryption`. But it
     is a claim about code, and ONE future `load_pem_private_key` would silently make four
     accepted HIGHs reachable while the waiver file still said they were not, and while the
     supply-chain wall still read green. Nothing would have gone red.

  2. *"a 50.0.0 bump was attempted and broke the governance runtime, so we waive these rather
     than force a breaking major."* True of four of the seven. It was NOT true of the other
     three: `PYSEC-2026-2141` (GHSA-r6ph-v2qm-q3c2, HIGH) is fixed in **46.0.5**,
     `PYSEC-2026-35` in **46.0.6**, `PYSEC-2026-36` in **46.0.7** — all patch releases inside
     the pinned 46.0 line, no major bump anywhere near them. The pin sat at 46.0.3 and three
     advisories, one of them HIGH, were waived under a reason that did not apply to them. That
     is what a waiver rots into: a sentence that was true about its neighbours.

So this gate holds both claims to the code and to the pin, with no network access:

  **Rule 1 — the surface.** No module under this repository may import a `cryptography` X.509,
  PKCS#7, PKCS#12, CMS or OCSP API, or call a PEM / DER / OpenSSH key *loader*. Those are the
  surfaces the waived advisories live on. Writing PEM is not parsing it, so only loaders are
  refused. A violation names the waivers that were resting on the file it found.

  **Rule 2 — waiver freshness.** Every waived `cryptography` id must record the release that
  fixes it, as `# fixed=<version>` in its own comment, and then two things must hold. A pin
  that has REACHED the fix means the waiver is dead and must be deleted, not carried. And a fix
  that sits in the same `major.minor` line as the pin is a patch release — not the breaking
  bump a waiver's excuse is made of — so it must be taken rather than waived. That second half
  is the one that catches the defect above: at pin 46.0.3, a waiver saying `fixed=46.0.5` is
  refused, and no reading of a neighbour's sentence can talk the gate out of it.

The `fixed=` datum lives inside the `#` comment because the workflow's own parser reads this
file with `id="${line%%#*}"` and then strips all whitespace — anything left outside the comment
would be concatenated onto the advisory id and passed to pip-audit as garbage.

Exit 0 = both rules hold. Exit 1 = a violation. No other outcome.

**What this gate does NOT do**, printed on every run because a gate that overstates its
coverage is the same lie one level up:
  - it is a static AST scan of `*.py`: `getattr(serialization, name)` or
    `importlib.import_module("cryptography.x509")` walks straight past it;
  - it reads Python only. The Rust workspace links its own TLS stack and is `cargo-audit`'s
    and `cargo-deny`'s problem, not this gate's;
  - it does not judge whether a waiver is CORRECTLY triaged — only that the premise it was
    written on still holds, and that it is still needed at all.
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import re
import sys

#: The advisory-waiver file whose premises this gate defends.
IGNORE_FILE = pathlib.Path(".github/supply-chain/pip-audit-ignore.txt")

#: The hash-pinned requirements that decide which waivers are still needed.
REQUIREMENTS = pathlib.Path("engine/requirements-ci.txt")

#: Directories never scanned: not ours, or not source.
SKIP_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        "target",
        "dist",
        "build",
        "__pycache__",
        ".venv",
        "venv",
        ".mypy_cache",
        ".pytest_cache",
    }
)

#: `cryptography` submodules whose mere import puts a waived advisory's surface in reach.
#: Each maps to the thing the advisories do there, so a RED line says why, not just what.
FORBIDDEN_MODULES = {
    "x509": "X.509 path validation — wildcard permittedSubtrees escape (GHSA-m2h6-j472-rp4c) "
    "and exponential path building (GHSA-jwv3-5hgf-82ww)",
    "pkcs7": "PKCS#7 — the Bleichenbacher oracle (GHSA-g6cj-pr64-35w5) and the bundled "
    "OpenSSL's PKCS7_verify use-after-free, CVE-2026-45447 (GHSA-537c-gmf6-5ccf)",
    "pkcs12": "PKCS#12 — PBMAC1 short-HMAC-key acceptance in the bundled OpenSSL, "
    "CVE-2026-34181 (GHSA-537c-gmf6-5ccf)",
    "cms": "CMS — AuthEnvelopedData forgery and password-based decryption reads in the "
    "bundled OpenSSL (GHSA-537c-gmf6-5ccf)",
    "ocsp": "OCSP — stapled-response double free, CVE-2026-35188 (GHSA-537c-gmf6-5ccf)",
}

#: Key *loaders*. These parse ASN.1 from a file or the wire, which is where the bundled
#: OpenSSL's ASN.1 over-read CVEs (CVE-2026-34180, CVE-2026-7383) are reached. Serialising
#: OUT to PEM parses nothing and is deliberately not listed.
FORBIDDEN_LOADERS = frozenset(
    {
        "load_pem_private_key",
        "load_pem_public_key",
        "load_pem_parameters",
        "load_der_private_key",
        "load_der_public_key",
        "load_der_parameters",
        "load_ssh_private_key",
        "load_ssh_public_key",
        "load_ssh_public_identity",
        "load_pem_x509_certificate",
        "load_der_x509_certificate",
        "load_pem_x509_certificates",
        "load_pem_x509_crl",
        "load_der_x509_crl",
        "load_pem_x509_csr",
        "load_der_x509_csr",
        "load_key_and_certificates",
        "load_pkcs12",
    }
)

#: The waiver file names advisories for many packages in principle; only `cryptography` ones
#: are governed by the pin this gate reads. A waived id is treated as a cryptography waiver
#: when its comment says so via `fixed=`, which is exactly what rule 2 requires of it.
FIXED_RE = re.compile(r"#.*?\bfixed=([0-9][0-9A-Za-z.\-]*)")

ADVISORY_RE = re.compile(r"^(GHSA-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4}|PYSEC-\d{4}-\d+|CVE-\d{4}-\d+)$")


def version_key(text: str) -> tuple[int, ...]:
    """Compare release numbers numerically: `46.0.10` is above `46.0.9`, not below it."""
    return tuple(int(part) for part in re.findall(r"\d+", text))


def pinned_cryptography(root: pathlib.Path) -> str | None:
    """The exact `cryptography==` version in the hash-pinned CI requirements."""
    path = root / REQUIREMENTS
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("cryptography=="):
            return stripped.split("==", 1)[1].split()[0].strip("\\ ")
    return None


def waived_entries(root: pathlib.Path) -> list[tuple[int, str, str | None]]:
    """Each waived advisory as `(line number, id, fixed-in version or None)`.

    Parsed the same way the workflow parses it — everything from `#` onward is comment — so
    this gate and pip-audit can never disagree about which ids are live.
    """
    path = root / IGNORE_FILE
    if not path.is_file():
        return []
    entries: list[tuple[int, str, str | None]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        identifier = line.split("#", 1)[0].strip()
        if not identifier:
            continue
        match = FIXED_RE.search(line)
        entries.append((number, identifier, match.group(1) if match else None))
    return entries


def python_files(root: pathlib.Path) -> list[pathlib.Path]:
    found = []
    for path in root.rglob("*.py"):
        if SKIP_DIRS.intersection(path.relative_to(root).parts):
            continue
        found.append(path)
    return sorted(found)


def scan_surface(root: pathlib.Path) -> list[str]:
    """Rule 1. Every `cryptography` reference that leaves the Ed25519-raw surface."""
    problems: list[str] = []
    for path in python_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        # Cheap reject first: a file that never says `cryptography` cannot import from it,
        # and parsing every .py in the repository otherwise dominates the runtime.
        if "cryptography" not in text and not FORBIDDEN_LOADERS.intersection(
            re.findall(r"\b[a-z_]+\b", text)
        ):
            continue
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as error:
            problems.append(f"{path.relative_to(root).as_posix()}: will not parse ({error})")
            continue
        relative = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("cryptography"):
                parts = set((node.module or "").split("."))
                for segment, why in FORBIDDEN_MODULES.items():
                    if segment in parts:
                        problems.append(
                            f"{relative}:{node.lineno}: imports from `{node.module}` — {why}"
                        )
                for alias in node.names:
                    if alias.name in FORBIDDEN_LOADERS:
                        problems.append(
                            f"{relative}:{node.lineno}: imports the key loader "
                            f"`{alias.name}` — parses ASN.1, which the bundled OpenSSL's "
                            f"over-read CVEs are reached through"
                        )
                    if alias.name in FORBIDDEN_MODULES:
                        problems.append(
                            f"{relative}:{node.lineno}: imports the `{alias.name}` module — "
                            f"{FORBIDDEN_MODULES[alias.name]}"
                        )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if not alias.name.startswith("cryptography"):
                        continue
                    parts = set(alias.name.split("."))
                    for segment, why in FORBIDDEN_MODULES.items():
                        if segment in parts:
                            problems.append(
                                f"{relative}:{node.lineno}: imports `{alias.name}` — {why}"
                            )
            elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_LOADERS:
                problems.append(
                    f"{relative}:{node.lineno}: calls `.{node.attr}` — parses ASN.1, which the "
                    f"bundled OpenSSL's over-read CVEs are reached through"
                )
            elif isinstance(node, ast.Name) and node.id in FORBIDDEN_LOADERS:
                problems.append(f"{relative}:{node.lineno}: uses the key loader `{node.id}`")
    return problems


def scan_waivers(root: pathlib.Path) -> tuple[list[str], str | None, int]:
    """Rule 2. Every waiver records what fixes it, and none has outlived the pin."""
    problems: list[str] = []
    pinned = pinned_cryptography(root)
    entries = waived_entries(root)
    if entries and pinned is None:
        problems.append(
            f"{REQUIREMENTS.as_posix()} names no `cryptography==` pin, so no waiver in "
            f"{IGNORE_FILE.as_posix()} can be checked for having outlived its fix"
        )
        return problems, pinned, len(entries)

    for number, identifier, fixed in entries:
        where = f"{IGNORE_FILE.as_posix()}:{number}"
        if not ADVISORY_RE.match(identifier):
            problems.append(
                f"{where}: `{identifier}` is not a GHSA / PYSEC / CVE id — pip-audit is "
                f"handed this verbatim as --ignore-vuln and will waive nothing"
            )
            continue
        if fixed is None:
            problems.append(
                f"{where}: `{identifier}` records no `fixed=<version>` in its comment, so "
                f"nothing can tell whether the pin has already outgrown this waiver"
            )
            continue
        if pinned is None:
            continue
        if version_key(pinned) >= version_key(fixed):
            problems.append(
                f"{where}: `{identifier}` is fixed in {fixed} and cryptography is pinned at "
                f"{pinned} — the waiver is dead. Delete the line; do not carry it"
            )
        elif version_key(pinned)[:2] == version_key(fixed)[:2]:
            problems.append(
                f"{where}: `{identifier}` is fixed in {fixed}, which is a PATCH release of the "
                f"pinned {pinned} — not a breaking bump. Take the patch; a waiver is for a fix "
                f"you cannot reach, not one you have not taken"
            )
    return problems, pinned, len(entries)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="repository root (default: cwd)")
    args = parser.parse_args(argv)
    root = pathlib.Path(args.root).resolve()

    surface = scan_surface(root)
    waivers, pinned, waived_count = scan_waivers(root)

    print("Limits of this gate, stated on every run:")
    print("  - a static AST scan of *.py; dynamic getattr/import_module walks past it")
    print("  - Python only; the Rust TLS stack is cargo-audit's and cargo-deny's surface")
    print("  - it checks a waiver's PREMISE and its freshness, never whether it was right")
    print()

    if surface or waivers:
        print("RED: the pip-audit waivers no longer rest on what they claim")
        if surface:
            print()
            waived = (
                "1 waived advisory in"
                if waived_count == 1
                else f"{waived_count} waived advisories in"
            )
            reach = "it" if waived_count == 1 else "them"
            print(
                f"  Rule 1 — the surface left Ed25519-raw. {waived} "
                f"{IGNORE_FILE.as_posix()} said this code could not reach {reach}:"
            )
            for problem in surface:
                print(f"    - {problem}")
            print()
            print(
                "  Either revert the call, or re-triage every waiver in that file against the "
                "surface this code now has. A waiver whose premise is gone is not a waiver."
            )
        if waivers:
            print()
            print("  Rule 2 — a waiver does not say what it rests on, or has outlived it:")
            for problem in waivers:
                print(f"    - {problem}")
        return 1

    tail = (
        "1 waived advisory records a fix"
        if waived_count == 1
        else f"{waived_count} waived advisories each record a fix"
    )
    print(
        f"GREEN: cryptography surface is Ed25519-raw only; {tail} above the pinned "
        f"{pinned or '(unpinned)'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
