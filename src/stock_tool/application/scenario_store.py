"""Independent synthetic evidence storage; never reads credentials or old research libraries."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import tempfile
import uuid

import pandas as pd

from stock_tool.application.scenario_research import (
    ALGORITHM,
    ScenarioBlocked,
    canonical,
    digest,
    qualify,
    run,
)

SCHEMA = "scenario-synthetic-v1"


def profile() -> dict:
    """Bind actual modules without changing their contracts or requiring source .py files."""
    import importlib.util

    names = [
        "application.scenario_research",
        "application.scenario_store",
        "backtest.engine",
        "backtest.broker",
        "backtest.portfolio",
        "backtest.orders",
        "backtest.metrics",
        "backtest.trade_evidence",
        "data.corporate_actions",
        "data.universe",
        "strategies.base",
        "risk",
        "risk.rules",
        "data.corporate_models",
        "domain.models",
    ]
    fingerprints = {}
    for name in names:
        spec = importlib.util.find_spec("stock_tool." + name)
        if spec is None or spec.loader is None or not hasattr(spec.loader, "get_code"):
            raise ScenarioBlocked("missing compatibility module")
        # Marshal includes the interpreter's code representation; no persisted code is executed.
        import marshal

        fingerprints[name] = hashlib.sha256(
            marshal.dumps(spec.loader.get_code("stock_tool." + name))
        ).hexdigest()
    import numpy as np

    return {
        "algorithm": ALGORITHM,
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "modules": fingerprints,
    }


def save(root: Path, request: dict) -> Path:
    """New immutable run, atomic rename; computations are never supplied by a caller."""
    qualify(request)
    result = run(request)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    target = root / run_id
    temp = Path(tempfile.mkdtemp(prefix=".pending-", dir=root))
    try:
        contents = {
            "input.json": request,
            "result.json": result,
            "metadata.json": {
                "schema": SCHEMA,
                "run_id": run_id,
                "profile": profile(),
                "synthetic_only": True,
            },
        }
        hashes = {}
        for name, value in contents.items():
            raw = canonical(value)
            (temp / name).write_bytes(raw)
            hashes[name] = hashlib.sha256(raw).hexdigest()
        manifest = {"schema": SCHEMA, "files": hashes}
        manifest["package_digest"] = digest(manifest)
        (temp / "manifest.json").write_bytes(canonical(manifest))
        os.rename(temp, target)
    except BaseException:
        shutil.rmtree(temp)
        raise
    return target


def load(path: Path) -> dict:
    path = Path(path)
    names = {"input.json", "result.json", "metadata.json", "manifest.json"}
    if path.is_symlink() or {p.name for p in path.iterdir()} != names:
        raise ScenarioBlocked("unexpected or missing package files")
    if any((path / n).is_symlink() or not (path / n).is_file() for n in names):
        raise ScenarioBlocked("unsafe package path")
    if any((path / n).stat().st_size > 50_000_000 for n in names):
        raise ScenarioBlocked("package file too large")
    manifest = json.loads((path / "manifest.json").read_bytes())
    if manifest.get("schema") != SCHEMA or set(manifest.get("files", {})) != names - {
        "manifest.json"
    }:
        raise ScenarioBlocked("unknown schema or unsafe manifest")
    expected = manifest.pop("package_digest", None)
    if digest(manifest) != expected:
        raise ScenarioBlocked("package digest mismatch")
    data = {}
    for name, expected_hash in manifest["files"].items():
        raw = (path / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_hash:
            raise ScenarioBlocked("file hash mismatch: " + name)
        data[name] = json.loads(raw)
    metadata = data["metadata.json"]
    if metadata.get("schema") != SCHEMA or metadata.get("synthetic_only") is not True:
        raise ScenarioBlocked("synthetic provenance missing")
    qualify(data["input.json"])
    if (
        data["result.json"].get("formal_research") is not False
        or data["result.json"].get("qualification") != "synthetic_only"
        or data["result.json"].get("run_input_digest") != digest(data["input.json"])
    ):
        raise ScenarioBlocked("result qualification binding mismatch")
    return {
        "input": data["input.json"],
        "result": data["result.json"],
        "metadata": metadata,
        "status": "保存的合成結果；尚未重算",
    }


def difference(a, b, path="result") -> str | None:
    if type(a) is not type(b):
        return f"{path}: {a!r} != {b!r}"
    if isinstance(a, dict):
        if a.keys() != b.keys():
            return f"{path}: keys differ"
        for key in a:
            found = difference(a[key], b[key], f"{path}.{key}")
            if found:
                return found
    elif isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: length differs"
        for i, (left, right) in enumerate(zip(a, b)):
            found = difference(left, right, f"{path}[{i}]")
            if found:
                return found
    elif isinstance(a, float):
        if (
            not math.isfinite(a)
            or not math.isfinite(b)
            or not math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
        ):
            return f"{path}: {a!r} != {b!r}"
    elif a != b:
        return f"{path}: {a!r} != {b!r}"
    return None


def replay(path: Path) -> dict:
    saved = load(path)
    if saved["metadata"].get("profile") != profile():
        raise ScenarioBlocked("不相容版本：只能查看保存的合成結果，不能重算")
    actual = run(saved["input"])
    mismatch = difference(saved["result"], actual)
    if mismatch:
        raise ScenarioBlocked("REPLAY_MISMATCH " + mismatch)
    return {"status": "合成結果逐欄重放一致", "formal_research": False, "result": actual}


def copy_package(source: Path, destination_root: Path) -> Path:
    """Backup/restore to a new directory only; no archive extraction or old library mutation."""
    load(source)
    destination_root = Path(destination_root)
    destination_root.mkdir(parents=True, exist_ok=True)
    target = destination_root / load(source)["metadata"]["run_id"]
    # Validate the untrusted ID before using it as a path.
    if len(target.name) != 32 or any(c not in "0123456789abcdef" for c in target.name):
        raise ScenarioBlocked("invalid run ID")
    if target.exists() or target.parent != destination_root:
        raise ScenarioBlocked("restore cannot overwrite")
    temp = Path(tempfile.mkdtemp(prefix=".restore-", dir=destination_root))
    try:
        for item in Path(source).iterdir():
            shutil.copyfile(item, temp / item.name)
        load(temp)
        os.rename(temp, target)
    except BaseException:
        shutil.rmtree(temp)
        raise
    return target
