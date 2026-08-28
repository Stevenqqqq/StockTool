from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from stock_tool.quality_gate import (
    COVERAGE_REPORT_FILE,
    MIN_BRANCH_COVERAGE,
    SPRINT18_FORMAT_FILES,
    GateStep,
    QualityGateResult,
    coverage_meets_floor,
    coverage_percent_from_json,
    main,
    quality_gate_steps,
    _content_secret_violations,
    run_quality_gate,
)


def test_quality_gate_stops_at_the_first_failed_step(tmp_path: Path) -> None:
    seen: list[str] = []

    def runner(step: GateStep) -> int:
        seen.append(step.name)
        return 1 if step.name == "full_pytest" else 0

    result = run_quality_gate(root=tmp_path, runner=runner)

    assert result.exit_code == 1
    assert result.failed_step == "full_pytest"
    assert seen == ["sprint19_1_targeted", "full_pytest"]


def test_quality_gate_has_no_build_or_publish_step(tmp_path: Path) -> None:
    seen: list[str] = []

    def runner(step: GateStep) -> int:
        seen.append(step.name)
        return 0

    result = run_quality_gate(root=tmp_path, runner=runner)

    assert result.exit_code == 0
    assert "build" not in " ".join(seen).lower()
    assert "publish" not in " ".join(seen).lower()
    assert seen[-1] == "regression_baseline"


def test_default_quality_gate_redirects_all_steps_to_temporary_user_data(
    tmp_path: Path, monkeypatch
) -> None:
    observed_user_data_dirs: list[str | None] = []

    def fake_run(command, *, cwd, check, env):
        del command, cwd, check
        observed_user_data_dirs.append(env.get("STOCK_TOOL_USER_DATA_DIR"))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("stock_tool.quality_gate.subprocess.run", fake_run)

    result = run_quality_gate(root=tmp_path)

    assert result.exit_code == 0
    assert len(observed_user_data_dirs) > 1
    assert len(set(observed_user_data_dirs)) == 1
    isolated_root = Path(observed_user_data_dirs[0] or "")
    assert isolated_root.name.startswith("stocktool-quality-gate-")
    assert not isolated_root.exists()


def test_quality_gate_uses_explicit_sprint19_1_quality_scope() -> None:
    steps = {step.name: step.command for step in quality_gate_steps(python="python")}

    assert steps["black"][-len(SPRINT18_FORMAT_FILES) :] == SPRINT18_FORMAT_FILES
    assert steps["ruff"][-len(SPRINT18_FORMAT_FILES) :] == SPRINT18_FORMAT_FILES
    assert "src/stock_tool/stable_entry.py" in SPRINT18_FORMAT_FILES
    assert "scripts/generate_sbom.py" in SPRINT18_FORMAT_FILES
    assert "scripts/measure_performance.py" in SPRINT18_FORMAT_FILES
    assert "src" not in steps["black"]
    assert "tests" not in steps["ruff"]


def test_quality_gate_enforces_current_coverage_floor() -> None:
    steps = {step.name: step.command for step in quality_gate_steps(python="python")}
    full = steps["full_pytest"]
    branch = steps["branch_coverage"]
    assert MIN_BRANCH_COVERAGE >= 82.71
    assert "--cov=stock_tool" in full
    assert "--cov-branch" in full
    assert f"--cov-report=json:{COVERAGE_REPORT_FILE}" in full
    assert branch[:4] == ("python", "-m", "stock_tool.quality_gate", "--verify-coverage")
    assert "pytest" not in branch


def test_coverage_floor_uses_unrounded_json_percent(tmp_path: Path) -> None:
    report = tmp_path / "coverage.json"
    report.write_text(json.dumps({"totals": {"percent_covered": 82.709999}}), encoding="utf-8")
    assert coverage_meets_floor(report) is False
    report.write_text(json.dumps({"totals": {"percent_covered": 82.710}}), encoding="utf-8")
    assert coverage_meets_floor(report) is True


def test_coverage_floor_rejects_display_only_or_invalid_percent(tmp_path: Path) -> None:
    report = tmp_path / "coverage.json"
    report.write_text(json.dumps({"totals": {"percent_covered": "83"}}), encoding="utf-8")
    assert coverage_meets_floor(report) is False
    report.write_text(json.dumps({"totals": {"percent_covered": 83.0}}), encoding="utf-8")
    assert coverage_meets_floor(report) is True


