from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pandas.testing as pdt

import stock_tool.dashboard.app as dashboard_app
from stock_tool.data.auto_fetch import FetchResult, ProviderAttempt
from stock_tool.data.storage import SQLitePriceStorage
from stock_tool.fundamentals.auto_fetch import FundamentalFetchResult
from stock_tool.portfolio_fx import FxResolution
from stock_tool.portfolio_valuation import Currency, FxQuote
from stock_tool.dashboard.app import (
    TRAILING_STOP_NOTICE,
    _concept_market_codes,
    _component_reason_breakdown,
    _get_company_research_profile,
    _hydrate_concept_matches,
    _infer_market_for_symbol,
    _source_label,
    _factor_health_frame,
    _build_research_snapshot,
    _stock_snapshot,
    compute_drawdown,
    standardize_price_columns,
)
from stock_tool.company_research import CompanyResearchProfile
from stock_tool.stock_scoring import score_stock


class _FakeSessionState(dict):
    def __getattr__(self, name: str) -> object:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: object) -> None:
        self[name] = value


class _FakeStreamlit:
    def __init__(self) -> None:
        self.session_state = _FakeSessionState()


def test_dashboard_one_click_portfolio_refresh_reuses_hydration_and_preserves_holdings(
    monkeypatch,
) -> None:
    calls: list[tuple[str, str, bool]] = []

    def fake_ensure(_st, *, symbol: str, market: str, force_refresh: bool = False):
        calls.append((symbol, market, force_refresh))
        if symbol == "AAPL":
            raise RuntimeError("provider failed token=secret-value")
        return {
            "price_rows": 120,
            "fundamental_rows": 1,
            "provider": "yfinance",
            "query_symbol": "2330.TW",
            "source_type": "online",
            "last_data_date": "2026-07-18",
            "fetched_at": "2026-07-18T00:00:00+00:00",
            "warnings": (),
        }

    class _FakeFxService:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def resolve(self, *, manual_rate: float | None = None) -> FxResolution:
            assert manual_rate is None
            return FxResolution(
                FxQuote(
                    Currency.USD,
                    Currency.TWD,
                    32.0,
                    "yfinance",
                    "2026-07-18T00:00:00+00:00",
                    "2026-07-18T00:00:00+00:00",
                ),
                "online",
            )

    monkeypatch.setattr(dashboard_app, "_ensure_symbol_data", fake_ensure)
    monkeypatch.setattr(dashboard_app, "UsdTwdFxResolutionService", _FakeFxService)
    fake_st = _FakeStreamlit()
    fake_st.session_state.portfolio_manual_usd_twd = 0.0
    positions = pd.DataFrame(
        {
            "symbol": ["2330", "AAPL", "PRIVATE"],
            "market": ["TWSE", "US", "CUSTOM"],
            "quantity": [1.5, 2.0, 1.0],
            "average_cost": [600.0, 100.0, 10.0],
            "note": ["keep", "keep", "keep"],
        }
    )
    original = positions.copy(deep=True)

    result = dashboard_app._refresh_portfolio_analysis(fake_st, positions, force_refresh=False)

    pdt.assert_frame_equal(positions, original)
    assert calls == [("2330", "TWSE", False), ("AAPL", "US", False)]
    statuses = {(item.symbol, item.market): item.status for item in result.items}
    assert statuses == {
        ("2330", "TWSE"): "success",
        ("AAPL", "US"): "failed",
        ("PRIVATE", "CUSTOM"): "manual_required",
    }
    assert fake_st.session_state.portfolio_fx_resolution.status == "online"
    assert "secret-value" not in " ".join(
        next(item for item in result.items if item.symbol == "AAPL").warnings
    )


def test_dashboard_portfolio_risk_classifications_use_cached_market_qualified_profiles_only() -> (
    None
):
    fake_st = _FakeStreamlit()
    us_profile = CompanyResearchProfile(
        symbol="DUP",
        provider_symbol="DUP",
        company_name="US duplicate",
        sector="Technology",
        industry="Hardware",
        website="",
        main_business=("fixture",),
        technical_features=(),
        linked_industries=(),
        current_applications=(),
        future_applications=(),
        bottlenecks=(),
        additional_checks=(),
        data_sources=("fixture",),
        limitations=(),
    )
    fake_st.session_state.company_research_cache = {"DUP|US": us_profile}
    positions = pd.DataFrame(
        {
            "symbol": ["DUP", "DUP"],
            "market": ["TWSE", "US"],
            "quantity": [1.0, 1.0],
            "average_cost": [1.0, 1.0],
            "note": ["", ""],
        }
    )

    actual = dashboard_app._portfolio_risk_classifications(fake_st, positions)

    assert actual.to_dict("records") == [
        {
            "symbol": "DUP",
            "market": "US",
            "sector": "Technology",
            "industry": "Hardware",
            "source": "fixture",
        }
    ]


