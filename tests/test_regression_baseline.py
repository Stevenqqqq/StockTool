from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from stock_tool import __version__
from stock_tool.backtest import BacktestEngine
from stock_tool.config import DEFAULT_FEATURE_FLAGS
from stock_tool.data.auto_fetch import normalize_yfinance_symbol
from stock_tool.data.cleaner import clean_price_data
from stock_tool.data.loader import STANDARD_COLUMNS, load_csv
from stock_tool.indicators import (
    add_atr,
    add_macd,
    add_rolling_return,
    add_rolling_volatility,
    add_rsi,
    add_sma,
)
from stock_tool.reports import ReportData
from stock_tool.reports.html import render_html_report
from stock_tool.stock_scoring import score_stock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PRICE_PATH = PROJECT_ROOT / "data" / "sample" / "sample_tw_prices_for_indicators.csv"
SAMPLE_FUNDAMENTAL_PATH = PROJECT_ROOT / "data" / "sample" / "sample_fundamental_scores.csv"
BASELINE_PATH = Path(__file__).parent / "fixtures" / "sprint1_baseline.json"

MARKET_CASES = (
    ("2330", "TWSE", "2330.TW"),
    ("6488", "TPEX", "6488.TWO"),
    ("AAPL", "US", "AAPL"),
)


def _sample_prices() -> pd.DataFrame:
    raw_rows = load_csv(SAMPLE_PRICE_PATH)
    cleaned = clean_price_data(raw_rows)
    return pd.DataFrame(cleaned.records)


def _sample_indicators(prices: pd.DataFrame) -> pd.DataFrame:
    indicators = add_sma(prices, periods=(20, 60))
    indicators = add_rsi(indicators)
    indicators = add_macd(indicators)
    indicators = add_atr(indicators)
    indicators = add_rolling_return(indicators, periods=(20,))
    return add_rolling_volatility(indicators, periods=(20,), annualize=False)


def _sample_fundamental_scores() -> pd.DataFrame:
    return pd.read_csv(SAMPLE_FUNDAMENTAL_PATH, dtype={"symbol": str})


def _baseline() -> dict[str, object]:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _market_acceptance() -> list[dict[str, object]]:
    return [
        {
            "input_symbol": input_symbol,
            "market": market,
            "query_symbol": normalize_yfinance_symbol(input_symbol, market=market),
            "source_type": "offline_symbol_contract_fixture",
            "available_columns": list(STANDARD_COLUMNS),
            "result_status": "validated",
        }
        for input_symbol, market, _ in MARKET_CASES
    ]


def test_sprint_one_baseline_preserves_sample_research_behavior() -> None:
    baseline = _baseline()
    raw_rows = load_csv(SAMPLE_PRICE_PATH)
    prices = _sample_prices()
    indicators = _sample_indicators(prices)
    fundamental_scores = _sample_fundamental_scores()
    score = score_stock(
        symbol="2330",
        price_data=prices,
        technical_indicators=indicators,
        fundamental_scores=fundamental_scores,
    )

    backtest_prices = prices.head(3).copy(deep=True)
    signal_date = str(backtest_prices.iloc[0]["date"])
    signals = pd.DataFrame(
        [{"date": signal_date, "symbol": "2330", "action": "buy", "quantity": 10}]
    )
    backtest = BacktestEngine(initial_cash=10_000).run(backtest_prices, signals)
    report_html = render_html_report(
        ReportData(
            symbol="2330",
            analysis_date="2024-12-31",
            price_data=prices,
            technical_indicators=indicators,
            fundamental_scores=fundamental_scores,
            backtest_result=backtest,
            parameters={"strategy": "sprint1.1-sample-baseline", "execution_price_col": "open"},
        )
    )
    latest = indicators.iloc[-1]

    actual = {
        "package_version": __version__,
        "feature_flags": {
            "legacy_dashboard_enabled": DEFAULT_FEATURE_FLAGS.legacy_dashboard_enabled,
            "research_workspace_enabled": DEFAULT_FEATURE_FLAGS.research_workspace_enabled,
        },
        "sample_data": {
            "price_file": "data/sample/sample_tw_prices_for_indicators.csv",
            "fundamental_file": "data/sample/sample_fundamental_scores.csv",
            "raw_price_rows": len(raw_rows),
            "clean_price_rows": len(prices),
            "symbol": str(prices.iloc[0]["symbol"]),
            "period_start": str(prices.iloc[0]["date"]),
            "period_end": str(prices.iloc[-1]["date"]),
            "latest_indicators": {
                "sma_20": round(float(latest["sma_20"]), 6),
                "sma_60": round(float(latest["sma_60"]), 6),
                "rsi_14": round(float(latest["rsi_14"]), 6),
                "macd_dif": round(float(latest["macd_dif"]), 6),
                "macd_dea": round(float(latest["macd_dea"]), 6),
                "atr_14": round(float(latest["atr_14"]), 6),
                "return_20": round(float(latest["return_20"]), 6),
                "volatility_20": round(float(latest["volatility_20"]), 6),
            },
        },
        "market_acceptance": _market_acceptance(),
        "stock_score": {
            "total_score": score.total_score,
            "available_score": score.available_score,
            "coverage": score.coverage,
            "technical_score": score.technical_score,
            "fundamental_score": score.fundamental_score,
            "valuation_score": score.valuation_score,
            "risk_score": score.risk_score,
            "rating_label": score.rating_label,
        },
        "backtest": {
            "trade_count": len(backtest.trades),
            "signal_date": backtest.trades[0].signal_date,
            "execution_date": backtest.trades[0].execution_date,
            "execution_price": round(backtest.trades[0].execution_price, 6),
            "ending_cash": round(backtest.portfolio.cash, 6),
            "total_return": round(backtest.metrics.total_return, 6),
        },
        "report_markers": {
            "has_history_disclaimer": "歷史績效不代表未來報酬" in report_html,
            "has_survivorship_warning": "存活者偏誤" in report_html,
            "has_trade_log": "交易紀錄" in report_html,
        },
    }

    assert actual == baseline


def test_sprint_one_market_acceptance_is_fixed_offline() -> None:
    baseline = _baseline()
    expected_cases = [
        {"input_symbol": symbol, "market": market, "query_symbol": query_symbol}
        for symbol, market, query_symbol in MARKET_CASES
    ]

    actual_cases = [
        {
            "input_symbol": case["input_symbol"],
            "market": case["market"],
            "query_symbol": case["query_symbol"],
        }
        for case in baseline["market_acceptance"]
    ]

    assert actual_cases == expected_cases
    assert _market_acceptance() == baseline["market_acceptance"]
