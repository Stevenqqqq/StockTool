"""Sprint 19 security/readiness contracts that do not require network access."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from uuid import UUID

from stock_tool.quality_gate import project_privacy_violations
from stock_tool.release_archive import archive_forbidden_entries

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_sbom_module():
    spec = importlib.util.spec_from_file_location(
        "stocktool_generate_sbom", PROJECT_ROOT / "scripts" / "generate_sbom.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_readiness_documents_preserve_non_release_boundary() -> None:
    for filename in ("SECURITY.md", "PRIVACY.md", "THIRD_PARTY_LICENSES.md"):
        assert (PROJECT_ROOT / filename).is_file()
    checklist = (PROJECT_ROOT / "docs" / "release" / "v3-checklist.md").read_text(encoding="utf-8")
    assert checklist.count("DEFERRED BY PRODUCT OWNER / NOT EXECUTED") == 3
    assert "release/StockTool" in checklist


def test_privacy_disclosure_distinguishes_market_data_and_optional_ai_payloads() -> None:
    privacy = (PROJECT_ROOT / "PRIVACY.md").read_text(encoding="utf-8")
    assert "date range" in privacy
    assert "interval" in privacy
    assert "bounded EvidenceBundle" in privacy
    assert "private-document contents or paths" in privacy
    assert "Local-rules mode does not call" in privacy
    assert "limited to the symbol and market" not in privacy


def test_machine_readable_sbom_comes_from_installed_distribution_metadata(tmp_path: Path) -> None:
    sbom = _load_sbom_module()
    payload = sbom.build_sbom()
    names = {component["name"].lower() for component in payload["components"]}
    assert {"pandas", "streamlit", "yfinance"}.issubset(names)
    destination = tmp_path / "sbom.json"
    destination.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    reread = json.loads(destination.read_text(encoding="utf-8"))
    assert reread["bomFormat"] == "CycloneDX"
    assert reread["specVersion"] == "1.5"
    assert reread["serialNumber"].startswith("urn:uuid:")
    UUID(reread["serialNumber"].removeprefix("urn:uuid:"))


def test_release_and_archive_scans_reject_runtime_private_data() -> None:
    names = (
        ".env",
        "portfolio.csv",
        "watchlist.csv",
        "data/cache/price.csv",
        ".streamlit/secrets.toml",
    )
    assert set(names).issubset(archive_forbidden_entries(names))
    assert project_privacy_violations(PROJECT_ROOT) == ()
