from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from scripts.verify_evidence_bundle import sha256_file, verify_evidence_bundle
from stock_tool.application.macro_snapshot import (
    FRED_SERIES,
    MacroEvidenceReference,
    MacroObservation,
    MacroSnapshot,
    MACRO_SCHEMA_VERSION,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _descriptor(root: Path, path: Path, *, captured: str | None = None) -> dict[str, object]:
    value: dict[str, object] = {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if captured is not None:
        value["captured_utc"] = captured
    return value


def _write_index(root: Path) -> None:
    index = {
        "schema_version": 2,
        "scope_exclusions": ["evidence-hash-index.json", "evidence-hash-index.sha256"],
        "entries": [
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in sorted(root.rglob("*"))
            if path.is_file()
            and path.name not in {"evidence-hash-index.json", "evidence-hash-index.sha256"}
        ],
    }
    index_path = root / "evidence-hash-index.json"
    _write_json(index_path, index)
    (root / "evidence-hash-index.sha256").write_bytes(sha256_file(index_path).encode("ascii"))


def _write_bundle(tmp_path: Path) -> tuple[Path, Path, dict[str, Path]]:
    workspace = tmp_path / "workspace"
    root = workspace / "evidence"
    root.mkdir(parents=True)
    candidate_paths = {
        "stable": workspace / "release" / "staging-sprint28.1.1" / "StockTool" / "StockTool.exe",
        "payload": workspace
        / "release"
        / "staging-sprint28.1.1"
        / "StockTool"
        / "versions"
        / "1.2.2"
        / "StockToolPayload.exe",
        "source_zip": workspace / "release" / "staging-sprint28.1.1-source.zip",
        "formal": workspace / "release" / "StockTool" / "StockTool.exe",
    }
    for name, path in candidate_paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"{name}-bytes".encode("ascii"))
    binding = {
        "schema_version": 2,
        "artifacts": {
            name: {
                "workspace_relative_path": path.relative_to(workspace).as_posix(),
                "expected_size_bytes": path.stat().st_size,
                "expected_sha256": sha256_file(path),
            }
            for name, path in candidate_paths.items()
        },
    }
    _write_json(root / "candidate-hash-binding.json", binding)
    launch_time = "2026-08-12T00:00:00+00:00"
    cleanup_time = "2026-08-12T00:01:00+00:00"
    session_id = "session-1"
    captures: dict[str, dict[str, object]] = {}
    for name in (
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
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".json":
            _write_json(path, {"session_id": session_id, "errors": []})
        elif path.suffix == ".png":
            path.write_bytes(b"\x89PNG\r\n\x1a\n" + name.encode("ascii") + b"x" * 128)
        else:
            path.write_bytes(f"StockTool {name}\n".encode("utf-8"))
        captures[name] = _descriptor(root, path, captured="2026-08-12T00:00:30+00:00")
    launch_path = root / "launch.json"
    guard_path = root / "guard-result.json"
    cleanup_path = root / "cleanup.json"
    transport_path = root / "transport.jsonl"
    _write_json(launch_path, {"session_id": session_id, "launch_started_utc": launch_time})
    _write_json(
        guard_path,
        {
            "session_id": session_id,
            "status": "passed",
            "harness_exit_code": 0,
            "cleanup_verified": True,
            "candidate_processes_remaining": [],
            "listeners_remaining": 0,
        },
    )
    _write_json(
        cleanup_path,
        {
            "session_id": session_id,
            "cleanup_completed_utc": cleanup_time,
            "cleanup_verified": True,
            "candidate_processes_remaining": [],
            "listeners_remaining": 0,
        },
    )
    transport_path.write_bytes(b'{"mode":"online"}\n')
    supporting = {
        name: _descriptor(root, path)
        for name, path in {
            "launch.json": launch_path,
            "guard-result.json": guard_path,
            "cleanup.json": cleanup_path,
            "transport.jsonl": transport_path,
        }.items()
    }
    manifest_path = root / "capture-session-manifest.json"
    _write_json(
        manifest_path,
        {
            "schema_version": 2,
            "session_id": session_id,
            "launch_started_utc": launch_time,
            "cleanup_completed_utc": cleanup_time,
            "captures": captures,
            "supporting_files": supporting,
        },
    )
    current = {"file_count": 191, "files": {"digest": "same"}}
    _write_json(root / "real-data-before.json", current)
    _write_json(root / "real-data-after.json", current)
    _write_json(root / "real-data-current.json", current)
    _write_json(
        root / "real-data-diff.json", {"zero_diff": True, "added": [], "removed": [], "changed": []}
    )
    task = {"production_task_status": "absent"}
    _write_json(root / "task-scheduler-before.json", task)
    _write_json(root / "task-scheduler-after.json", task)
    _write_json(
        root / "task-scheduler-diff.json",
        {"zero_diff": True, "added": [], "removed": [], "changed": []},
    )
    artifacts = binding["artifacts"]
    assert isinstance(artifacts, dict)
    browser = {
        "status": "passed",
        "overall_passed": True,
        "session_id": session_id,
        "capture_manifest": _descriptor(root, manifest_path),
        "candidate_binding": _descriptor(root, root / "candidate-hash-binding.json"),
        "candidate_hashes": {
            name: item["expected_sha256"]
            for name, item in artifacts.items()
            if isinstance(item, dict)
        },
        "active_console_error_count": 0,
    }
    _write_json(root / "browser-result.json", browser)
    _write_index(root)
    return root, workspace, candidate_paths


def _add_macro_scenario(root: Path, session_id: str = "session-1") -> None:
    now = "2026-08-12T00:00:00+00:00"
    references = []
    observations = []
    import hashlib

    for index, (key, (fred_id, _title, unit)) in enumerate(FRED_SERIES.items()):
        digest = hashlib.sha256(fred_id.encode()).hexdigest()
        reference_id = f"macro-{key.lower()}"
        references.append(
            MacroEvidenceReference(
                reference_id=reference_id,
                provider="FRED",
                series_id=fred_id,
                source_url=f"https://fred.test/{fred_id}",
                observed_date="2026-08-12",
                fetched_at=now,
                payload_sha256=digest,
            )
        )
        observations.append(
            MacroObservation(
                series_id=key,
                observation_period="2026-08-12",
                value=float(index + 1),
                unit=unit,
                source="FRED official",
                source_url=f"https://fred.test/{fred_id}",
                fetched_at=now,
                observed_date="2026-08-12",
                release_date=None,
                freshness_status="fresh",
                snapshot_fingerprint="0" * 64,
                schema_version=MACRO_SCHEMA_VERSION,
                reference_id=reference_id,
            )
        )
    snapshot = MacroSnapshot.create(
        status="ready",
        source="FRED official",
        observations=observations,
        references=references,
        generated_at=datetime.fromisoformat(now),
        as_of_date="2026-08-12",
    )
    files: dict[str, Path] = {
        "macro.png": root / "macro.png",
        "macro.dom.txt": root / "macro.dom.txt",
        "macro.console.json": root / "macro.console.json",
        "macro-provider-metadata.json": root / "macro-provider-metadata.json",
        "macro-snapshot.json": root / "macro-snapshot.json",
        "macro-payload-hashes.json": root / "macro-payload-hashes.json",
    }
    files["macro.png"].write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 200)
    files["macro.dom.txt"].write_bytes("StockTool 今日總經背景\n".encode("utf-8"))
    _write_json(files["macro.console.json"], {"errors": []})
    _write_json(
        files["macro-provider-metadata.json"],
        {"status": "ready", "source": "FRED official", "coverage": 6},
    )
    _write_json(files["macro-snapshot.json"], snapshot.to_dict())
    _write_json(
        files["macro-payload-hashes.json"],
        {"series": {reference.series_id: reference.payload_sha256 for reference in references}},
    )
    manifest_path = root / "capture-session-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, path in files.items():
        manifest["captures"][name] = _descriptor(root, path, captured="2026-08-12T00:00:30+00:00")
    _write_json(manifest_path, manifest)
    browser_path = root / "browser-result.json"
    browser = json.loads(browser_path.read_text(encoding="utf-8"))
    browser["scenarios"] = {
        "macro_online": {
            "status": "passed",
            "coverage": 6,
            "snapshot_status": "ready",
            "source": "FRED official",
            "session_id": session_id,
            "same_session": True,
            "snapshot_record_sha256": snapshot.record_sha256,
            "captures": {
                "screenshot": _descriptor(
                    root, files["macro.png"], captured="2026-08-12T00:00:30+00:00"
                ),
                "dom": _descriptor(
                    root, files["macro.dom.txt"], captured="2026-08-12T00:00:30+00:00"
                ),
                "console": _descriptor(
                    root, files["macro.console.json"], captured="2026-08-12T00:00:30+00:00"
                ),
                "provider_metadata": _descriptor(
                    root,
                    files["macro-provider-metadata.json"],
                    captured="2026-08-12T00:00:30+00:00",
                ),
                "snapshot": _descriptor(
                    root, files["macro-snapshot.json"], captured="2026-08-12T00:00:30+00:00"
                ),
                "payload_hashes": _descriptor(
                    root, files["macro-payload-hashes.json"], captured="2026-08-12T00:00:30+00:00"
                ),
            },
        }
    }
    _write_json(browser_path, browser)
    browser["capture_manifest"] = _descriptor(root, manifest_path)
    _write_json(browser_path, browser)
    _write_index(root)


def test_verifier_accepts_complete_raw_byte_bundle(tmp_path: Path) -> None:
    root, workspace, candidate_paths = _write_bundle(tmp_path)
    result = verify_evidence_bundle(root, workspace_root=workspace, candidate_paths=candidate_paths)
    assert result["passed"] is True
    assert "home.png" in result["checked_captures"]


def test_verifier_accepts_raw_jpeg_when_browser_backend_returns_jpeg(tmp_path: Path) -> None:
    root, workspace, candidate_paths = _write_bundle(tmp_path)
    screenshot = root / "home.png"
    screenshot.write_bytes(b"\xff\xd8\xff\xe0" + b"raw-browser-jpeg" * 16)
    manifest_path = root / "capture-session-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["captures"]["home.png"] = _descriptor(
        root, screenshot, captured="2026-08-12T00:00:30+00:00"
    )
    _write_json(manifest_path, manifest)
    browser_path = root / "browser-result.json"
    browser = json.loads(browser_path.read_text(encoding="utf-8"))
    browser["capture_manifest"] = _descriptor(root, manifest_path)
    _write_json(browser_path, browser)
    _write_index(root)

    assert (
        verify_evidence_bundle(root, workspace_root=workspace, candidate_paths=candidate_paths)[
            "passed"
        ]
        is True
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "truncated_hash",
        "browser_not_passed",
        "harness_none",
        "capture_after_cleanup",
        "session_mismatch",
        "missing_capture",
        "extra_file",
        "real_data_changed",
        "production_task_present",
        "formal_bytes_changed",
    ],
)
def test_verifier_rejects_adversarial_bundle_shapes(tmp_path: Path, mutation: str) -> None:
    root, workspace, candidate_paths = _write_bundle(tmp_path)
    if mutation == "truncated_hash":
        path = root / "candidate-hash-binding.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["artifacts"]["source_zip"]["expected_sha256"] = "A" * 63
        _write_json(path, payload)
    elif mutation == "browser_not_passed":
        path = root / "browser-result.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["overall_passed"] = False
        _write_json(path, payload)
    elif mutation == "harness_none":
        path = root / "guard-result.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["harness_exit_code"] = None
        _write_json(path, payload)
    elif mutation == "capture_after_cleanup":
        path = root / "capture-session-manifest.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["captures"]["home.png"]["captured_utc"] = "2026-08-12T00:02:00+00:00"
        _write_json(path, payload)
    elif mutation == "session_mismatch":
        path = root / "guard-result.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["session_id"] = "other"
        _write_json(path, payload)
    elif mutation == "missing_capture":
        (root / "home.png").unlink()
    elif mutation == "extra_file":
        (root / "unexpected.txt").write_bytes(b"unexpected\n")
    elif mutation == "real_data_changed":
        _write_json(
            root / "real-data-diff.json",
            {"zero_diff": True, "added": ["x"], "removed": [], "changed": []},
        )
    elif mutation == "production_task_present":
        _write_json(root / "task-scheduler-after.json", {"production_task_status": "present"})
    elif mutation == "formal_bytes_changed":
        candidate_paths["formal"].write_bytes(b"changed")
    result = verify_evidence_bundle(root, workspace_root=workspace, candidate_paths=candidate_paths)
    assert result["passed"] is False


