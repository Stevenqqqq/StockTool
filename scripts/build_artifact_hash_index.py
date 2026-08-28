from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a strict artifact hash index.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("artifacts/sprint30.2.1"),
        help="artifact directory to index",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="index path; defaults to <root>/artifact-hash-index.json",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    output = (args.output or root / "artifact-hash-index.json").resolve()
    excluded = {"artifact-hash-index.json", "artifact-hash-index.sha256"}
    # Only the index and sidecar at the indexed root are self references.
    # Historical nested bundles may contain their own index files and remain
    # ordinary, hash-bound evidence entries in the enclosing canonical index.
    excluded_paths = {
        output.relative_to(root).as_posix(),
        (root / "artifact-hash-index.sha256").relative_to(root).as_posix(),
    }
    entries = []
    for path in sorted(
        item
        for item in root.rglob("*")
        if item.is_file() and item.relative_to(root).as_posix() not in excluded_paths
    ):
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
            }
        )
    payload = {
        "schema_version": 1,
        "index_kind": "canonical",
        "self_reference_exclusions": sorted(excluded),
        "entry_count": len(entries),
        "entries": entries,
    }
    index = output
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    digest = hashlib.sha256(index.read_bytes()).hexdigest().upper()
    (root / "artifact-hash-index.sha256").write_bytes((digest + "\n").encode("ascii"))
    print(json.dumps({"entry_count": len(entries), "sha256": digest}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
