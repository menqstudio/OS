#!/usr/bin/env python3
"""i18n key-parity gate for apps/desktop/src/i18n/{en,hy,ru}.ts.

Stdlib-only, offline. Fail-closed: the three dictionaries MUST declare the EXACT same
set of keys. If `en` gains a key that `hy`/`ru` lack (or vice-versa), or any file
declares a duplicate key, the untranslated string would silently fall back to English
at runtime (see i18n/index.ts `translate()`), so this gate turns that drift into a RED.

Why a text scan and not `tsc`/`node`: CI's python gates run with no Node toolchain in
their job, matching the other tools/*.py gates. Each dictionary entry lives on a single
line as `'key.name': 'value',`, so anchoring a regex to the start of each line extracts
the KEY unambiguously without parsing TypeScript (a value may contain quotes/colons, but
it never starts a line, so it can't be mistaken for a key).
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

# A dictionary key: a single-quoted string at the start of a line (after indentation),
# immediately followed by a colon. Values never start a line, so they can't match.
_KEY_RE = re.compile(r"^\s*'([^']+)'\s*:")

# The three dictionaries that must stay in lock-step, relative to the repo root.
LANGS = ("en", "hy", "ru")
_I18N_DIR = pathlib.PurePosixPath("apps/desktop/src/i18n")


def extract_keys(source: str) -> list[str]:
    """Return the dictionary keys, in file order (duplicates preserved so the caller can
    detect a repeated key — a real bug in a TS object literal that the compiler tolerates)."""
    keys: list[str] = []
    for line in source.splitlines():
        m = _KEY_RE.match(line)
        if m:
            keys.append(m.group(1))
    return keys


def parity_failures(keysets: dict[str, list[str]]) -> list[str]:
    """Pure, offline-testable core. `keysets` maps lang -> ordered key list. Returns a list
    of human-readable failures (empty == GREEN). Fail-closed: an empty key list (parse
    failure / wrong file), an in-file duplicate, or any divergence from the `en` reference
    is a failure."""
    failures: list[str] = []

    # (1) every declared language must have parsed at least one key.
    for lang in LANGS:
        if not keysets.get(lang):
            failures.append(f"{lang}: no keys parsed — file missing, empty, or unreadable (fail-closed)")
    # If a file didn't parse we can't meaningfully diff; report and stop here.
    if failures:
        return failures

    # (2) no duplicate keys within a file (a later duplicate silently shadows the earlier one).
    for lang in LANGS:
        seen: set[str] = set()
        for k in keysets[lang]:
            if k in seen:
                failures.append(f"{lang}: duplicate key {k!r}")
            seen.add(k)

    # (3) exact set parity against the `en` reference (both directions).
    ref = set(keysets["en"])
    for lang in ("hy", "ru"):
        other = set(keysets[lang])
        for missing in sorted(ref - other):
            failures.append(f"{lang}: missing key {missing!r} present in en")
        for extra in sorted(other - ref):
            failures.append(f"{lang}: extra key {extra!r} not present in en")
    return failures


def load_keysets(root: pathlib.Path) -> dict[str, list[str]]:
    """Read and key-extract the three dictionary files under `root`. A file that can't be
    read yields an empty list, which parity_failures() treats as a fail-closed RED."""
    keysets: dict[str, list[str]] = {}
    for lang in LANGS:
        path = root / _I18N_DIR / f"{lang}.ts"
        try:
            keysets[lang] = extract_keys(path.read_text(encoding="utf-8"))
        except OSError:
            keysets[lang] = []
    return keysets


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="i18n en/hy/ru key-parity gate")
    ap.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parents[1]),
                    help="repository root (defaults to the parent of tools/)")
    args = ap.parse_args(argv)
    root = pathlib.Path(args.root)

    keysets = load_keysets(root)
    failures = parity_failures(keysets)
    if failures:
        print("RED: i18n dictionaries are out of parity —", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        print(f"\n{len(failures)} problem(s). Add the missing translations so en/hy/ru match.",
              file=sys.stderr)
        return 1
    count = len(keysets["en"])
    print(f"GREEN: en/hy/ru all declare the same {count} i18n keys.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