def test_dashboard_revalidates_expired_session_fx_resolution(monkeypatch) -> None:
    calls: list[float | None] = []

    class _FakeFxService:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def resolve(self, *, manual_rate: float | None = None) -> FxResolution:
            calls.append(manual_rate)
            now = datetime.now(UTC).isoformat()
            return FxResolution(
                FxQuote(Currency.USD, Currency.TWD, 32.0, "yfinance", now, now),
                "online",
            )

    monkeypatch.setattr(dashboard_app, "UsdTwdFxResolutionService", _FakeFxService)
    fake_st = _FakeStreamlit()
    old = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    fake_st.session_state.portfolio_fx_resolution = FxResolution(
        FxQuote(Currency.USD, Currency.TWD, 31.0, "old", old, old), "online"
    )
    fake_st.session_state.portfolio_manual_usd_twd = 0.0

    result = dashboard_app._stored_portfolio_fx_resolution(fake_st)

    assert calls == [None]
    assert result.status == "online"
    assert result.quote is not None and result.quote.rate == 32.0


def test_dashboard_standardizes_price_columns_and_preserves_symbol_text() -> None:
    raw = pd.DataFrame(
        {
            "日期": ["2024-01-01"],
            "股票代號": ["0050"],
            "開盤價": [100],
            "最高價": [101],
            "最低價": [99],
            "收盤價": [100.5],
            "成交量": [1000],
        }
    )

    result = standardize_price_columns(raw)

    assert list(result.columns) == [
        "date",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "adjusted_close",
    ]
    assert result.loc[0, "symbol"] == "0050"
    assert result.loc[0, "adjusted_close"] is None


def test_dashboard_compute_drawdown_does_not_mutate_input() -> None:
    equity_curve = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "total_equity": [100.0, 120.0, 90.0],
        }
    )
    original = equity_curve.copy(deep=True)

    drawdown = compute_drawdown(equity_curve)

    assert drawdown.tolist() == [0.0, 0.0, -0.25]
    pdt.assert_frame_equal(equity_curve, original)


def test_dashboard_detects_only_explicitly_checked_stale_price_frames() -> None:
    stale = pd.DataFrame({"checked_at": ["2000-01-01T00:00:00+00:00"], "close": [100.0]})
    legacy = pd.DataFrame({"date": ["2000-01-01"], "close": [100.0]})

    assert dashboard_app._price_frame_is_stale(stale)
    assert not dashboard_app._price_frame_is_stale(legacy)


def test_dashboard_stock_snapshot_formats_latest_quote() -> None:
    prices = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02"],
            "symbol": ["2330", "2330"],
            "close": [100.0, 110.0],
            "volume": [1000.0, 1200.0],
        }
    )

    snapshot = _stock_snapshot("2330", prices)

    assert snapshot["close"] == "110.00"
    assert snapshot["change"] == "+10.00 (+10.00%)"
    assert snapshot["volume"] == "1,200"


def test_dashboard_builds_market_qualified_research_snapshot_without_mutating_session_frames(
    monkeypatch,
) -> None:
    prices = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=80),
            "symbol": ["2330"] * 80,
            "market": ["TWSE"] * 80,
            "open": [100.0] * 80,
            "high": [105.0] * 80,
            "low": [99.0] * 80,
            "close": [104.0] * 80,
            "volume": [1000.0] * 80,
            "adjusted_close": [104.0] * 80,
        }
    )
    fundamentals = pd.DataFrame(
        {
            "symbol": ["2330"],
            "market": ["TWSE"],
            "total_score": [80.0],
            "growth_score": [20.0],
            "profitability_score": [20.0],
            "financial_safety_score": [20.0],
            "valuation_score": [10.0],
            "cashflow_score": [10.0],
        }
    )
    profile = CompanyResearchProfile(
        symbol="2330",
        provider_symbol="2330.TW",
        company_name="測試公司",
        sector="科技",
        industry="半導體",
        website="",
        main_business=("測試業務",),
        technical_features=("測試技術",),
        linked_industries=("半導體",),
        current_applications=("測試應用",),
        future_applications=(),
        bottlenecks=("測試風險",),
        additional_checks=(),
        data_sources=("fixture",),
        limitations=(),
        fact_fields=("company_name",),
    )
    fake_st = _FakeStreamlit()
    fake_st.session_state.update(
        {
            "price_data": prices,
            "technical_indicators": prices.copy(deep=True),
            "fundamental_scores": fundamentals,
            "backtest_result": None,
            "price_data_source": {
                "provider": "fixture",
                "query_symbol": "2330.TW",
                "source_type": "線上下載",
            },
            "dashboard_status": "ready",
            "company_research_cache": {},
        }
    )
    before_prices = prices.copy(deep=True)
    before_fundamentals = fundamentals.copy(deep=True)
    monkeypatch.setattr(
        dashboard_app, "_get_company_research_profile", lambda _st, _symbol: profile
    )

    snapshot = _build_research_snapshot(fake_st, symbol="2330", market="TWSE")

    assert snapshot.symbol.canonical == "TWSE:2330"
    assert snapshot.component_scores
    assert snapshot.source_metadata.source_type == "online"
    pdt.assert_frame_equal(prices, before_prices)
    pdt.assert_frame_equal(fundamentals, before_fundamentals)


