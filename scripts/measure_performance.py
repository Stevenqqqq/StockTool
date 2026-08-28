"""Run fixed-data Sprint 19.1.1 performance hard gates and write JSON evidence."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
import tracemalloc
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.evidence_launcher import run_evidence
from stock_tool.application.portfolio_risk import PortfolioRiskService
from stock_tool.indicators import add_atr, add_macd, add_rolling_return, add_rsi, add_sma
from stock_tool.portfolio_health import PortfolioHealthService
from stock_tool.portfolio_valuation import (
    Currency,
    FxQuote,
    PortfolioValuationService,
    StaticFxRateProvider,
)
from stock_tool.reports import ReportData, generate_excel_report
from stock_tool.research.assistant import (
    AIResearchAssistant,
    ClaimKind,
    EvidenceBundle,
    EvidenceRecord,
    ResearchAssistantCache,
)
from stock_tool.stock_scoring import score_stock

RUNS = 3
THRESHOLDS = {
    "indicators_scoring": 2.0,
    "excel_export": 5.0,
    "cached_research": 5.0,
    "portfolio_allocation_risk": 1.0,
    "exe_health_ready": 5.0,
}


@dataclass(frozen=True, slots=True)
class Measurement:
    name: str
    seconds: list[float]
    median_seconds: float
    max_seconds: float
    threshold_seconds: float
    passed: bool


def prices(rows: int) -> pd.DataFrame:
    dates = pd.date_range("1980-01-01", periods=rows, freq="B")
    close = pd.Series(range(rows), dtype="float64").mul(0.05).add(100.0)
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": "2330",
            "open": close - 0.2,
            "high": close + 0.8,
            "low": close - 0.8,
            "close": close,
            "adjusted_close": close,
            "volume": 10_000,
        }
    )


def _measure(name: str, operation) -> Measurement:
    elapsed: list[float] = []
    for _ in range(RUNS):
        started = time.perf_counter()
        operation()
        elapsed.append(time.perf_counter() - started)
    threshold = THRESHOLDS[name]
    return Measurement(
        name=name,
        seconds=elapsed,
        median_seconds=statistics.median(elapsed),
        max_seconds=max(elapsed),
        threshold_seconds=threshold,
        passed=max(elapsed) <= threshold,
    )


def _measure_allocation(operations) -> int:
    """Measure representative allocations without timing instrumentation overhead."""

    tracemalloc.start()
    try:
        for operation in operations:
            operation()
        _, peak_bytes = tracemalloc.get_traced_memory()
        return peak_bytes
    finally:
        tracemalloc.stop()


def _research_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        symbol="2330",
        market="TWSE",
        snapshot_fingerprint="sprint19.1.1-fixed-cache-fixture",
        evidence=(
            EvidenceRecord(
                evidence_id="close",
                kind=ClaimKind.FACT,
                label="最新收盤價",
                text="最新收盤價為 100。",
                source="deterministic-fixture",
                provider="deterministic-fixture",
                symbol="2330",
                market="TWSE",
                field="close",
                available_at="2026-07-29",
                fetched_at="2026-07-29T00:00:00+00:00",
            ),
        ),
    )


class _FixedResearchProvider:
    def generate(self, _bundle: EvidenceBundle) -> object:
        return {
            "claims": [
                {
                    "kind": "fact",
                    "section": "facts",
                    "text": "最新收盤價為 100。",
                    "citation_ids": ["close"],
                }
            ]
        }


def _portfolio_frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    portfolio = pd.DataFrame(
        {
            "symbol": ["2330", "AAPL", "6488", "UNCLASSIFIED"],
            "market": ["TWSE", "US", "TPEX", "US"],
            "currency": ["TWD", "USD", "TWD", "USD"],
            "quantity": [10.0, 2.0, 5.0, 1.0],
            "average_cost": [500.0, 100.0, 80.0, 20.0],
            "note": ["", "", "", ""],
        }
    )
    market_prices = pd.DataFrame(
        {
            "date": ["2026-07-20"] * 4,
            "symbol": ["2330", "AAPL", "6488", "UNCLASSIFIED"],
            "market": ["TWSE", "US", "TPEX", "US"],
            "close": [600.0, 120.0, 100.0, 30.0],
        }
    )
    classifications = pd.DataFrame(
        {
            "symbol": ["2330", "AAPL", "6488"],
            "market": ["TWSE", "US", "TPEX"],
            "sector": ["Semiconductors", "Technology", "Semiconductors"],
            "industry": ["Foundry", "Hardware", "Memory"],
            "source": ["fixture"] * 3,
            "as_of_date": ["2026-07-20"] * 3,
        }
    )
    return portfolio, market_prices, classifications


def _measure_exe_health(
    stable_entry: Path,
    evidence_root: Path,
    *,
    workspace_root: Path,
    real_user_root: Path,
    timing_output: Path,
) -> Measurement:
    elapsed: list[float] = []
    timing_output.mkdir(parents=True, exist_ok=True)
    for run in range(RUNS):
        run_evidence_root = evidence_root / f"guard-evidence-{run + 1}"
        result = run_evidence(
            candidate=stable_entry,
            evidence_root=run_evidence_root,
            real_user_root=real_user_root,
            workspace_root=workspace_root,
            # Keep the candidate alive briefly after readiness so the harness
            # can persist a complete launch/cleanup record.  This is not a
            # warm-up: health_ready_seconds is measured from process launch
            # and remains the hard-gate value for every cold run.
            duration_seconds=2,
            timeout_seconds=60,
            capture_startup_timing=True,
        )
        if result.status != "passed":
            raise RuntimeError(f"Guarded candidate health run failed: {result}")
        if result.health_ready_seconds is None:
            raise RuntimeError("Guarded candidate health run did not record readiness timing.")
        for name in ("startup-timing.jsonl", "launch.json", "guard-result.json", "cleanup.json"):
            source = run_evidence_root / name
            if source.is_file():
                shutil.copy2(source, timing_output / f"run-{run + 1}-{name}")
        elapsed.append(result.health_ready_seconds)
    threshold = THRESHOLDS["exe_health_ready"]
    return Measurement(
        name="exe_health_ready",
        seconds=elapsed,
        median_seconds=statistics.median(elapsed),
        max_seconds=max(elapsed),
        threshold_seconds=threshold,
        passed=max(elapsed) <= threshold,
    )


def run(output: Path, stable_entry: Path) -> dict[str, object]:
    fixed_prices = prices(12_000)
    export_prices = prices(1_200)
    with tempfile.TemporaryDirectory(prefix="stocktool-performance-") as temporary:
        temporary_root = Path(temporary)

        def indicators_operation() -> None:
            indicators = add_rolling_return(
                add_atr(add_macd(add_rsi(add_sma(fixed_prices, periods=(20, 60))))), periods=(20,)
            )
            if (
                score_stock(
                    symbol="2330",
                    price_data=fixed_prices,
                    technical_indicators=indicators,
                )
                is None
            ):
                raise RuntimeError("Fixed indicators fixture did not score.")

        def export_operation() -> None:
            destination = temporary_root / "large-dataset.xlsx"
            generate_excel_report(
                ReportData(
                    symbol="2330",
                    analysis_date="2026-07-29",
                    price_data=export_prices,
                    technical_indicators=export_prices,
                    fundamental_scores=pd.DataFrame(),
                    backtest_result=None,
                    parameters={"data_source": "deterministic-fixture"},
                ),
                destination,
            )
            if not destination.is_file():
                raise RuntimeError("Excel fixture was not written.")

        cache = ResearchAssistantCache(temporary_root / "cache")
        assistant = AIResearchAssistant(cache=cache, provider=_FixedResearchProvider())
        bundle = _research_bundle()
        assistant.generate(bundle)

        def cached_research_operation() -> None:
            if assistant.generate(bundle).mode != "ai":
                raise RuntimeError("Fixed research cache was not reused.")

        portfolio, market_prices, classifications = _portfolio_frames()
        fx_quote = FxQuote.manual(Currency.USD, Currency.TWD, 32.0, "2026-07-20T00:00:00+00:00")

        def portfolio_operation() -> None:
            valuation = PortfolioValuationService(StaticFxRateProvider([fx_quote])).value(
                positions=portfolio, prices=market_prices
            )
            health = PortfolioHealthService().assess(portfolio=portfolio, valuation=valuation)
            result = PortfolioRiskService().assess(
                portfolio=portfolio,
                prices=market_prices,
                valuation=valuation,
                health=health,
                classifications=classifications,
            )
            if result.total_portfolio_value is None:
                raise RuntimeError("Fixed portfolio fixture was not valued.")

        measurements = [
            _measure("indicators_scoring", indicators_operation),
            _measure("excel_export", export_operation),
            _measure("cached_research", cached_research_operation),
            _measure("portfolio_allocation_risk", portfolio_operation),
            _measure_exe_health(
                stable_entry,
                temporary_root / "guard-evidence",
                workspace_root=Path.cwd(),
                real_user_root=Path(os.environ.get("LOCALAPPDATA", "")) / "StockTool",
                timing_output=output.parent / "cold-start-timing",
            ),
        ]
        peak_bytes = _measure_allocation(
            [
                indicators_operation,
                export_operation,
                cached_research_operation,
                portfolio_operation,
            ]
        )
    allocation_passed = peak_bytes <= 512 * 1024 * 1024
    result = {
        "schema_version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "runs_per_measurement": RUNS,
        "measurements": [asdict(item) for item in measurements],
        "allocation_peak_bytes": peak_bytes,
        "allocation_threshold_bytes": 512 * 1024 * 1024,
        "allocation_passed": allocation_passed,
        "passed": allocation_passed and all(item.passed for item in measurements),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stable-entry", type=Path, required=True)
    arguments = parser.parse_args()
    result = run(arguments.output, arguments.stable_entry)
    print(json.dumps({"passed": result["passed"], "output": str(arguments.output)}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
