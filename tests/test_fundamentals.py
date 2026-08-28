from __future__ import annotations

from pathlib import Path
from time import monotonic

import pandas as pd
import pytest

import stock_tool.fundamentals.auto_fetch as fundamental_auto_fetch
from stock_tool.fundamentals import (
    FUNDAMENTAL_COLUMNS,
    FundamentalFetchError,
    FundamentalDataError,
    IndustryScoringProfile,
    MetricRule,
    fetch_yfinance_fundamentals,
    load_fundamentals_csv,
    score_fundamentals,
)


def test_load_fundamentals_csv_standardizes_sample() -> None:
    fundamentals = load_fundamentals_csv("data/sample/sample_fundamentals.csv")

    assert list(fundamentals.columns[: len(FUNDAMENTAL_COLUMNS)]) == list(FUNDAMENTAL_COLUMNS)
    assert fundamentals.loc[0, "symbol"] == "2330"
    assert fundamentals.loc[0, "fiscal_period"] == "2024Q4"
    assert fundamentals.loc[0, "revenue_growth_yoy"] == pytest.approx(0.18)
    assert pd.isna(fundamentals.loc[2, "revenue_growth_yoy"])


def test_load_fundamentals_normalizes_market_and_period_metadata(tmp_path: Path) -> None:
    source = tmp_path / "fundamentals.csv"
    source.write_text(
        "symbol,market,fiscal_period,period_type,as_of_date,revenue\n"
        "MU,us,2025-08-31,mixed,2026-07-13,100\n",
        encoding="utf-8",
    )

    fundamentals = load_fundamentals_csv(source)

    assert fundamentals.loc[0, "market"] == "US"
    assert fundamentals.loc[0, "period_type"] == "mixed"
    assert fundamentals.loc[0, "as_of_date"] == "2026-07-13"


def test_load_fundamentals_keeps_legacy_identity_explicitly_unknown(tmp_path: Path) -> None:
    source = tmp_path / "legacy.csv"
    source.write_text(
        "symbol,fiscal_period,revenue\nMU,2025-08-31,100\n",
        encoding="utf-8",
    )

    fundamentals = load_fundamentals_csv(source)

    assert fundamentals.loc[0, "market"] == "UNKNOWN"
    assert fundamentals.loc[0, "period_type"] == "unknown"
    assert pd.isna(fundamentals.loc[0, "as_of_date"])


def test_load_fundamentals_allows_same_symbol_and_period_in_different_markets(
    tmp_path: Path,
) -> None:
    source = tmp_path / "cross_market.csv"
    source.write_text(
        "symbol,market,fiscal_period,revenue\n"
        "DUP,US,2025-12-31,100\n"
        "DUP,TWSE,2025-12-31,200\n",
        encoding="utf-8",
    )

    fundamentals = load_fundamentals_csv(source)

    assert fundamentals[["symbol", "market"]].to_dict("records") == [
        {"symbol": "DUP", "market": "US"},
        {"symbol": "DUP", "market": "TWSE"},
    ]


def test_load_fundamentals_csv_raises_when_required_columns_missing(tmp_path: Path) -> None:
    csv_path = tmp_path / "bad_fundamentals.csv"
    csv_path.write_text("symbol,revenue\n2330,100\n", encoding="utf-8")

    with pytest.raises(FundamentalDataError, match="fiscal_period"):
        load_fundamentals_csv(csv_path)


def test_load_fundamentals_csv_rejects_blank_required_values(tmp_path: Path) -> None:
    csv_path = tmp_path / "blank_fundamentals.csv"
    csv_path.write_text(
        "symbol,fiscal_period,revenue\n,2024Q4,100\n2330,,200\n",
        encoding="utf-8",
    )

    with pytest.raises(FundamentalDataError, match="blank symbol"):
        load_fundamentals_csv(csv_path)