def test_verifier_rejects_raw_newline_or_bom_rewrite_without_writing(tmp_path: Path) -> None:
    root, workspace, candidate_paths = _write_bundle(tmp_path)
    before = (root / "home.dom.txt").read_bytes()
    (root / "home.dom.txt").write_bytes(b"\xef\xbb\xbf" + before.replace(b"\n", b"\r\n"))
    result = verify_evidence_bundle(root, workspace_root=workspace, candidate_paths=candidate_paths)
    assert result["passed"] is False
    assert (root / "home.dom.txt").read_bytes().startswith(b"\xef\xbb\xbf")


def test_verifier_rejects_indexed_unexpected_file(tmp_path: Path) -> None:
    root, workspace, candidate_paths = _write_bundle(tmp_path)
    unexpected = root / "unexpected.json"
    _write_json(unexpected, {"unexpected": True})
    _write_index(root)
    result = verify_evidence_bundle(root, workspace_root=workspace, candidate_paths=candidate_paths)
    assert result["passed"] is False


def test_verifier_rejects_duplicate_capture_path_alias(tmp_path: Path) -> None:
    root, workspace, candidate_paths = _write_bundle(tmp_path)
    manifest_path = root / "capture-session-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["captures"]["changes.png"]["path"] = "./home.png"
    _write_json(manifest_path, manifest)
    result = verify_evidence_bundle(root, workspace_root=workspace, candidate_paths=candidate_paths)
    assert result["passed"] is False


