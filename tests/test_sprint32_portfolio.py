from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pandas.testing as pdt
import pytest

from stock_tool.dashboard import app as dashboard_app
from stock_tool.portfolio_health import PortfolioHealthConfig, PortfolioHealthService
import stock_tool.portfolio_health as portfolio_health
from stock_tool.portfolio_management import (
    load_portfolio,
    remove_portfolio_position,
)
from stock_tool.portfolio_research import build_portfolio_research_brief
from stock_tool.portfolio_stress import (
    PortfolioStressService,
    StressScenario,
    StressScenarioType,
)
from stock_tool.portfolio_valuation import (
    CachedFxRateProvider,
    Currency,
    FxQuote,
    PortfolioValuationConfig,
    PortfolioValuationService,
    StaticFxRateProvider,
)
from stock_tool.runtime_paths import RuntimePaths, migrate_legacy_user_data

FIXTURE = Path(__file__).parent / "fixtures" / "sprint32_positions.csv"


def _positions() -> pd.DataFrame:
    return pd.read_csv(FIXTURE, dtype={"symbol": str, "market": str, "currency": str})


def _prices() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2026-01-02", "2026-01-02"],
            "symbol": ["TWDEMO", "USDEMO"],
            "market": ["TWSE", "US"],
            "close": [120.0, 60.0],
        }
    )


def _usd_twd_quote(*, source: str = "fixture", stale: bool = False) -> FxQuote:
    return FxQuote(
        from_currency=Currency.USD,
        to_currency=Currency.TWD,
        rate=32.0,
        source=source,
        fetched_at="2026-01-02T00:00:00+00:00",
        effective_at="2026-01-02T00:00:00+00:00",
        stale=stale,
    )


def test_fixed_fixture_supports_twd_only_and_usd_only_views() -> None:
    positions = _positions()
    twd = positions.loc[positions["currency"] == "TWD"].copy()
    usd = positions.loc[positions["currency"] == "USD"].copy()
    prices = _prices()

    twd_result = PortfolioValuationService().value(
        positions=twd, prices=prices.loc[prices["market"] == "TWSE"]
    )
    usd_result = PortfolioValuationService(
        config=PortfolioValuationConfig(base_currency=Currency.USD)
    ).value(positions=usd, prices=prices.loc[prices["market"] == "US"])

    assert twd_result.base_market_value == 1200.0
    assert usd_result.base_market_value == 120.0
    assert twd_result.positions["weight"].sum() == 1.0
    assert usd_result.positions["weight"].sum() == 1.0


def test_mixed_fixture_requires_fx_before_consolidated_weight() -> None:
    result = PortfolioValuationService().value(positions=_positions(), prices=_prices())

    assert result.base_market_value is None
    assert result.positions["weight"].isna().all()
    assert any(item.field == "fx_rate_to_base" for item in result.missing_data)


def test_mixed_fixture_uses_base_currency_for_totals_and_weights() -> None:
    result = PortfolioValuationService(fx_provider=StaticFxRateProvider([_usd_twd_quote()])).value(
        positions=_positions(), prices=_prices()
    )

    assert result.base_cost_basis == 4200.0
    assert result.base_market_value == 5040.0
    assert result.base_unrealized_pnl == 840.0
    assert result.positions["weight"].sum() == 1.0


def test_stale_and_manual_fx_are_explicit() -> None:
    stale = PortfolioValuationService(
        fx_provider=StaticFxRateProvider([_usd_twd_quote(source="fixture", stale=True)])
    ).value(positions=_positions(), prices=_prices())
    manual = FxQuote.manual(Currency.USD, Currency.TWD, 32.0, "2026-01-02T00:00:00+00:00")

    assert any("stale" in warning.lower() for warning in stale.warnings)
    assert stale.positions.loc[stale.positions["market"] == "US", "fx_source"].iloc[0] == "fixture"
    assert manual.source == "manual"


def test_cached_fx_provider_uses_fresh_cache_and_rejects_expired_cache() -> None:
    cached_quote = _usd_twd_quote(source="fixture-cache")
    cache = StaticFxRateProvider([cached_quote])

    def now() -> datetime:
        return datetime(2026, 1, 2, tzinfo=timezone.utc)

    provider = CachedFxRateProvider(None, cache, max_age_seconds=86_400, now=now)
    expired = CachedFxRateProvider(
        None,
        cache,
        max_age_seconds=60,
        now=lambda: datetime(2026, 1, 3, tzinfo=timezone.utc),
    )

    assert provider.get_quote(Currency.USD, Currency.TWD) is not None
    assert provider.get_quote(Currency.USD, Currency.TWD).source == "cache:fixture-cache"
    assert expired.get_quote(Currency.USD, Currency.TWD) is None