def test_load_fundamentals_csv_rejects_duplicate_symbol_period(tmp_path: Path) -> None:
    csv_path = tmp_path / "duplicate_fundamentals.csv"
    csv_path.write_text(
        "symbol,fiscal_period,revenue\n2330,2024Q4,100\n2330,2024Q4,200\n",
        encoding="utf-8",
    )

    with pytest.raises(FundamentalDataError, match="duplicate symbol/fiscal_period"):
        load_fundamentals_csv(csv_path)


def test_load_fundamentals_csv_supports_column_aliases(tmp_path: Path) -> None:
    csv_path = tmp_path / "alias_fundamentals.csv"
    csv_path.write_text(
        "股票代號,財報期間,營收年增率,EPS年增率,ROE,負債比\n" "2330,2024Q4,0.18,0.21,0.29,0.28\n",
        encoding="utf-8",
    )

    fundamentals = load_fundamentals_csv(csv_path)

    assert fundamentals.loc[0, "symbol"] == "2330"
    assert fundamentals.loc[0, "fiscal_period"] == "2024Q4"
    assert fundamentals.loc[0, "revenue_growth_yoy"] == pytest.approx(0.18)
    assert fundamentals.loc[0, "eps_growth_yoy"] == pytest.approx(0.21)
    assert fundamentals.loc[0, "roe"] == pytest.approx(0.29)
    assert fundamentals.loc[0, "debt_ratio"] == pytest.approx(0.28)


def test_score_fundamentals_returns_required_output_columns() -> None:
    fundamentals = pd.DataFrame(
        [
            {
                "symbol": "2330",
                "fiscal_period": "2024Q4",
                "revenue_growth_yoy": 0.18,
                "eps_growth_yoy": 0.21,
                "gross_margin": 0.54,
                "operating_margin": 0.42,
                "net_margin": 0.38,
                "roe": 0.29,
                "roa": 0.17,
                "debt_ratio": 0.28,
                "operating_cash_flow": 100.0,
                "free_cash_flow": 50.0,
                "pe_ratio": 22.5,
                "pb_ratio": 5.1,
                "dividend_yield": 0.018,
            }
        ]
    )

    scores = score_fundamentals(fundamentals)

    assert list(scores.columns) == [
        "symbol",
        "market",
        "fiscal_period",
        "period_type",
        "as_of_date",
        "total_score",
        "growth_score",
        "profitability_score",
        "financial_safety_score",
        "valuation_score",
        "cashflow_score",
        "strengths",
        "weaknesses",
        "missing_data",
        "risk_notes",
    ]
    assert scores.loc[0, "symbol"] == "2330"
    assert scores.loc[0, "growth_score"] == pytest.approx(25.0)
    assert scores.loc[0, "profitability_score"] == pytest.approx(25.0)
    assert scores.loc[0, "financial_safety_score"] == pytest.approx(20.0)
    assert scores.loc[0, "cashflow_score"] == pytest.approx(10.0)
    assert isinstance(scores.loc[0, "total_score"], float)
    assert "營收年增率" in scores.loc[0, "strengths"]
    assert "研究參考" in scores.loc[0, "risk_notes"]


def test_score_fundamentals_marks_missing_data_unknown() -> None:
    fundamentals = load_fundamentals_csv("data/sample/sample_fundamentals.csv")

    scores = score_fundamentals(fundamentals)
    missing_row = scores.loc[scores["symbol"] == "2454"].iloc[0]

    assert missing_row["total_score"] == "unknown"
    assert missing_row["growth_score"] == "unknown"
    assert missing_row["cashflow_score"] == "unknown"
    assert "revenue_growth_yoy" in missing_row["missing_data"]
    assert "free_cash_flow" in missing_row["missing_data"]


