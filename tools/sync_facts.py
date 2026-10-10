#!/usr/bin/env python3
"""Entry point for the facts tool. The implementation is the MenQ Standard kit's file.

OS wrote this tool (T-171) and it then moved into the standard's consumer kit, which OS adopted:
`menq-standard/sync_facts.py`, hash-pinned in `.menq-standard.json` and never edited here. For a
while OS held both — two byte-identical copies, which is two copies only until the kit's next
update. This file is what is left: it loads the kit's file and IS that module, so
`import sync_facts`, `python3 tools/sync_facts.py --check|--write` and `tools/check_facts.py` all
run the one implementation. `tools/SYNC_FACTS.md` is still the manual.

The kit's file resolves the repository root as its own grandparent directory, which is the same
directory this file's is, so no default changes.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

KIT_FILE = pathlib.Path(__file__).resolve().parents[1] / "menq-standard" / "sync_facts.py"


def _load():
    if not KIT_FILE.is_file():
        raise SystemExit(
            f"sync_facts: the kit's file is missing: {KIT_FILE}. It comes with MenQ Standard; "
            "restore it with `python3 menq-standard/check_conformance.py install` from a checkout "
            "of the standard, or `git checkout -- menq-standard/`."
        )
    spec = importlib.util.spec_from_file_location("sync_facts", KIT_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_kit = _load()

if __name__ == "__main__":
    sys.exit(_kit.main())

# Imported: this name now refers to the kit's module itself, so a caller that patches or reads an
# attribute of `sync_facts` reaches the implementation and not a wrapper around it.
sys.modules[__name__] = _kit
