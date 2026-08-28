"""Read-only evidence helpers for Sprint 20 data and artifact manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def build_manifest(root: Path) -> dict[str, object]:
    """Hash regular files below *root* without copying or changing them."""

    files: list[dict[str, object]] = []
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    size += len(chunk)
                    digest.update(chunk)
            files.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "size_bytes": size,
                    "sha256": digest.hexdigest().upper(),
                }
            )
    return {
        "root": str(root.resolve()),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "file_count": len(files),
        "files": files,
    }


def compare_manifests(before: dict[str, object], after: dict[str, object]) -> dict[str, object]:
    """Return a deterministic zero-diff comparison without exposing file content."""

    before_files = before.get("files", [])
    after_files = after.get("files", [])
    if not isinstance(before_files, list):
        before_files = []
    if not isinstance(after_files, list):
        after_files = []
    before_rows = {
        str(item["path"]): item
        for item in before_files
        if isinstance(item, dict) and "path" in item
    }
    after_rows = {
        str(item["path"]): item for item in after_files if isinstance(item, dict) and "path" in item
    }
    added = sorted(set(after_rows) - set(before_rows))
    removed = sorted(set(before_rows) - set(after_rows))
    changed = sorted(
        path for path in set(before_rows) & set(after_rows) if before_rows[path] != after_rows[path]
    )
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "zero_diff": not added and not removed and not changed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("manifest", "compare"))
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--after", type=Path)
    args = parser.parse_args()
    if args.command == "manifest":
        payload = build_manifest(args.root)
    else:
        if args.after is None:
            parser.error("compare requires --after")
        payload = compare_manifests(
            json.loads(args.root.read_text(encoding="utf-8")),
            json.loads(args.after.read_text(encoding="utf-8")),
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