def test_coverage_verifier_rejects_malformed_reports_without_rounding(
    tmp_path: Path, monkeypatch
) -> None:
    report = tmp_path / "coverage.json"
    malformed = (
        b"\xef\xbb\xbf{}",
        b"[]",
        b"{}",
        json.dumps({"totals": []}).encode("utf-8"),
        json.dumps({"totals": {"percent_covered": True}}).encode("utf-8"),
        json.dumps({"totals": {"percent_covered": 101}}).encode("utf-8"),
        json.dumps({"totals": {"percent_covered": float("nan")}}).encode("utf-8"),
    )
    for raw in malformed:
        report.write_bytes(raw)
        assert coverage_meets_floor(report) is False
        with pytest.raises((ValueError, UnicodeDecodeError)):
            coverage_percent_from_json(report)
        assert main(["--verify-coverage", str(report)]) == 1

    report.write_text(json.dumps({"totals": {"percent_covered": 82.709999}}), encoding="utf-8")
    assert main(["--verify-coverage", str(report)]) == 1
    report.write_text(json.dumps({"totals": {"percent_covered": 82.710001}}), encoding="utf-8")
    assert main(["--verify-coverage", str(report)]) == 0
    monkeypatch.chdir(tmp_path)
    assert main(["--verify-coverage"]) == 0
    assert coverage_meets_floor(tmp_path / "missing.json") is False


def test_quality_gate_main_reports_success_and_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "stock_tool.quality_gate.run_quality_gate",
        lambda *, root: QualityGateResult(0, None, ("all",)),
    )
    monkeypatch.chdir(tmp_path)
    assert main([]) == 0
    monkeypatch.setattr(
        "stock_tool.quality_gate.run_quality_gate",
        lambda *, root: QualityGateResult(1, "coverage", ()),
    )
    assert main([]) == 1


def test_privacy_scan_rejects_private_and_unreadable_candidates(tmp_path: Path) -> None:
    from stock_tool.quality_gate import project_privacy_violations

    (tmp_path / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "secrets.toml").write_text('token="secret"\n', encoding="utf-8")
    (tmp_path / "src" / "portfolio.csv").write_text("symbol\n2330\n", encoding="utf-8")
    violations = project_privacy_violations(tmp_path)
    assert ".env" in violations
    assert "src/secrets.toml" in violations
    assert "src/portfolio.csv" not in violations
    unreadable = tmp_path / "unreadable.txt"
    assert _content_secret_violations(unreadable, "unreadable.txt") == [
        "unreadable.txt:0:unreadable_text_candidate",
    ]


def test_project_privacy_scan_detects_real_secret_without_echoing_value(tmp_path: Path) -> None:
    from stock_tool.quality_gate import project_privacy_violations

    (tmp_path / "src").mkdir()
    secret = "real-" + "secret-value"
    (tmp_path / "src" / "sample.toml").write_text("API_KEY=" + secret + "\n", encoding="utf-8")
    violations = project_privacy_violations(tmp_path)

    assert violations == ("src/sample.toml:1:api_key",)
    assert secret not in " ".join(violations)


def test_project_privacy_scan_allows_empty_env_example_placeholder(tmp_path: Path) -> None:
    from stock_tool.quality_gate import project_privacy_violations

    (tmp_path / ".env.example").write_text("API_KEY=\nTOKEN=${TOKEN}\n", encoding="utf-8")
    assert project_privacy_violations(tmp_path) == ()


def test_project_privacy_scan_reports_credential_categories_without_values(tmp_path: Path) -> None:
    from stock_tool.quality_gate import project_privacy_violations

    (tmp_path / "src").mkdir()
    secret = "not-" + "for-output"
    (tmp_path / "src" / "credentials.toml").write_text(
        "Authorization: Bearer " + secret + "\n"
        "endpoint=https://account:" + secret + "@example.test/path\n"
        "password=" + secret + "\n",
        encoding="utf-8",
    )

    violations = project_privacy_violations(tmp_path)

    assert violations == (
        "src/credentials.toml:1:authorization",
        "src/credentials.toml:2:url_credentials",
        "src/credentials.toml:3:password",
    )
    assert secret not in " ".join(violations)


def test_project_privacy_scan_detects_quoted_and_python_default_credentials(
    tmp_path: Path,
) -> None:
    from stock_tool.quality_gate import project_privacy_violations

    (tmp_path / "src").mkdir()
    secret = "credential-" + "value"
    (tmp_path / "src" / "config.json").write_text(
        '{"API_KEY": "'
        + secret
        + '", "token": "'
        + secret
        + '", "Authorization": "Bearer '
        + secret
        + '"}\n',
        encoding="utf-8",
    )
    (tmp_path / "src" / "client.py").write_text(
        '{"password": "' + secret + '"}\n'
        'def connect(api_key="' + secret + '"):\n'
        "    return api_key\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "settings.yaml").write_text(
        '"secret": "' + secret + '"\n', encoding="utf-8"
    )
    (tmp_path / "src" / "settings.toml").write_text(
        '"api_key" = "' + secret + '"\n', encoding="utf-8"
    )

    violations = project_privacy_violations(tmp_path)

    assert violations == (
        "src/client.py:1:password",
        "src/client.py:2:api_key",
        "src/config.json:1:api_key",
        "src/config.json:1:authorization",
        "src/config.json:1:token",
        "src/settings.toml:1:api_key",
        "src/settings.yaml:1:secret",
    )
    assert secret not in " ".join(violations)


