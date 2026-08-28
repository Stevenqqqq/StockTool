"""Fail-closed local quality gate for the approved StockTool release candidate."""

from __future__ import annotations

import ast
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

MIN_BRANCH_COVERAGE = 82.71
COVERAGE_REPORT_FILE = "coverage.json"

SPRINT19_1_CHANGED_FILES = (
    "src/stock_tool/release_manifest.py",
    "src/stock_tool/installer_build.py",
    "src/stock_tool/version_resource.py",
    "src/stock_tool/release_archive.py",
    "src/stock_tool/release_assets.py",
    "src/stock_tool/stable_entry.py",
    "src/stock_tool/quality_gate.py",
    "launcher.py",
    "stable_launcher.py",
    "StockTool.spec",
    "StableLauncher.spec",
    "build_exe.bat",
    "build_installer.bat",
    "installer/StockTool.iss",
    "scripts/verify_installer_lifecycle.ps1",
    "tests/test_installer_manifest.py",
    "tests/test_user_data_paths.py",
    "tests/test_release_layout.py",
    "tests/test_runtime_paths.py",
    "tests/test_release_assets.py",
    "tests/test_exe_smoke.py",
    "tests/test_launcher.py",
    "tests/test_quality_gate.py",
    "tests/test_dashboard_navigation.py",
    "tests/test_release_archive.py",
    "tests/test_stable_entry.py",
    "tests/test_stable_launcher.py",
    "src/stock_tool/dashboard/components/research_chart.py",
    "src/stock_tool/application/portfolio_workspace.py",
    "src/stock_tool/application/settings_workspace.py",
    "src/stock_tool/application/__init__.py",
    "src/stock_tool/dashboard/pages/portfolio_workspace.py",
    "src/stock_tool/dashboard/pages/settings_workspace.py",
    "src/stock_tool/dashboard/app.py",
    "src/stock_tool/dashboard/shell.py",
    "src/stock_tool/dashboard/state.py",
    "src/stock_tool/dashboard/pages/library.py",
    "src/stock_tool/dashboard/pages/research.py",
    "src/stock_tool/dashboard/pages/strategy_workspace.py",
    "src/stock_tool/application/research_context.py",
    "src/stock_tool/application/market_monitor.py",
    "src/stock_tool/application/daily_research_brief.py",
    "src/stock_tool/runtime_paths.py",
    "src/stock_tool/dashboard/pages/discovery.py",
    "src/stock_tool/dashboard/pages/home.py",
    "src/stock_tool/application/daily_research_scheduler.py",
    "src/stock_tool/application/daily_research_runner.py",
    "src/stock_tool/application/prediction_lab.py",
    "src/stock_tool/application/daily_research_inbox.py",
    "src/stock_tool/application/daily_research_changes.py",
    "src/stock_tool/application/macro_snapshot.py",
    "scripts/verify_evidence_bundle.py",
    "scripts/verify_artifact_hash_index.py",
    "scripts/sprint30_2_1_installer_lifecycle.py",
    "tests/test_daily_research_changes.py",
    "tests/test_evidence_bundle_verifier.py",
    "tests/test_macro_snapshot.py",
    "tests/test_artifact_hash_index.py",
    "tests/test_sprint30_2_1_installer_lifecycle.py",
    "tests/test_daily_research_scheduler.py",
    "tests/test_daily_research_runner.py",
    "tests/test_daily_schedule_ui.py",
    "tests/test_daily_research_inbox.py",
    "scripts/generate_sbom.py",
    "scripts/measure_performance.py",
    "scripts/browser_transport_harness.py",
    "scripts/evidence_launcher.py",
    "scripts/sprint20_evidence.py",
    "scripts/verify_sprint26_2_task.py",
    "tests/security/test_release_readiness.py",
    "tests/performance/test_large_dataset.py",
    "tests/e2e/test_product_acceptance.py",
    "tests/test_research_workspace.py",
    "tests/test_portfolio_workspace.py",
    "tests/test_settings_workspace.py",
    "tests/test_roadmap_structure.py",
    "tests/test_evidence_launcher.py",
    "tests/test_research_context.py",
    "tests/test_research_handoff.py",
    "tests/test_market_monitor.py",
    "tests/test_daily_research_brief.py",
    "tests/test_daily_brief.py",
    "tests/test_daily_research_loop.py",
    "tests/test_daily_home.py",
    "tests/test_prediction_lab.py",
    "tests/test_research_assistant.py",
    "tests/test_research_assistant_dashboard.py",
    "SECURITY.md",
    "PRIVACY.md",
    "THIRD_PARTY_LICENSES.md",
    "docs/release/v3-checklist.md",
    "docs/product/social-reference-backlog.md",
    "requirements/stocktool-runtime-constraints.txt",
)
SPRINT19_1_FORMAT_FILES = tuple(path for path in SPRINT19_1_CHANGED_FILES if path.endswith(".py"))
# Compatibility aliases retain the public import surface used by Sprint 18
# tests while the actual gate is scoped to the approved Sprint 19.1 work.
SPRINT18_CHANGED_FILES = SPRINT19_1_CHANGED_FILES
SPRINT18_FORMAT_FILES = SPRINT19_1_FORMAT_FILES


