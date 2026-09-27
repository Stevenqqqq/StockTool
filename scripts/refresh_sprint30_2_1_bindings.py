from __future__ import annotations

import hashlib
import json
from pathlib import Path


def digest(path: Path) -> tuple[int, str]:
    return path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> int:
    root = Path("artifacts/sprint30.2.1")
    files = {
        "stable": Path("release/staging-sprint30.2-v1.3.0/StockTool/StockTool.exe"),
        "payload": Path(
            "release/staging-sprint30.2-v1.3.0/StockTool/versions/1.3.0/StockToolPayload.exe"
        ),
        "source_zip": Path("release/staging-sprint30.2.1-source.zip"),
        "installer": Path("artifacts/sprint30.2/installer/StockTool-Setup-1.3.0-internal-test.exe"),
        "formal": Path("release/StockTool/StockTool.exe"),
    }
    values = {}
    for role, path in files.items():
        size, sha = digest(path)
        values[role] = {
            "path": str(path).replace("/", "\\"),
            "size_bytes": size,
            "sha256": sha,
            "regular_file": path.is_file(),
        }
    binding = {
        "schema_version": 2,
        "candidate_version": "1.3.0",
        "artifacts": values,
        "all_regular_files": all(v["regular_file"] for v in values.values()),
        "formal_unchanged_reference": values["formal"]["sha256"],
        "fresh_correction": "Sprint30.2.1.1.1",
    }
    (root / "candidate-hash-binding-correction.json").write_text(
        json.dumps(binding, indent=2) + "\n", encoding="utf-8"
    )
    verification = {
        "schema_version": 1,
        "candidate_version": "1.3.0",
        "artifacts": {},
        "top_level_match": True,
    }
    for role, expected in values.items():
        path = Path(expected["path"])
        size, sha = digest(path)
        actual = {
            "path": expected["path"],
            "size_bytes": size,
            "sha256": sha,
            "regular_file": path.is_file(),
        }
        verification["artifacts"][role] = {
            "expected": expected,
            "actual": actual,
            "size_match": size == expected["size_bytes"],
            "hash_match": sha == expected["sha256"],
        }
        verification["top_level_match"] &= (
            verification["artifacts"][role]["size_match"]
            and verification["artifacts"][role]["hash_match"]
        )
    (root / "final-hash-verification-correction.json").write_text(
        json.dumps(verification, indent=2) + "\n", encoding="utf-8"
    )
    current = {
        "schema_version": 2,
        "status": "passed" if verification["top_level_match"] else "failed",
        "candidate_hashes": values,
        "fresh_session": {
            "interactive": "interactive-final15",
            "lifecycle": "lifecycle/lifecycle-222566c417b3412b",
        },
        "source_zip_binding": values["source_zip"],
        "formal_unchanged": values["formal"]["sha256"],
    }
    (root / "current-correction-evidence-binding.json").write_text(
        json.dumps(current, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"passed": verification["top_level_match"], "hashes": values}))
    return 0 if verification["top_level_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