def test_verifier_rejects_duplicate_page_capture_bytes(tmp_path: Path) -> None:
    root, workspace, candidate_paths = _write_bundle(tmp_path)
    home_bytes = (root / "home.png").read_bytes()
    (root / "changes.png").write_bytes(home_bytes)
    manifest_path = root / "capture-session-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["captures"]["changes.png"] = _descriptor(
        root, root / "changes.png", captured="2026-08-12T00:00:30+00:00"
    )
    _write_json(manifest_path, manifest)
    _write_index(root)
    result = verify_evidence_bundle(root, workspace_root=workspace, candidate_paths=candidate_paths)
    assert result["passed"] is False


def test_verifier_accepts_hash_bound_macro_online_scenario(tmp_path: Path) -> None:
    root, workspace, candidate_paths = _write_bundle(tmp_path)
    _add_macro_scenario(root)
    result = verify_evidence_bundle(root, workspace_root=workspace, candidate_paths=candidate_paths)
    assert result["passed"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        "coverage_zero",
        "missing_macro_file",
        "zero_provider_hash",
        "path_escape",
        "wrong_session",
        "capture_after_cleanup",
        "snapshot_not_ready",
        "missing_series",
        "tampered_value",
    ],
)
def test_verifier_rejects_macro_adversarial_evidence(tmp_path: Path, mutation: str) -> None:
    root, workspace, candidate_paths = _write_bundle(tmp_path)
    _add_macro_scenario(root)
    browser_path = root / "browser-result.json"
    browser = json.loads(browser_path.read_text(encoding="utf-8"))
    scenario = browser["scenarios"]["macro_online"]
    if mutation == "coverage_zero":
        scenario["coverage"] = 0
    elif mutation == "missing_macro_file":
        (root / "macro.png").unlink()
    elif mutation == "zero_provider_hash":
        path = root / "macro-payload-hashes.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["series"][next(iter(payload["series"]))] = "0" * 64
        _write_json(path, payload)
    elif mutation == "path_escape":
        scenario["captures"]["dom"]["path"] = "../macro.dom.txt"
    elif mutation == "wrong_session":
        scenario["session_id"] = "other"
    elif mutation == "capture_after_cleanup":
        scenario["captures"]["screenshot"]["captured_utc"] = "2026-08-12T00:02:00+00:00"
    elif mutation == "snapshot_not_ready":
        path = root / "macro-snapshot.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["status"] = "partial"
        _write_json(path, payload)
    elif mutation == "missing_series":
        path = root / "macro-snapshot.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["observations"] = payload["observations"][:-1]
        _write_json(path, payload)
    elif mutation == "tampered_value":
        path = root / "macro-snapshot.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["observations"][0]["value"] = 999.0
        _write_json(path, payload)
    _write_json(browser_path, browser)
    _write_index(root)
    result = verify_evidence_bundle(root, workspace_root=workspace, candidate_paths=candidate_paths)
    assert result["passed"] is False