@dataclass(frozen=True, slots=True)
class GateStep:
    """One named command in the deterministic local quality-gate sequence."""

    name: str
    command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QualityGateResult:
    """Public result for one complete or fail-closed local gate run."""

    exit_code: int
    failed_step: str | None
    completed_steps: tuple[str, ...]


def quality_gate_steps(python: str | None = None) -> tuple[GateStep, ...]:
    """Return the fixed gate order without build, publish, Git, or network steps."""

    executable = python or sys.executable
    return (
        GateStep(
            "sprint19_1_targeted",
            (
                executable,
                "-m",
                "pytest",
                "-q",
                "tests/test_installer_manifest.py",
                "tests/test_user_data_paths.py",
                "tests/test_release_layout.py",
                "tests/test_runtime_paths.py",
                "tests/test_release_assets.py",
                "tests/test_exe_smoke.py",
                "tests/test_launcher.py",
                "tests/test_quality_gate.py",
                "tests/test_dashboard_navigation.py",
                "tests/test_release_archive.py",
                "tests/test_stable_entry.py",
                "tests/test_stable_launcher.py",
                "tests/security/test_release_readiness.py",
                "tests/performance/test_large_dataset.py",
                "tests/e2e/test_product_acceptance.py",
                "tests/test_research_workspace.py",
                "tests/test_portfolio_workspace.py",
                "tests/test_settings_workspace.py",
                "tests/test_roadmap_structure.py",
                "tests/test_evidence_launcher.py",
                "tests/test_research_context.py",
                "tests/test_research_handoff.py",
                "tests/test_market_monitor.py",
                "tests/test_daily_research_brief.py",
                "tests/test_daily_brief.py",
                "tests/test_daily_research_loop.py",
                "tests/test_daily_home.py",
                "tests/test_research_assistant.py",
                "tests/test_research_assistant_dashboard.py",
                "tests/test_daily_research_scheduler.py",
                "tests/test_daily_research_runner.py",
                "tests/test_daily_schedule_ui.py",
                "tests/test_daily_research_inbox.py",
                "tests/test_daily_research_changes.py",
                "tests/test_evidence_bundle_verifier.py",
                "tests/test_macro_snapshot.py",
                "tests/test_artifact_hash_index.py",
                "tests/test_sprint30_2_1_installer_lifecycle.py",
            ),
        ),
        GateStep(
            "full_pytest",
            (
                executable,
                "-m",
                "pytest",
                "-q",
                "--cov=stock_tool",
                "--cov-branch",
                "--cov-report=term",
                f"--cov-report=json:{COVERAGE_REPORT_FILE}",
            ),
        ),
        GateStep(
            "branch_coverage",
            (
                executable,
                "-m",
                "stock_tool.quality_gate",
                "--verify-coverage",
                COVERAGE_REPORT_FILE,
            ),
        ),
        GateStep("black", (executable, "-m", "black", "--check", *SPRINT19_1_FORMAT_FILES)),
        GateStep("ruff", (executable, "-m", "ruff", "check", *SPRINT19_1_FORMAT_FILES)),
        GateStep(
            "focused_mypy",
            (
                executable,
                "-m",
                "mypy",
                "--ignore-missing-imports",
                "src/stock_tool/release_manifest.py",
                "src/stock_tool/installer_build.py",
                "src/stock_tool/release_archive.py",
                "src/stock_tool/quality_gate.py",
                "src/stock_tool/application/daily_research_brief.py",
                "src/stock_tool/release_assets.py",
                "src/stock_tool/stable_entry.py",
                "launcher.py",
                "stable_launcher.py",
                "tests/test_installer_manifest.py",
                "tests/test_user_data_paths.py",
                "tests/test_release_layout.py",
                "tests/test_runtime_paths.py",
                "tests/test_release_assets.py",
                "tests/test_exe_smoke.py",
                "tests/test_quality_gate.py",
                "tests/test_launcher.py",
                "tests/test_dashboard_navigation.py",
                "tests/test_release_archive.py",
                "tests/test_stable_entry.py",
                "tests/test_stable_launcher.py",
                "src/stock_tool/dashboard/components/research_chart.py",
                "scripts/generate_sbom.py",
                "scripts/measure_performance.py",
                "scripts/browser_transport_harness.py",
                "scripts/evidence_launcher.py",
                "scripts/sprint20_evidence.py",
                "scripts/verify_sprint26_2_task.py",
                "tests/security/test_release_readiness.py",
                "tests/performance/test_large_dataset.py",
                "tests/e2e/test_product_acceptance.py",
                "tests/test_research_workspace.py",
                "src/stock_tool/application/portfolio_workspace.py",
                "src/stock_tool/application/settings_workspace.py",
                "tests/test_evidence_launcher.py",
                "src/stock_tool/application/__init__.py",
                "src/stock_tool/dashboard/pages/portfolio_workspace.py",
                "src/stock_tool/dashboard/pages/settings_workspace.py",
                "src/stock_tool/dashboard/shell.py",
                "src/stock_tool/dashboard/state.py",
                "src/stock_tool/dashboard/pages/library.py",
                "src/stock_tool/dashboard/pages/research.py",
                "src/stock_tool/dashboard/pages/strategy_workspace.py",
                "src/stock_tool/application/research_context.py",
                "src/stock_tool/application/market_monitor.py",
                "src/stock_tool/runtime_paths.py",
                "src/stock_tool/dashboard/pages/discovery.py",
                "src/stock_tool/application/daily_research_scheduler.py",
                "src/stock_tool/application/daily_research_runner.py",
                "src/stock_tool/application/daily_research_inbox.py",
                "src/stock_tool/application/daily_research_changes.py",
                "src/stock_tool/application/macro_snapshot.py",
                "scripts/verify_evidence_bundle.py",
                "scripts/verify_artifact_hash_index.py",
                "scripts/sprint30_2_1_installer_lifecycle.py",
                "tests/test_daily_research_changes.py",
                "tests/test_evidence_bundle_verifier.py",
                "tests/test_macro_snapshot.py",
                "tests/test_artifact_hash_index.py",
                "tests/test_sprint30_2_1_installer_lifecycle.py",
                "tests/test_daily_research_scheduler.py",
                "tests/test_daily_schedule_ui.py",
                "tests/test_daily_research_inbox.py",
            ),
        ),
        GateStep("python_compile", (executable, "-m", "compileall", "-q", "src")),
        GateStep(
            "project_privacy_scan",
            (
                executable,
                "-c",
                "from pathlib import Path; from stock_tool.quality_gate import project_privacy_violations; "
                "violations=project_privacy_violations(Path('.')); "
                "print('privacy violations:', len(violations)); raise SystemExit(bool(violations))",
            ),
        ),
        GateStep(
            "release_layout",
            (
                executable,
                "-c",
                "from pathlib import Path; from stock_tool.release_assets import validate_release_source_assets; "
                "validate_release_source_assets(Path('.'))",
            ),
        ),
        GateStep(
            "regression_baseline",
            (
                executable,
                "-m",
                "pytest",
                "-q",
                "tests/test_dashboard_shell.py",
                "tests/test_serenity_agent.py",
                "tests/test_portfolio_ledger.py",
            ),
        ),
    )