def test_project_privacy_scan_allows_quoted_placeholders_and_environment_lookup(
    tmp_path: Path,
) -> None:
    from stock_tool.quality_gate import project_privacy_violations

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "safe.py").write_text(
        'config = {"token": "${TOKEN}", "password": None, "secret": ""}\n'
        'api_key = os.getenv("API_KEY")\n',
        encoding="utf-8",
    )
    (tmp_path / "src" / "safe.yaml").write_text('"api_key": "${API_KEY}"\n', encoding="utf-8")

    assert project_privacy_violations(tmp_path) == ()


def test_project_privacy_scan_uses_python_structure_for_typed_defaults_and_annotations(
    tmp_path: Path,
) -> None:
    from stock_tool.quality_gate import project_privacy_violations

    (tmp_path / "src").mkdir()
    secret = "typed-" + "credential"
    (tmp_path / "src" / "client.py").write_text(
        "from typing import Optional\n"
        "def connect(\n"
        '    api_key: str = "' + secret + '",\n'
        "):\n"
        "    return api_key\n"
        "async def async_connect(\n"
        '    password: str = "' + secret + '",\n'
        "):\n"
        "    return password\n"
        "def keyword_only(*,\n"
        '    token: str = "' + secret + '",\n'
        "):\n"
        "    return token\n"
        "def positional_only(\n"
        '    secret: str = "' + secret + '",\n'
        "    /,\n"
        "):\n"
        "    return secret\n"
        "token: Optional[str]\n"
        "api_key: str\n"
        'payload = {"token": token_value}\n',
        encoding="utf-8",
    )

    violations = project_privacy_violations(tmp_path)

    assert violations == (
        "src/client.py:3:api_key",
        "src/client.py:7:password",
        "src/client.py:11:token",
        "src/client.py:15:secret",
    )
    assert secret not in " ".join(violations)


def test_project_privacy_scan_uses_only_ast_string_literals_for_python(tmp_path: Path) -> None:
    from stock_tool.quality_gate import project_privacy_violations

    (tmp_path / "src").mkdir()
    secret = "real-" + "typed-secret"
    (tmp_path / "src" / "semantics.py").write_text(
        "from typing import Optional\n"
        "token = []\n"
        "api_key = {}\n"
        "password = 0\n"
        "secret = object()\n"
        "API_KEY = real-secret-value\n"
        "token: Optional[str]\n"
        "api_key: str\n"
        "password = password_value\n"
        "secret = None\n"
        'def connect(api_key: str = "' + secret + '"):\n'
        "    return api_key\n",
        encoding="utf-8",
    )

    violations = project_privacy_violations(tmp_path)

    assert violations == ("src/semantics.py:11:api_key",)
    assert secret not in " ".join(violations)


def test_project_privacy_scan_detects_toml_quoted_authorization_assignment(
    tmp_path: Path,
) -> None:
    from stock_tool.quality_gate import project_privacy_violations

    (tmp_path / "src").mkdir()
    secret = "toml-" + "credential"
    (tmp_path / "src" / "settings.toml").write_text(
        '"Authorization" = "Bearer ' + secret + '"\n' 'Authorization = "Basic ' + secret + '"\n',
        encoding="utf-8",
    )

    violations = project_privacy_violations(tmp_path)

    assert violations == (
        "src/settings.toml:1:authorization",
        "src/settings.toml:2:authorization",
    )
    assert secret not in " ".join(violations)


def test_project_privacy_scan_fails_closed_for_unparseable_python(
    tmp_path: Path,
) -> None:
    from stock_tool.quality_gate import project_privacy_violations

    (tmp_path / "src").mkdir()
    secret = "broken-" + "credential"
    (tmp_path / "src" / "broken.py").write_text(
        'def connect(api_key="' + secret + '"\n', encoding="utf-8"
    )

    violations = project_privacy_violations(tmp_path)

    assert violations == ("src/broken.py:1:unparseable_python",)
    assert secret not in " ".join(violations)
