from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pandas.testing as pdt

from stock_tool.application.daily_brief import (
    DailyBriefService,
    DailyRefreshRecord,
    DailyRefreshService,
    ResearchContinuation,
    _normalize_prices,
    _percent_from_evidence,
    _portfolio_pulse,
    _price_events,
)
from stock_tool.domain.models import Market, MissingData, MissingDataState, Symbol
from stock_tool.portfolio_valuation import Currency, PortfolioValuationResult


def _portfolio() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "2330",
                "market": "TWSE",
                "quantity": 10.0,
                "average_cost": 100.0,
                "currency": "TWD",
                "note": "",
            },
            {
                "symbol": "MU",
                "market": "US",
                "quantity": 2.0,
                "average_cost": 80.0,
                "currency": "USD",
                "note": "",
            },
        ]
    )


def _prices() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "2330",
                "market": "TWSE",
                "date": "2024-01-08",
                "close": 100.0,
                "volume": 100.0,
            },
            {
                "symbol": "2330",
                "market": "TWSE",
                "date": "2024-01-10",
                "close": 108.0,
                "volume": 220.0,
            },
            {
                "symbol": "AAPL",
                "market": "US",
                "date": "2024-01-08",
                "close": 180.0,
                "volume": 50.0,
            },
        ]
    )


def _valuation() -> PortfolioValuationResult:
    positions = pd.DataFrame(
        [
            {
                "symbol": "2330",
                "market": "TWSE",
                "base_market_value": 1_080.0,
                "weight": 0.9,
            },
            {
                "symbol": "MU",
                "market": "US",
                "base_market_value": 120.0,
                "weight": 0.1,
            },
        ]
    )
    return PortfolioValuationResult(
        positions=positions,
        base_currency=Currency.TWD,
        base_cost_basis=1_160.0,
        base_market_value=1_200.0,
        base_unrealized_pnl=40.0,
        native_totals={"TWD": 1_080.0},
        warnings=(),
        missing_data=(),
    )


def test_daily_brief_is_deterministic_and_does_not_mutate_inputs() -> None:
    portfolio = _portfolio()
    watchlist = pd.DataFrame([{"symbol": "AAPL", "market": "US", "note": ""}])
    prices = _prices()
    valuation = _valuation()
    before_portfolio = portfolio.copy(deep=True)
    before_watchlist = watchlist.copy(deep=True)
    before_prices = prices.copy(deep=True)
    before_valuation = valuation.positions.copy(deep=True)
    continuations = (
        ResearchContinuation(
            symbol=Symbol.parse("2330", market=Market.TWSE),
            researched_at="2024-01-10T09:00:00+00:00",
            data_as_of_date="2024-01-10",
            coverage=0.8,
        ),
    )

    service = DailyBriefService(stale_after_days=2, significant_move_pct=0.05)
    first = service.build(
        portfolio=portfolio,
        watchlist=watchlist,
        prices=prices,
        valuation=valuation,
        continuations=continuations,
        reference_at="2024-01-12T00:00:00+00:00",
        risk_alert_count=1,
    )
    second = service.build(
        portfolio=portfolio,
        watchlist=watchlist,
        prices=prices,
        valuation=valuation,
        continuations=continuations,
        reference_at="2024-01-12T00:00:00+00:00",
        risk_alert_count=1,
    )

    assert first == second
    assert first.data_as_of_date == "2024-01-10"
    assert first.portfolio.position_count == 2
    assert first.portfolio.priced_position_count == 1
    assert first.portfolio.max_position_weight == 0.9
    assert first.portfolio.risk_alert_count == 1
    assert first.attention_items
    assert all(item.evidence and item.as_of_date for item in first.attention_items)
    pdt.assert_frame_equal(portfolio, before_portfolio)
    pdt.assert_frame_equal(watchlist, before_watchlist)
    pdt.assert_frame_equal(prices, before_prices)
    pdt.assert_frame_equal(valuation.positions, before_valuation)


