"""Fail-closed verifier for hash-bound StockTool acceptance evidence.

This module is deliberately read-only.  It validates raw bytes exactly as
captured; it never repairs line endings, recalculates a manifest, or accepts a
partial browser bundle as a successful acceptance session.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
TEXT_SUFFIXES = frozenset({".json", ".jsonl", ".log", ".txt", ".csv", ".sha256"})
REQUIRED_CAPTURE_NAMES = frozenset(
    {
        "home.png",
        "home.dom.txt",
        "home.console.json",
        "changes.png",
        "changes.dom.txt",
        "changes.console.json",
        "brief.png",
        "brief.dom.txt",
        "brief.console.json",
        "settings.png",
        "settings.dom.txt",
        "settings.console.json",
    }
)
REQUIRED_SUPPORTING_NAMES = frozenset(
    {"launch.json", "guard-result.json", "cleanup.json", "transport.jsonl"}
)
STRICT_SUPPORTING_NAMES = REQUIRED_SUPPORTING_NAMES | frozenset({"launch-binding.json"})
PAGE_CAPTURE_ASSERTIONS: dict[str, tuple[str, ...]] = {
    "home": ("研究首頁", "今天先看這些", "每日證據鏈研究簡報"),
    "brief": ("每日證據鏈研究簡報", "產生今日研究簡報"),
    "changes": ("今天的重點變化", "尚未有可驗證的前後研究簡報"),
    "settings": (
        "設定",
        "每日研究排程",
        "目前狀態：未安裝",
        "週一至週五 18:30（Asia/Taipei）",
    ),
}
MACRO_CAPTURE_NAMES = frozenset(
    {
        "macro.png",
        "macro.dom.txt",
        "macro.console.json",
        "macro-provider-metadata.json",
        "macro-snapshot.json",
        "macro-payload-hashes.json",
    }
)
ZOOM_CAPTURE_NAMES = frozenset(
    {
        "zoom_100.png",
        "zoom_100.dom.txt",
        "zoom_100.console.json",
        "zoom_125.png",
        "zoom_125.dom.txt",
        "zoom_125.console.json",
        "zoom_150.png",
        "zoom_150.dom.txt",
        "zoom_150.console.json",
        "zoom-metadata.json",
    }
)
KEYBOARD_CAPTURE_NAMES = frozenset(
    {
        "keyboard_initial.png",
        "keyboard_initial.dom.txt",
        "keyboard_initial.console.json",
        "keyboard_opened.png",
        "keyboard_opened.dom.txt",
        "keyboard_opened.console.json",
        "keyboard_changed.png",
        "keyboard_changed.dom.txt",
        "keyboard_changed.console.json",
        "keyboard-navigation-trace.json",
    }
)
REQUIRED_ROOT_FILES = frozenset(
    {
        "browser-result.json",
        "candidate-hash-binding.json",
        "real-data-before.json",
        "real-data-after.json",
        "real-data-current.json",
        "real-data-diff.json",
        "task-scheduler-before.json",
        "task-scheduler-after.json",
        "task-scheduler-diff.json",
        "evidence-hash-index.json",
        "evidence-hash-index.sha256",
        "capture-session-manifest.json",
    }
)
ROLE_NAMES = ("stable", "payload", "source_zip", "formal")
# The verifier owns this role contract.  A bundle may report hashes and paths,
# but it can never choose which workspace files those roles refer to.
DEFAULT_ROLE_RELATIVE_PATHS = {
    "stable": "release/staging-sprint28.1.1/StockTool/StockTool.exe",
    "payload": "release/staging-sprint28.1.1/StockTool/versions/1.2.2/StockToolPayload.exe",
    "source_zip": "release/staging-sprint28.1.1-source.zip",
    "formal": "release/StockTool/StockTool.exe",
}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be exactly 64 hexadecimal characters")
    return value.upper()


def _require_size(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _utc(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} timestamp is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} timestamp lacks timezone")
    return parsed


def _safe_relative(root: Path, value: object, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} relative path is missing")
    # Evidence paths are canonical POSIX-relative names.  Rejecting aliases
    # before resolution prevents two descriptors from naming one file through
    # different spellings (./, backslashes, or traversal components).
    if "\\" in value:
        raise ValueError(f"{field} path must use canonical forward slashes")
    candidate = Path(value)
    if (
        candidate.is_absolute()
        or candidate.as_posix() != value
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ValueError(f"{field} path traversal is forbidden")
    resolved = (root / candidate).resolve()
    root_resolved = root.resolve()
    if root_resolved not in resolved.parents:
        raise ValueError(f"{field} path escapes evidence root")
    return resolved


def _json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> Any:
    raw = path.read_bytes()
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        raise ValueError(f"UTF-8 BOM is forbidden: {path.name}")
    if b"\r" in raw:
        raise ValueError(f"CRLF/raw-byte normalization mismatch: {path.name}")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_json_pairs)
    except UnicodeDecodeError as exc:
        raise ValueError(f"strict UTF-8 is required: {path.name}") from exc


def _read_text_strict(path: Path) -> bytes:
    raw = path.read_bytes()
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")) or b"\r" in raw:
        raise ValueError(f"UTF-8 raw-byte mismatch: {path.name}")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"strict UTF-8 is required: {path.name}") from exc
    return raw


def _verify_descriptor(
    root: Path,
    name: str,
    value: object,
    *,
    launch_time: datetime | None = None,
    cleanup_time: datetime | None = None,
    require_capture_time: bool = False,
) -> tuple[Path, dict[str, Any]]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} descriptor is invalid")
    path = _safe_relative(root, value.get("path"), name)
    expected_size = _require_size(value.get("size_bytes"), f"{name}.size_bytes")
    expected_hash = _require_sha256(value.get("sha256"), f"{name}.sha256")
    if not path.is_file():
        raise ValueError(f"{name} is missing")
    if path.stat().st_size != expected_size or sha256_file(path) != expected_hash:
        raise ValueError(f"{name} raw bytes do not match descriptor")
    if path.suffix.lower() in TEXT_SUFFIXES:
        raw = _read_text_strict(path)
        if path.suffix.lower() == ".json":
            json.loads(raw.decode("utf-8"), object_pairs_hook=_json_pairs)
    if require_capture_time:
        captured = _utc(value.get("captured_utc"), f"{name}.captured_utc")
        if (
            launch_time is None
            or cleanup_time is None
            or not (launch_time <= captured <= cleanup_time)
        ):
            raise ValueError(f"{name} was captured outside launch-to-cleanup session")
    return path, value


def _png_dimensions(raw: bytes, field: str) -> tuple[int, int]:
    """Read PNG dimensions from the raw IHDR chunk without normalizing bytes."""

    if len(raw) < 24 or not raw.startswith(PNG_SIGNATURE) or raw[12:16] != b"IHDR":
        raise ValueError(f"{field} is not a PNG with an IHDR chunk")
    width = int.from_bytes(raw[16:20], "big")
    height = int.from_bytes(raw[20:24], "big")
    if width <= 0 or height <= 0:
        raise ValueError(f"{field} PNG dimensions are invalid")
    return width, height


def _verify_page_capture_contract(
    bundle_root: Path,
    captures: Mapping[str, Any],
    *,
    page_contract: object,
) -> None:
    """Verify four distinct page captures and their page-specific semantics."""

    if not isinstance(page_contract, dict) or page_contract.get("schema_version") != 1:
        raise ValueError("page capture contract is invalid")
    if set(page_contract.get("scenes", {})) != set(PAGE_CAPTURE_ASSERTIONS):
        raise ValueError("page capture scenes are incomplete")

    raw_hashes: dict[str, str] = {}
    dimensions: set[tuple[int, int]] = set()
    for scene, assertions in PAGE_CAPTURE_ASSERTIONS.items():
        scene_meta = page_contract["scenes"].get(scene)
        if not isinstance(scene_meta, dict) or scene_meta.get("capture_prefix") != scene:
            raise ValueError(f"{scene} page capture metadata is invalid")
        expected_assertions = list(assertions)
        if scene_meta.get("semantic_assertions") != expected_assertions:
            raise ValueError(f"{scene} semantic assertions are invalid")
        dom_name = f"{scene}.dom.txt"
        png_name = f"{scene}.png"
        console_name = f"{scene}.console.json"
        descriptor = captures.get(dom_name)
        if not isinstance(descriptor, dict) or descriptor.get("scene") != scene:
            raise ValueError(f"{scene} DOM descriptor is not scene-bound")
        if descriptor.get("semantic_assertions") != expected_assertions:
            raise ValueError(f"{scene} DOM descriptor assertions are invalid")
        dom_path = (bundle_root / dom_name).resolve()
        dom_raw = _read_text_strict(dom_path)
        dom_text = dom_raw.decode("utf-8")
        for assertion in assertions:
            if assertion not in dom_text:
                raise ValueError(f"{scene} DOM lacks semantic assertion: {assertion}")
        png_path = (bundle_root / png_name).resolve()
        png_raw = png_path.read_bytes()
        dimensions.add(_png_dimensions(png_raw, png_name))
        console_path = (bundle_root / console_name).resolve()
        console = _load_json(console_path)
        if not isinstance(console, dict) or console.get("scene") != scene:
            raise ValueError(f"{scene} console descriptor is not scene-bound")
        if console.get("errors") != []:
            raise ValueError(f"{scene} active console contains errors")
        for name, raw in (
            (png_name, png_raw),
            (dom_name, dom_raw),
            (console_name, console_path.read_bytes()),
        ):
            digest = hashlib.sha256(raw).hexdigest()
            if digest in raw_hashes.values():
                prior = next(key for key, value in raw_hashes.items() if value == digest)
                raise ValueError(f"page captures reuse identical raw bytes: {prior} and {name}")
            raw_hashes[name] = digest
    if len(dimensions) != 1:
        raise ValueError("page capture PNG dimensions are inconsistent")


def _verify_launch_binding(
    bundle_root: Path,
    binding_path: Path,
    *,
    session_id: str,
    launch_time: datetime,
    cleanup_time: datetime,
    candidate_hashes: Mapping[str, str],
    trusted_stable: Path,
) -> None:
    payload = _load_json(binding_path)
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("launch binding schema is invalid")
    if payload.get("session_id") != session_id:
        raise ValueError("launch binding session mismatch")
    absolute_path = payload.get("candidate_absolute_path")
    if not isinstance(absolute_path, str) or not absolute_path.strip():
        raise ValueError("launch binding candidate path is missing")
    if Path(absolute_path).resolve() != trusted_stable:
        raise ValueError("launch binding candidate path is not trusted")
    if (
        _require_sha256(payload.get("candidate_sha256"), "launch binding candidate_sha256")
        != candidate_hashes["stable"]
    ):
        raise ValueError("launch binding candidate hash mismatch")
    pid = payload.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ValueError("launch binding pid is invalid")
    process_tree = payload.get("process_tree")
    if not isinstance(process_tree, list) or not process_tree:
        raise ValueError("launch binding process tree is missing")
    if not isinstance(payload.get("health_endpoint"), str) or not payload[
        "health_endpoint"
    ].startswith("http://127.0.0.1:"):
        raise ValueError("launch binding health endpoint is invalid")
    listener = payload.get("listener")
    if not isinstance(listener, int) or listener not in {8501, 8502}:
        raise ValueError("launch binding listener is invalid")
    isolated_root = payload.get("isolated_data_root")
    if not isinstance(isolated_root, str) or not isolated_root.strip():
        raise ValueError("launch binding isolated root is missing")
    if (
        Path(isolated_root).resolve()
        == Path(os.environ.get("LOCALAPPDATA", "")).joinpath("StockTool").resolve()
    ):
        raise ValueError("launch binding uses the real user-data root")
    started = _utc(payload.get("launch_started_utc"), "launch binding launch_started_utc")
    completed = _utc(payload.get("cleanup_completed_utc"), "launch binding cleanup_completed_utc")
    if started != launch_time or completed != cleanup_time or completed < started:
        raise ValueError("launch binding time window is invalid")


def _trusted_candidate_paths(
    workspace_root: Path,
    candidate_paths: Mapping[str, str | Path] | None,
) -> dict[str, Path]:
    """Resolve the external candidate role contract, never the bundle claim."""

    # The default role mapping is intentionally fixed for callers that do not
    # provide an external contract.  A correction/staging candidate may use a
    # different release directory, but only when every role path is supplied by
    # the trusted verifier caller (never by the evidence bundle itself).
    externally_supplied = candidate_paths is not None
    role_mapping = candidate_paths or DEFAULT_ROLE_RELATIVE_PATHS
    if set(role_mapping) != set(ROLE_NAMES):
        raise ValueError("trusted candidate role contract is incomplete")
    workspace = workspace_root.resolve()
    trusted: dict[str, Path] = {}
    for role in ROLE_NAMES:
        supplied = Path(role_mapping[role])
        physical = (workspace / supplied) if not supplied.is_absolute() else supplied
        resolved = physical.resolve()
        if workspace not in resolved.parents or not resolved.is_file():
            raise ValueError(f"trusted candidate {role} is unavailable")
        relative = resolved.relative_to(workspace)
        parts = relative.parts
        if role == "formal" and relative != Path("release/StockTool/StockTool.exe"):
            raise ValueError("trusted candidate formal path is not approved")
        if role == "stable" and (
            len(parts) < 3
            or parts[0] != "release"
            or parts[-2] != "StockTool"
            or parts[-1] != "StockTool.exe"
            or relative == Path("release/StockTool/StockTool.exe")
        ):
            raise ValueError("trusted candidate stable path is not approved")
        if role == "payload" and (
            len(parts) < 5
            or parts[0] != "release"
            or parts[-4] != "StockTool"
            or parts[-3] != "versions"
            or parts[-1] != "StockToolPayload.exe"
        ):
            raise ValueError("trusted candidate payload path is not approved")
        if role == "source_zip" and (
            len(parts) != 2 or parts[0] != "release" or not parts[1].endswith("-source.zip")
        ):
            raise ValueError("trusted candidate source ZIP path is not approved")
        if not externally_supplied:
            expected = (workspace / DEFAULT_ROLE_RELATIVE_PATHS[role]).resolve()
            if resolved != expected:
                raise ValueError(f"trusted candidate {role} path is not approved")
        trusted[role] = resolved
    return trusted


def _verify_candidate_binding(
    bundle_root: Path,
    workspace_root: Path,
    candidate_paths: Mapping[str, str | Path] | None,
) -> dict[str, str]:
    path = bundle_root / "candidate-hash-binding.json"
    payload = _load_json(path)
    if not isinstance(payload, dict) or payload.get("schema_version") != 2:
        raise ValueError("candidate binding schema is invalid")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {
        "stable",
        "payload",
        "source_zip",
        "formal",
    }:
        raise ValueError("candidate binding artifacts are incomplete")
    hashes: dict[str, str] = {}
    trusted = _trusted_candidate_paths(workspace_root, candidate_paths)
    for name in ROLE_NAMES:
        item = artifacts[name]
        if not isinstance(item, dict):
            raise ValueError(f"candidate binding {name} is invalid")
        rel = item.get("workspace_relative_path")
        if not isinstance(rel, str) or not rel.strip():
            raise ValueError(f"candidate binding {name} path is invalid")
        candidate = Path(rel)
        if (
            candidate.is_absolute()
            or "\\" in rel
            or candidate.as_posix() != rel
            or any(part in {"", ".", ".."} for part in candidate.parts)
        ):
            raise ValueError(f"candidate binding {name} path escapes workspace")
        physical = (workspace_root / candidate).resolve()
        if physical != trusted[name]:
            raise ValueError(f"candidate binding {name} path is not the trusted role target")
        expected_hash = _require_sha256(item.get("expected_sha256"), f"{name}.expected_sha256")
        expected_size = _require_size(
            item.get("expected_size_bytes"), f"{name}.expected_size_bytes"
        )
        actual_hash = sha256_file(physical)
        actual_size = physical.stat().st_size
        if actual_hash != expected_hash or actual_size != expected_size:
            raise ValueError(f"candidate binding {name} exact size/hash mismatch")
        hashes[name] = expected_hash
    return hashes


def _verify_real_data(bundle_root: Path) -> None:
    before = _load_json(bundle_root / "real-data-before.json")
    after = _load_json(bundle_root / "real-data-after.json")
    current = _load_json(bundle_root / "real-data-current.json")
    diff = _load_json(bundle_root / "real-data-diff.json")
    if not all(isinstance(value, dict) for value in (before, after, current, diff)):
        raise ValueError("real-data manifests are invalid")
    if diff.get("zero_diff") is not True or any(
        diff.get(key) != [] for key in ("added", "removed", "changed")
    ):
        raise ValueError("real user-data manifest is not zero-diff")
    for key in ("file_count", "files"):
        if before.get(key) != after.get(key) or before.get(key) != current.get(key):
            raise ValueError("real-data before/after/current mismatch")


def _verify_task_state(bundle_root: Path) -> None:
    before = _load_json(bundle_root / "task-scheduler-before.json")
    after = _load_json(bundle_root / "task-scheduler-after.json")
    diff = _load_json(bundle_root / "task-scheduler-diff.json")
    if not all(isinstance(value, dict) for value in (before, after, diff)):
        raise ValueError("task scheduler manifests are invalid")
    if (
        before.get("production_task_status") != "absent"
        or after.get("production_task_status") != "absent"
    ):
        raise ValueError("production task is present or unverified")
    if diff.get("zero_diff") is not True or any(
        diff.get(key) != [] for key in ("added", "removed", "changed")
    ):
        raise ValueError("task scheduler state is not zero-diff")


def _verify_macro_scenario(
    bundle_root: Path,
    scenario: object,
    *,
    session_id: str,
    launch_time: datetime,
    cleanup_time: datetime,
    manifest_captures: Mapping[str, Any],
) -> None:
    """Verify one same-session, six-series official FRED evidence scenario."""

    if not isinstance(scenario, dict):
        raise ValueError("macro scenario is invalid")
    if scenario.get("status") != "passed" or scenario.get("coverage") != 6:
        raise ValueError("macro scenario must be passed with coverage 6")
    if scenario.get("snapshot_status") != "ready" or scenario.get("source") != "FRED official":
        raise ValueError("macro scenario source/status is invalid")
    if scenario.get("session_id") != session_id or scenario.get("same_session") is not True:
        raise ValueError("macro scenario session mismatch")
    descriptors = scenario.get("captures")
    if not isinstance(descriptors, dict) or set(descriptors) != {
        "screenshot",
        "dom",
        "console",
        "provider_metadata",
        "snapshot",
        "payload_hashes",
    }:
        raise ValueError("macro scenario capture descriptors are incomplete")
    expected_names = {
        "screenshot": "macro.png",
        "dom": "macro.dom.txt",
        "console": "macro.console.json",
        "provider_metadata": "macro-provider-metadata.json",
        "snapshot": "macro-snapshot.json",
        "payload_hashes": "macro-payload-hashes.json",
    }
    paths: dict[str, Path] = {}
    for key, expected_name in expected_names.items():
        path, descriptor = _verify_descriptor(
            bundle_root,
            f"macro.{key}",
            descriptors[key],
            launch_time=launch_time,
            cleanup_time=cleanup_time,
            require_capture_time=True,
        )
        if path != (bundle_root / expected_name).resolve():
            raise ValueError(f"macro.{key} path is not canonical")
        manifest_descriptor = manifest_captures.get(expected_name)
        if not isinstance(manifest_descriptor, dict) or any(
            descriptor.get(field) != manifest_descriptor.get(field)
            for field in ("path", "size_bytes", "sha256", "captured_utc")
        ):
            raise ValueError(f"macro.{key} descriptor is not manifest-bound")
        paths[key] = path
        if descriptor.get("session_id") not in (None, session_id):
            raise ValueError(f"macro.{key} session mismatch")
    screenshot = paths["screenshot"].read_bytes()
    if len(screenshot) < 100 or not screenshot.startswith((PNG_SIGNATURE, JPEG_SIGNATURE)):
        raise ValueError("macro screenshot is invalid")
    if "StockTool" not in paths["dom"].read_text(encoding="utf-8"):
        raise ValueError("macro DOM lacks StockTool content")
    console = _load_json(paths["console"])
    if not isinstance(console, dict) or console.get("errors") != []:
        raise ValueError("macro active console contains errors")
    metadata = _load_json(paths["provider_metadata"])
    if not isinstance(metadata, dict) or metadata.get("coverage") != 6:
        raise ValueError("macro provider metadata coverage is invalid")
    if metadata.get("source") != "FRED official" or metadata.get("status") != "ready":
        raise ValueError("macro provider metadata source/status is invalid")
    payload_hashes = _load_json(paths["payload_hashes"])
    if not isinstance(payload_hashes, dict):
        raise ValueError("macro payload hashes are invalid")
    try:
        from stock_tool.application.macro_snapshot import FRED_SERIES, MacroSnapshot
    except ImportError as exc:
        raise ValueError("macro snapshot verifier dependencies are unavailable") from exc
    required_series = {item[0] for item in FRED_SERIES.values()}
    series_hashes = payload_hashes.get("series")
    if not isinstance(series_hashes, dict) or set(series_hashes) != required_series:
        raise ValueError("macro payload hash series are incomplete")
    for series_id, value in series_hashes.items():
        digest = _require_sha256(value, f"macro payload {series_id}")
        if digest == "0" * 64:
            raise ValueError("macro provider payload hash is zero")
    try:
        expected_series = set(FRED_SERIES)
        expected_raw = {item[0] for item in FRED_SERIES.values()}
        snapshot_payload = _load_json(paths["snapshot"])
        snapshot = MacroSnapshot.from_dict(snapshot_payload)
    except (ImportError, ValueError, TypeError, KeyError) as exc:
        raise ValueError("macro snapshot cannot be validated") from exc
    if snapshot.status != "ready" or snapshot.source != "FRED official":
        raise ValueError("macro snapshot status/source is invalid")
    if {item.series_id for item in snapshot.observations} != expected_series:
        raise ValueError("macro snapshot required series are incomplete")
    if {item.series_id for item in snapshot.references} != expected_raw:
        raise ValueError("macro snapshot references are incomplete")
    snapshot_hashes = {
        reference.series_id: reference.payload_sha256.upper() for reference in snapshot.references
    }
    if snapshot_hashes != {
        key: _require_sha256(value, f"macro payload {key}") for key, value in series_hashes.items()
    }:
        raise ValueError("macro snapshot/provider payload hashes disagree")
    if scenario.get("snapshot_record_sha256") != snapshot.record_sha256:
        raise ValueError("macro snapshot record hash mismatch")


def _verify_zoom_scenario(
    bundle_root: Path,
    scenario: object,
    *,
    session_id: str,
    launch_time: datetime,
    cleanup_time: datetime,
    manifest_captures: Mapping[str, Any],
) -> None:
    """Verify same-session native Chrome 100%, 125%, 150% zoom evidence."""

    if not isinstance(scenario, dict):
        raise ValueError("zoom scenario is invalid")
    if scenario.get("status") != "passed" or scenario.get("zoom_levels") != [
        "100%",
        "125%",
        "150%",
    ]:
        raise ValueError("zoom scenario must be passed with levels [100%, 125%, 150%]")
    if scenario.get("session_id") != session_id or scenario.get("same_session") is not True:
        raise ValueError("zoom scenario session mismatch")

    expected_files = {
        "zoom_100_png": "zoom_100.png",
        "zoom_100_dom": "zoom_100.dom.txt",
        "zoom_100_console": "zoom_100.console.json",
        "zoom_125_png": "zoom_125.png",
        "zoom_125_dom": "zoom_125.dom.txt",
        "zoom_125_console": "zoom_125.console.json",
        "zoom_150_png": "zoom_150.png",
        "zoom_150_dom": "zoom_150.dom.txt",
        "zoom_150_console": "zoom_150.console.json",
        "metadata": "zoom-metadata.json",
    }

    descriptors = scenario.get("captures")
    if not isinstance(descriptors, dict) or set(descriptors) != set(expected_files):
        raise ValueError("zoom scenario capture descriptors are incomplete")

    paths: dict[str, Path] = {}
    for key, expected_name in expected_files.items():
        path, descriptor = _verify_descriptor(
            bundle_root,
            f"zoom.{key}",
            descriptors[key],
            launch_time=launch_time,
            cleanup_time=cleanup_time,
            require_capture_time=True,
        )
        if path != (bundle_root / expected_name).resolve():
            raise ValueError(f"zoom.{key} path is not canonical")
        manifest_descriptor = manifest_captures.get(expected_name)
        if not isinstance(manifest_descriptor, dict) or any(
            descriptor.get(field) != manifest_descriptor.get(field)
            for field in ("path", "size_bytes", "sha256", "captured_utc")
        ):
            raise ValueError(f"zoom.{key} descriptor is not manifest-bound")
        paths[key] = path
        if descriptor.get("session_id") not in (None, session_id):
            raise ValueError(f"zoom.{key} session mismatch")

    for p_key in ("zoom_100_png", "zoom_125_png", "zoom_150_png"):
        raw_png = paths[p_key].read_bytes()
        if len(raw_png) < 100 or not raw_png.startswith((PNG_SIGNATURE, JPEG_SIGNATURE)):
            raise ValueError(f"zoom {p_key} screenshot is invalid")

    for d_key in ("zoom_100_dom", "zoom_125_dom", "zoom_150_dom"):
        dom_text = paths[d_key].read_text(encoding="utf-8")
        if "StockTool" not in dom_text:
            raise ValueError(f"zoom {d_key} lacks StockTool content")

    for c_key in ("zoom_100_console", "zoom_125_console", "zoom_150_console"):
        console = _load_json(paths[c_key])
        if not isinstance(console, dict) or console.get("errors") != []:
            raise ValueError(f"zoom {c_key} contains active errors")

    metadata = _load_json(paths["metadata"])
    if not isinstance(metadata, dict) or metadata.get("schema_version") != 2:
        raise ValueError("zoom metadata schema is invalid")
    if metadata.get("session_id") != session_id:
        raise ValueError("zoom metadata session mismatch")
    zooms = metadata.get("zooms")
    if not isinstance(zooms, dict) or set(zooms) != {"100%", "125%", "150%"}:
        raise ValueError("zoom metadata levels are incomplete")

    expected_dpr = {"100%": 1.0, "125%": 1.25, "150%": 1.5}
    physical_widths = set()
    physical_heights = set()
    for level, data in zooms.items():
        if not isinstance(data, dict):
            raise ValueError(f"zoom {level} data is invalid")
        dpr = data.get("devicePixelRatio")
        if not isinstance(dpr, (int, float)):
            raise ValueError(f"zoom {level} devicePixelRatio is invalid")
        if abs(float(dpr) - expected_dpr[level]) > 0.01:
            raise ValueError(
                f"zoom {level} devicePixelRatio {dpr} != expected {expected_dpr[level]}"
            )
        p_w = data.get("physical_viewport_width")
        p_h = data.get("physical_viewport_height")
        if (
            not isinstance(p_w, (int, float))
            or not isinstance(p_h, (int, float))
            or p_w <= 0
            or p_h <= 0
        ):
            raise ValueError(f"zoom {level} physical dimensions are invalid")
        physical_widths.add(p_w)
        physical_heights.add(p_h)

    if len(physical_widths) != 1 or len(physical_heights) != 1:
        raise ValueError("physical viewport dimensions vary across zoom levels")


def _verify_keyboard_scenario(
    bundle_root: Path,
    scenario: object,
    *,
    session_id: str,
    launch_time: datetime,
    cleanup_time: datetime,
    manifest_captures: Mapping[str, Any],
) -> None:
    """Verify same-session keyboard accessibility, focus trace, and DOM value change."""

    if not isinstance(scenario, dict):
        raise ValueError("keyboard scenario is invalid")
    if scenario.get("status") != "passed" or scenario.get("value_changed") is not True:
        raise ValueError("keyboard scenario must be passed with value_changed=True")
    if scenario.get("session_id") != session_id or scenario.get("same_session") is not True:
        raise ValueError("keyboard scenario session mismatch")

    expected_files = {
        "keyboard_initial_png": "keyboard_initial.png",
        "keyboard_initial_dom": "keyboard_initial.dom.txt",
        "keyboard_initial_console": "keyboard_initial.console.json",
        "keyboard_opened_png": "keyboard_opened.png",
        "keyboard_opened_dom": "keyboard_opened.dom.txt",
        "keyboard_opened_console": "keyboard_opened.console.json",
        "keyboard_changed_png": "keyboard_changed.png",
        "keyboard_changed_dom": "keyboard_changed.dom.txt",
        "keyboard_changed_console": "keyboard_changed.console.json",
        "trace": "keyboard-navigation-trace.json",
    }

    descriptors = scenario.get("captures")
    if not isinstance(descriptors, dict) or set(descriptors) != set(expected_files):
        raise ValueError("keyboard scenario capture descriptors are incomplete")

    paths: dict[str, Path] = {}
    for key, expected_name in expected_files.items():
        path, descriptor = _verify_descriptor(
            bundle_root,
            f"keyboard.{key}",
            descriptors[key],
            launch_time=launch_time,
            cleanup_time=cleanup_time,
            require_capture_time=True,
        )
        if path != (bundle_root / expected_name).resolve():
            raise ValueError(f"keyboard.{key} path is not canonical")
        manifest_descriptor = manifest_captures.get(expected_name)
        if not isinstance(manifest_descriptor, dict) or any(
            descriptor.get(field) != manifest_descriptor.get(field)
            for field in ("path", "size_bytes", "sha256", "captured_utc")
        ):
            raise ValueError(f"keyboard.{key} descriptor is not manifest-bound")
        paths[key] = path
        if descriptor.get("session_id") not in (None, session_id):
            raise ValueError(f"keyboard.{key} session mismatch")

    for p_key in ("keyboard_initial_png", "keyboard_opened_png", "keyboard_changed_png"):
        raw_png = paths[p_key].read_bytes()
        if len(raw_png) < 100 or not raw_png.startswith((PNG_SIGNATURE, JPEG_SIGNATURE)):
            raise ValueError(f"keyboard {p_key} screenshot is invalid")

    for c_key in (
        "keyboard_initial_console",
        "keyboard_opened_console",
        "keyboard_changed_console",
    ):
        console = _load_json(paths[c_key])
        if not isinstance(console, dict) or console.get("errors") != []:
            raise ValueError(f"keyboard {c_key} contains active errors")

    initial_dom = paths["keyboard_initial_dom"].read_text(encoding="utf-8")
    changed_dom = paths["keyboard_changed_dom"].read_text(encoding="utf-8")
    if "StockTool" not in initial_dom or "StockTool" not in changed_dom:
        raise ValueError("keyboard DOM lacks StockTool content")

    trace = _load_json(paths["trace"])
    if not isinstance(trace, dict) or trace.get("schema_version") != 2:
        raise ValueError("keyboard navigation trace schema is invalid")
    if trace.get("session_id") != session_id:
        raise ValueError("keyboard trace session mismatch")

    initial_val = trace.get("initial_value")
    changed_val = trace.get("changed_value")
    if (
        not isinstance(initial_val, str)
        or not isinstance(changed_val, str)
        or not initial_val
        or not changed_val
    ):
        raise ValueError("keyboard trace initial/changed values are missing")
    if initial_val == changed_val:
        raise ValueError("keyboard trace initial and changed values are identical")
    if initial_val not in initial_dom:
        raise ValueError(f"initial value '{initial_val}' not found in initial DOM")
    if changed_val not in changed_dom:
        raise ValueError(f"changed value '{changed_val}' not found in changed DOM")
    if initial_dom == changed_dom:
        raise ValueError("initial and changed DOM are identical; no value change proved")

    steps = trace.get("steps")
    if not isinstance(steps, list) or len(steps) < 5:
        raise ValueError("keyboard navigation trace steps are incomplete")

    actions = [s.get("action") for s in steps if isinstance(s, dict)]
    if not any("tab" in str(a).lower() for a in actions):
        raise ValueError("keyboard navigation trace missing Tab actions")
    if not any(
        "open" in str(a).lower() or "enter" in str(a).lower() or "space" in str(a).lower()
        for a in actions
    ):
        raise ValueError("keyboard navigation trace missing Open action")
    if not any(
        "arrow" in str(a).lower() or "down" in str(a).lower() or "up" in str(a).lower()
        for a in actions
    ):
        raise ValueError("keyboard navigation trace missing Arrow navigation action")
    if not any("select" in str(a).lower() or "enter" in str(a).lower() for a in actions):
        raise ValueError("keyboard navigation trace missing Select action")


def _verify_index(bundle_root: Path) -> None:
    index_path = bundle_root / "evidence-hash-index.json"
    index = _load_json(index_path)
    if not isinstance(index, dict) or index.get("schema_version") != 2:
        raise ValueError("evidence index schema is invalid")
    exclusions = index.get("scope_exclusions")
    if exclusions != ["evidence-hash-index.json", "evidence-hash-index.sha256"]:
        raise ValueError("evidence index self-reference policy is invalid")
    raw_entries = index.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("evidence index entries are invalid")
    expected: dict[str, tuple[int, str]] = {}
    for value in raw_entries:
        if not isinstance(value, dict):
            raise ValueError("evidence index entry is invalid")
        relative = value.get("path")
        if not isinstance(relative, str) or not relative.strip() or relative in expected:
            raise ValueError("evidence index contains duplicate/invalid path")
        path = _safe_relative(bundle_root, relative, "evidence index")
        if path in {index_path.resolve(), (bundle_root / "evidence-hash-index.sha256").resolve()}:
            raise ValueError("evidence index must not reference itself or sidecar")
        expected[relative] = (
            _require_size(value.get("size_bytes"), "evidence index size"),
            _require_sha256(value.get("sha256"), "evidence index hash"),
        )
    actual = {
        path.relative_to(bundle_root).as_posix(): path
        for path in bundle_root.rglob("*")
        if path.is_file()
        and path.name not in {"evidence-hash-index.json", "evidence-hash-index.sha256"}
    }
    if set(expected) != set(actual):
        raise ValueError("evidence index has missing, extra, or stale entries")
    for relative, path in actual.items():
        size, digest = expected[relative]
        if path.stat().st_size != size or sha256_file(path) != digest:
            raise ValueError(f"evidence index raw-byte mismatch: {relative}")
    sidecar = _read_text_strict(bundle_root / "evidence-hash-index.sha256").decode("utf-8").strip()
    if sidecar != sha256_file(index_path):
        raise ValueError("evidence index sidecar mismatch")


def verify_evidence_bundle(
    root: str | Path,
    *,
    workspace_root: str | Path | None = None,
    candidate_paths: Mapping[str, str | Path] | None = None,
) -> dict[str, Any]:
    """Validate a complete immutable browser/evidence bundle without writes."""

    evidence_root = Path(root).resolve()
    workspace = (
        Path(workspace_root).resolve() if workspace_root is not None else Path.cwd().resolve()
    )
    errors: list[str] = []
    checked: list[str] = []
    try:
        if not evidence_root.is_dir():
            raise ValueError("evidence root is unavailable")
        missing_root = [
            name for name in REQUIRED_ROOT_FILES if not (evidence_root / name).is_file()
        ]
        if missing_root:
            raise ValueError(
                f"required root evidence is missing: {', '.join(sorted(missing_root))}"
            )
        manifest_path = evidence_root / "capture-session-manifest.json"
        manifest = _load_json(manifest_path)
        if not isinstance(manifest, dict) or manifest.get("schema_version") not in {2, 3}:
            raise ValueError("capture manifest schema is invalid")
        strict_page_contract = manifest.get("schema_version") == 3
        session_id = manifest.get("session_id")
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("capture manifest session_id is invalid")
        launch_time = _utc(manifest.get("launch_started_utc"), "launch")
        cleanup_time = _utc(manifest.get("cleanup_completed_utc"), "cleanup")
        if cleanup_time < launch_time:
            raise ValueError("cleanup precedes launch")
        captures = manifest.get("captures")
        supporting = manifest.get("supporting_files")
        if not isinstance(captures, dict) or not isinstance(supporting, dict):
            raise ValueError("capture manifest sections are invalid")
        browser_hint = _load_json(evidence_root / "browser-result.json")
        macro_enabled = (
            isinstance(browser_hint, dict)
            and isinstance(browser_hint.get("scenarios"), dict)
            and "macro_online" in browser_hint["scenarios"]
        )
        zoom_enabled = (
            isinstance(browser_hint, dict)
            and isinstance(browser_hint.get("scenarios"), dict)
            and (
                "zoom" in browser_hint["scenarios"]
                or "zoom_100_125_150" in browser_hint["scenarios"]
            )
        )
        keyboard_enabled = (
            isinstance(browser_hint, dict)
            and isinstance(browser_hint.get("scenarios"), dict)
            and (
                "keyboard" in browser_hint["scenarios"]
                or "keyboard_navigation" in browser_hint["scenarios"]
            )
        )
        expected_capture_names = (
            REQUIRED_CAPTURE_NAMES
            | (MACRO_CAPTURE_NAMES if macro_enabled else frozenset())
            | (ZOOM_CAPTURE_NAMES if zoom_enabled else frozenset())
            | (KEYBOARD_CAPTURE_NAMES if keyboard_enabled else frozenset())
        )
        if set(captures) != expected_capture_names:
            raise ValueError("capture descriptor keys do not exactly match the contract")
        expected_supporting_names = (
            STRICT_SUPPORTING_NAMES if strict_page_contract else REQUIRED_SUPPORTING_NAMES
        )
        if set(supporting) != expected_supporting_names:
            raise ValueError("supporting descriptor keys do not exactly match the contract")
        seen_physical: dict[str, str] = {}
        descriptor_paths: set[str] = set()
        page_capture_hashes: dict[str, str] = {}
        for name, descriptor in captures.items():
            capture_path, _ = _verify_descriptor(
                evidence_root,
                name,
                descriptor,
                launch_time=launch_time,
                cleanup_time=cleanup_time,
                require_capture_time=True,
            )
            relative = capture_path.relative_to(evidence_root).as_posix()
            if relative != name:
                raise ValueError(f"{name} must use its canonical bundle path")
            identity = os.path.normcase(str(capture_path.resolve()))
            if identity in seen_physical:
                raise ValueError(f"capture descriptors alias {seen_physical[identity]} and {name}")
            seen_physical[identity] = name
            descriptor_paths.add(relative)
            if name.endswith(".png"):
                raw_screenshot = capture_path.read_bytes()
                if capture_path.stat().st_size < 100 or not raw_screenshot.startswith(
                    (PNG_SIGNATURE, JPEG_SIGNATURE)
                ):
                    raise ValueError(f"{name} is not a non-empty raw browser screenshot")
            elif name.endswith(".dom.txt"):
                if "StockTool" not in capture_path.read_text(encoding="utf-8"):
                    raise ValueError(f"{name} does not contain rendered StockTool content")
            elif name.endswith(".console.json"):
                console = _load_json(capture_path)
                if not isinstance(console, dict) or console.get("errors") != []:
                    raise ValueError(f"{name} contains active browser errors")
            if strict_page_contract and name.split(".", 1)[0] in PAGE_CAPTURE_ASSERTIONS:
                raw_hash = hashlib.sha256(capture_path.read_bytes()).hexdigest()
                if raw_hash in page_capture_hashes.values():
                    prior = next(
                        key for key, value in page_capture_hashes.items() if value == raw_hash
                    )
                    raise ValueError(f"page captures reuse identical raw bytes: {prior} and {name}")
                page_capture_hashes[name] = raw_hash
            checked.append(name)
        for name, descriptor in supporting.items():
            supporting_path, _ = _verify_descriptor(evidence_root, name, descriptor)
            relative = supporting_path.relative_to(evidence_root).as_posix()
            if relative != name:
                raise ValueError(f"{name} must use its canonical bundle path")
            identity = os.path.normcase(str(supporting_path.resolve()))
            if identity in seen_physical:
                raise ValueError(
                    f"supporting descriptor aliases {seen_physical[identity]} and {name}"
                )
            seen_physical[identity] = name
            descriptor_paths.add(relative)
            checked.append(name)
        allowed_files = set(REQUIRED_ROOT_FILES) | descriptor_paths
        actual_files = {
            path.relative_to(evidence_root).as_posix()
            for path in evidence_root.rglob("*")
            if path.is_file()
        }
        if actual_files != allowed_files:
            raise ValueError("evidence bundle contains files outside the strict allowlist")
        guard_path, _ = _verify_descriptor(
            evidence_root, "guard-result.json", supporting["guard-result.json"]
        )
        cleanup_path, _ = _verify_descriptor(
            evidence_root, "cleanup.json", supporting["cleanup.json"]
        )
        launch_path, _ = _verify_descriptor(evidence_root, "launch.json", supporting["launch.json"])
        guard = _load_json(guard_path)
        cleanup = _load_json(cleanup_path)
        launch = _load_json(launch_path)
        if not all(isinstance(value, dict) for value in (guard, cleanup, launch)):
            raise ValueError("launch/guard/cleanup payload is invalid")
        if guard.get("status") != "passed" or guard.get("harness_exit_code") != 0:
            raise ValueError("guard must be passed with harness exit code exactly 0")
        if guard.get("cleanup_verified") is not True or cleanup.get("cleanup_verified") is not True:
            raise ValueError("cleanup is not verified")
        for payload in (guard, cleanup):
            if (
                payload.get("candidate_processes_remaining") != []
                or payload.get("listeners_remaining") != 0
            ):
                raise ValueError("candidate process or listener residue exists")
        if (
            launch.get("session_id") != session_id
            or guard.get("session_id") != session_id
            or cleanup.get("session_id") != session_id
        ):
            raise ValueError("launch, guard, or cleanup session mismatch")
        if _utc(launch.get("launch_started_utc"), "launch evidence") != launch_time:
            raise ValueError("launch timestamp mismatch")
        if _utc(cleanup.get("cleanup_completed_utc"), "cleanup evidence") != cleanup_time:
            raise ValueError("cleanup timestamp mismatch")
        candidate_hashes = _verify_candidate_binding(evidence_root, workspace, candidate_paths)
        if strict_page_contract:
            _verify_page_capture_contract(
                evidence_root,
                captures,
                page_contract=manifest.get("page_capture_contract"),
            )
            launch_binding_path, _ = _verify_descriptor(
                evidence_root, "launch-binding.json", supporting["launch-binding.json"]
            )
            trusted = _trusted_candidate_paths(workspace, candidate_paths)
            _verify_launch_binding(
                evidence_root,
                launch_binding_path,
                session_id=session_id,
                launch_time=launch_time,
                cleanup_time=cleanup_time,
                candidate_hashes=candidate_hashes,
                trusted_stable=trusted["stable"],
            )
        result = browser_hint
        if not isinstance(result, dict):
            raise ValueError("browser-result is invalid")
        if result.get("status") != "passed" or result.get("overall_passed") is not True:
            raise ValueError("browser-result is not passed")
        if result.get("session_id") != session_id:
            raise ValueError("browser-result session mismatch")
        manifest_descriptor = result.get("capture_manifest")
        reported_manifest_path, _ = _verify_descriptor(
            evidence_root, "capture manifest", manifest_descriptor
        )
        if reported_manifest_path != manifest_path:
            raise ValueError("browser-result references a different capture manifest")
        binding_descriptor = result.get("candidate_binding")
        reported_binding_path, _ = _verify_descriptor(
            evidence_root, "candidate binding", binding_descriptor
        )
        if reported_binding_path != evidence_root / "candidate-hash-binding.json":
            raise ValueError("browser-result references a different candidate binding")
        if strict_page_contract:
            launch_descriptor = result.get("launch_binding")
            reported_launch_path, _ = _verify_descriptor(
                evidence_root, "launch binding", launch_descriptor
            )
            if reported_launch_path != evidence_root / "launch-binding.json":
                raise ValueError("browser-result references a different launch binding")
        reported_hashes = result.get("candidate_hashes")
        if reported_hashes != candidate_hashes:
            raise ValueError("browser-result candidate hashes disagree with exact binding")
        if result.get("active_console_error_count") != 0:
            raise ValueError("active browser console errors are not zero")
        if macro_enabled:
            _verify_macro_scenario(
                evidence_root,
                result["scenarios"]["macro_online"],
                session_id=session_id,
                launch_time=launch_time,
                cleanup_time=cleanup_time,
                manifest_captures=captures,
            )
        if zoom_enabled:
            zoom_scen = result["scenarios"].get("zoom") or result["scenarios"].get(
                "zoom_100_125_150"
            )
            _verify_zoom_scenario(
                evidence_root,
                zoom_scen,
                session_id=session_id,
                launch_time=launch_time,
                cleanup_time=cleanup_time,
                manifest_captures=captures,
            )
        if keyboard_enabled:
            kb_scen = result["scenarios"].get("keyboard") or result["scenarios"].get(
                "keyboard_navigation"
            )
            _verify_keyboard_scenario(
                evidence_root,
                kb_scen,
                session_id=session_id,
                launch_time=launch_time,
                cleanup_time=cleanup_time,
                manifest_captures=captures,
            )
        _verify_real_data(evidence_root)
        _verify_task_state(evidence_root)
        _verify_index(evidence_root)
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    return {"passed": not errors, "errors": errors, "checked_captures": sorted(set(checked))}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--workspace-root", type=Path, default=Path.cwd())
    parser.add_argument("--stable-candidate", type=Path)
    parser.add_argument("--payload-candidate", type=Path)
    parser.add_argument("--source-zip", type=Path)
    parser.add_argument("--formal-exe", type=Path)
    args = parser.parse_args()
    explicit = {
        "stable": args.stable_candidate,
        "payload": args.payload_candidate,
        "source_zip": args.source_zip,
        "formal": args.formal_exe,
    }
    if any(value is not None for value in explicit.values()) and any(
        value is None for value in explicit.values()
    ):
        parser.error("all four candidate role paths must be supplied together")
    candidate_paths = explicit if all(value is not None for value in explicit.values()) else None
    result = verify_evidence_bundle(
        args.root,
        workspace_root=args.workspace_root,
        candidate_paths=candidate_paths,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
