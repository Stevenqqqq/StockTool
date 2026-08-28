"""Deterministic high-level integration tests for the v1.1 research journey.

These are automated application integrations, not browser automation.  All
provider outputs are explicit fixtures so no assertion depends on live market
data or network availability.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from stock_tool.application.analysis import AnalysisService
from stock_tool.application.data_hydration import DataHydrationService
from stock_tool.application.research_snapshot import (
    ResearchSourceMetadata,
    ResearchWorkspaceService,
)
from stock_tool.application.results import AnalysisRequest, DataHydrationRequest
from stock_tool.backtest import BacktestEngine, BrokerConfig
from stock_tool.data.contracts import (
    DataSourceMetadata,
    DataSourceType,
    ProviderAttemptRecord,
    ProviderResult,
    provider_failure_result,
    provider_result_from_price_frame,
)
from stock_tool.domain.models import Market, Symbol
from stock_tool.indicators import add_atr, add_macd, add_rolling_return, add_rsi, add_sma
from stock_tool.reports import ReportData, generate_excel_report
from stock_tool.stock_scoring import score_stock


@dataclass(slots=True)
class _StaticProvider:
    result: ProviderResult[pd.DataFrame]

    def load_price_result(self) -> ProviderResult[pd.DataFrame]:
        return self.result


@dataclass(slots=True)
class _Resolver:
    results: dict[Symbol, ProviderResult[pd.DataFrame]]

    def resolve(self, request: DataHydrationRequest) -> _StaticProvider:
        return _StaticProvider(self.results[request.symbol])


def _prices(symbol: Symbol) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=90, freq="B")
    closes = [100.0 + index * 0.4 for index in range(len(dates))]
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": [symbol.code] * len(dates),
            "open": [value - 0.2 for value in closes],
            "high": [value + 0.8 for value in closes],
            "low": [value - 0.8 for value in closes],
            "close": closes,
            "volume": [10_000 + index for index in range(len(dates))],
            "adjusted_close": closes,
        }
    )


def _provider_result(
    symbol: Symbol,
    *,
    source_type: DataSourceType = DataSourceType.SAMPLE,
    attempts: tuple[ProviderAttemptRecord, ...] = (),
) -> ProviderResult[pd.DataFrame]:
    suffix = {Market.TWSE: ".TW", Market.TPEX: ".TWO", Market.US: ""}[symbol.market]
    return provider_result_from_price_frame(
        _prices(symbol),
        metadata=DataSourceMetadata(
            provider="journey-fixture",
            source_type=source_type,
            requested_symbol=symbol,
            resolved_symbol=symbol,
            provider_symbol=f"{symbol.code}{suffix}",
            request_start="2024-01-01",
            request_end="2024-12-31",
        ),
        attempts=attempts
        or (ProviderAttemptRecord("journey-fixture", True, "controlled fixture data"),),
    )


def _indicators(prices: pd.DataFrame) -> pd.DataFrame:
    output = add_sma(prices, periods=(20, 60))
    output = add_rsi(output)
    output = add_macd(output)
    output = add_atr(output)
    return add_rolling_return(output, periods=(20,))


def _service(results: dict[Symbol, ProviderResult[pd.DataFrame]]) -> AnalysisService:
    return AnalysisService(
        hydration_service=DataHydrationService(
            provider_resolver=_Resolver(results),
            clock=lambda: datetime(2025, 1, 2, tzinfo=timezone.utc),
            run_id_factory=lambda: "journey-run",
        ),
        indicator_calculator=_indicators,
        stock_scorer=score_stock,
    )


def _source_metadata(result: object) -> ResearchSourceMetadata:
    metadata = result.hydration.metadata.source  # type: ignore[attr-defined]
    return ResearchSourceMetadata(
        provider=metadata.provider,
        query_symbol=metadata.provider_symbol,
        market=metadata.resolved_symbol.market.value,
        source_type=metadata.source_type.value,
        fetched_at="2025-01-02T00:00:00+00:00",
        last_data_date=result.hydration.metadata.last_data_date,  # type: ignore[attr-defined]
        row_count=result.hydration.metadata.output_rows,  # type: ignore[attr-defined]
    )


@pytest.mark.parametrize(
    ("code", "market", "provider_symbol"),
    [
        ("2330", Market.TWSE, "2330.TW"),
        ("6488", Market.TPEX, "6488.TWO"),
        ("AAPL", Market.US, "AAPL"),
    ],
)
def test_research_journey_resolves_three_markets_and_keeps_partial_scores_honest(
    code: str,
    market: Market,
    provider_symbol: str,
) -> None:
    symbol = Symbol(code, market)
    analysis = _service({symbol: _provider_result(symbol)}).analyze(
        AnalysisRequest(DataHydrationRequest(symbol, "2024-01-01", "2024-12-31"))
    )
    snapshot = ResearchWorkspaceService().build(
        symbol=symbol,
        price_data=analysis.hydration.data,
        indicators=analysis.indicators,
        fundamental_results=analysis.fundamental_scores,
        stock_score=analysis.stock_score,
        company_profile=None,
        scenario_reference=None,
        source_metadata=_source_metadata(analysis),
        missing_data=analysis.missing_data,
        warnings=analysis.warnings,
        limitations=analysis.limitations,
    )

    assert analysis.symbol == symbol
    assert analysis.hydration.metadata.source.provider_symbol == provider_symbol
    assert snapshot.symbol == symbol
    assert snapshot.source_metadata.query_symbol == provider_symbol
    assert snapshot.source_metadata.source_type == DataSourceType.SAMPLE.value
    assert snapshot.price is not None
    assert snapshot.score_coverage is not None
    assert snapshot.composite_score is None
    assert snapshot.status.value == "partial"
    assert any(item.field == "fundamental_data" for item in snapshot.missing_data)


def test_cache_fallback_is_visible_and_provider_error_never_fabricates_a_score() -> None:
    symbol = Symbol("AAPL", Market.US)
    cache_result = _provider_result(
        symbol,
        source_type=DataSourceType.CACHE,
        attempts=(
            ProviderAttemptRecord("yfinance", False, "controlled online failure"),
            ProviderAttemptRecord("journey-cache", True, "controlled cache fallback"),
        ),
    )
    cache_analysis = _service({symbol: cache_result}).analyze(
        AnalysisRequest(DataHydrationRequest(symbol, "2024-01-01", "2024-12-31"))
    )
    failed = provider_failure_result(
        metadata=cache_result.metadata,
        message="controlled provider failure",
    )
    failed_analysis = _service({symbol: failed}).analyze(
        AnalysisRequest(DataHydrationRequest(symbol, "2024-01-01", "2024-12-31"))
    )

    assert cache_analysis.hydration.metadata.source.source_type is DataSourceType.CACHE
    assert cache_analysis.hydration.metadata.cache_hit is True
    assert cache_analysis.stock_score is not None
    assert failed_analysis.status.value == "error"
    assert failed_analysis.stock_score is None


def test_research_journey_preserves_t_plus_one_costs_benchmark_and_report_provenance(
    tmp_path: Path,
) -> None:
    symbol = Symbol("2330", Market.TWSE)
    analysis = _service({symbol: _provider_result(symbol)}).analyze(
        AnalysisRequest(DataHydrationRequest(symbol, "2024-01-01", "2024-12-31"))
    )
    assert analysis.hydration.data is not None
    prices = analysis.hydration.data
    signals = pd.DataFrame(
        [{"date": prices.iloc[10]["date"], "symbol": "2330", "signal": 1, "quantity": 10}]
    )
    backtest = BacktestEngine(
        initial_cash=100_000,
        broker_config=BrokerConfig(commission_rate=0.001, tax_rate=0.003, slippage_rate=0.001),
    ).run(prices, signals, benchmark=prices)
    output = generate_excel_report(
        ReportData(
            symbol="2330",
            analysis_date="2025-01-02",
            price_data=prices,
            technical_indicators=analysis.indicators,
            fundamental_scores=analysis.fundamental_scores,
            backtest_result=backtest,
            parameters={
                "data_source": analysis.hydration.metadata.source.source_type.value,
                "provider": analysis.hydration.metadata.source.provider,
                "data_period": "2024-01-01 to 2024-12-31",
                "execution_rule": "T+1 next bar",
                "commission_rate": 0.001,
                "tax_rate": 0.003,
                "slippage_rate": 0.001,
            },
        ),
        tmp_path / "journey.xlsx",
    )

    assert backtest.trades
    assert backtest.trades[0].signal_date < backtest.trades[0].execution_date
    assert backtest.trades[0].commission > 0
    assert backtest.metrics.benchmark_total_return is not None
    assert output.exists()