def test_dashboard_factor_health_frame_uses_score_components() -> None:
    prices = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=80).strftime("%Y-%m-%d"),
            "symbol": ["2330"] * 80,
            "open": [100.0] * 80,
            "high": [105.0] * 80,
            "low": [99.0] * 80,
            "close": [104.0] * 80,
            "volume": [1000.0] * 80,
            "adjusted_close": [104.0] * 80,
        }
    )
    fundamentals = pd.DataFrame(
        [
            {
                "symbol": "2330",
                "total_score": 80.0,
                "growth_score": 20.0,
                "profitability_score": 20.0,
                "financial_safety_score": 20.0,
                "valuation_score": 10.0,
                "cashflow_score": 10.0,
                "strengths": "",
                "weaknesses": "",
                "missing_data": "",
                "risk_notes": "",
            }
        ]
    )
    result = score_stock(
        symbol="2330",
        price_data=prices,
        technical_indicators=prices,
        fundamental_scores=fundamentals,
    )

    frame = _factor_health_frame(result)

    assert set(frame["factor"]) == {"趨勢動能", "基本體質", "估值風險", "波動風險", "資料完整度"}
    assert frame["score"].between(0, 100).all()


def test_dashboard_component_reason_breakdown_splits_strengths_and_weaknesses() -> None:
    prices = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=80).strftime("%Y-%m-%d"),
            "symbol": ["2330"] * 80,
            "open": [100.0] * 80,
            "high": [105.0] * 80,
            "low": [99.0] * 80,
            "close": [104.0] * 80,
            "volume": [1000.0] * 80,
            "adjusted_close": [104.0] * 80,
            "sma_20": [100.0] * 80,
            "sma_60": [98.0] * 80,
            "rsi_14": [55.0] * 80,
            "macd_dif": [2.0] * 80,
            "macd_dea": [1.0] * 80,
            "return_20": [0.05] * 80,
        }
    )
    result = score_stock(symbol="2330", price_data=prices, technical_indicators=prices)
    technical = next(component for component in result.components if component.name == "技術面")
    fundamental = next(component for component in result.components if component.name == "基本面")

    strengths, weaknesses = _component_reason_breakdown(technical)
    _, fundamental_weaknesses = _component_reason_breakdown(fundamental)

    assert any("高於 20 日均線" in item for item in strengths)
    assert any("目前沒有明確缺點" in item for item in weaknesses)
    assert any("缺少資料" in item for item in fundamental_weaknesses)


def test_dashboard_discloses_trailing_stop_daily_model() -> None:
    assert "conservative daily model" in TRAILING_STOP_NOTICE


def test_dashboard_auto_loads_existing_sqlite_import(tmp_path, monkeypatch) -> None:
    database = tmp_path / "stock_data.sqlite"
    SQLitePriceStorage(database).save_price_data(
        [
            {
                "date": "2024-01-02",
                "symbol": "2330",
                "open": 100.0,
                "high": 105.0,
                "low": 99.0,
                "close": 104.0,
                "volume": 1000.0,
                "adjusted_close": 104.0,
            }
        ]
    )
    monkeypatch.setattr(dashboard_app, "DEFAULT_DATABASE", database)

    fake_st = _FakeStreamlit()
    dashboard_app._init_state(fake_st)

    assert fake_st.session_state.price_data is not None
    assert len(fake_st.session_state.price_data) == 1
    assert fake_st.session_state.price_data_source["provider"] == "sqlite"
    assert fake_st.session_state.price_data_source["source_type"] == "SQLite 匯入資料"
    assert fake_st.session_state.technical_indicators is not None