def test_same_code_different_market_is_not_collided_or_removed_together() -> None:
    positions = pd.DataFrame(
        {
            "symbol": ["DUP", "DUP"],
            "market": ["TWSE", "US"],
            "currency": ["TWD", "USD"],
            "quantity": [1.0, 2.0],
            "average_cost": [10.0, 20.0],
        }
    )
    prices = pd.DataFrame(
        {
            "date": ["2026-01-02", "2026-01-02"],
            "symbol": ["DUP", "DUP"],
            "market": ["TWSE", "US"],
            "close": [11.0, 22.0],
        }
    )

    retained = remove_portfolio_position(positions, symbol="DUP", market="US")
    valued = PortfolioValuationService().value(
        positions=retained, prices=prices.loc[prices["market"] == "TWSE"]
    )

    assert retained[["symbol", "market"]].to_dict("records") == [
        {"symbol": "DUP", "market": "TWSE"}
    ]
    assert valued.positions.iloc[0]["latest_price"] == 11.0


def test_runtime_migration_is_repeat_safe_and_does_not_overwrite_new_data(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    legacy_file = legacy / "data" / "portfolio.csv"
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text(
        "symbol,market,quantity,average_cost\nLEGACY,TWSE,1,10\n",
        encoding="utf-8",
    )
    paths = RuntimePaths(tmp_path / "runtime")
    first = migrate_legacy_user_data(paths, legacy_root=legacy)
    first_bytes = paths.portfolio_file.read_bytes()
    second = migrate_legacy_user_data(paths, legacy_root=legacy)

    assert first.item("portfolio").status == "migrated"
    assert second.item("portfolio").status == "skipped_existing"
    assert paths.portfolio_file.read_bytes() == first_bytes
    assert legacy_file.exists()
    assert load_portfolio(paths.portfolio_file).loc[0, "symbol"] == "LEGACY"


def test_health_score_is_deterministic_evidenced_and_not_based_on_unrealized_pnl() -> None:
    positions = _positions()
    valuation = PortfolioValuationService(
        fx_provider=StaticFxRateProvider([_usd_twd_quote()])
    ).value(positions=positions, prices=_prices())
    indicators = pd.DataFrame(
        {
            "symbol": ["TWDEMO", "USDEMO"],
            "market": ["TWSE", "US"],
            "rolling_volatility_20": [0.2, 0.3],
            "max_drawdown": [-0.1, -0.2],
        }
    )
    scores = pd.DataFrame(
        {
            "symbol": ["TWDEMO", "USDEMO"],
            "market": ["TWSE", "US"],
            "total_score": [70.0, 80.0],
        }
    )
    service = PortfolioHealthService(PortfolioHealthConfig(minimum_coverage_pct=0.7))
    first = service.assess(
        portfolio=positions,
        valuation=valuation,
        fundamentals=scores,
        indicators=indicators,
        stock_scores=scores,
    )
    second = service.assess(
        portfolio=positions,
        valuation=valuation,
        fundamentals=scores,
        indicators=indicators,
        stock_scores=scores,
    )

    assert first == second
    assert first.overall_score is not None
    assert all(component.evidence for component in first.components)
    assert all(
        "unrealized" not in " ".join(component.reasons).lower() for component in first.components
    )


def test_low_coverage_uses_canonical_missing_data_and_research_brief_has_no_trade_instruction() -> (
    None
):
    valuation = PortfolioValuationService().value(positions=_positions(), prices=_prices())
    health = PortfolioHealthService().assess(
        portfolio=_positions(),
        valuation=valuation,
    )
    brief = build_portfolio_research_brief(health)
    text = " ".join(
        [
            brief.overall_summary,
            *brief.strengths,
            *brief.top_risks,
            *brief.next_checks,
            brief.disclaimer,
        ]
    )

    assert health.overall_score is None
    assert any(item.field == "technical_indicators" for item in health.missing_data)
    assert any(item.field == "composite_score" for item in health.missing_data)
    assert not any(word in text for word in ("買進", "賣出", "加碼", "減碼"))


def test_stress_scenarios_are_transparent_and_do_not_mutate_inputs() -> None:
    positions = _positions()
    valuation = PortfolioValuationService(
        fx_provider=StaticFxRateProvider([_usd_twd_quote()])
    ).value(positions=positions, prices=_prices())
    before = valuation.positions.copy(deep=True)
    service = PortfolioStressService()

    all_down = service.run(
        valuation=valuation,
        scenario=StressScenario("all", StressScenarioType.ALL_HOLDINGS_DECLINE, 0.1),
    )
    usd_move = service.run(
        valuation=valuation,
        scenario=StressScenario("fx", StressScenarioType.USD_TWD_MOVE, 0.1),
    )

    assert all_down.base_impact == -504.0
    assert usd_move.base_impact == 384.0
    pdt.assert_frame_equal(valuation.positions, before)
    assert "not a forecast" in all_down.disclaimer.lower()


def test_dashboard_missing_price_check_does_not_use_unqualified_price_for_duplicate_identity() -> (
    None
):
    portfolio = pd.DataFrame(
        {
            "symbol": ["DUP", "DUP"],
            "market": ["TWSE", "US"],
            "quantity": [1.0, 1.0],
            "average_cost": [10.0, 10.0],
        }
    )
    prices = pd.DataFrame({"symbol": ["DUP"], "close": [11.0], "date": ["2026-01-02"]})

    assert dashboard_app._missing_portfolio_price_symbols(portfolio, prices) == ("DUP",)


def test_risk_inputs_use_latest_value_and_weight_each_identity_once() -> None:
    positions = pd.DataFrame(
        {
            "symbol": ["A", "B"],
            "market": ["TWSE", "US"],
            "weight": [0.5, 0.5],
        }
    )
    indicators = pd.DataFrame(
        {
            "symbol": ["A"] * 100 + ["B"],
            "market": ["TWSE"] * 100 + ["US"],
            "date": list(pd.date_range("2026-01-01", periods=100, freq="D"))
            + [pd.Timestamp("2026-04-10")],
            "rolling_volatility_20": [0.10] * 100 + [0.50],
            "max_drawdown": [-0.10] * 100 + [-0.50],
        }
    )
    original = indicators.copy(deep=True)

    volatility = portfolio_health._weighted_numeric(
        indicators, positions, ("rolling_volatility_20",)
    )
    drawdown = portfolio_health._weighted_numeric(indicators, positions, ("max_drawdown",))

    assert volatility == 0.30
    assert drawdown == -0.30
    pdt.assert_frame_equal(indicators, original)


def test_position_quality_uses_current_weighted_positions_and_reports_missing_scores() -> None:
    positions = pd.DataFrame(
        {
            "symbol": ["A", "B"],
            "market": ["TWSE", "US"],
            "weight": [0.5, 0.5],
        }
    )
    scores = pd.DataFrame(
        {
            "symbol": ["A", "A", "B", "OUTSIDE"],
            "market": ["TWSE", "TWSE", "US", "US"],
            "date": ["2026-01-01", "2026-01-02", "2026-01-02", "2026-01-02"],
            "total_score": [20.0, 40.0, 60.0, 100.0],
        }
    )
    component = PortfolioHealthService()._quality_component(scores, positions)

    assert component.score == 50.0
    assert component.evidence[0]["count"] == 2

    incomplete = PortfolioHealthService()._quality_component(
        scores.loc[scores["symbol"] != "B"], positions
    )
    assert incomplete.score is None
    assert incomplete.missing_data[0].field == "composite_score"


def test_dashboard_composite_scores_enable_health_only_with_canonical_score_inputs() -> None:
    dates = pd.date_range("2026-01-01", periods=20, freq="D")
    portfolio = pd.DataFrame(
        {
            "symbol": ["TW", "US"],
            "market": ["TWSE", "US"],
            "currency": ["TWD", "USD"],
            "quantity": [10.0, 10.0],
            "average_cost": [100.0, 10.0],
        }
    )
    prices = pd.concat(
        [
            pd.DataFrame({"date": dates, "symbol": symbol, "market": market, "close": close})
            for symbol, market, close in (("TW", "TWSE", 100.0), ("US", "US", 10.0))
        ],
        ignore_index=True,
    )
    indicators = prices.assign(
        sma_20=lambda frame: frame["close"],
        sma_60=lambda frame: frame["close"],
        rsi_14=55.0,
        macd_dif=1.0,
        macd_dea=0.0,
        return_20=0.01,
        volatility_20=0.01,
        rolling_volatility_20=0.10,
        max_drawdown=-0.10,
        atr_14=1.0,
    )
    fundamental_scores = pd.DataFrame(
        {
            "symbol": ["TW", "US"],
            "market": ["TWSE", "US"],
            "growth_score": [20.0, 20.0],
            "profitability_score": [20.0, 20.0],
            "financial_safety_score": [20.0, 20.0],
            "cashflow_score": [20.0, 20.0],
            "valuation_score": [20.0, 20.0],
        }
    )
    valuation = PortfolioValuationService(
        fx_provider=StaticFxRateProvider([_usd_twd_quote()])
    ).value(positions=portfolio, prices=prices)

    composite_scores = dashboard_app._portfolio_composite_scores(
        portfolio=portfolio,
        prices=prices,
        indicators=indicators,
        fundamental_scores=fundamental_scores,
    )
    health = PortfolioHealthService().assess(
        portfolio=portfolio,
        valuation=valuation,
        fundamentals=fundamental_scores,
        indicators=indicators,
        stock_scores=composite_scores,
    )

    assert composite_scores["total_score"].notna().all()
    assert set(map(tuple, composite_scores[["symbol", "market"]].to_numpy())) == {
        ("TW", "TWSE"),
        ("US", "US"),
    }
    assert health.status == "available"
    assert health.coverage.composite_score_coverage_pct == 1.0


def test_usd_twd_stress_uses_correct_base_currency_direction_and_does_not_mutate() -> None:
    positions = pd.DataFrame(
        {
            "symbol": ["TW", "US"],
            "market": ["TWSE", "US"],
            "currency": ["TWD", "USD"],
            "quantity": [10.0, 10.0],
            "average_cost": [100.0, 10.0],
        }
    )
    prices = pd.DataFrame(
        {
            "date": ["2026-01-02", "2026-01-02"],
            "symbol": ["TW", "US"],
            "market": ["TWSE", "US"],
            "close": [100.0, 10.0],
        }
    )
    tWD_valuation = PortfolioValuationService(
        fx_provider=StaticFxRateProvider([_usd_twd_quote()])
    ).value(positions=positions, prices=prices)
    usd_valuation = PortfolioValuationService(
        fx_provider=StaticFxRateProvider(
            [
                FxQuote(
                    from_currency=Currency.TWD,
                    to_currency=Currency.USD,
                    rate=1.0 / 32.0,
                    source="fixture",
                    fetched_at="2026-01-02T00:00:00+00:00",
                    effective_at="2026-01-02T00:00:00+00:00",
                )
            ]
        ),
        config=PortfolioValuationConfig(base_currency=Currency.USD),
    ).value(positions=positions, prices=prices)
    service = PortfolioStressService()
    before_twd = tWD_valuation.positions.copy(deep=True)
    before_usd = usd_valuation.positions.copy(deep=True)

    twd_positive = service.run(
        valuation=tWD_valuation,
        scenario=StressScenario("fx", StressScenarioType.USD_TWD_MOVE, 0.10),
    )
    twd_negative = service.run(
        valuation=tWD_valuation,
        scenario=StressScenario("fx", StressScenarioType.USD_TWD_MOVE, -0.10),
    )
    usd_positive = service.run(
        valuation=usd_valuation,
        scenario=StressScenario("fx", StressScenarioType.USD_TWD_MOVE, 0.10),
    )
    zero_move = service.run(
        valuation=tWD_valuation,
        scenario=StressScenario("fx", StressScenarioType.USD_TWD_MOVE, 0.0),
    )

    assert twd_positive.base_value_after == 4520.0
    assert twd_negative.base_value_after == 3880.0
    assert usd_positive.base_value_after == pytest.approx(128.4090909091)
    assert zero_move.base_impact == 0.0
    assert "USD/TWD +10.0%" in twd_positive.assumptions[0]
    pdt.assert_frame_equal(tWD_valuation.positions, before_twd)
    pdt.assert_frame_equal(usd_valuation.positions, before_usd)