def project_privacy_violations(root: Path) -> tuple[str, ...]:
    """Fail closed on forbidden archive inputs or credential-bearing source text.

    Findings intentionally identify only the path, one-based line number, and
    category.  They never include the matched value in test output or logs.
    """

    root = root.resolve()
    violations: list[str] = []
    # The source archive is the product-rebuild boundary. Scanning only its
    # explicit allowlist avoids false positives from historical acceptance
    # artifacts and source modules with ordinary names such as ``reports``.
    from stock_tool.release_archive import _archive_files

    candidates = list(_archive_files(root))
    private_env = root / ".env"
    if private_env.is_file():
        candidates.append(private_env)
    for candidate in candidates:
        relative = candidate.relative_to(root).as_posix()
        name = candidate.name.lower()
        if name == ".env" or name.startswith("secrets") and name.endswith(".toml"):
            violations.append(relative)
        elif name in {
            "portfolio.csv",
            "watchlist.csv",
            "stock_data.sqlite",
        }:
            violations.append(relative)
        elif relative.startswith("tests/"):
            # Regression fixtures intentionally exercise sanitization. They are
            # not release runtime inputs, while production/text configuration
            # candidates remain fail-closed below.
            continue
        else:
            violations.extend(_content_secret_violations(candidate, relative))

    def violation_key(violation: str) -> tuple[str, int, str]:
        fields = violation.rsplit(":", 2)
        if len(fields) != 3:
            return violation, 0, ""
        path, line_number, category = fields
        return path, int(line_number) if line_number.isdigit() else 0, category

    return tuple(sorted(set(violations), key=violation_key))


