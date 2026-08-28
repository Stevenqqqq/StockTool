from __future__ import annotations

import json

import pytest

from stock_tool.config import DEFAULT_FEATURE_FLAGS
from stock_tool.domain.models import Market, MissingData, MissingDataState, Symbol


@pytest.mark.parametrize(
    ("raw_market", "expected"),
    [
        ("TWSE", Market.TWSE),
        ("台股上市 TWSE", Market.TWSE),
        ("TPEx", Market.TPEX),
        ("台股上櫃 TPEx", Market.TPEX),
        ("US", Market.US),
        ("美股 US", Market.US),
        ("AUTO", Market.AUTO),
    ],
)
def test_market_parse_normalizes_supported_aliases(
    raw_market: str,
    expected: Market,
) -> None:
    assert Market.parse(raw_market) is expected


@pytest.mark.parametrize(
    ("raw_symbol", "market", "expected_code", "expected_market"),
    [
        ("2330", "TWSE", "2330", Market.TWSE),
        ("2330.TW", "TWSE", "2330", Market.TWSE),
        ("6488", "TPEx", "6488", Market.TPEX),
        ("6488.TWO", "TPEx", "6488", Market.TPEX),
        ("aapl", "US", "AAPL", Market.US),
        ("BRK.B", "US", "BRK.B", Market.US),
        ("2330.TW", "AUTO", "2330", Market.TWSE),
        ("6488.TWO", "AUTO", "6488", Market.TPEX),
    ],
)
def test_symbol_parse_produces_canonical_identity(
    raw_symbol: str,
    market: str,
    expected_code: str,
    expected_market: Market,
) -> None:
    symbol = Symbol.parse(raw_symbol, market=market)

    assert symbol.code == expected_code
    assert symbol.market is expected_market
    assert symbol.canonical == f"{expected_market.value}:{expected_code}"


def test_symbol_rejects_empty_or_conflicting_market_suffix() -> None:
    with pytest.raises(ValueError, match="股票代號不可為空"):
        Symbol.parse("", market="TWSE")

    with pytest.raises(ValueError, match="市場與代號後綴不一致"):
        Symbol.parse("2330.TW", market="TPEx")


def test_symbol_serialization_round_trip_is_stable() -> None:
    symbol = Symbol.parse("6488.TWO", market="TPEx")

    payload = symbol.to_dict()
    encoded = json.dumps(payload, sort_keys=True)
    restored = Symbol.from_dict(json.loads(encoded))

    assert payload == {"code": "6488", "market": "TPEX"}
    assert restored == symbol


@pytest.mark.parametrize(
    "state",
    [
        MissingDataState.MISSING,
        MissingDataState.UNKNOWN,
        MissingDataState.NOT_APPLICABLE,
        MissingDataState.STALE,
    ],
)
def test_missing_data_states_are_json_serializable(state: MissingDataState) -> None:
    missing = MissingData(
        field="pe_ratio",
        state=state,
        reason="provider did not supply a reliable value",
    )

    encoded = json.dumps(missing.to_dict(), sort_keys=True)
    restored = MissingData.from_dict(json.loads(encoded))

    assert restored == missing
    assert restored.to_dict()["state"] == state.value


def test_missing_data_requires_explicit_field_and_reason() -> None:
    with pytest.raises(ValueError, match="field"):
        MissingData(field="", state=MissingDataState.UNKNOWN, reason="not available")

    with pytest.raises(ValueError, match="reason"):
        MissingData(field="eps", state=MissingDataState.UNKNOWN, reason="")


def test_provider_contract_feature_flag_defaults_off() -> None:
    assert DEFAULT_FEATURE_FLAGS.provider_contracts_enabled is False