def test_verifier_rejects_candidate_role_path_escape_or_wrong_basename(
    tmp_path: Path,
) -> None:
    root, workspace, candidate_paths = _write_bundle(tmp_path)
    binding_path = root / "candidate-hash-binding.json"
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    binding["artifacts"]["stable"][
        "workspace_relative_path"
    ] = "release/staging-sprint28.1.1/StockTool/not-stocktool.exe"
    _write_json(binding_path, binding)
    _write_index(root)
    result = verify_evidence_bundle(root, workspace_root=workspace, candidate_paths=candidate_paths)
    assert result["passed"] is False


def test_verifier_rejects_external_candidate_mapping_wrong_basename(tmp_path: Path) -> None:
    root, workspace, candidate_paths = _write_bundle(tmp_path)
    bad = dict(candidate_paths)
    bad_stable = workspace / "release" / "staging-sprint28.1.1" / "StockTool" / "other.exe"
    bad_stable.write_bytes(candidate_paths["stable"].read_bytes())
    bad["stable"] = bad_stable
    result = verify_evidence_bundle(root, workspace_root=workspace, candidate_paths=bad)
    assert result["passed"] is False


def test_verifier_accepts_zoom_and_keyboard_scenarios(tmp_path: Path) -> None:
    root, workspace, candidate_paths = _write_bundle(tmp_path)
    session_id = "session-1"
    captured = "2026-08-12T00:00:30+00:00"
    manifest_path = root / "capture-session-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    browser_path = root / "browser-result.json"
    browser = json.loads(browser_path.read_text(encoding="utf-8"))

    # 1. Setup zoom files
    zoom_captures = {}
    for level, w, h, dpr in (
        ("100", 1400, 900, 1.0),
        ("125", 1120, 720, 1.25),
        ("150", 933, 600, 1.5),
    ):
        png_p = root / f"zoom_{level}.png"
        png_p.write_bytes(b"\x89PNG\r\n\x1a\n" + f"zoom_{level}".encode("ascii") + b"x" * 128)
        dom_p = root / f"zoom_{level}.dom.txt"
        dom_p.write_bytes(f"StockTool zoom {level}\n".encode("utf-8"))
        console_p = root / f"zoom_{level}.console.json"
        _write_json(console_p, {"session_id": session_id, "errors": []})
        manifest["captures"][f"zoom_{level}.png"] = _descriptor(root, png_p, captured=captured)
        manifest["captures"][f"zoom_{level}.dom.txt"] = _descriptor(root, dom_p, captured=captured)
        manifest["captures"][f"zoom_{level}.console.json"] = _descriptor(
            root, console_p, captured=captured
        )
        zoom_captures[f"zoom_{level}_png"] = _descriptor(root, png_p, captured=captured)
        zoom_captures[f"zoom_{level}_dom"] = _descriptor(root, dom_p, captured=captured)
        zoom_captures[f"zoom_{level}_console"] = _descriptor(root, console_p, captured=captured)

    zoom_meta_p = root / "zoom-metadata.json"
    _write_json(
        zoom_meta_p,
        {
            "schema_version": 2,
            "session_id": session_id,
            "zooms": {
                "100%": {
                    "innerWidth": 1400,
                    "innerHeight": 900,
                    "devicePixelRatio": 1.0,
                    "physical_viewport_width": 1400,
                    "physical_viewport_height": 900,
                },
                "125%": {
                    "innerWidth": 1120,
                    "innerHeight": 720,
                    "devicePixelRatio": 1.25,
                    "physical_viewport_width": 1400,
                    "physical_viewport_height": 900,
                },
                "150%": {
                    "innerWidth": 933,
                    "innerHeight": 600,
                    "devicePixelRatio": 1.5,
                    "physical_viewport_width": 1400,
                    "physical_viewport_height": 900,
                },
            },
        },
    )
    manifest["captures"]["zoom-metadata.json"] = _descriptor(root, zoom_meta_p, captured=captured)
    zoom_captures["metadata"] = _descriptor(root, zoom_meta_p, captured=captured)

    # 2. Setup keyboard files
    kb_captures = {}
    for stage in ("initial", "opened", "changed"):
        png_p = root / f"keyboard_{stage}.png"
        png_p.write_bytes(b"\x89PNG\r\n\x1a\n" + f"kb_{stage}".encode("ascii") + b"x" * 128)
        dom_p = root / f"keyboard_{stage}.dom.txt"
        val = "請選擇市場" if stage != "changed" else "台股上市 TWSE"
        dom_p.write_bytes(f"StockTool market selector {stage} {val}\n".encode("utf-8"))
        console_p = root / f"keyboard_{stage}.console.json"
        _write_json(console_p, {"session_id": session_id, "errors": []})
        manifest["captures"][f"keyboard_{stage}.png"] = _descriptor(root, png_p, captured=captured)
        manifest["captures"][f"keyboard_{stage}.dom.txt"] = _descriptor(
            root, dom_p, captured=captured
        )
        manifest["captures"][f"keyboard_{stage}.console.json"] = _descriptor(
            root, console_p, captured=captured
        )
        kb_captures[f"keyboard_{stage}_png"] = _descriptor(root, png_p, captured=captured)
        kb_captures[f"keyboard_{stage}_dom"] = _descriptor(root, dom_p, captured=captured)
        kb_captures[f"keyboard_{stage}_console"] = _descriptor(root, console_p, captured=captured)

    kb_trace_p = root / "keyboard-navigation-trace.json"
    _write_json(
        kb_trace_p,
        {
            "schema_version": 2,
            "session_id": session_id,
            "initial_value": "請選擇市場",
            "changed_value": "台股上市 TWSE",
            "steps": [
                {"step": 1, "action": "Tab", "focus": "sidebar"},
                {"step": 2, "action": "Tab", "focus": "market_select"},
                {"step": 3, "action": "Enter", "focus": "menu_open"},
                {"step": 4, "action": "ArrowDown", "focus": "option_twse"},
                {"step": 5, "action": "Enter", "focus": "option_selected"},
            ],
        },
    )
    manifest["captures"]["keyboard-navigation-trace.json"] = _descriptor(
        root, kb_trace_p, captured=captured
    )
    kb_captures["trace"] = _descriptor(root, kb_trace_p, captured=captured)

    browser.setdefault("scenarios", {})["zoom"] = {
        "status": "passed",
        "same_session": True,
        "session_id": session_id,
        "zoom_levels": ["100%", "125%", "150%"],
        "captures": zoom_captures,
    }
    browser["scenarios"]["keyboard"] = {
        "status": "passed",
        "same_session": True,
        "session_id": session_id,
        "value_changed": True,
        "captures": kb_captures,
    }

    _write_json(manifest_path, manifest)
    browser["capture_manifest"] = _descriptor(root, manifest_path)
    _write_json(browser_path, browser)
    _write_index(root)

    result = verify_evidence_bundle(root, workspace_root=workspace, candidate_paths=candidate_paths)
    assert result["passed"] is True, f"Verifier failed: {result['errors']}"


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_dpr",
        "mismatched_physical_dimensions",
        "missing_zoom_capture",
    ],
)
def test_verifier_rejects_tampered_zoom_scenario(tmp_path: Path, mutation: str) -> None:
    root, workspace, candidate_paths = _write_bundle(tmp_path)
    session_id = "session-1"
    captured = "2026-08-12T00:00:30+00:00"
    manifest_path = root / "capture-session-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    browser_path = root / "browser-result.json"
    browser = json.loads(browser_path.read_text(encoding="utf-8"))

    zoom_captures = {}
    for level, w, h, dpr in (
        ("100", 1400, 900, 1.0),
        ("125", 1120, 720, 1.25),
        ("150", 933, 600, 1.5),
    ):
        png_p = root / f"zoom_{level}.png"
        png_p.write_bytes(b"\x89PNG\r\n\x1a\n" + f"zoom_{level}".encode("ascii") + b"x" * 128)
        dom_p = root / f"zoom_{level}.dom.txt"
        dom_p.write_bytes(f"StockTool zoom {level}\n".encode("utf-8"))
        console_p = root / f"zoom_{level}.console.json"
        _write_json(console_p, {"session_id": session_id, "errors": []})
        manifest["captures"][f"zoom_{level}.png"] = _descriptor(root, png_p, captured=captured)
        manifest["captures"][f"zoom_{level}.dom.txt"] = _descriptor(root, dom_p, captured=captured)
        manifest["captures"][f"zoom_{level}.console.json"] = _descriptor(
            root, console_p, captured=captured
        )
        zoom_captures[f"zoom_{level}_png"] = _descriptor(root, png_p, captured=captured)
        zoom_captures[f"zoom_{level}_dom"] = _descriptor(root, dom_p, captured=captured)
        zoom_captures[f"zoom_{level}_console"] = _descriptor(root, console_p, captured=captured)

    zooms_meta = {
        "100%": {
            "innerWidth": 1400,
            "innerHeight": 900,
            "devicePixelRatio": 1.0,
            "physical_viewport_width": 1400,
            "physical_viewport_height": 900,
        },
        "125%": {
            "innerWidth": 1120,
            "innerHeight": 720,
            "devicePixelRatio": 1.25,
            "physical_viewport_width": 1400,
            "physical_viewport_height": 900,
        },
        "150%": {
            "innerWidth": 933,
            "innerHeight": 600,
            "devicePixelRatio": 1.5,
            "physical_viewport_width": 1400,
            "physical_viewport_height": 900,
        },
    }
    if mutation == "wrong_dpr":
        zooms_meta["150%"]["devicePixelRatio"] = 1.2
    elif mutation == "mismatched_physical_dimensions":
        zooms_meta["150%"]["physical_viewport_width"] = 1200

    zoom_meta_p = root / "zoom-metadata.json"
    _write_json(
        zoom_meta_p,
        {
            "schema_version": 2,
            "session_id": session_id,
            "zooms": zooms_meta,
        },
    )
    manifest["captures"]["zoom-metadata.json"] = _descriptor(root, zoom_meta_p, captured=captured)
    zoom_captures["metadata"] = _descriptor(root, zoom_meta_p, captured=captured)

    if mutation == "missing_zoom_capture":
        del manifest["captures"]["zoom_150.png"]
        (root / "zoom_150.png").unlink()

    browser.setdefault("scenarios", {})["zoom"] = {
        "status": "passed",
        "same_session": True,
        "session_id": session_id,
        "zoom_levels": ["100%", "125%", "150%"],
        "captures": zoom_captures,
    }

    _write_json(manifest_path, manifest)
    browser["capture_manifest"] = _descriptor(root, manifest_path)
    _write_json(browser_path, browser)
    _write_index(root)

    result = verify_evidence_bundle(root, workspace_root=workspace, candidate_paths=candidate_paths)
    assert result["passed"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        "no_dom_change",
        "missing_arrow_action",
        "missing_initial_value_in_dom",
    ],
)
def test_verifier_rejects_tampered_keyboard_scenario(tmp_path: Path, mutation: str) -> None:
    root, workspace, candidate_paths = _write_bundle(tmp_path)
    session_id = "session-1"
    captured = "2026-08-12T00:00:30+00:00"
    manifest_path = root / "capture-session-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    browser_path = root / "browser-result.json"
    browser = json.loads(browser_path.read_text(encoding="utf-8"))

    kb_captures = {}
    for stage in ("initial", "opened", "changed"):
        png_p = root / f"keyboard_{stage}.png"
        png_p.write_bytes(b"\x89PNG\r\n\x1a\n" + f"kb_{stage}".encode("ascii") + b"x" * 128)
        dom_p = root / f"keyboard_{stage}.dom.txt"
        val = (
            "請選擇市場"
            if stage != "changed"
            else ("請選擇市場" if mutation == "no_dom_change" else "台股上市 TWSE")
        )
        if mutation == "missing_initial_value_in_dom" and stage == "initial":
            val = "其他文字"
        dom_p.write_bytes(f"StockTool market selector {stage} {val}\n".encode("utf-8"))
        console_p = root / f"keyboard_{stage}.console.json"
        _write_json(console_p, {"session_id": session_id, "errors": []})
        manifest["captures"][f"keyboard_{stage}.png"] = _descriptor(root, png_p, captured=captured)
        manifest["captures"][f"keyboard_{stage}.dom.txt"] = _descriptor(
            root, dom_p, captured=captured
        )
        manifest["captures"][f"keyboard_{stage}.console.json"] = _descriptor(
            root, console_p, captured=captured
        )
        kb_captures[f"keyboard_{stage}_png"] = _descriptor(root, png_p, captured=captured)
        kb_captures[f"keyboard_{stage}_dom"] = _descriptor(root, dom_p, captured=captured)
        kb_captures[f"keyboard_{stage}_console"] = _descriptor(root, console_p, captured=captured)

    steps = [
        {"step": 1, "action": "Tab", "focus": "sidebar"},
        {"step": 2, "action": "Tab", "focus": "market_select"},
        {"step": 3, "action": "Enter", "focus": "menu_open"},
        {
            "step": 4,
            "action": "ArrowDown" if mutation != "missing_arrow_action" else "Tab",
            "focus": "option_twse",
        },
        {"step": 5, "action": "Enter", "focus": "option_selected"},
    ]

    kb_trace_p = root / "keyboard-navigation-trace.json"
    _write_json(
        kb_trace_p,
        {
            "schema_version": 2,
            "session_id": session_id,
            "initial_value": "請選擇市場",
            "changed_value": "台股上市 TWSE",
            "steps": steps,
        },
    )
    manifest["captures"]["keyboard-navigation-trace.json"] = _descriptor(
        root, kb_trace_p, captured=captured
    )
    kb_captures["trace"] = _descriptor(root, kb_trace_p, captured=captured)

    browser.setdefault("scenarios", {})["keyboard"] = {
        "status": "passed",
        "same_session": True,
        "session_id": session_id,
        "value_changed": True,
        "captures": kb_captures,
    }

    _write_json(manifest_path, manifest)
    browser["capture_manifest"] = _descriptor(root, manifest_path)
    _write_json(browser_path, browser)
    _write_index(root)

    result = verify_evidence_bundle(root, workspace_root=workspace, candidate_paths=candidate_paths)
    assert result["passed"] is False
