from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from stock_tool.data.universe import (
    HistoricalUniverse,
    UniverseDataError,
    load_historical_universe_csv,
    survivorship_bias_warnings,
)

SAMPLE_UNIVERSE = (
    Path(__file__).resolve().parents[1] / "data" / "sample" / "historical_universe_synthetic.csv"
)


def test_universe_members_change_by_as_of_date() -> None:
    universe = load_historical_universe_csv(SAMPLE_UNIVERSE)

    january = {
        (item.symbol.code, item.symbol.market.value)
        for item in universe.members_as_of("2024-01-15")
    }
    march = {
        (item.symbol.code, item.symbol.market.value)
        for item in universe.members_as_of("2024-03-15")
    }

    assert january == {("2330", "TWSE"), ("OLD", "TWSE")}
    assert march == {("2330", "TWSE"), ("6488", "TPEX")}
    assert universe.dataset_completeness == "partial"


def test_universe_rejects_invalid_and_overlapping_memberships(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.csv"
    invalid.write_text(
        "\n".join(
            [
                "symbol,market,effective_from,effective_to,status,source,dataset_completeness",
                "2330,TWSE,2024-02-01,2024-01-01,listed,fixture,partial",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(UniverseDataError, match="effective_to"):
        load_historical_universe_csv(invalid)

    overlap = tmp_path / "overlap.csv"
    overlap.write_text(
        "\n".join(
            [
                "symbol,market,effective_from,effective_to,status,source,dataset_completeness",
                "2330,TWSE,2024-01-01,2024-03-01,listed,fixture,partial",
                "2330,TWSE,2024-02-01,,listed,fixture,partial",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(UniverseDataError, match="overlap"):
        load_historical_universe_csv(overlap)


def test_survivorship_warnings_do_not_overstate_partial_universe() -> None:
    assert any("存活者偏誤" in item for item in survivorship_bias_warnings(None))

    partial = HistoricalUniverse(
        memberships=(),
        dataset_completeness="partial",
        source="fixture",
    )
    warnings = survivorship_bias_warnings(partial)

    assert any("partial" in item or "部分" in item for item in warnings)
    assert not any("已解決" in item for item in warnings)


def test_universe_loader_does_not_mutate_input_frame() -> None:
    source = pd.DataFrame(
        {
            "symbol": ["2330"],
            "market": ["TWSE"],
            "effective_from": ["2024-01-01"],
            "effective_to": [pd.NA],
            "status": ["listed"],
            "source": ["fixture"],
            "dataset_completeness": ["unknown"],
        }
    )
    original = source.copy(deep=True)

    universe = HistoricalUniverse.from_frame(source)

    assert universe.members_as_of("2024-06-01")[0].symbol.code == "2330"
    pd.testing.assert_frame_equal(source, original)