def test_daily_brief_uses_adjacent_trading_rows_and_never_emits_trade_advice() -> None:
    brief = DailyBriefService(significant_move_pct=0.05).build(
        portfolio=_portfolio().iloc[:1],
        watchlist=pd.DataFrame(columns=["symbol", "market", "note"]),
        prices=_prices(),
        valuation=_valuation(),
        continuations=(),
        reference_at="2024-01-12T00:00:00+00:00",
    )

    move = next(item for item in brief.attention_items if item.code == "daily_move")
    assert move.as_of_date == "2024-01-10"
    assert "8.00%" in move.evidence
    rendered = " ".join(
        [item.title + " " + item.detail + " " + item.evidence for item in brief.attention_items]
    ).lower()
    assert "買進" not in rendered
    assert "賣出" not in rendered
    assert "保證" not in rendered


def test_daily_brief_keeps_missing_price_fundamental_and_fx_explicit() -> None:
    valuation = replace(
        _valuation(),
        base_market_value=None,
        missing_data=(
            MissingData(
                field="fx_rate_to_base",
                state=MissingDataState.MISSING,
                reason="No USD/TWD quote is available.",
            ),
        ),
    )
    brief = DailyBriefService().build(
        portfolio=_portfolio(),
        watchlist=pd.DataFrame(columns=["symbol", "market", "note"]),
        prices=_prices(),
        valuation=valuation,
        continuations=(),
        reference_at="2024-01-12T00:00:00+00:00",
    )

    fields = {item.field for item in brief.action_required}
    assert {"price_data", "fundamentals", "fx_rate_to_base"}.issubset(fields)
    assert brief.portfolio.max_position_weight is None
    assert brief.portfolio.unavailable_reason is not None


def test_daily_brief_deduplicates_market_qualified_continuations() -> None:
    twse = ResearchContinuation(
        symbol=Symbol.parse("2330", market="TWSE"),
        researched_at="2024-01-09T00:00:00+00:00",
        data_as_of_date="2024-01-08",
        coverage=0.5,
    )
    newer_twse = replace(twse, researched_at="2024-01-10T00:00:00+00:00", coverage=0.8)
    us = ResearchContinuation(
        symbol=Symbol.parse("2330", market="US"),
        researched_at="2024-01-11T00:00:00+00:00",
        data_as_of_date="2024-01-10",
        coverage=0.7,
    )

    brief = DailyBriefService().build(
        portfolio=pd.DataFrame(columns=["symbol", "market"]),
        watchlist=pd.DataFrame(columns=["symbol", "market", "note"]),
        prices=pd.DataFrame(columns=["symbol", "market", "date", "close"]),
        valuation=None,
        continuations=(twse, newer_twse, us),
        reference_at=None,
    )

    assert [(item.symbol.code, item.symbol.market.value) for item in brief.continuations] == [
        ("2330", "US"),
        ("2330", "TWSE"),
    ]
    assert brief.continuations[1].coverage == 0.8


def test_daily_refresh_limits_to_twenty_and_preserves_success_when_one_identity_fails() -> None:
    symbols = tuple(Symbol.parse(f"S{index}", market="US") for index in range(22))
    called: list[str] = []

    def hydrate(symbol: Symbol) -> DailyRefreshRecord:
        called.append(symbol.code)
        if symbol.code == "S1":
            raise RuntimeError("provider unavailable")
        return DailyRefreshRecord(
            symbol=symbol,
            status="success",
            provider="fixture",
            query_symbol=symbol.code,
            last_data_date="2024-01-10",
        )

    result = DailyRefreshService(max_symbols=20).refresh(symbols=symbols, hydrate=hydrate)

    assert result.requested_count == 22
    assert result.limited_count == 20
    assert result.success_count == 19
    assert result.failure_count == 1
    assert called == [f"S{index}" for index in range(20)]
    assert result.records[1].status == "failure"
    assert "provider unavailable" not in (result.records[1].reason or "")


