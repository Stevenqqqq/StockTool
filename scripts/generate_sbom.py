"""Generate a deterministic, metadata-backed CycloneDX-like SBOM without network access."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import tomllib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, cast

from packaging.requirements import Requirement


def distribution_records(project_file: Path) -> list[dict[str, str]]:
    """Return the installed runtime dependency closure declared by the project.

    This deliberately excludes developer and audit-tool packages installed in
    the virtual environment.  The SBOM is therefore a product runtime record,
    not an inventory of arbitrary local tooling.
    """

    with project_file.open("rb") as stream:
        project = tomllib.load(stream)
    declared = project.get("project", {}).get("dependencies", [])
    if not isinstance(declared, list):
        raise ValueError("Project runtime dependencies are invalid.")
    installed: dict[str, importlib.metadata.Distribution] = {}
    for distribution in importlib.metadata.distributions():
        metadata = cast(Mapping[str, str], distribution.metadata)
        name = metadata.get("Name")
        if name:
            installed[_normalized_name(name)] = distribution
    names = _runtime_closure((str(item) for item in declared), installed)
    records = []
    for name in sorted(names):
        distribution = installed[name]
        metadata = cast(Mapping[str, str], distribution.metadata)
        records.append(
            {
                "name": str(metadata["Name"]),
                "version": distribution.version,
                "license": metadata.get("License") or "UNKNOWN",
                "home_page": metadata.get("Home-page") or "",
            }
        )
    return records


def _runtime_closure(
    requirements: Iterable[str], installed: Mapping[str, importlib.metadata.Distribution]
) -> set[str]:
    pending = list(requirements)
    resolved: set[str] = set()
    while pending:
        requirement = Requirement(pending.pop())
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        name = _normalized_name(requirement.name)
        if name in resolved:
            continue
        if name not in installed:
            raise ValueError(f"Declared runtime dependency is not installed: {requirement.name}")
        resolved.add(name)
        pending.extend(installed[name].requires or ())
    return resolved


def _normalized_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def build_sbom(project_file: Path = Path("pyproject.toml")) -> dict[str, object]:
    """Build a machine-readable inventory from actual installed metadata."""

    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "metadata": {
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "component": {"name": "StockTool", "type": "application"},
            "tools": [{"name": "scripts/generate_sbom.py", "version": "1"}],
        },
        "components": [
            {
                "type": "library",
                "name": item["name"],
                "version": item["version"],
                "licenses": [{"license": {"name": item["license"]}}],
                "externalReferences": (
                    [{"type": "website", "url": item["home_page"]}] if item["home_page"] else []
                ),
            }
            for item in distribution_records(project_file)
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project-file", type=Path, default=Path("pyproject.toml"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(build_sbom(args.project_file), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