def test_dashboard_persists_new_symbol_to_existing_sqlite(tmp_path) -> None:
    database = tmp_path / "stock_data.sqlite"
    SQLitePriceStorage(database).save_price_data(
        [
            {
                "date": "2024-01-02",
                "symbol": "2330",
                "open": 100.0,
                "high": 105.0,
                "low": 99.0,
                "close": 104.0,
                "volume": 1000.0,
                "adjusted_close": 104.0,
            }
        ]
    )
    new_symbol = pd.DataFrame(
        [
            {
                "date": "2024-01-02",
                "symbol": "AAPL",
                "open": 190.0,
                "high": 195.0,
                "low": 188.0,
                "close": 194.0,
                "volume": 5000.0,
                "adjusted_close": 194.0,
            }
        ]
    )

    saved_count = dashboard_app._persist_price_data(new_symbol, database)
    loaded = dashboard_app._load_default_database_prices(database)

    assert saved_count == 1
    assert loaded is not None
    assert set(loaded["symbol"].tolist()) == {"2330", "AAPL"}


def test_dashboard_auto_loads_bundled_fundamentals(tmp_path, monkeypatch) -> None:
    fundamental_file = tmp_path / "fundamentals.csv"
    fundamental_file.write_text(
        "\n".join(
            [
                "symbol,fiscal_period,revenue,revenue_growth_yoy,eps,eps_growth_yoy,gross_margin,operating_margin,net_margin,roe,roa,debt_ratio,operating_cash_flow,free_cash_flow,pe_ratio,pb_ratio,dividend_yield",
                "2330,2024Q4,100,0.1,10,0.1,0.5,0.3,0.2,0.2,0.1,0.3,50,40,20,3,0.02",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(dashboard_app, "DEFAULT_DATABASE", tmp_path / "missing.sqlite")
    monkeypatch.setattr(dashboard_app, "SAMPLE_FUNDAMENTAL_FILE", fundamental_file)
    monkeypatch.setattr(dashboard_app, "AUTO_FUNDAMENTAL_FILE", tmp_path / "missing_auto.csv")

    fake_st = _FakeStreamlit()
    dashboard_app._init_state(fake_st)

    assert fake_st.session_state.fundamentals is not None
    assert fake_st.session_state.fundamental_scores is not None
    assert fake_st.session_state.fundamental_scores["symbol"].tolist() == ["2330"]


def test_dashboard_ensure_symbol_data_fetches_and_persists_new_symbol(
    tmp_path, monkeypatch
) -> None:
    database = tmp_path / "stock_data.sqlite"
    auto_fundamentals = tmp_path / "fundamentals_auto.csv"
    monkeypatch.setattr(dashboard_app, "DEFAULT_DATABASE", database)
    monkeypatch.setattr(dashboard_app, "AUTO_FUNDAMENTAL_FILE", auto_fundamentals)
    monkeypatch.setattr(dashboard_app, "SAMPLE_FUNDAMENTAL_FILE", tmp_path / "missing.csv")

    dates = pd.date_range("2024-01-01", periods=80, freq="D")
    price_frame = pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "symbol": "AAPL",
            "open": [100.0] * 80,
            "high": [105.0] * 80,
            "low": [99.0] * 80,
            "close": [104.0] * 80,
            "volume": [1000.0] * 80,
            "adjusted_close": [104.0] * 80,
        }
    )
    fundamental_frame = pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "market": "US",
                "fiscal_period": "2024-12-31",
                "period_type": "mixed",
                "as_of_date": "2026-07-13",
                "revenue": 100.0,
                "revenue_growth_yoy": 0.1,
                "eps": 10.0,
                "eps_growth_yoy": 0.1,
                "gross_margin": 0.5,
                "operating_margin": 0.3,
                "net_margin": 0.2,
                "roe": 0.2,
                "roa": 0.1,
                "debt_ratio": 0.3,
                "operating_cash_flow": 30.0,
                "free_cash_flow": 15.0,
                "pe_ratio": 20.0,
                "pb_ratio": 3.0,
                "dividend_yield": 0.02,
            }
        ]
    )

    monkeypatch.setattr(
        dashboard_app,
        "fetch_prices",
        lambda *args, **kwargs: FetchResult(
            data=price_frame,
            source="yfinance",
            symbol="AAPL",
            provider_symbol="AAPL",
            from_cache=False,
            cache_file=None,
            market="US",
            start_date="2024-01-01",
            end_date="2024-03-20",
            source_type="online",
        ),
    )
    monkeypatch.setattr(
        dashboard_app,
        "fetch_yfinance_fundamentals",
        lambda *args, **kwargs: FundamentalFetchResult(
            data=fundamental_frame,
            source="yfinance",
            symbol="AAPL",
            provider_symbol="AAPL",
        ),
    )

    fake_st = _FakeStreamlit()
    dashboard_app._init_state(fake_st)
    result = dashboard_app._ensure_symbol_data(fake_st, symbol="AAPL", market="US")

    assert result["symbol"] == "AAPL"
    assert fake_st.session_state.active_symbol == "AAPL"
    assert fake_st.session_state.price_data["symbol"].unique().tolist() == ["AAPL"]
    assert fake_st.session_state.fundamental_scores["symbol"].tolist() == ["AAPL"]
    assert database.exists()
    assert auto_fundamentals.exists()
    persisted = pd.read_csv(auto_fundamentals, dtype={"symbol": str, "market": str})
    assert persisted.loc[0, "market"] == "US"
    assert persisted.loc[0, "period_type"] == "mixed"
    assert persisted.loc[0, "as_of_date"] == "2026-07-13"