def test_daily_brief_validates_configuration_and_handles_invalid_identity_rows() -> None:
    """Invalid configuration and unresolved market rows stay explicit and cannot fabricate alerts."""

    for kwargs in (
        {"stale_after_days": -1},
        {"significant_move_pct": 0.0},
        {"volume_multiple": 1.0},
        {"max_attention_items": 0},
    ):
        try:
            DailyBriefService(**kwargs)
        except ValueError:
            pass
        else:  # pragma: no cover - assertion branch only
            raise AssertionError("invalid DailyBriefService configuration was accepted")

    brief = DailyBriefService().build(
        portfolio=pd.DataFrame({"symbol": ["2330"], "market": ["UNKNOWN"]}),
        watchlist=pd.DataFrame(columns=["symbol", "market"]),
        prices=_prices(),
        valuation=None,
        continuations=(),
        reference_at="not-a-date",
    )
    assert brief.first_use is True
    assert brief.attention_items == ()


def test_daily_price_events_cover_range_breakouts_volume_and_adjacent_price_rules() -> None:
    """Range and volume events use only prior trading rows and keep their actual final date."""

    history = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=21, freq="B"),
            "close": [100.0] * 20 + [110.0],
            "volume": [100.0] * 20 + [300.0],
        }
    )
    high_events = _price_events(
        Symbol.parse("2330", market="TWSE"),
        history,
        reference_date=pd.Timestamp("2024-02-10"),
        stale_after_days=2,
        significant_move_pct=0.05,
        volume_multiple=1.5,
    )
    assert {item.code for item in high_events}.issuperset(
        {"stale_price", "daily_move", "range_breakout_high", "volume_spike"}
    )
    assert all(item.as_of_date == "2024-01-29" for item in high_events)

    low_history = history.copy(deep=True)
    low_history.loc[20, "close"] = 90.0
    low_events = _price_events(
        Symbol.parse("AAPL", market="US"),
        low_history,
        reference_date=None,
        stale_after_days=7,
        significant_move_pct=0.05,
        volume_multiple=1.5,
    )
    assert "range_breakout_low" in {item.code for item in low_events}


def test_daily_refresh_rejects_mismatched_identity_without_mutating_successes() -> None:
    """A provider record with a different canonical identity is not accepted into the batch result."""

    requested = Symbol.parse("2330", market="TWSE")
    wrong = Symbol.parse("2330", market="US")
    result = DailyRefreshService().refresh(
        symbols=(requested,),
        hydrate=lambda _: DailyRefreshRecord(symbol=wrong, status="success"),
    )

    assert result.success_count == 0
    assert result.failure_count == 1
    assert result.records[0].symbol == requested
    assert result.records[0].reason == "資料更新回傳的股票身分不一致。"


def test_daily_brief_safe_empty_and_unavailable_helpers_do_not_infer_data() -> None:
    """Malformed, partial, and unavailable local inputs remain unavailable rather than guessed."""

    try:
        DailyRefreshService(max_symbols=0)
    except ValueError:
        pass
    else:  # pragma: no cover - assertion branch only
        raise AssertionError("zero refresh limit was accepted")

    automatic = Symbol("AUTO", Market.AUTO)
    assert (
        DailyRefreshService()
        .refresh(
            symbols=(automatic,),
            hydrate=lambda symbol: DailyRefreshRecord(symbol=symbol, status="success"),
        )
        .requested_count
        == 0
    )
    assert _normalize_prices(pd.DataFrame({"symbol": ["2330"]})).empty
    assert _normalize_prices(
        pd.DataFrame(
            {"symbol": ["2330"], "market": ["UNKNOWN"], "date": ["2024-01-01"], "close": [1]}
        )
    ).empty
    normalized = _normalize_prices(
        pd.DataFrame({"symbol": ["2330"], "market": ["TWSE"], "date": ["2024-01-01"], "close": [1]})
    )
    assert normalized["volume"].isna().all()
    assert (
        _price_events(
            Symbol.parse("2330", market="TWSE"),
            None,
            reference_date=None,
            stale_after_days=7,
            significant_move_pct=0.05,
            volume_multiple=1.5,
        )
        == ()
    )
    pulse = _portfolio_pulse(
        portfolio_ids=(Symbol.parse("2330", market="TWSE"),),
        price_by_identity={},
        valuation=None,
        risk_alert_count=0,
        attention=(),
    )
    assert pulse.unavailable_reason == "尚未取得既有投資組合估值結果。"
    assert _percent_from_evidence("invalid evidence") == 0.0
    assert _percent_from_evidence("變動 nope%") == 0.0
