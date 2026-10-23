"""Isolated regressions for explicit fundamental identity and cached valuation."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from stock_tool.dashboard import app
from stock_tool.application.holding_analysis import (
    build_holding_analysis,
    holding_fx_is_usable,
    validated_holding_prices,
)
from stock_tool.fundamentals.auto_fetch import FundamentalFetchResult
from stock_tool.fundamentals.loader import load_fundamentals_csv
from stock_tool.portfolio_valuation import FxQuote, PortfolioValuationService, StaticFxRateProvider

WEEKEND = datetime(2026, 10, 18, 12, tzinfo=UTC)
FRIDAY_FETCHED = "2026-10-16T22:30:00Z"


class State(dict):
    def __getattr__(self, key):
        return self[key]

    def __setattr__(self, key, value):
        self[key] = value


def fundamental_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(app, "DEFAULT_DATABASE", tmp_path / "absent.sqlite")
    monkeypatch.setattr(app, "SAMPLE_FUNDAMENTAL_FILE", tmp_path / "absent.csv")
    monkeypatch.setattr(app, "AUTO_FUNDAMENTAL_FILE", tmp_path / "fundamentals_auto.csv")


def session():
    st = SimpleNamespace(session_state=State())
    app._init_state(st)
    return st


def seed_prices(st, symbol, market):
    st.session_state.price_data = pd.DataFrame(
        {
            "date": pd.date_range("2026-07-01", periods=80),
            "symbol": symbol,
            "market": market,
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 1000.0,
            "adjusted_close": 101.0,
        }
    )


@pytest.mark.parametrize("market", ["TWSE", "TPEX", "US"])
def test_fresh_provider_identity_survives_csv_and_new_session(tmp_path, monkeypatch, market):
    fundamental_runtime(tmp_path, monkeypatch)
    st = session()
    seed_prices(st, "TEST", market)
    # Only this new result has an explicit request identity. Legacy CSV does not.
    raw = pd.DataFrame([dict(symbol="TEST", fiscal_period="2026-06-30", pe_ratio=12)])
    original = raw.copy(deep=True)
    monkeypatch.setattr(
        app,
        "fetch_yfinance_fundamentals",
        lambda *_a, **_k: FundamentalFetchResult(raw, "fixture", "TEST", "TEST"),
    )
    app._ensure_symbol_data(st, symbol="TEST", market=market)
    assert st.session_state.fundamentals.market.tolist() == [market]
    stored = load_fundamentals_csv(tmp_path / "fundamentals_auto.csv")
    assert stored.market.tolist() == [market]
    restarted = session()
    assert restarted.session_state.fundamentals.market.tolist() == [market]
    assert restarted.session_state.fundamental_scores.market.tolist() == [market]
    pd.testing.assert_frame_equal(raw, original)


def test_legacy_unknown_and_same_ticker_markets_stay_separate_after_restart(tmp_path, monkeypatch):
    fundamental_runtime(tmp_path, monkeypatch)
    legacy = pd.DataFrame(
        [dict(symbol="TEST", fiscal_period="2026-06-30", pe_ratio=99, custom_field="legacy")]
    )
    legacy.to_csv(tmp_path / "fundamentals_auto.csv", index=False, encoding="utf-8-sig")
    st = session()
    assert st.session_state.fundamentals.market.tolist() == ["UNKNOWN"]
    raw = pd.DataFrame([dict(symbol="TEST", fiscal_period="2026-06-30", pe_ratio=12)])
    monkeypatch.setattr(
        app,
        "fetch_yfinance_fundamentals",
        lambda *_a, **_k: FundamentalFetchResult(raw, "fixture", "TEST", "TEST"),
    )
    for market in ("TWSE", "US"):
        seed_prices(st, "TEST", market)
        app._ensure_symbol_data(st, symbol="TEST", market=market)
    reloaded = session().session_state.fundamentals
    assert set(reloaded.market) == {"UNKNOWN", "TWSE", "US"}
    assert reloaded.loc[reloaded.market.eq("UNKNOWN"), "pe_ratio"].tolist() == [99]
    assert reloaded.loc[reloaded.market.eq("UNKNOWN"), "custom_field"].tolist() == ["legacy"]
    assert reloaded.available_date.isna().all()
    assert not reloaded.duplicated(["symbol", "market", "fiscal_period"]).any()


def test_explicit_provider_market_is_not_overwritten_by_request(tmp_path, monkeypatch):
    fundamental_runtime(tmp_path, monkeypatch)
    st = session()
    seed_prices(st, "TEST", "TWSE")
    raw = pd.DataFrame([dict(symbol="TEST", market="US", fiscal_period="2026-06-30")])
    monkeypatch.setattr(
        app,
        "fetch_yfinance_fundamentals",
        lambda *_a, **_k: FundamentalFetchResult(raw, "fixture", "TEST", "TEST"),
    )
    app._ensure_symbol_data(st, symbol="TEST", market="TWSE")
    assert load_fundamentals_csv(tmp_path / "fundamentals_auto.csv").market.tolist() == ["US"]
    assert app._filter_identity(st.session_state.fundamentals, symbol="TEST", market="TWSE").empty


def test_auto_fundamentals_do_not_borrow_resolved_price_market(tmp_path, monkeypatch):
    fundamental_runtime(tmp_path, monkeypatch)
    st = session()
    seed_prices(st, "TEST", "TWSE")
    prices = st.session_state.price_data.copy(deep=True)
    prices["date"] = prices.date.dt.strftime("%Y-%m-%d")
    st.session_state.price_data = None
    monkeypatch.setattr(app, "_persist_price_data", lambda *_a: 0)
    monkeypatch.setattr(
        app,
        "fetch_prices",
        lambda *_a, **_k: SimpleNamespace(
            data=prices,
            source="fixture",
            provider_symbol="TEST.TW",
            market="TWSE",
            warnings=(),
            source_type="online",
            last_data_date="2026-09-18",
            fetched_at="2026-10-16T22:30:00Z",
            from_cache=False,
            cache_file=None,
            start_date="2026-07-01",
            end_date="2026-09-18",
            cache_state=None,
            cache_age_seconds=None,
            attempts=(),
        ),
    )
    raw = pd.DataFrame([dict(symbol="TEST", fiscal_period="2026-06-30", market="UNKNOWN")])
    calls = []

    def fetch(_symbol, *, market):
        calls.append(market)
        return FundamentalFetchResult(raw, "fixture", "TEST", "TEST")

    monkeypatch.setattr(app, "fetch_yfinance_fundamentals", fetch)
    app._ensure_symbol_data(st, symbol="TEST", market="AUTO")
    assert calls == ["AUTO"]
    assert load_fundamentals_csv(tmp_path / "fundamentals_auto.csv").market.tolist() == ["UNKNOWN"]
    assert st.session_state.fundamentals.market.tolist() == ["UNKNOWN"]


def position(symbol="MU", market="US"):
    return dict(
        symbol=symbol,
        market=market,
        currency="USD" if market == "US" else "TWD",
        quantity=2,
        average_cost=80,
        note="synthetic private note",
    )


def price_frame(symbol="MU", market="US", **updates):
    row = dict(
        symbol=symbol,
        market=market,
        date="2026-10-16",
        close=100.0,
        provider="fixture",
        fetched_at=FRIDAY_FETCHED,
    )
    row.update(updates)
    return pd.DataFrame([row])


@pytest.mark.parametrize("market", ["TWSE", "US"])
def test_weekend_closing_price_keeps_reference_value_and_freshness(market):
    holding = position("TEST", market)
    prices = price_frame("TEST", market)
    original = prices.copy(deep=True)
    result = build_holding_analysis(holding, prices=prices, fx_quote=None, now=WEEKEND)
    native = next((d for d in result.data if d.label == "原幣市值"), None)
    assert native is not None
    assert native.value == f"{holding['currency']} 200.00"
    assert native.as_of == "2026-10-16"
    assert native.fetched_at == FRIDAY_FETCHED
    assert native.status != "可用"
    assert "參考" in native.status + native.reason
    assert "24" in native.status + native.reason
    filtered = validated_holding_prices(pd.DataFrame([holding]), prices, {}, now=WEEKEND)
    assert filtered is not None and len(filtered) == 1
    pd.testing.assert_frame_equal(prices, original)


@pytest.mark.parametrize("stale_fx", [False, True])
def test_mixed_portfolio_never_invents_complete_weights_when_fx_unusable(stale_fx):
    positions = pd.DataFrame([position("3006", "TWSE"), position()])
    prices = pd.concat([price_frame("3006", "TWSE"), price_frame()], ignore_index=True)
    fetched = FRIDAY_FETCHED if stale_fx else "2026-10-18T10:00:00Z"
    quote = FxQuote.manual("USD", "TWD", 32.0, fetched)
    usable = holding_fx_is_usable(quote, now=WEEKEND)
    assert usable is not stale_fx
    filtered = validated_holding_prices(positions, prices, {}, now=WEEKEND)
    service = PortfolioValuationService(StaticFxRateProvider([quote]) if usable else None)
    result = service.value(positions=positions, prices=filtered)
    assert result.positions.native_market_value.tolist() == [200.0, 200.0]
    if stale_fx:
        assert result.base_market_value is None
        assert result.positions.weight.isna().all()
    else:
        assert result.base_market_value == 6600.0
        assert result.positions.weight.sum() == pytest.approx(1.0)


def test_offline_reference_preserves_dates_and_shared_evidence():
    prices = price_frame()
    result = build_holding_analysis(
        position(),
        prices=prices,
        fx_quote=None,
        now=WEEKEND + timedelta(days=2),
        refresh_failed=True,
    )
    native = next((d for d in result.data if d.label == "原幣市值"), None)
    assert native is not None
    assert "更新失敗" in native.reason
    assert "參考" in native.status + native.reason
    bundle = result.evidence_bundle()
    matching = next(e for e in bundle.evidence if e.label == "原幣市值")
    assert matching.available_at == "2026-10-16"
    assert matching.fetched_at == FRIDAY_FETCHED
    assert native.value in matching.text
    assert "synthetic private note" not in str(bundle)


@pytest.mark.parametrize(
    "updates",
    [
        {"date": "2025-01-01"},
        {"date": "2026-10-20"},
        {"provider": ""},
        {"fetched_at": ""},
        {"fetched_at": "2025-01-01T00:00:00Z"},
        {"fetched_at": "2099-01-01T00:00:00Z"},
    ],
)
def test_cached_reference_keeps_existing_untrusted_data_exclusions(updates):
    prices = price_frame(**updates)
    result = build_holding_analysis(position(), prices=prices, fx_quote=None, now=WEEKEND)
    assert not any(d.label == "原幣市值" for d in result.data)
    filtered = validated_holding_prices(pd.DataFrame([position()]), prices, {}, now=WEEKEND)
    assert filtered is not None and filtered.empty


@pytest.mark.parametrize(
    "market,fetched",
    [
        ("TWSE", "2026-10-16T02:20:00Z"),
        ("US", "2026-10-16T14:20:00Z"),
        ("US", "2026-10-16T22:30:00"),
    ],
)
def test_old_intraday_or_unknown_timezone_does_not_upgrade_to_close(market, fetched):
    result = build_holding_analysis(
        position("TEST", market),
        prices=price_frame("TEST", market, fetched_at=fetched),
        fx_quote=None,
        now=WEEKEND,
    )
    assert not any(d.label == "原幣市值" for d in result.data)


def test_partial_price_coverage_and_conflicts_do_not_create_full_weights():
    holdings = pd.DataFrame([position("3006", "TWSE"), position()])
    prices = pd.concat(
        [price_frame("3006", "TWSE"), price_frame(), price_frame(close=150)], ignore_index=True
    )
    filtered = validated_holding_prices(holdings, prices, {}, now=WEEKEND)
    assert filtered is not None and filtered.symbol.tolist() == ["3006"]
    quote = FxQuote.manual("USD", "TWD", 32, "2026-10-18T10:00:00Z")
    result = PortfolioValuationService(StaticFxRateProvider([quote])).value(
        positions=holdings, prices=filtered
    )
    assert result.base_market_value is None
    assert result.positions.weight.isna().all()
    assert result.positions.native_market_value.notna().tolist() == [True, False]


@pytest.mark.parametrize("stale_fx", [False, True])
def test_actual_workspace_offline_recalculation_uses_reference_gate(
    tmp_path, monkeypatch, stale_fx
):
    from stock_tool.application import holding_analysis
    from stock_tool.application.portfolio_workspace import PortfolioWorkspaceApplicationService
    from stock_tool.dashboard.pages import portfolio_workspace

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return WEEKEND.astimezone(tz) if tz else WEEKEND.replace(tzinfo=None)

    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setattr(holding_analysis, "datetime", Clock)
    monkeypatch.setattr(portfolio_workspace, "datetime", Clock)
    positions = pd.DataFrame([position("3006", "TWSE"), position()])
    prices = pd.concat([price_frame("3006", "TWSE"), price_frame()], ignore_index=True)
    quote = FxQuote.manual("USD", "TWD", 32, FRIDAY_FETCHED if stale_fx else "2026-10-18T10:00:00Z")
    st = SimpleNamespace(
        session_state=State(
            price_data=prices, portfolio_fx_resolution=SimpleNamespace(quote=quote)
        ),
        error=lambda *_a: None,
    )
    service = PortfolioWorkspaceApplicationService(
        portfolio_path=tmp_path / "positions.csv",
        ledger_path=tmp_path / "missing.sqlite",
        now=lambda: WEEKEND,
    )

    def offline():
        raise OSError("synthetic offline provider")

    portfolio_workspace._refresh_and_analyze(st, service, positions, offline, None)
    analysis = st.session_state.portfolio_workspace_analysis
    assert st.session_state.holding_refresh_failed
    assert analysis.valuation.positions.native_market_value.tolist() == [200.0, 200.0]
    if stale_fx:
        assert analysis.valuation.base_market_value is None
        assert analysis.valuation.positions.weight.isna().all()
    else:
        assert analysis.valuation.base_market_value == 6600.0
        assert analysis.valuation.positions.weight.sum() == pytest.approx(1.0)
    pd.testing.assert_frame_equal(st.session_state.price_data, prices)