def test_dashboard_fundamental_identity_lookup_requires_symbol_and_market() -> None:
    fundamentals = pd.DataFrame(
        {
            "symbol": ["DUP", "DUP", "MU"],
            "market": ["US", "TWSE", "UNKNOWN"],
            "fiscal_period": ["2025-12-31"] * 3,
        }
    )

    assert dashboard_app._has_fundamental_row(fundamentals, "DUP", "US")
    assert dashboard_app._has_fundamental_row(fundamentals, "DUP", "TWSE")
    assert not dashboard_app._has_fundamental_row(fundamentals, "DUP", "TPEX")
    assert not dashboard_app._has_fundamental_row(fundamentals, "MU", "US")


def test_dashboard_fundamental_merge_keeps_same_symbol_in_different_markets() -> None:
    merged = dashboard_app._merge_fundamentals(
        [
            pd.DataFrame([{"symbol": "DUP", "market": "US", "fiscal_period": "2025-12-31"}]),
            pd.DataFrame([{"symbol": "DUP", "market": "TWSE", "fiscal_period": "2025-12-31"}]),
        ]
    )

    assert merged[["symbol", "market"]].to_dict("records") == [
        {"symbol": "DUP", "market": "US"},
        {"symbol": "DUP", "market": "TWSE"},
    ]


def test_dashboard_fundamental_merge_keeps_distinct_fiscal_periods_within_market() -> None:
    merged = dashboard_app._merge_fundamentals(
        [
            pd.DataFrame(
                [
                    {"symbol": "MU", "market": "US", "fiscal_period": "2025-08-31"},
                    {"symbol": "MU", "market": "US", "fiscal_period": "2026-08-31"},
                ]
            )
        ]
    )

    assert merged[["symbol", "market", "fiscal_period"]].to_dict("records") == [
        {"symbol": "MU", "market": "US", "fiscal_period": "2025-08-31"},
        {"symbol": "MU", "market": "US", "fiscal_period": "2026-08-31"},
    ]


def test_dashboard_keeps_legacy_unknown_fundamentals_unknown_despite_unambiguous_prices() -> None:
    fake_st = _FakeStreamlit()
    dashboard_app._init_state(fake_st)
    fake_st.session_state.price_data = pd.DataFrame(
        {
            "date": ["2026-01-02"],
            "symbol": ["MU"],
            "market": ["US"],
            "close": [100.0],
        }
    )
    legacy = pd.DataFrame([{"symbol": "MU", "market": "UNKNOWN", "fiscal_period": "2025-08-31"}])

    dashboard_app._set_fundamentals_state(fake_st, legacy)

    assert fake_st.session_state.fundamentals.loc[0, "market"] == "UNKNOWN"
    assert fake_st.session_state.fundamental_scores.loc[0, "market"] == "UNKNOWN"


