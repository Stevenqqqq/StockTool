"""Hand-calculable corporate-action regression tests."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from stock_tool.backtest import BacktestEngine
from stock_tool.data.corporate_actions import (
    AdjustedSeriesContract,
    CorporateAction,
    CorporateActionDataError,
    CorporateActionType,
    PricePolicy,
    ReturnBasis,
    load_corporate_actions_csv,
)
from stock_tool.domain.models import Market, Symbol


def _prices(*, split_price: float = 50.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
            "symbol": ["ABC"] * 4,
            "market": ["US"] * 4,
            "open": [100.0, 100.0, split_price, split_price],
            "high": [100.0, 100.0, split_price, split_price],
            "low": [100.0, 100.0, split_price, split_price],
            "close": [100.0, 100.0, split_price, split_price],
            "volume": [100] * 4,
        }
    )


def _buy_signal(quantity: int = 10) -> pd.DataFrame:
    return pd.DataFrame(
        [{"date": "2024-01-01", "symbol": "ABC", "action": "buy", "quantity": quantity}]
    )


def _action(
    action_type: CorporateActionType,
    *,
    effective_date: str = "2024-01-03",
    available_date: str = "2024-01-02",
    payable_date: str | None = None,
    split_ratio: float | None = None,
    cash_per_share: float | None = None,
    tax_rate: float | None = None,
    source: str = "synthetic-fixture",
) -> CorporateAction:
    return CorporateAction(
        symbol=Symbol("ABC", Market.US),
        action_type=action_type,
        effective_date=effective_date,
        available_date=available_date,
        payable_date=payable_date,
        split_ratio=split_ratio,
        cash_per_share=cash_per_share,
        currency="USD",
        tax_rate=tax_rate,
        source=source,
        provenance={"fixture": "corporate_actions"},
        confidence="complete",
    )


def test_two_for_one_split_preserves_cost_basis_value_and_daily_reconciliation() -> None:
    split = _action(CorporateActionType.SPLIT, split_ratio=2.0)

    result = BacktestEngine(
        initial_cash=1_100.0,
        corporate_actions=(split,),
        price_policy=PricePolicy.RAW_PRICE_WITH_EXPLICIT_ACTIONS,
        return_basis=ReturnBasis.PRICE_RETURN,
    ).run(_prices(), _buy_signal())

    position = result.portfolio.positions["ABC"]
    assert position.quantity == 20
    assert position.average_cost == pytest.approx(50.0)
    assert position.market_value == pytest.approx(1_000.0)
    assert result.portfolio.cash == pytest.approx(100.0)
    assert result.corporate_action_audit.iloc[0]["status"] == "applied"
    assert result.corporate_action_audit.iloc[0]["quantity_before"] == 10
    assert result.corporate_action_audit.iloc[0]["quantity_after"] == 20
    assert result.daily_reconciliation["difference"].abs().max() == pytest.approx(0.0)


def test_reverse_split_rejects_non_integral_quantity_without_rounding() -> None:
    split = _action(CorporateActionType.SPLIT, split_ratio=0.5)

    result = BacktestEngine(
        initial_cash=1_100.0,
        corporate_actions=(split,),
        price_policy=PricePolicy.RAW_PRICE_WITH_EXPLICIT_ACTIONS,
    ).run(_prices(split_price=200.0), _buy_signal(quantity=5))

    position = result.portfolio.positions["ABC"]
    assert position.quantity == 5
    assert position.average_cost == pytest.approx(100.0)
    assert result.corporate_action_audit.iloc[0]["status"] == "unavailable"
    assert "fractional" in result.corporate_action_audit.iloc[0]["reason"]


def test_cash_dividend_uses_ex_date_entitlement_and_payable_date_cash() -> None:
    dividend = _action(
        CorporateActionType.CASH_DIVIDEND,
        payable_date="2024-01-04",
        cash_per_share=2.0,
        tax_rate=0.10,
    )

    result = BacktestEngine(
        initial_cash=1_100.0,
        corporate_actions=(dividend,),
        price_policy=PricePolicy.RAW_PRICE_WITH_EXPLICIT_ACTIONS,
        return_basis=ReturnBasis.TOTAL_RETURN,
    ).run(_prices(split_price=100.0), _buy_signal())

    day_three = result.equity_curve.loc[result.equity_curve["date"] == "2024-01-03"].iloc[0]
    day_four = result.equity_curve.loc[result.equity_curve["date"] == "2024-01-04"].iloc[0]
    audit = result.corporate_action_audit.iloc[0]
    assert day_three["cash"] == pytest.approx(100.0)
    assert day_four["cash"] == pytest.approx(118.0)
    assert audit["gross_cash_delta"] == pytest.approx(20.0)
    assert audit["tax"] == pytest.approx(2.0)
    assert audit["net_cash_delta"] == pytest.approx(18.0)
    assert audit["status"] == "applied"
    assert result.daily_reconciliation["difference"].abs().max() == pytest.approx(0.0)


def test_cash_dividend_fails_closed_for_price_return() -> None:
    dividend = _action(
        CorporateActionType.CASH_DIVIDEND,
        payable_date="2024-01-04",
        cash_per_share=2.0,
        tax_rate=0.10,
    )

    with pytest.raises(ValueError, match="cash dividends require total_return"):
        BacktestEngine(
            initial_cash=1_100.0,
            corporate_actions=(dividend,),
            price_policy=PricePolicy.RAW_PRICE_WITH_EXPLICIT_ACTIONS,
            return_basis=ReturnBasis.PRICE_RETURN,
        )


def test_unavailable_corporate_action_is_not_used_before_available_date() -> None:
    split = _action(
        CorporateActionType.SPLIT,
        available_date="2024-01-04",
        split_ratio=2.0,
    )

    result = BacktestEngine(
        initial_cash=1_100.0,
        corporate_actions=(split,),
        price_policy=PricePolicy.RAW_PRICE_WITH_EXPLICIT_ACTIONS,
    ).run(_prices(), _buy_signal())

    assert result.portfolio.positions["ABC"].quantity == 10
    assert result.corporate_action_audit.iloc[0]["status"] == "unavailable"
    assert "available_date" in result.corporate_action_audit.iloc[0]["reason"]


def test_duplicate_action_is_applied_once_and_no_action_mode_is_unchanged() -> None:
    split = _action(CorporateActionType.SPLIT, split_ratio=2.0)
    with_actions = BacktestEngine(
        initial_cash=1_100.0,
        corporate_actions=(split, split),
        price_policy=PricePolicy.RAW_PRICE_WITH_EXPLICIT_ACTIONS,
    ).run(_prices(), _buy_signal())
    legacy = BacktestEngine(initial_cash=1_100.0).run(_prices(split_price=100.0), _buy_signal())
    explicit_no_action = BacktestEngine(
        initial_cash=1_100.0,
        price_policy=PricePolicy.RAW_PRICE_WITH_EXPLICIT_ACTIONS,
        return_basis=ReturnBasis.PRICE_RETURN,
    ).run(_prices(split_price=100.0), _buy_signal())

    assert with_actions.portfolio.positions["ABC"].quantity == 20
    assert (with_actions.corporate_action_audit["status"] == "applied").sum() == 1
    pd.testing.assert_frame_equal(legacy.equity_curve, explicit_no_action.equity_curve)


def test_equivalent_multi_source_actions_apply_once_and_preserve_source_evidence() -> None:
    provider_a = _action(CorporateActionType.SPLIT, split_ratio=2.0, source="provider-a")
    provider_b = _action(CorporateActionType.SPLIT, split_ratio=2.0, source="provider-b")

    result = BacktestEngine(
        initial_cash=1_100.0,
        corporate_actions=(provider_a, provider_b),
        price_policy=PricePolicy.RAW_PRICE_WITH_EXPLICIT_ACTIONS,
    ).run(_prices(), _buy_signal())

    assert result.portfolio.positions["ABC"].quantity == 20
    audit = result.corporate_action_audit.iloc[0]
    assert audit["status"] == "applied"
    assert set(audit["source_evidence"]) == {"provider-a", "provider-b"}


def test_conflicting_multi_source_actions_fail_closed_with_audit() -> None:
    provider_a = _action(CorporateActionType.SPLIT, split_ratio=2.0, source="provider-a")
    provider_b = _action(CorporateActionType.SPLIT, split_ratio=3.0, source="provider-b")

    result = BacktestEngine(
        initial_cash=1_100.0,
        corporate_actions=(provider_a, provider_b),
        price_policy=PricePolicy.RAW_PRICE_WITH_EXPLICIT_ACTIONS,
    ).run(_prices(), _buy_signal())

    assert result.portfolio.positions["ABC"].quantity == 10
    assert set(result.corporate_action_audit["status"]) == {"unavailable"}
    assert result.corporate_action_audit["reason"].str.contains("conflicting sources").all()
    assert set(result.corporate_action_audit["source"]) == {"provider-a", "provider-b"}


def test_cash_dividend_tax_rate_conflict_fails_closed_without_crediting_cash() -> None:
    provider_a = _action(
        CorporateActionType.CASH_DIVIDEND,
        payable_date="2024-01-04",
        cash_per_share=2.0,
        tax_rate=0.10,
        source="provider-a",
    )
    provider_b = _action(
        CorporateActionType.CASH_DIVIDEND,
        payable_date="2024-01-04",
        cash_per_share=2.0,
        tax_rate=0.20,
        source="provider-b",
    )

    result = BacktestEngine(
        initial_cash=1_100.0,
        corporate_actions=(provider_a, provider_b),
        price_policy=PricePolicy.RAW_PRICE_WITH_EXPLICIT_ACTIONS,
        return_basis=ReturnBasis.TOTAL_RETURN,
    ).run(_prices(split_price=100.0), _buy_signal())

    assert result.portfolio.cash == pytest.approx(100.0)
    assert set(result.corporate_action_audit["status"]) == {"unavailable"}
    assert result.corporate_action_audit["reason"].str.contains("conflicting sources").all()
    assert set(result.corporate_action_audit["source"]) == {"provider-a", "provider-b"}


def test_equivalent_cash_dividend_sources_apply_once_independent_of_input_order() -> None:
    provider_a = _action(
        CorporateActionType.CASH_DIVIDEND,
        payable_date="2024-01-04",
        cash_per_share=2.0,
        tax_rate=0.10,
        source="provider-a",
    )
    provider_b = _action(
        CorporateActionType.CASH_DIVIDEND,
        payable_date="2024-01-04",
        cash_per_share=2.0,
        tax_rate=0.10,
        source="provider-b",
    )
    engine_kwargs = {
        "initial_cash": 1_100.0,
        "price_policy": PricePolicy.RAW_PRICE_WITH_EXPLICIT_ACTIONS,
        "return_basis": ReturnBasis.TOTAL_RETURN,
    }

    forward = BacktestEngine(corporate_actions=(provider_a, provider_b), **engine_kwargs).run(
        _prices(split_price=100.0), _buy_signal()
    )
    reverse = BacktestEngine(corporate_actions=(provider_b, provider_a), **engine_kwargs).run(
        _prices(split_price=100.0), _buy_signal()
    )

    assert forward.portfolio.cash == pytest.approx(118.0)
    assert reverse.portfolio.cash == pytest.approx(118.0)
    assert forward.corporate_action_audit.iloc[0]["net_cash_delta"] == pytest.approx(18.0)
    assert set(forward.corporate_action_audit.iloc[0]["source_evidence"]) == {
        "provider-a",
        "provider-b",
    }
    pd.testing.assert_frame_equal(forward.equity_curve, reverse.equity_curve)
    pd.testing.assert_frame_equal(forward.corporate_action_audit, reverse.corporate_action_audit)


def test_no_trade_corporate_action_is_audited_without_creating_cash() -> None:
    dividend = _action(
        CorporateActionType.CASH_DIVIDEND,
        payable_date="2024-01-04",
        cash_per_share=2.0,
    )

    result = BacktestEngine(
        initial_cash=1_000.0,
        corporate_actions=(dividend,),
        price_policy=PricePolicy.RAW_PRICE_WITH_EXPLICIT_ACTIONS,
        return_basis=ReturnBasis.TOTAL_RETURN,
    ).run(_prices(split_price=100.0))

    assert result.portfolio.cash == pytest.approx(1_000.0)
    assert result.corporate_action_audit.iloc[0]["status"] == "unavailable"
    assert "no eligible position" in result.corporate_action_audit.iloc[0]["reason"]


def test_corporate_action_csv_contract_preserves_explicit_coverage_metadata() -> None:
    fixture = Path(__file__).parent / "fixtures" / "corporate_actions_golden.csv"

    action = load_corporate_actions_csv(fixture)[0]

    assert action.symbol == Symbol("ABC", Market.US)
    assert action.available_date == "2024-01-02"
    assert action.to_dict()["completeness"] == "partial"


def test_mixed_market_duplicate_symbol_price_rows_fail_closed_with_actions() -> None:
    action = _action(CorporateActionType.SPLIT, split_ratio=2.0)
    prices = pd.concat(
        [_prices(), _prices().assign(market="TWSE")],
        ignore_index=True,
    )

    with pytest.raises(ValueError, match="duplicate symbol/date rows across markets"):
        BacktestEngine(corporate_actions=(action,)).run(prices, _buy_signal())


def test_action_fails_closed_when_one_symbol_has_multiple_markets_over_time() -> None:
    action = CorporateAction(
        symbol=Symbol("ABC", Market.TWSE),
        action_type=CorporateActionType.SPLIT,
        effective_date="2024-01-03",
        available_date="2024-01-02",
        split_ratio=2.0,
        source="provider-a",
    )
    prices = pd.concat(
        [
            _prices().iloc[:2].copy(),
            _prices().iloc[2:].assign(market="TWSE"),
        ],
        ignore_index=True,
    )

    with pytest.raises(ValueError, match="market identity ambiguity"):
        BacktestEngine(corporate_actions=(action,)).run(prices, _buy_signal())


def test_corporate_action_contract_rejects_ambiguous_or_malformed_inputs() -> None:
    with pytest.raises(CorporateActionDataError, match="source is required"):
        AdjustedSeriesContract(source="", verified=True)
    with pytest.raises(CorporateActionDataError, match="must be verified"):
        AdjustedSeriesContract(source="provider", verified=False)
    with pytest.raises(CorporateActionDataError, match="requires adjusted_close"):
        AdjustedSeriesContract(source="provider", verified=True, price_column="close")
    with pytest.raises(CorporateActionDataError, match="unsupported"):
        AdjustedSeriesContract(source="provider", verified=True, return_basis="bad")
    with pytest.raises(CorporateActionDataError, match="requires total_return"):
        AdjustedSeriesContract(
            source="provider", verified=True, return_basis=ReturnBasis.PRICE_RETURN
        )

    valid = dict(
        symbol=Symbol("ABC", Market.US),
        action_type=CorporateActionType.SPLIT,
        effective_date="2024-01-03",
        available_date="2024-01-02",
        split_ratio=2.0,
        source="provider",
    )
    invalid_cases = [
        {"symbol": "ABC"},
        {"symbol": Symbol("ABC", Market.AUTO)},
        {"action_type": "unknown"},
        {"effective_date": "not-a-date"},
        {"payable_date": "2024-01-01"},
        {"source": ""},
        {"confidence": "invalid"},
        {"completeness": "invalid"},
        {"split_ratio": 0},
        {"split_ratio": "not-a-number"},
        {"cash_per_share": 1.0},
    ]
    for overrides in invalid_cases:
        payload = dict(valid)
        payload.update(overrides)
        with pytest.raises((TypeError, ValueError, CorporateActionDataError)):
            CorporateAction(**payload)

    dividend = dict(valid)
    dividend.update(
        action_type=CorporateActionType.CASH_DIVIDEND,
        split_ratio=None,
        cash_per_share=2.0,
        currency=None,
    )
    with pytest.raises(CorporateActionDataError, match="require currency"):
        CorporateAction(**dividend)
    dividend["currency"] = "USD"
    dividend["tax_rate"] = 2.0
    with pytest.raises(CorporateActionDataError, match="between 0 and 1"):
        CorporateAction(**dividend)


def test_corporate_action_csv_rejects_encoding_empty_and_missing_columns(tmp_path: Path) -> None:
    invalid_utf8 = tmp_path / "invalid.csv"
    invalid_utf8.write_bytes(b"\xff\xfe")
    with pytest.raises(CorporateActionDataError, match="UTF-8"):
        load_corporate_actions_csv(invalid_utf8)

    empty = tmp_path / "empty.csv"
    empty.write_text("symbol,market\n", encoding="utf-8")
    with pytest.raises(CorporateActionDataError, match="empty"):
        load_corporate_actions_csv(empty)

    missing = tmp_path / "missing.csv"
    missing.write_text("symbol,market\nABC,US\n", encoding="utf-8")
    with pytest.raises(CorporateActionDataError, match="missing columns"):
        load_corporate_actions_csv(missing)

    malformed = tmp_path / "malformed.csv"
    malformed.write_text(
        "symbol,market,action_type,effective_date,available_date,source\n"
        "ABC,US,split,2024-01-03,2024-01-02,provider\n",
        encoding="utf-8",
    )
    with pytest.raises(CorporateActionDataError, match="split actions require"):
        load_corporate_actions_csv(malformed)