_ASSIGNMENT_RE = re.compile(r"""(?ix)
    (?<![\w-])["']?(?P<key>api[_-]?key|token|password|secret)["']?(?![\w-])
    \s*(?::|=(?!=))\s*
    (?:
        "(?P<double>[^\"]*)"
        | '(?P<single>[^']*)'
        | (?P<bare>[^\s#,:}\]\\)]*)
    )
    """)
_AUTHORIZATION_RE = re.compile(r"""(?ix)
    (?<![\w-])(?:["']authorization["']|authorization)(?![\w-])\s*(?::|=)\s*
    (?:
        "(?:bearer|basic)\s+(?P<double>[^\"]*)"
        | '(?:bearer|basic)\s+(?P<single>[^']*)'
        | (?:bearer|basic)\s+(?P<bare>[^\s#,:}\]\\)]+)
    )
    """)
_URL_CREDENTIAL_RE = re.compile(r"(?i)https?://[^\s/@:]+:([^\s@]+)@")


def _content_secret_violations(candidate: Path, relative: str) -> list[str]:
    """Return redacted credential findings for text archive candidates only."""

    if candidate.suffix.lower() not in {
        ".py",
        ".toml",
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
        ".ini",
        ".cfg",
        ".bat",
        ".md",
        ".txt",
        "",
    }:
        return []
    try:
        text = candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [f"{relative}:0:unreadable_text_candidate"]
    if candidate.suffix.lower() == ".py":
        return _python_content_secret_violations(text, relative)

    lines = text.splitlines()
    findings: list[str] = []
    for line_number, line in enumerate(lines, start=1):
        for match in _ASSIGNMENT_RE.finditer(line):
            value = _matched_value(match)
            if (
                not _matched_is_quoted(match)
                and candidate.suffix.lower() == ".py"
                and value.isidentifier()
            ):
                # Python annotations and dictionary values such as ``token``
                # are references, not embedded credential literals.
                continue
            if not _placeholder_value(value) and not value.startswith("os.getenv("):
                findings.append(
                    f"{relative}:{line_number}:{match.group('key').lower().replace('-', '_')}"
                )
        authorization = _AUTHORIZATION_RE.search(line)
        if authorization and not _placeholder_value(_matched_value(authorization)):
            findings.append(f"{relative}:{line_number}:authorization")
        if _URL_CREDENTIAL_RE.search(line):
            findings.append(f"{relative}:{line_number}:url_credentials")
    return findings


_CREDENTIAL_KEYS = {"api_key", "token", "password", "secret", "authorization"}


def _python_content_secret_violations(text: str, relative: str) -> list[str]:
    """Inspect Python credential literals with syntax-aware AST traversal."""

    try:
        tree = ast.parse(text, filename=relative)
    except SyntaxError as error:
        line_number = error.lineno or 0
        return [f"{relative}:{line_number}:unparseable_python"]

    findings: set[str] = set()

    def record(key: str | None, value_node: ast.AST | None) -> None:
        normalized_key = _credential_key(key)
        value = _string_literal(value_node)
        if (
            normalized_key is None
            or value is None
            or _placeholder_value(value)
            or value.startswith("os.getenv(")
        ):
            return
        line_number = getattr(value_node, "lineno", 0)
        findings.add(f"{relative}:{line_number}:{normalized_key}")

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            positional = [*node.args.posonlyargs, *node.args.args]
            default_offset = len(positional) - len(node.args.defaults)
            for argument, default in zip(
                positional[default_offset:], node.args.defaults, strict=False
            ):
                record(argument.arg, default)
            for argument, kw_default in zip(
                node.args.kwonlyargs, node.args.kw_defaults, strict=False
            ):
                if kw_default is not None:
                    record(argument.arg, kw_default)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                record(_python_target_name(target), node.value)
        elif isinstance(node, ast.AnnAssign):
            record(_python_target_name(node.target), node.value)
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=False):
                record(_string_literal(key), value)

    def finding_key(finding: str) -> tuple[str, int, str]:
        path, line_number, category = finding.rsplit(":", 2)
        return path, int(line_number), category

    return sorted(findings, key=finding_key)