def test_dashboard_refetches_legacy_unknown_fundamentals_for_requested_market(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(dashboard_app, "DEFAULT_DATABASE", tmp_path / "missing.sqlite")
    monkeypatch.setattr(dashboard_app, "AUTO_FUNDAMENTAL_FILE", tmp_path / "fundamentals_auto.csv")
    monkeypatch.setattr(dashboard_app, "SAMPLE_FUNDAMENTAL_FILE", tmp_path / "missing.csv")

    fake_st = _FakeStreamlit()
    dashboard_app._init_state(fake_st)
    dates = pd.date_range("2026-01-01", periods=80, freq="D")
    fake_st.session_state.price_data = pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "symbol": ["MU"] * 80,
            "market": ["US"] * 80,
            "open": [100.0] * 80,
            "high": [102.0] * 80,
            "low": [99.0] * 80,
            "close": [101.0] * 80,
            "volume": [1000.0] * 80,
            "adjusted_close": [101.0] * 80,
        }
    )
    fake_st.session_state.fundamentals = pd.DataFrame(
        [{"symbol": "MU", "market": "UNKNOWN", "fiscal_period": "2025-08-31"}]
    )

    fetched = pd.DataFrame(
        [
            {
                "symbol": "MU",
                "market": "US",
                "fiscal_period": "2025-08-31",
                "period_type": "mixed",
                "as_of_date": "2026-07-13",
                "revenue": 100.0,
                "revenue_growth_yoy": 0.1,
                "eps": 10.0,
                "eps_growth_yoy": 0.1,
                "gross_margin": 0.5,
                "operating_margin": 0.3,
                "net_margin": 0.2,
                "roe": 0.2,
                "roa": 0.1,
                "debt_ratio": 0.3,
                "operating_cash_flow": 30.0,
                "free_cash_flow": 15.0,
                "pe_ratio": 20.0,
                "pb_ratio": 3.0,
                "dividend_yield": 0.02,
                "source": "yfinance",
                "provider_symbol": "MU",
            }
        ]
    )
    calls: list[tuple[str, str]] = []

    def fake_fetch(symbol: str, *, market: str) -> FundamentalFetchResult:
        calls.append((symbol, market))
        return FundamentalFetchResult(
            data=fetched,
            source="yfinance",
            symbol=symbol,
            provider_symbol="MU",
        )

    monkeypatch.setattr(dashboard_app, "fetch_yfinance_fundamentals", fake_fetch)

    result = dashboard_app._ensure_symbol_data(fake_st, symbol="MU", market="US")

    assert calls == [("MU", "US")]
    assert result["fundamental_rows"] == 1
    persisted = pd.read_csv(
        tmp_path / "fundamentals_auto.csv", dtype={"symbol": str, "market": str}
    )
    persisted_mu = persisted.loc[persisted["symbol"].eq("MU") & persisted["market"].eq("US")]
    assert len(persisted_mu) == 1
    assert persisted_mu.iloc[0]["period_type"] == "mixed"
    assert persisted_mu.iloc[0]["as_of_date"] == "2026-07-13"
    assert not dashboard_app._filter_identity(
        fake_st.session_state.fundamentals, symbol="MU", market="US"
    ).empty
    assert not dashboard_app._filter_identity(
        fake_st.session_state.fundamental_scores, symbol="MU", market="US"
    ).empty
    monkeypatch.setattr(dashboard_app, "_get_company_research_profile", lambda *_args: None)

    snapshot = dashboard_app._build_research_snapshot(fake_st, symbol="MU", market="US")

    assert snapshot.fundamental_results is not None
    assert snapshot.fundamental_results["market"].tolist() == ["US"]
    assert "fundamental_scores" not in {item.field for item in snapshot.missing_data}
    assert "valuation_score" not in {item.field for item in snapshot.missing_data}


def test_dashboard_sample_data_source_is_not_labeled_as_online_download() -> None:
    label = _source_label(
        {
            "source_type": "範例資料",
            "provider": "sample",
            "query_symbol": None,
            "market": None,
            "start_date": None,
            "end_date": None,
            "cache_file": None,
        }
    )

    assert "範例資料" in label
    assert "線上下載" not in label


def test_dashboard_concept_market_codes_default_to_all_markets() -> None:
    assert _concept_market_codes(["台股上市 TWSE", "美股 US"]) == ("TWSE", "US")
    assert _concept_market_codes([]) == ("TWSE", "TPEX", "US")


def test_dashboard_infers_market_for_company_research() -> None:
    fake_st = _FakeStreamlit()
    fake_st.session_state.price_data_source = {"market": "TPEX", "user_symbol": "6488"}

    assert _infer_market_for_symbol(fake_st, "6488") == "TPEX"
    assert _infer_market_for_symbol(fake_st, "2330") == "AUTO"
    assert _infer_market_for_symbol(fake_st, "AAPL") == "US"
    assert _infer_market_for_symbol(fake_st, "2330.TW") == "TWSE"


def test_dashboard_company_research_profile_is_cached(monkeypatch, tmp_path) -> None:
    calls: list[tuple[str, str]] = []

    def fake_build(symbol: str, *, market: str, **_kwargs: object):
        calls.append((symbol, market))
        return dashboard_app.CompanyResearchProfile(
            symbol=symbol,
            provider_symbol=symbol,
            company_name=symbol,
            sector="科技",
            industry="半導體",
            website="",
            main_business=("半導體相關業務。",),
            technical_features=("製程與良率。",),
            linked_industries=("半導體",),
            current_applications=("資料中心。",),
            future_applications=("AI。",),
            bottlenecks=("景氣循環。",),
            additional_checks=("查證營收占比。",),
            data_sources=("test",),
            limitations=("test",),
        )

    monkeypatch.setattr(dashboard_app, "build_company_research_profile", fake_build)
    monkeypatch.setattr(dashboard_app, "DEFAULT_DATABASE", tmp_path / "research.sqlite")
    fake_st = _FakeStreamlit()
    fake_st.session_state.company_research_cache = {}
    fake_st.session_state.price_data_source = {"market": "US", "user_symbol": "AAPL"}

    first = _get_company_research_profile(fake_st, "AAPL")
    second = _get_company_research_profile(fake_st, "AAPL")

    assert first is second
    assert calls == [("AAPL", "US")]


