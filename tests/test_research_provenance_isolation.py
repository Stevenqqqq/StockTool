"""Research completion and provenance must never borrow a different identity."""

from copy import deepcopy

import pandas as pd
import pytest

from stock_tool.dashboard import app
from test_dashboard import _FakeStreamlit
from test_research_workspace import _prices, _profile


def _state(monkeypatch, *, market="TWSE", session=None):
    raw = _prices().assign(
        market=market,
        provider="yfinance",
        provider_symbol="2330.TW" if market == "TWSE" else "2330.TWO",
        source_type="online",
        fetched_at="2026-10-13T12:00:00Z",
    )
    st = _FakeStreamlit()
    st.session_state.update(
        price_data=raw,
        fundamental_scores=None,
        backtest_result=None,
        dashboard_status="ready",
        price_data_source=session,
    )
    monkeypatch.setattr(app, "_get_company_research_profile", lambda *_: None)
    return st


def _foreign_source(*, market="TWSE", symbol="6669"):
    return {
        "market": market,
        "user_symbol": symbol,
        "query_symbol": symbol + (".TW" if market == "TWSE" else ".TWO"),
        "provider": "OTHER_COMPANY_PROVIDER",
        "source_type": "SQLite 匯入資料",
        "fetched_at": "2026-10-20T12:00:00Z",
        "updated_at": "2099-01-01T00:00:00Z",
        "warnings": ("OTHER_COMPANY_WARNING",),
    }


@pytest.mark.parametrize("session_identity", [("TWSE", "6669"), ("TPEX", "2330")])
@pytest.mark.parametrize("mode", ["absent", "null"])
@pytest.mark.parametrize(
    "columns",
    [
        ("provider",),
        ("provider_symbol",),
        ("source_type",),
        ("fetched_at",),
        ("provider", "provider_symbol", "source_type", "fetched_at"),
    ],
)
def test_missing_columns_never_borrow_session_provenance(
    monkeypatch, session_identity, mode, columns
):
    market, symbol = session_identity
    session = _foreign_source(market=market, symbol=symbol)
    st = _state(monkeypatch, session=session)
    if mode == "absent":
        st.session_state.price_data = st.session_state.price_data.drop(columns=list(columns))
    else:
        st.session_state.price_data.loc[:, list(columns)] = None
    before = st.session_state.price_data.copy(deep=True)
    session_before = deepcopy(session)
    result = app._build_research_snapshot(st, symbol="2330", market="TWSE")
    source = result.source_metadata
    assert "OTHER_COMPANY" not in str(source)
    assert source.market == "TWSE"
    if "fetched_at" in columns:
        assert result.price is None
        assert source.row_count == 0
        assert source.fetched_at is None
        assert result.scenario_reference is None
        assert result.indicators is None or result.indicators.empty
        assert any("完成狀態無法確認" in warning for warning in source.warnings)
    else:
        assert result.price.latest_close == 179
        assert source.row_count == len(before)
        assert source.fetched_at == "2026-10-13T12:00:00Z"
        if "provider" in columns:
            assert source.provider is None
        if "provider_symbol" in columns:
            assert source.query_symbol is None
        if "source_type" in columns:
            assert source.source_type == "unknown"
    pd.testing.assert_frame_equal(st.session_state.price_data, before)
    assert session == session_before


@pytest.mark.parametrize(
    "session_time", ["2026-10-14T02:20:00Z", "2026-10-14T12:00:00Z", "2099-01-01T00:00:00Z", None]
)
@pytest.mark.parametrize("own_time", [None, "2026-10-14T02:20:00Z"])
def test_completion_uses_only_identity_row_acquisition_time(monkeypatch, session_time, own_time):
    session = _foreign_source()
    session["fetched_at"] = session_time
    st = _state(monkeypatch, session=session)
    raw = st.session_state.price_data.tail(1).assign(date="2026-10-14")
    st.session_state.price_data = (
        raw.drop(columns="fetched_at") if own_time is None else raw.assign(fetched_at=own_time)
    )
    before = st.session_state.price_data.copy(deep=True)
    result = app._build_research_snapshot(st, symbol="2330", market="TWSE")
    assert result.price is None
    assert result.source_metadata.row_count == 0
    pd.testing.assert_frame_equal(st.session_state.price_data, before)