def test_score_fundamentals_scores_valuation_when_only_dividend_yield_is_missing() -> None:
    fundamentals = pd.DataFrame(
        [
            {
                "symbol": "MU",
                "fiscal_period": "2025-08-31",
                "revenue": 100.0,
                "revenue_growth_yoy": 0.20,
                "eps": 5.0,
                "eps_growth_yoy": 0.30,
                "gross_margin": 0.50,
                "operating_margin": 0.30,
                "net_margin": 0.20,
                "roe": 0.20,
                "roa": 0.10,
                "debt_ratio": 0.20,
                "operating_cash_flow": 20.0,
                "free_cash_flow": 10.0,
                "pe_ratio": 18.0,
                "pb_ratio": 2.5,
                "dividend_yield": pd.NA,
            }
        ]
    )

    scores = score_fundamentals(fundamentals)
    row = scores.iloc[0]

    assert row["valuation_score"] != "unknown"
    assert row["total_score"] != "unknown"
    assert "dividend_yield" in row["missing_data"]
    assert "股利殖利率 缺漏" in row["weaknesses"]


def test_industry_profile_can_override_metric_thresholds() -> None:
    fundamentals = pd.DataFrame(
        [
            {
                "symbol": "TEST",
                "industry": "strict_valuation",
                "fiscal_period": "2024Q4",
                "revenue_growth_yoy": 0.10,
                "eps_growth_yoy": 0.10,
                "gross_margin": 0.30,
                "operating_margin": 0.15,
                "net_margin": 0.10,
                "roe": 0.10,
                "roa": 0.04,
                "debt_ratio": 0.50,
                "operating_cash_flow": 10.0,
                "free_cash_flow": 5.0,
                "pe_ratio": 25.0,
                "pb_ratio": 2.0,
                "dividend_yield": 0.03,
            }
        ]
    )
    default_score = score_fundamentals(fundamentals)
    strict_profile = IndustryScoringProfile(
        name="strict_valuation",
        metric_rules={
            "pe_ratio": MetricRule(
                column="pe_ratio",
                label="PE ratio",
                weight=8.0,
                direction="lower",
                strong=8.0,
                acceptable=12.0,
                weak=18.0,
            )
        },
        risk_notes=("Strict valuation profile applied.",),
    )

    strict_score = score_fundamentals(
        fundamentals,
        industry_profiles={"strict_valuation": strict_profile},
    )

    assert strict_score.loc[0, "valuation_score"] < default_score.loc[0, "valuation_score"]
    assert "Strict valuation profile applied." in strict_score.loc[0, "risk_notes"]


def test_score_fundamentals_empty_input_returns_empty_output() -> None:
    scores = score_fundamentals(pd.DataFrame(columns=["symbol"]))

    assert scores.empty
    assert list(scores.columns) == [
        "symbol",
        "market",
        "fiscal_period",
        "period_type",
        "as_of_date",
        "total_score",
        "growth_score",
        "profitability_score",
        "financial_safety_score",
        "valuation_score",
        "cashflow_score",
        "strengths",
        "weaknesses",
        "missing_data",
        "risk_notes",
    ]


def test_fetch_yfinance_fundamentals_builds_best_effort_row(monkeypatch) -> None:
    class FakeTicker:
        def get_info(self) -> dict[str, float]:
            return {
                "trailingEps": 10.0,
                "earningsGrowth": 0.12,
                "returnOnEquity": 0.2,
                "returnOnAssets": 0.1,
                "trailingPE": 20.0,
                "priceToBook": 3.0,
                "dividendYield": 0.02,
            }

        financials = pd.DataFrame(
            {
                pd.Timestamp("2024-12-31"): [100.0, 50.0, 30.0, 20.0],
                pd.Timestamp("2023-12-31"): [80.0, 35.0, 20.0, 12.0],
            },
            index=["Total Revenue", "Gross Profit", "Operating Income", "Net Income"],
        )
        balance_sheet = pd.DataFrame(
            {pd.Timestamp("2024-12-31"): [200.0, 80.0]},
            index=["Total Assets", "Total Debt"],
        )
        cashflow = pd.DataFrame(
            {pd.Timestamp("2024-12-31"): [30.0, 15.0]},
            index=["Operating Cash Flow", "Free Cash Flow"],
        )

    monkeypatch.setattr(fundamental_auto_fetch, "_ticker_for_symbol", lambda _: FakeTicker())

    result = fetch_yfinance_fundamentals("2330", market="TWSE")
    row = result.data.iloc[0]

    assert result.provider_symbol == "2330.TW"
    assert row["symbol"] == "2330"
    assert row["market"] == "TWSE"
    assert row["fiscal_period"] == "2024-12-31"
    assert row["period_type"] == "mixed"
    assert pd.notna(row["as_of_date"])
    assert row["revenue"] == pytest.approx(100.0)
    assert row["revenue_growth_yoy"] == pytest.approx(0.25)
    assert row["gross_margin"] == pytest.approx(0.5)
    assert row["debt_ratio"] == pytest.approx(0.4)
    assert row["free_cash_flow"] == pytest.approx(15.0)