def test_dashboard_offline_cache_skips_fundamentals_and_company_metadata(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(dashboard_app, "DEFAULT_DATABASE", tmp_path / "research.sqlite")
    monkeypatch.setattr(dashboard_app, "AUTO_FUNDAMENTAL_FILE", tmp_path / "fundamentals_auto.csv")
    dates = pd.date_range("2026-01-01", periods=80, freq="D")
    cached = pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "symbol": ["2330"] * 80,
            "market": ["TWSE"] * 80,
            "open": [100.0] * 80,
            "high": [102.0] * 80,
            "low": [99.0] * 80,
            "close": [101.0] * 80,
            "volume": [1000.0] * 80,
            "adjusted_close": [101.0] * 80,
        }
    )
    calls: list[str] = []
    monkeypatch.setattr(
        dashboard_app,
        "fetch_prices",
        lambda *_args, **_kwargs: FetchResult(
            data=cached,
            source="cache",
            symbol="2330",
            provider_symbol="2330.TW",
            from_cache=True,
            cache_file=None,
            market="TWSE",
            start_date="2026-01-01",
            end_date="2026-03-20",
            source_type="cache",
            attempts=(
                ProviderAttempt("yfinance", False, "controlled offline"),
                ProviderAttempt("cache", True, "cached"),
            ),
        ),
    )
    monkeypatch.setattr(
        dashboard_app,
        "fetch_yfinance_fundamentals",
        lambda *_args, **_kwargs: calls.append("fundamentals"),
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        dashboard_app,
        "build_company_research_profile",
        lambda *_args, **kwargs: captured.update(kwargs) or object(),
    )

    fake_st = _FakeStreamlit()
    dashboard_app._init_state(fake_st)
    outcome = dashboard_app._ensure_symbol_data(fake_st, symbol="2330", market="TWSE")
    dashboard_app._get_company_research_profile(fake_st, "2330")

    assert calls == []
    assert any("略過基本面" in warning for warning in outcome["warnings"])
    assert captured["allow_remote_fetch"] is False


def test_dashboard_explore_uses_canonical_discovery_renderer(monkeypatch, tmp_path) -> None:
    fake_st = _FakeStreamlit()
    rendered: list[object] = []
    monkeypatch.setattr(dashboard_app, "DEFAULT_DATABASE", tmp_path / "research.sqlite")
    monkeypatch.setattr(
        dashboard_app,
        "render_discovery",
        lambda _st, repository: rendered.append(repository),
    )

    dashboard_app._render_canonical_discovery(fake_st)

    assert len(rendered) == 1


def test_dashboard_hydrate_concept_matches_uses_existing_auto_pipeline(monkeypatch) -> None:
    calls: list[tuple[str, str, bool]] = []

    def fake_ensure_symbol_data(fake_st, *, symbol: str, market: str, force_refresh: bool = False):
        calls.append((symbol, market, force_refresh))
        return {
            "symbol": symbol,
            "market": market,
            "price_rows": 120,
            "fundamental_rows": 1,
            "warnings": [],
            "summary": f"{symbol} 已更新",
        }

    monkeypatch.setattr(dashboard_app, "_ensure_symbol_data", fake_ensure_symbol_data)
    fake_st = _FakeStreamlit()
    matches = pd.DataFrame(
        [
            {"symbol": "2330", "name": "台積電", "market": "TWSE"},
            {"symbol": "NVDA", "name": "NVIDIA", "market": "US"},
        ]
    )

    result = _hydrate_concept_matches(fake_st, matches, limit=2, force_refresh=True)

    assert calls == [("2330", "TWSE", True), ("NVDA", "US", True)]
    assert result["status"].tolist() == ["成功", "成功"]
    assert result["price_rows"].tolist() == [120, 120]


