"""Deterministic performance contracts for Sprint 19 readiness evidence.

The full three-run machine-readable hard gate lives in
``scripts/measure_performance.py``. These focused tests retain the same fixed
workloads with the corresponding per-run safety limits.
"""

from __future__ import annotations

import time

import pandas as pd

from stock_tool.indicators import add_atr, add_macd, add_rolling_return, add_rsi, add_sma
from stock_tool.reports import ReportData, generate_excel_report
from stock_tool.stock_scoring import score_stock


def _large_prices(rows: int = 12_000) -> pd.DataFrame:
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


def test_large_dataset_indicators_and_score_are_deterministic() -> None:
    prices = _large_prices()
    started = time.perf_counter()
    indicators = add_rolling_return(
        add_atr(add_macd(add_rsi(add_sma(prices, periods=(20, 60))))), periods=(20,)
    )
    elapsed = time.perf_counter() - started
    result = score_stock(symbol="2330", price_data=prices, technical_indicators=indicators)

    assert len(indicators) == len(prices)
    assert result is not None
    assert elapsed <= 2.0


def test_large_dataset_excel_export_retains_reproducible_inputs(tmp_path) -> None:
    prices = _large_prices(rows=1_200)
    started = time.perf_counter()
    output = generate_excel_report(
        ReportData(
            symbol="2330",
            analysis_date="2025-01-02",
            price_data=prices,
            technical_indicators=prices,
            fundamental_scores=pd.DataFrame(),
            backtest_result=None,
            parameters={"data_source": "deterministic-fixture", "risk_notice": "research only"},
        ),
        tmp_path / "large-dataset.xlsx",
    )
    elapsed = time.perf_counter() - started

    assert output.is_file()
    assert output.stat().st_size > 0
    assert elapsed <= 5.0