def test_score_fundamentals_preserves_canonical_market_identity() -> None:
    fundamentals = load_fundamentals_csv("data/sample/sample_fundamentals.csv")
    fundamentals["market"] = "TWSE"

    scores = score_fundamentals(fundamentals)

    assert scores["market"].tolist() == ["TWSE", "TWSE", "TWSE"]
    assert scores["fiscal_period"].tolist() == fundamentals["fiscal_period"].tolist()
    assert scores["period_type"].tolist() == fundamentals["period_type"].tolist()
    assert scores["as_of_date"].tolist() == fundamentals["as_of_date"].tolist()


def test_fetch_yfinance_fundamentals_retries_tpex_suffix(monkeypatch) -> None:
    class EmptyTicker:
        def get_info(self) -> dict[str, float]:
            return {}

        financials = pd.DataFrame()
        balance_sheet = pd.DataFrame()
        cashflow = pd.DataFrame()

    class ValidTicker:
        def get_info(self) -> dict[str, float]:
            return {"trailingEps": 8.0, "trailingPE": 15.0}

        financials = pd.DataFrame()
        balance_sheet = pd.DataFrame()
        cashflow = pd.DataFrame()

    def fake_ticker(query_symbol: str) -> object:
        if query_symbol == "3105.TW":
            return EmptyTicker()
        if query_symbol == "3105.TWO":
            return ValidTicker()
        raise AssertionError(f"unexpected query symbol: {query_symbol}")

    monkeypatch.setattr(fundamental_auto_fetch, "_ticker_for_symbol", fake_ticker)

    result = fetch_yfinance_fundamentals("3105", market="TWSE")

    assert result.provider_symbol == "3105.TWO"
    assert result.data.loc[0, "symbol"] == "3105"
    assert result.data.loc[0, "eps"] == pytest.approx(8.0)
    assert any("3105.TWO" in warning for warning in result.warnings)


def test_fetch_yfinance_fundamentals_raises_when_no_metrics(monkeypatch) -> None:
    class EmptyTicker:
        def get_info(self) -> dict[str, float]:
            return {}

        financials = pd.DataFrame()
        balance_sheet = pd.DataFrame()
        cashflow = pd.DataFrame()

    monkeypatch.setattr(fundamental_auto_fetch, "_ticker_for_symbol", lambda _: EmptyTicker())

    with pytest.raises(FundamentalFetchError):
        fetch_yfinance_fundamentals("NOPE", market="US")


def test_fetch_yfinance_fundamentals_returns_after_total_timeout(monkeypatch) -> None:
    class BlockingTicker:
        def get_info(self) -> dict[str, float]:
            import time

            time.sleep(1.0)
            return {"trailingEps": 10.0}

        financials = pd.DataFrame()
        balance_sheet = pd.DataFrame()
        cashflow = pd.DataFrame()

    monkeypatch.setattr(fundamental_auto_fetch, "_ticker_for_symbol", lambda _: BlockingTicker())

    started = monotonic()
    with pytest.raises(FundamentalFetchError, match="timed out"):
        fetch_yfinance_fundamentals("AAPL", market="US", timeout_seconds=0.02)
    assert monotonic() - started < 0.4
