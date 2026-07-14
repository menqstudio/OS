from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


class DocsError(ValueError):
    pass


def validate_docs(root: pathlib.Path = ROOT) -> int:
    path = root / "config" / "documentation-manifest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise DocsError(f"documentation manifest unreadable: {exc}") from exc
    if (
        data.get("schema") != 1
        or data.get("reviewed_at") != "2026-07-14"
        or data.get("branch") != "bro-execution-control-plane-v2"
        or data.get("pr") != 2
    ):
        raise DocsError("documentation manifest metadata stale")
    docs = data.get("documents")
    if not isinstance(docs, list) or not docs:
        raise DocsError("documentation manifest empty")
    registered = [
        item.get("path")
        for item in docs
        if isinstance(item, dict) and item.get("reviewed") is True
    ]
    actual = sorted(
        str(path.relative_to(root)).replace("\\", "/")
        for path in root.rglob("*")
        if path.is_file()
        and (path.suffix.lower() in {".md", ".markdown"} or path.name == "SKILL.md")
    )
    if sorted(registered) != actual:
        raise DocsError("documentation inventory differs from manifest")
    stale = {
        "NEXT_CHAT.md": ["bro-agent-os-v1", "draft PR `#1`"],
        "ROADMAP.md": ["bro-agent-os-v1", "draft PR: `#1`"],
        "docs/EXECUTION_CONTROL_PLANE_V2_SPEC.md": [
            "Runtime behavior changed by this commit: None"
        ],
    }
    for rel, needles in stale.items():
        text = (root / rel).read_text(encoding="utf-8")
        for needle in needles:
            if needle in text:
                raise DocsError(f"stale documentation marker in {rel}: {needle}")
    return len(actual)


if __name__ == "__main__":
    print(f"GREEN: documentation freshness valid; documents={validate_docs()}")