def test_dashboard_portfolio_price_context_merges_sqlite_and_current_session(
    tmp_path,
    monkeypatch,
) -> None:
    database = tmp_path / "stock_data.sqlite"
    SQLitePriceStorage(database).save_price_data(
        [
            {
                "date": "2024-01-02",
                "symbol": "6789",
                "open": 100.0,
                "high": 105.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1000.0,
                "adjusted_close": 100.0,
            },
            {
                "date": "2024-01-02",
                "symbol": "00935",
                "open": 45.0,
                "high": 46.0,
                "low": 44.0,
                "close": 45.8,
                "volume": 1000.0,
                "adjusted_close": 45.8,
            },
        ]
    )
    monkeypatch.setattr(dashboard_app, "DEFAULT_DATABASE", database)
    fake_st = _FakeStreamlit()
    fake_st.session_state.price_data = pd.DataFrame(
        {
            "date": ["2024-01-02"],
            "symbol": ["6789"],
            "close": [543.0],
        }
    )
    fake_st.session_state.price_data_source = {"market": "TWSE"}

    result = dashboard_app._portfolio_price_context(fake_st)

    assert result is not None
    assert set(result["symbol"].tolist()) == {"00935", "6789"}
    assert result.loc[result["symbol"] == "6789", "close"].iloc[0] == 543.0


def test_dashboard_session_market_fallback_is_scoped_to_one_symbol_only() -> None:
    fake_st = _FakeStreamlit()
    fake_st.session_state.price_data = pd.DataFrame(
        {
            "date": ["2026-01-02", "2026-01-02"],
            "symbol": ["00935", "DRAM"],
            "close": [45.8, 60.0],
        }
    )
    fake_st.session_state.price_data_source = {"market": "US"}

    assert dashboard_app._market_qualified_current_prices(fake_st) is None


def test_dashboard_price_merge_keeps_market_identities_and_current_wins_same_identity() -> None:
    stored = pd.DataFrame(
        {
            "date": ["2026-01-02", "2026-01-02", "2026-01-02"],
            "symbol": ["00935", "DRAM", "DRAM"],
            "market": ["TWSE", "US", "UNKNOWN"],
            "close": [45.0, 50.0, 49.0],
        }
    )
    current = pd.DataFrame(
        {
            "date": ["2026-01-02", "2026-01-02"],
            "symbol": ["00935", "DRAM"],
            "market": ["TWSE", "US"],
            "close": [45.8, 60.0],
        }
    )

    merged = dashboard_app._merge_price_frames([stored, current])
    reverse = dashboard_app._merge_price_frames([stored, current.iloc[::-1]])

    assert merged is not None
    assert reverse is not None
    values = merged.set_index(["symbol", "market", "date"])["close"].to_dict()
    assert values[("00935", "TWSE", "2026-01-02")] == 45.8
    assert values[("DRAM", "US", "2026-01-02")] == 60.0
    assert values[("DRAM", "UNKNOWN", "2026-01-02")] == 49.0
    pdt.assert_frame_equal(merged, reverse)


def test_dashboard_stress_market_options_only_apply_to_market_decline() -> None:
    assert dashboard_app._stress_market_options("market_decline") == ("TWSE", "TPEX", "US")
    assert dashboard_app._stress_market_options("all_holdings_decline") == ()


def test_dashboard_missing_portfolio_price_symbols_are_case_insensitive() -> None:
    portfolio = pd.DataFrame(
        {
            "symbol": ["00935", "mu"],
            "quantity": [950.0, 1.0],
            "average_cost": [45.8, 1085.0],
            "market": ["TW", "US"],
        }
    )
    prices = pd.DataFrame(
        {
            "date": ["2024-01-02"],
            "symbol": ["MU"],
            "close": [120.0],
        }
    )

    result = dashboard_app._missing_portfolio_price_symbols(portfolio, prices)

    assert result == ("00935",)


def test_dashboard_hydrate_portfolio_prices_fetches_missing_symbols_without_mutation(
    monkeypatch,
) -> None:
    calls: list[tuple[str, str, bool]] = []

    def fake_ensure_symbol_data(fake_st, *, symbol: str, market: str, force_refresh: bool = False):
        calls.append((symbol, market, force_refresh))
        return {
            "symbol": symbol,
            "market": market,
            "price_rows": 120,
            "fundamental_rows": 1,
            "warnings": [],
            "summary": f"{symbol} ok",
        }

    monkeypatch.setattr(dashboard_app, "_ensure_symbol_data", fake_ensure_symbol_data)
    fake_st = _FakeStreamlit()
    portfolio = pd.DataFrame(
        {
            "symbol": ["00935", "mu"],
            "quantity": [950.0, 1.0],
            "average_cost": [45.8, 1085.0],
            "market": ["TW", "us"],
        }
    )
    original = portfolio.copy(deep=True)

    result = dashboard_app._hydrate_portfolio_prices(
        fake_st,
        portfolio,
        missing_symbols=("00935", "MU"),
        force_refresh=True,
    )

    pdt.assert_frame_equal(portfolio, original)
    assert calls == [("00935", "TWSE", True), ("MU", "US", True)]
    assert result["股票代號"].tolist() == ["00935", "MU"]
    assert result["股價筆數"].tolist() == [120, 120]