@pytest.mark.parametrize("market", ["TWSE", "TPEX"])
def test_same_code_other_market_rows_cannot_supply_completion_or_metadata(monkeypatch, market):
    other_market = "TPEX" if market == "TWSE" else "TWSE"
    st = _state(
        monkeypatch, market=market, session=_foreign_source(market=other_market, symbol="2330")
    )
    target = st.session_state.price_data
    other = target.assign(market=other_market, close=9999, provider="OTHER_MARKET")
    st.session_state.price_data = pd.concat([other, target], ignore_index=True)
    before = st.session_state.price_data.copy(deep=True)
    result = app._build_research_snapshot(st, symbol="2330", market=market)
    assert result.price.latest_close == 179
    assert result.source_metadata.row_count == len(target)
    assert result.source_metadata.provider == "yfinance"
    assert result.source_metadata.query_symbol == target.provider_symbol.iloc[-1]
    assert result.source_metadata.fetched_at == target.fetched_at.iloc[-1]
    pd.testing.assert_frame_equal(st.session_state.price_data, before)


def test_unbound_same_identity_session_is_not_a_legacy_time_fallback(monkeypatch):
    st = _state(monkeypatch, session=_foreign_source(symbol="2330"))
    st.session_state.price_data = st.session_state.price_data.drop(columns="fetched_at")
    result = app._build_research_snapshot(st, symbol="2330", market="TWSE")
    assert result.price is None
    assert result.source_metadata.fetched_at is None


@pytest.mark.parametrize("column", ["market", "symbol"])
def test_unidentified_rows_cannot_be_qualified_by_session(monkeypatch, column):
    st = _state(monkeypatch, session=_foreign_source(symbol="2330"))
    st.session_state.price_data = st.session_state.price_data.drop(columns=column)
    before = st.session_state.price_data.copy(deep=True)
    result = app._build_research_snapshot(st, symbol="2330", market="TWSE")
    assert result.price is None
    assert result.source_metadata.row_count == 0
    assert result.source_metadata.provider is None
    pd.testing.assert_frame_equal(st.session_state.price_data, before)


def test_latest_accepted_row_owns_time_not_rejected_tail_or_session(monkeypatch):
    st = _state(monkeypatch, session=_foreign_source())
    raw = st.session_state.price_data.tail(2).copy(deep=True)
    raw["date"] = ["2026-10-13", "2026-10-14"]
    raw["fetched_at"] = ["2026-10-13T12:00:00Z", "2026-10-14T02:20:00Z"]
    st.session_state.price_data = raw
    before = raw.copy(deep=True)
    result = app._build_research_snapshot(st, symbol="2330", market="TWSE")
    assert result.price.latest_close == 178
    assert result.source_metadata.fetched_at == "2026-10-13T12:00:00Z"
    assert pd.Timestamp(result.source_metadata.last_data_date) == pd.Timestamp("2026-10-13")
    assert result.source_metadata.row_count == 1
    pd.testing.assert_frame_equal(st.session_state.price_data, before)


def test_missing_price_time_preserves_available_company_profile(monkeypatch):
    st = _state(monkeypatch, session=_foreign_source())
    st.session_state.price_data = st.session_state.price_data.drop(columns="fetched_at")
    profile = _profile()
    monkeypatch.setattr(app, "_get_company_research_profile", lambda *_: profile)
    result = app._build_research_snapshot(st, symbol="2330", market="TWSE")
    assert result.price is None
    assert result.company_profile == profile
    assert result.company_name == profile.company_name