def _credential_key(value: str | None) -> str | None:
    """Normalize a credential key and return it only for supported names."""

    if value is None:
        return None
    normalized = value.strip().lower().replace("-", "_")
    return normalized if normalized in _CREDENTIAL_KEYS else None


def _python_target_name(node: ast.AST) -> str | None:
    """Return a simple assignment target name without evaluating Python code."""

    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _string_literal(node: ast.AST | None) -> str | None:
    """Return a literal string value, excluding names, calls, and ``None``."""

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _matched_value(match: re.Match[str]) -> str:
    """Return the matched credential value without exposing it to callers."""

    for group in ("double", "single", "bare"):
        value = match.group(group)
        if value is not None:
            return value
    return ""


def _matched_is_quoted(match: re.Match[str]) -> bool:
    """Return whether the credential value was an explicit string literal."""

    return match.group("double") is not None or match.group("single") is not None


def coverage_percent_from_json(path: str | Path) -> float:
    """Read the unrounded total coverage percentage from a JSON report.

    The human-facing coverage report may round values for display.  The
    quality gate must instead compare the raw ``totals.percent_covered``
    value emitted by coverage.py, so values just below the floor cannot pass
    because they happen to display as the next integer.
    """

    report = Path(path)
    raw = report.read_bytes()
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        raise ValueError("coverage report must be UTF-8 without a BOM")
    payload: Any = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("coverage report must be a JSON object")
    totals = payload.get("totals")
    if not isinstance(totals, dict):
        raise ValueError("coverage report totals are missing")
    value = totals.get("percent_covered")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("coverage report percent_covered is invalid")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 100.0:
        raise ValueError("coverage report percent_covered is out of range")
    return result


def coverage_meets_floor(path: str | Path, minimum: float = MIN_BRANCH_COVERAGE) -> bool:
    """Return whether raw JSON coverage meets the exact configured floor."""

    try:
        value = coverage_percent_from_json(path)
    except (OSError, UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError):
        return False
    return value >= minimum


def _placeholder_value(value: str) -> bool:
    """Allow explicit empty/template values while rejecting real-looking credentials."""

    cleaned = value.strip().strip("'\"").lower()
    return (
        not cleaned
        or cleaned.startswith("${")
        or cleaned.startswith("{{")
        or cleaned.startswith("<")
        or cleaned
        in {
            "none",
            "null",
            "your_value_here",
            "replace_me",
            "changeme",
            "example",
            "placeholder",
        }
    )


def run_quality_gate(
    *,
    root: Path,
    runner: Callable[[GateStep], int] | None = None,
) -> QualityGateResult:
    """Run each required check exactly once and stop at the first nonzero exit."""

    def execute_steps(execute: Callable[[GateStep], int]) -> QualityGateResult:
        completed: list[str] = []
        for step in quality_gate_steps():
            code = execute(step)
            if code != 0:
                return QualityGateResult(code, step.name, tuple(completed))
            completed.append(step.name)
        return QualityGateResult(0, None, tuple(completed))

    if runner is not None:
        return execute_steps(runner)
    with tempfile.TemporaryDirectory(prefix="stocktool-quality-gate-") as temporary_root:
        return execute_steps(_subprocess_runner(root, user_data_dir=Path(temporary_root)))


def _subprocess_runner(
    root: Path, *, user_data_dir: Path | None = None
) -> Callable[[GateStep], int]:
    environment = os.environ.copy()
    if user_data_dir is not None:
        environment["STOCK_TOOL_USER_DATA_DIR"] = str(user_data_dir)

    def execute(step: GateStep) -> int:
        print(f"[quality-gate] {step.name}")
        return subprocess.run(
            step.command,
            cwd=root,
            check=False,
            env=environment,
        ).returncode

    return execute


def main(argv: Sequence[str] | None = None) -> int:
    """Run the local gate from the project root, returning its first failure code."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "--verify-coverage":
        report = arguments[1] if len(arguments) > 1 else COVERAGE_REPORT_FILE
        try:
            value = coverage_percent_from_json(report)
        except (OSError, UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError) as exc:
            print(f"[coverage] INVALID: {exc}")
            return 1
        print(f"[coverage] raw={value:.15f}; floor={MIN_BRANCH_COVERAGE:.2f}")
        return 0 if value >= MIN_BRANCH_COVERAGE else 1
    result = run_quality_gate(root=Path.cwd())
    if result.failed_step:
        print(f"[quality-gate] FAILED: {result.failed_step}")
    else:
        print("[quality-gate] PASSED")
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
