from __future__ import annotations

from dataclasses import dataclass

from stock_tool.stock_scoring import (
    FORBIDDEN_PHRASES,
    score_components_frame,
    score_stock,
    strategy_health_check,
)

import pandas as pd


def _indicator_frame() -> pd.DataFrame:
    rows = []
    for index in range(80):
        close = 100.0 + index
        rows.append(
            {
                "date": f"2024-03-{(index % 28) + 1:02d}",
                "symbol": "2330",
                "open": close - 1,
                "high": close + 1,
                "low": close - 2,
                "close": close,
                "volume": 1000 + index,
                "adjusted_close": close,
                "sma_20": close - 2,
                "sma_60": close - 5,
                "rsi_14": 55.0,
                "macd_dif": 2.0,
                "macd_dea": 1.0,
                "return_20": 0.10,
                "volatility_20": 0.01,
                "atr_14": 2.0,
            }
        )
    return pd.DataFrame(rows)


def _fundamental_scores() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["2330"],
            "growth_score": [25.0],
            "profitability_score": [25.0],
            "financial_safety_score": [20.0],
            "valuation_score": [15.0],
            "cashflow_score": [10.0],
            "strengths": ["Revenue growth is strong"],
            "weaknesses": ["PB ratio should be reviewed"],
            "missing_data": [""],
            "risk_notes": ["research only"],
        }
    )


def test_score_stock_returns_complete_weighted_score_when_all_components_exist() -> None:
    indicators = _indicator_frame()

    result = score_stock(
        symbol="2330",
        price_data=indicators,
        technical_indicators=indicators,
        fundamental_scores=_fundamental_scores(),
    )

    assert result.total_score != "unknown"
    assert 0 <= float(result.total_score) <= 100
    assert result.technical_score == 30.0
    assert result.fundamental_score == 30.0
    assert result.valuation_score == 15.0
    assert result.coverage == 1.0
    assert "個人化投資建議" in " ".join(result.risk_notes)


def test_score_stock_keeps_numeric_score_when_only_dividend_yield_is_missing() -> None:
    fundamentals = _fundamental_scores()
    fundamentals.loc[0, "valuation_score"] = 8.0
    fundamentals.loc[0, "missing_data"] = "dividend_yield"
    indicators = _indicator_frame()

    result = score_stock(
        symbol="2330",
        price_data=indicators,
        technical_indicators=indicators,
        fundamental_scores=fundamentals,
    )

    assert result.total_score != "unknown"
    assert "dividend_yield" in result.missing_data
    valuation = next(component for component in result.components if component.name == "估值面")
    assert "dividend_yield" in valuation.missing_data


def test_score_stock_does_not_fake_total_when_fundamentals_are_missing() -> None:
    indicators = _indicator_frame()

    result = score_stock(
        symbol="2330",
        price_data=indicators,
        technical_indicators=indicators,
        fundamental_scores=None,
    )

    assert result.total_score == "unknown"
    assert result.available_score != "unknown"
    assert result.coverage < 1.0
    assert "fundamental_scores" in result.missing_data
    assert "valuation_score" in result.missing_data


def test_score_components_frame_contains_all_four_weights() -> None:
    result = score_stock(
        symbol="2330",
        price_data=_indicator_frame(),
        technical_indicators=_indicator_frame(),
        fundamental_scores=_fundamental_scores(),
    )

    frame = score_components_frame(result)

    assert frame["component"].tolist() == ["技術面", "基本面", "估值面", "風險面"]
    assert frame["weight"].sum() == 100.0


@dataclass(frozen=True)
class _Metrics:
    number_of_trades: int = 3
    max_drawdown: float = -0.18
    sharpe_ratio: float = 0.4
    profit_factor: float = 0.9
    benchmark_excess_return: float | None = None


@dataclass(frozen=True)
class _BacktestResult:
    metrics: _Metrics


def test_strategy_health_check_reports_risks_without_forbidden_language() -> None:
    notes = strategy_health_check(_BacktestResult(metrics=_Metrics()))
    text = " ".join(notes)

    assert "交易次數偏少" in text
    assert "最大回撤" in text
    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in text
