from datetime import UTC, datetime

import pandas as pd
import pytest

from stock_tool.application.holding_analysis import build_holding_analysis
from stock_tool.application.holding_identity import fetch_holding_identity
from stock_tool.portfolio_valuation import FxQuote

NOW = datetime(2026, 9, 8, 12, tzinfo=UTC)


def position():
    return dict(
        symbol="MU", market="US", currency="USD", quantity=2, average_cost=80, note="private"
    )


def prices(**updates):
    row = dict(
        symbol="MU",
        market="US",
        close=100,
        date="2026-09-08",
        fetched_at="2026-09-08T10:00:00Z",
        provider="fixture",
    )
    row.update(updates)
    return pd.DataFrame([row])


def test_native_value_survives_missing_fx_and_fundamentals():
    original = position()
    result = build_holding_analysis(original, prices=prices(), fx_quote=None, now=NOW)
    assert any(d.label == "原幣市值" and d.value == "USD 200.00" for d in result.data)
    assert any("匯率" in gap for gap in result.gaps)
    assert original == position()
    assert "private" not in str(result.evidence_bundle())


def test_future_fx_is_rejected_by_both_totals_and_holding_snapshot():
    from stock_tool.application.holding_analysis import holding_fx_is_usable

    quote = FxQuote.manual("USD", "TWD", 32, "2099-01-01T00:00:00Z")
    assert not holding_fx_is_usable(quote)
    result = build_holding_analysis(position(), prices=prices(), fx_quote=quote, now=NOW)
    assert not any(datum.label == "台幣參考市值" for datum in result.data)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, 0])
def test_invalid_price_never_becomes_valuation(bad):
    result = build_holding_analysis(position(), prices=prices(close=bad), fx_quote=None, now=NOW)
    assert not any(d.label == "原幣市值" for d in result.data)


def test_identity_and_currency_conflicts_do_not_produce_valuation():
    result = build_holding_analysis(
        position(), prices=prices(market="TWSE"), fx_quote=None, now=NOW
    )
    assert not any(d.label == "原幣市值" for d in result.data)
    conflict = build_holding_analysis(
        position(), prices=prices(), fx_quote=None, profile={"currency": "TWD"}, now=NOW
    )
    assert not any(d.label == "原幣市值" for d in conflict.data)


def test_snapshot_and_ai_share_exact_values_and_fingerprint():
    quote = FxQuote.manual("USD", "TWD", 32, "2026-09-08T10:00:00Z")
    result = build_holding_analysis(
        position(), prices=prices(), fx_quote=quote, weight=0.2, now=NOW
    )
    bundle = result.evidence_bundle()
    assert bundle.snapshot_fingerprint == result.fingerprint
    for datum in result.data:
        assert any(datum.value in item.text for item in bundle.evidence)
    assert any(d.value == "TWD 6,400.00" for d in result.data)
    assert all(item.symbol == "MU" and item.market == "US" for item in bundle.evidence)


def test_old_or_failed_prices_are_not_presented_as_current():
    old = build_holding_analysis(
        position(), prices=prices(date="2025-01-01"), fx_quote=None, now=NOW
    )
    assert next(d for d in old.data if d.label == "收盤價").status == "可能過期"
    failed = build_holding_analysis(
        position(), prices=prices(), fx_quote=None, refresh_failed=True, now=NOW
    )
    assert next(d for d in failed.data if d.label == "收盤價").status == "保留前次資料"


def test_etf_has_no_company_profitability_conclusion():
    result = build_holding_analysis(
        position(), prices=prices(), fx_quote=None, profile={"instrument_type": "ETF"}, now=NOW
    )
    assert any("成分" in gap for gap in result.gaps)
    assert not any("公司前景" in gap for gap in result.gaps)


def test_provider_profile_rejects_mismatched_symbols():
    with pytest.raises(ValueError, match="身份"):
        fetch_holding_identity("MU", "US", loader=lambda _: {"symbol": "AAPL", "currency": "USD"})


def test_provider_profile_resolves_etf_without_guessing_from_ticker():
    result = fetch_holding_identity(
        "00935",
        "TWSE",
        loader=lambda query: {"symbol": query, "currency": "TWD", "quoteType": "ETF"},
    )
    assert result["instrument_type"] == "ETF"


def test_same_day_conflicting_quotes_do_not_enter_totals():
    from stock_tool.application.holding_analysis import validated_holding_prices

    conflicting = pd.concat([prices(close=100), prices(close=200)], ignore_index=True)
    result = build_holding_analysis(position(), prices=conflicting, fx_quote=None, now=NOW)
    assert not any(item.label == "原幣市值" for item in result.data)
    filtered = validated_holding_prices(pd.DataFrame([position()]), conflicting, {})
    assert filtered is not None and filtered.empty


def test_identity_store_rejects_corruption_and_preserves_manual_type(tmp_path):
    from stock_tool.application.holding_identity import load_identity_state, save_identity_state

    path = tmp_path / "identity.json"
    save_identity_state(path, {"profiles": {}, "overrides": {"MU|US": "股票"}})
    assert load_identity_state(path)["overrides"] == {"MU|US": "股票"}
    path.write_text('{"profiles": []}', encoding="utf-8")
    assert load_identity_state(path) == {}


def test_ui_auto_refresh_once_and_cost_edit_recalculates_without_refetch(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STOCK_TOOL_AI_API_KEY", "")
    data = tmp_path / "data"
    data.mkdir()
    pd.DataFrame([position()]).to_csv(data / "portfolio.csv", index=False)
    app = AppTest.from_string("""
import streamlit as st
import pandas as pd
from datetime import datetime, UTC
from types import SimpleNamespace
from stock_tool.application.portfolio_workspace import PortfolioWorkspaceApplicationService
from stock_tool.dashboard.pages.portfolio_workspace import render_portfolio_workspace
from stock_tool.portfolio_valuation import FxQuote
def refresh():
    st.session_state['refresh_count'] = st.session_state.get('refresh_count', 0) + 1
    stamp = datetime.now(UTC).isoformat()
    st.session_state.price_data = pd.DataFrame([dict(symbol='MU', market='US', date=stamp[:10], close=100., provider='fixture', fetched_at=stamp)])
    st.session_state.portfolio_fx_resolution = SimpleNamespace(quote=FxQuote.manual('USD', 'TWD', 32, stamp))
    return ()
render_portfolio_workspace(st, service=PortfolioWorkspaceApplicationService(), refresh_callback=refresh)
""").run(timeout=20)
    assert not app.exception
    assert app.session_state["refresh_count"] == 1
    assert app.session_state["portfolio_workspace_analysis"].valuation.base_market_value == 6400
    app.run(timeout=20)
    assert app.session_state["refresh_count"] == 1
    app.text_input(key="portfolio_workspace_symbol").set_value("MU")
    app.selectbox(key="portfolio_workspace_market").set_value("US")
    app.number_input(key="portfolio_workspace_quantity").set_value(3)
    app.number_input(key="portfolio_workspace_average_cost").set_value(80)
    app.text_input(key="portfolio_workspace_note").set_value("private")
    app.button(key="portfolio_workspace_upsert").click().run(timeout=20)
    assert not app.exception
    assert app.session_state["refresh_count"] == 1
    assert app.session_state["portfolio_workspace_analysis"].valuation.base_market_value == 9600
    saved = pd.read_csv(data / "portfolio.csv")
    assert saved.iloc[0]["note"] == "private"
    assert saved.iloc[0]["average_cost"] == 80
    app.button(key="holding_generate_ai").click().run(timeout=20)
    assert not app.exception
    assert len(app.session_state["holding_ai_notes"]) == 1


@pytest.mark.parametrize(
    "updates",
    [
        {"date": "2025-01-01"},
        {"fetched_at": ""},
        {"provider": ""},
        {"date": "2099-01-01"},
        {"fetched_at": "2025-01-01T00:00:00Z"},
    ],
)
@pytest.mark.parametrize("failed", [False, True])
def test_untrusted_prices_never_enter_snapshot_totals_or_ai(updates, failed):
    from stock_tool.application.holding_analysis import validated_holding_prices

    frame = prices(**updates)
    result = build_holding_analysis(
        position(), prices=frame, fx_quote=None, now=NOW, refresh_failed=failed, weight=1.0
    )
    assert not any(d.label in {"原幣市值", "原幣未實現損益", "台幣參考市值"} for d in result.data)
    assert not any("100.0%" in text for text in result.observations)
    assert not any("市值：" in item.text for item in result.evidence_bundle().evidence)
    filtered = validated_holding_prices(pd.DataFrame([position()]), frame, {}, now=NOW)
    assert filtered is not None and filtered.empty


def test_restored_etf_override_initializes_control_and_analysis(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from stock_tool.application.holding_identity import save_identity_state

    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path))
    save_identity_state(
        tmp_path / "data" / "holding_identity.json",
        {"profiles": {}, "overrides": {"00935|TWSE": "ETF"}},
    )
    script = """
import streamlit as st
import pandas as pd
from stock_tool.application.holding_identity import load_identity_state
from stock_tool.runtime_paths import RuntimePaths
from stock_tool.dashboard.components.holding_analysis import render_holding_analysis
state = load_identity_state(RuntimePaths.from_environment().data_dir/'holding_identity.json')
st.session_state.setdefault('holding_type_overrides', state['overrides'])
render_holding_analysis(st, pd.DataFrame([dict(symbol='00935',market='TWSE',currency='TWD',quantity=1,average_cost=10)]), None)
"""
    for _ in range(2):
        app = AppTest.from_string(script).run()
        assert not app.exception
        assert app.selectbox(key="holding_kind_00935|TWSE").value == "ETF"
        assert (
            app.session_state["holding_analysis_snapshots"]["00935|TWSE"].instrument_type == "ETF"
        )


def test_yfinance_databases_are_bound_to_runtime_before_use(tmp_path):
    import os
    import subprocess
    import sys

    script = """
from pathlib import Path
from stock_tool.yfinance_runtime import configure_yfinance_cache
import yfinance.cache as cache
root = configure_yfinance_cache()
assert root == configure_yfinance_cache()
cache.get_tz_cache().store('FIXTURE', 'UTC')
cache.get_isin_cache().store('FIXTURE', 'TEST')
cache.get_cookie_cache().initialise()
assert all(Path(manager.get_location()) == root for manager in
           [cache._TzDBManager, cache._CookieDBManager, cache._ISINDBManager])
assert (root/'tkr-tz.db').exists()
assert (root/'cookies.db').exists()
assert (root/'isin-tkr.db').exists()
"""
    env = dict(
        os.environ,
        STOCK_TOOL_USER_DATA_DIR=str(tmp_path / "runtime"),
        LOCALAPPDATA=str(tmp_path / "uncreated-local"),
        PYTHONPATH=str(__import__("pathlib").Path("src").resolve()),
    )
    completed = subprocess.run(
        [sys.executable, "-B", "-c", script], env=env, capture_output=True, text=True, timeout=30
    )
    assert completed.returncode == 0, completed.stderr
    assert not (tmp_path / "uncreated-local").exists()
