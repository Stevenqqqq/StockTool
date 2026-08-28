from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from stock_tool.application.portfolio_workspace import (
    PortfolioDataStatus,
    PortfolioWorkspaceApplicationService,
    PortfolioWorkspaceSnapshot,
    PortfolioWorkspaceStressResult,
    _analysis_status,
    _canonical_json,
    _json_default,
    _price_as_of,
    _prices_fingerprint,
)
from stock_tool.dashboard.pages.portfolio_workspace import (
    _frame_or_none,
    _health_percent,
    _manual_quote,
    _money,
    _percent,
    _rerun,
)
from stock_tool.domain.models import MissingData, MissingDataState
from stock_tool.portfolio_health import PortfolioHealthConfig
from stock_tool.portfolio_stress import StressScenario, StressScenarioType
from stock_tool.portfolio_valuation import Currency, FxQuote


def _service(tmp_path: Path) -> PortfolioWorkspaceApplicationService:
    return PortfolioWorkspaceApplicationService(
        portfolio_path=tmp_path / "portfolio.csv",
        ledger_path=tmp_path / "ledger.sqlite",
    )


def _positions(*rows: tuple[str, str, str, float, float]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": symbol,
                "market": market,
                "currency": currency,
                "quantity": quantity,
                "average_cost": average_cost,
                "note": "private note must not enter manifest",
            }
            for symbol, market, currency, quantity, average_cost in rows
        ],
        columns=["symbol", "quantity", "average_cost", "market", "currency", "note"],
    )


def _prices() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"symbol": "2330", "market": "TWSE", "date": "2026-08-01", "close": 600.0},
            {"symbol": "6488", "market": "TPEX", "date": "2026-08-01", "close": 120.0},
            {"symbol": "AAPL", "market": "US", "date": "2026-08-01", "close": 210.0},
        ]
    )


def _quote(stale: bool = False) -> FxQuote:
    return FxQuote(
        from_currency=Currency.USD,
        to_currency=Currency.TWD,
        rate=32.0,
        source="manual",
        fetched_at="2026-08-01T00:00:00+00:00",
        effective_at="2026-08-01T00:00:00+00:00",
        stale=stale,
    )


def test_empty_snapshot_is_missing_and_does_not_create_ledger(tmp_path: Path) -> None:
    service = _service(tmp_path)

    snapshot = service.load_snapshot()

    assert snapshot.status is PortfolioDataStatus.MISSING
    assert snapshot.positions.empty
    assert snapshot.portfolio is snapshot.positions
    assert not (tmp_path / "ledger.sqlite").exists()


def test_market_qualified_positions_support_all_markets_and_odd_lots(tmp_path: Path) -> None:
    service = _service(tmp_path)
    empty = service.load_positions()

    updated = service.add_position(
        empty,
        symbol="2330",
        market="TWSE",
        currency=None,
        quantity=1.25,
        average_cost=500,
    )
    updated = service.add_position(
        updated,
        symbol="2330",
        market="TPEX",
        currency=None,
        quantity=2,
        average_cost=100,
    )
    updated = service.add_position(
        updated,
        symbol="AAPL",
        market="US",
        currency=None,
        quantity=0.5,
        average_cost=200,
    )
    updated = service.add_position(
        updated,
        symbol="CUSTOM-1",
        market="CUSTOM",
        currency="USD",
        quantity=3,
        average_cost=10,
    )

    assert len(updated) == 4
    assert set(zip(updated.market, updated.symbol)) == {
        ("TWSE", "2330"),
        ("TPEX", "2330"),
        ("US", "AAPL"),
        ("CUSTOM", "CUSTOM-1"),
    }
    assert float(updated.loc[updated.symbol == "AAPL", "quantity"].iloc[0]) == 0.5
    reloaded = service.reload().positions
    assert reloaded.equals(updated)

    removed = service.remove_position(reloaded, symbol="2330", market="TPEX")
    assert set(removed.loc[removed.symbol == "2330", "market"]) == {"TWSE"}
    assert len(service.load_positions()) == 3

    with pytest.raises(ValueError):
        service.add_position(
            removed,
            symbol="CUSTOM-2",
            market="CUSTOM",
            currency=None,
            quantity=1,
            average_cost=1,
        )


def test_save_failure_does_not_mutate_input_frame_or_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path)
    original = _positions(("2330", "TWSE", "TWD", 1, 500))
    service.save_positions(original)
    before = (tmp_path / "portfolio.csv").read_bytes()

    def fail_save(*args: object, **kwargs: object) -> None:
        raise OSError("isolated save failure")

    monkeypatch.setattr("stock_tool.application.portfolio_workspace.save_portfolio", fail_save)
    with pytest.raises(OSError):
        service.add_position(
            original,
            symbol="AAPL",
            market="US",
            currency=None,
            quantity=1,
            average_cost=200,
        )

    assert original.equals(_positions(("2330", "TWSE", "TWD", 1, 500)))
    assert (tmp_path / "portfolio.csv").read_bytes() == before


def test_missing_prices_and_fx_never_create_fake_base_weights(tmp_path: Path) -> None:
    service = _service(tmp_path)
    positions = _positions(
        ("2330", "TWSE", "TWD", 1, 500),
        ("AAPL", "US", "USD", 1, 100),
    )

    missing = service.analyze(positions=positions, prices=None, fx_quote=None)
    assert missing.status is PortfolioDataStatus.PARTIAL
    assert missing.valuation.base_market_value is None
    assert missing.valuation.positions["weight"].isna().all()

    no_fx = service.analyze(positions=positions, prices=_prices(), fx_quote=None)
    assert no_fx.status is PortfolioDataStatus.PARTIAL
    assert no_fx.valuation.base_market_value is None
    assert no_fx.valuation.positions["weight"].isna().all()


def test_manual_and_stale_fx_are_explicit_and_manifest_is_private_deterministic(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    positions = _positions(("AAPL", "US", "USD", 1, 100))
    prices = _prices()
    quote = _quote()
    scenario = StressScenario(
        name="all-down", scenario_type=StressScenarioType.ALL_HOLDINGS_DECLINE, shock_pct=0.1
    )

    first = service.analyze(
        positions=positions,
        prices=prices,
        fx_quote=quote,
        stress_scenarios=(scenario,),
    )
    second = service.analyze(
        positions=positions,
        prices=prices,
        fx_quote=quote,
        stress_scenarios=(scenario,),
    )
    assert first.manifest.digest == second.manifest.digest
    assert first.result is first
    assert first.is_current is True
    assert "private note" not in first.manifest.to_json()
    assert "portfolio.csv" not in first.manifest.to_json()
    assert first.manifest.core["fx"]["source"] == "manual"

    stale = service.analyze(positions=positions, prices=prices, fx_quote=_quote(stale=True))
    assert stale.status is PortfolioDataStatus.STALE
    assert service.result_is_current(
        first,
        positions=positions,
        prices=prices,
        base_currency="TWD",
        fx_quote=quote,
        stress_scenarios=(scenario,),
    )
    changed = positions.copy()
    changed.loc[0, "quantity"] = 2
    assert not service.result_is_current(
        first,
        positions=changed,
        prices=prices,
        base_currency="TWD",
        fx_quote=quote,
        stress_scenarios=(scenario,),
    )
    changed_prices = prices.copy()
    changed_prices.loc[0, "close"] = 999
    assert not service.result_is_current(
        first,
        positions=positions,
        prices=changed_prices,
        base_currency="TWD",
        fx_quote=quote,
        stress_scenarios=(scenario,),
    )
    assert service.run_stress(first, scenario).base_value_after != first.valuation.base_market_value


def test_native_workspace_apptest_isolated_add_analyze_stress_and_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    data = runtime / "data"
    data.mkdir(parents=True)
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(runtime))
    app = AppTest.from_string("""
import streamlit as st
import pandas as pd
from stock_tool.application.portfolio_workspace import PortfolioWorkspaceApplicationService
from stock_tool.dashboard.pages.portfolio_workspace import render_portfolio_workspace

prices = pd.DataFrame([
    {"symbol": "2330", "market": "TWSE", "date": "2026-08-01", "close": 600.0},
    {"symbol": "AAPL", "market": "US", "date": "2026-08-01", "close": 210.0},
])
st.session_state.price_data = prices
service = PortfolioWorkspaceApplicationService()
render_portfolio_workspace(st, service=service)
""").run(timeout=20)
    assert not app.exception
    assert any(item.value == "持倉工作區" for item in app.title)

    app.text_input(key="portfolio_workspace_symbol").set_value("2330")
    app.selectbox(key="portfolio_workspace_market").set_value("TWSE")
    app.button(key="portfolio_workspace_upsert").click().run(timeout=20)
    assert not app.exception
    assert (data / "portfolio.csv").exists()

    app.text_input(key="portfolio_workspace_symbol").set_value("AAPL")
    app.selectbox(key="portfolio_workspace_market").set_value("US")
    app.selectbox(key="portfolio_workspace_currency").set_value("USD")
    app.number_input(key="portfolio_workspace_average_cost").set_value(100.0)
    app.button(key="portfolio_workspace_upsert").click().run(timeout=20)
    assert not app.exception
    assert len(pd.read_csv(data / "portfolio.csv")) == 2

    app.number_input(key="portfolio_workspace_manual_fx_input").set_value(32.0)
    app.button(key="portfolio_workspace_apply_fx").click().run(timeout=20)
    app.button(key="portfolio_workspace_analyze").click().run(timeout=20)
    assert not app.exception
    assert any("manifest digest" in str(item.value) for item in app.caption)
    assert any("分析持倉" in item.label for item in app.button)
    app.button(key="portfolio_workspace_run_stress").click().run(timeout=20)
    assert not app.exception
    first_stress = app.session_state["portfolio_workspace_stress_result"]
    assert isinstance(first_stress, PortfolioWorkspaceStressResult)
    first_digest = first_stress.manifest_digest

    app.number_input(key="portfolio_workspace_quantity").set_value(2.0)
    app.button(key="portfolio_workspace_upsert").click().run(timeout=20)
    assert not app.exception
    assert "portfolio_workspace_stress_result" not in app.session_state
    app.button(key="portfolio_workspace_analyze").click().run(timeout=20)
    assert not app.exception
    app.button(key="portfolio_workspace_run_stress").click().run(timeout=20)
    assert not app.exception
    second_stress = app.session_state["portfolio_workspace_stress_result"]
    assert isinstance(second_stress, PortfolioWorkspaceStressResult)
    assert second_stress.manifest_digest != first_digest

    app.selectbox(key="portfolio_workspace_stress_type").set_value("market_decline").run(timeout=20)
    app.selectbox(key="portfolio_workspace_stress_market").set_value("TWSE")
    app.button(key="portfolio_workspace_run_stress").click().run(timeout=20)
    assert not app.exception

    app.number_input(key="portfolio_workspace_manual_fx_input").set_value(0.0)
    app.button(key="portfolio_workspace_apply_fx").click().run(timeout=20)
    assert not app.exception

    app.selectbox(key="portfolio_workspace_base_currency").set_value("USD").run(timeout=20)
    assert any("過期" in str(item.value) for item in app.warning)
    app.button(key="portfolio_workspace_analyze").click().run(timeout=20)
    assert not app.exception
    app.selectbox(key="portfolio_workspace_remove_identity").set_value("AAPL / US")
    app.button(key="portfolio_workspace_remove").click().run(timeout=20)
    assert not app.exception
    assert len(pd.read_csv(data / "portfolio.csv")) == 1
    app.button(key="portfolio_workspace_reload").click().run(timeout=20)
    assert not app.exception


def test_application_does_not_use_global_runtime_path_for_injected_portfolio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated = tmp_path / "isolated.csv"
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path / "runtime"))
    service = PortfolioWorkspaceApplicationService(portfolio_path=isolated)
    positions = _positions(("2330", "TWSE", "TWD", 1, 500))
    service.save_positions(positions)
    assert isolated.exists()
    assert not (Path(os.environ["STOCK_TOOL_USER_DATA_DIR"]) / "data" / "portfolio.csv").exists()


def test_manifest_helpers_cover_empty_malformed_and_safe_serialization() -> None:
    assert _prices_fingerprint(None) is None
    assert _prices_fingerprint(pd.DataFrame()) is None
    assert _prices_fingerprint(pd.DataFrame({"symbol": ["A"]})) is None
    assert _price_as_of(None) is None
    assert _price_as_of(pd.DataFrame({"close": [1]})) is None
    assert _price_as_of(pd.DataFrame({"date": ["not-a-date"]})) is None
    missing = MissingData("price", MissingDataState.MISSING, "not available")
    assert _json_default(Path("private.csv")) == "private.csv"
    assert _json_default(PortfolioDataStatus.READY) == "ready"
    assert _json_default(("a", "b")) == ["a", "b"]
    assert _json_default(missing) == missing.to_dict()
    assert "a" in _canonical_json({"a": (1, 2)})
    with pytest.raises(TypeError):
        _json_default(object())


def test_analysis_reads_an_existing_ledger_but_never_creates_one(
    tmp_path: Path, monkeypatch
) -> None:
    service = _service(tmp_path)
    positions = _positions(("2330", "TWSE", "TWD", 1, 500))
    ledger = tmp_path / "ledger.sqlite"
    ledger.write_bytes(b"not-a-valid-ledger")
    analysis = service.analyze(positions=positions, prices=_prices())
    assert analysis.ledger_snapshot is None

    class BrokenRepository:
        def __init__(self, path: Path) -> None:
            raise RuntimeError("broken isolated ledger")

    monkeypatch.setattr(
        "stock_tool.application.portfolio_workspace.LedgerRepository", BrokenRepository
    )
    assert service._read_existing_ledger() is None


def test_render_helpers_are_explicit_for_missing_and_invalid_values() -> None:
    assert _manual_quote(None) is None
    assert _manual_quote("not-a-rate") is None
    assert _manual_quote(0) is None
    assert _manual_quote(32).source == "manual"
    assert _manual_quote(32).effective_at != "2026-01-01T00:00:00+00:00"
    assert _manual_quote(32, "2020-01-01T00:00:00+00:00").stale is True
    assert _frame_or_none(None) is None
    assert _frame_or_none(pd.DataFrame({"x": [1]})) is not None
    assert _money(None, None) == "資料不足"
    assert (
        _money(12.5, SimpleNamespace(manifest=SimpleNamespace(core={"base_currency": "USD"})))
        == "USD 12.50"
    )
    assert _money(12.5, None) == "TWD 12.50"
    assert _percent(None) == "資料不足"
    assert _percent(0.5) == "50.00%"
    assert _percent(0.5445) == "54.45%"
    assert _health_percent(None) == "無資料"
    assert _health_percent(84.82) == "84.82%"
    assert _health_percent(92.13) == "92.13%"
    assert _health_percent(100.0) == "100.00%"
    assert _health_percent(84.82) not in {"8482.00%", "10000.00%"}
    _rerun(SimpleNamespace())


def test_stress_result_binds_manifest_and_scenario_and_classification_is_source_backed(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    positions = _positions(
        ("2330", "TWSE", "TWD", 1, 500),
        ("6488", "TPEX", "TWD", 2, 100),
        ("AAPL", "US", "USD", 1, 100),
    )
    prices = pd.DataFrame(
        [
            {"symbol": "2330", "market": "TWSE", "date": "2026-08-01", "close": 600},
            {"symbol": "6488", "market": "TPEX", "date": "2026-08-01", "close": 110},
            {"symbol": "AAPL", "market": "US", "date": "2026-08-01", "close": 200},
        ]
    )
    quote = _quote()
    scenario = StressScenario("decline", StressScenarioType.ALL_HOLDINGS_DECLINE, 0.1)
    classifications = pd.DataFrame(
        [
            {
                "symbol": "2330",
                "market": "TWSE",
                "sector": "半導體",
                "industry": "IC",
                "source": "cache",
            },
            {
                "symbol": "6488",
                "market": "TPEX",
                "sector": "半導體",
                "industry": "矽晶圓",
                "source": "cache",
            },
            {
                "symbol": "AAPL",
                "market": "US",
                "sector": "Technology",
                "industry": "Hardware",
                "source": "cache",
            },
        ]
    )
    analysis = service.analyze(
        positions=positions,
        prices=prices,
        fx_quote=quote,
        classifications=classifications,
        stress_scenarios=(scenario,),
    )
    bound = service.run_stress(analysis, scenario)
    assert bound.manifest_digest == analysis.manifest.digest
    assert bound.scenario == scenario
    assert service.stress_result_is_current(bound, analysis, scenario)
    assert analysis.risk.sector_exposure.status == "available"
    changed = positions.copy()
    changed.loc[0, "quantity"] = 2
    changed_analysis = service.analyze(positions=changed, prices=prices, fx_quote=quote)
    assert not service.stress_result_is_current(bound, changed_analysis, scenario)


def test_status_helper_and_optional_service_inputs_are_explicit(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.save_positions(_positions(("2330", "TWSE", "TWD", 1, 500)))
    loaded = service.analyze(positions=None, prices=None)
    assert loaded.status is PortfolioDataStatus.PARTIAL
    configured = service.analyze(
        positions=_positions(("2330", "TWSE", "TWD", 1, 500)),
        prices=_prices(),
        health_config=PortfolioHealthConfig(),
        classifications=pd.DataFrame(),
        scenario_inputs=pd.DataFrame(),
    )
    assert configured.result is configured
    snapshot = PortfolioWorkspaceSnapshot(
        positions=_positions(("2330", "TWSE", "TWD", 1, 500)),
        status=PortfolioDataStatus.READY,
    )
    valuation = SimpleNamespace(base_market_value=1.0)
    risk = SimpleNamespace(price_data_status=SimpleNamespace(status="ready"))
    assert _analysis_status(snapshot, valuation, risk, None, ()) is PortfolioDataStatus.READY
    empty_snapshot = PortfolioWorkspaceSnapshot(pd.DataFrame(), PortfolioDataStatus.MISSING)
    assert (
        _analysis_status(empty_snapshot, valuation, risk, None, ()) is PortfolioDataStatus.MISSING
    )
    assert (
        _analysis_status(
            snapshot,
            valuation,
            SimpleNamespace(price_data_status=SimpleNamespace(status="stale")),
            None,
            (),
        )
        is PortfolioDataStatus.STALE
    )


def test_native_workspace_refresh_is_explicit_and_errors_are_recoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path / "runtime"))
    app = AppTest.from_string("""
import streamlit as st
from stock_tool.application.portfolio_workspace import PortfolioWorkspaceApplicationService
from stock_tool.dashboard.pages.portfolio_workspace import render_portfolio_workspace
service = PortfolioWorkspaceApplicationService()
render_portfolio_workspace(st, service=service, refresh_callback=lambda: {"refreshed": True})
""").run(timeout=20)
    app.button(key="portfolio_workspace_refresh").click().run(timeout=20)
    assert not app.exception

    failing = AppTest.from_string("""
import streamlit as st
from stock_tool.application.portfolio_workspace import PortfolioWorkspaceApplicationService
from stock_tool.dashboard.pages.portfolio_workspace import render_portfolio_workspace
def fail():
    raise RuntimeError("isolated provider failure")
render_portfolio_workspace(st, service=PortfolioWorkspaceApplicationService(), refresh_callback=fail)
""").run(timeout=20)
    failing.button(key="portfolio_workspace_refresh").click().run(timeout=20)
    assert not failing.exception
    assert failing.error


def test_native_workspace_save_error_does_not_change_session_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path / "runtime"))
    app = AppTest.from_string("""
import streamlit as st
from stock_tool.application.portfolio_workspace import PortfolioWorkspaceApplicationService
from stock_tool.dashboard.pages.portfolio_workspace import render_portfolio_workspace
class FailingService(PortfolioWorkspaceApplicationService):
    def add_or_update_position(self, *args, **kwargs):
        raise OSError("isolated write failure")
render_portfolio_workspace(st, service=FailingService())
""").run(timeout=20)
    app.text_input(key="portfolio_workspace_symbol").set_value("2330")
    app.button(key="portfolio_workspace_upsert").click().run(timeout=20)
    assert not app.exception
    assert app.error


def test_native_workspace_recovers_non_dataframe_session_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path / "runtime"))
    app = AppTest.from_string("""
import streamlit as st
from stock_tool.application.portfolio_workspace import PortfolioWorkspaceApplicationService
from stock_tool.dashboard.pages.portfolio_workspace import render_portfolio_workspace
st.session_state.portfolio_workspace_positions = "invalid-cache"
render_portfolio_workspace(st, service=PortfolioWorkspaceApplicationService())
""").run(timeout=20)
    assert not app.exception


def test_native_workspace_surfaces_stale_analysis_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path / "runtime"))
    app = AppTest.from_string("""
import streamlit as st
import pandas as pd
from stock_tool.application.portfolio_workspace import PortfolioWorkspaceApplicationService
from stock_tool.dashboard.pages.portfolio_workspace import render_portfolio_workspace
from stock_tool.portfolio_valuation import FxQuote, Currency
positions = pd.DataFrame([{"symbol":"AAPL","market":"US","currency":"USD","quantity":1,"average_cost":100,"note":""}])
prices = pd.DataFrame([{"symbol":"AAPL","market":"US","date":"2026-08-01","close":210.0}])
service = PortfolioWorkspaceApplicationService()
stale = FxQuote(from_currency=Currency.USD, to_currency=Currency.TWD, rate=32, source="manual", fetched_at="2026-08-01T00:00:00+00:00", effective_at="2026-08-01T00:00:00+00:00", stale=True)
st.session_state.portfolio_workspace_analysis = service.analyze(positions=positions, prices=prices, fx_quote=stale)
st.session_state.portfolio_workspace_snapshot = service._snapshot_from_positions(positions)
st.session_state.price_data = prices
render_portfolio_workspace(st, service=service)
""").run(timeout=20)
    assert not app.exception
    assert app.warning


def test_native_workspace_remove_failure_and_non_dataframe_prices_are_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path / "runtime"))
    app = AppTest.from_string("""
import streamlit as st
import pandas as pd
from stock_tool.application.portfolio_workspace import PortfolioWorkspaceApplicationService
from stock_tool.dashboard.pages.portfolio_workspace import render_portfolio_workspace

class FailingRemoveService(PortfolioWorkspaceApplicationService):
    def remove_position(self, *args, **kwargs):
        raise OSError("isolated remove failure")

service = FailingRemoveService()
service.save_positions(pd.DataFrame([{
    "symbol": "2330", "market": "TWSE", "currency": "TWD",
    "quantity": 1.0, "average_cost": 500.0, "note": ""
}]))
st.session_state.price_data = "not-a-dataframe"
render_portfolio_workspace(st, service=service)
""").run(timeout=20)
    app.selectbox(key="portfolio_workspace_remove_identity").set_value("2330 / TWSE")
    app.button(key="portfolio_workspace_remove").click().run(timeout=20)
    assert not app.exception
    assert app.error

    app.button(key="portfolio_workspace_analyze").click().run(timeout=20)
    assert not app.exception


def test_native_workspace_renders_empty_valuation_ledger_and_gaps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path / "runtime"))
    app = AppTest.from_string("""
import streamlit as st
import pandas as pd
from dataclasses import replace
from stock_tool.application.portfolio_workspace import PortfolioWorkspaceApplicationService
from stock_tool.dashboard.pages.portfolio_workspace import render_portfolio_workspace
from stock_tool.portfolio.ledger import LedgerSnapshot

positions = pd.DataFrame([{
    "symbol": "AAPL", "market": "US", "currency": "USD",
    "quantity": 1.0, "average_cost": 100.0, "note": ""
}])
prices = pd.DataFrame([{
    "symbol": "AAPL", "market": "US", "date": "2026-08-01", "close": 210.0
}])
service = PortfolioWorkspaceApplicationService()
analysis = service.analyze(positions=positions, prices=prices, base_currency="TWD")
analysis = replace(
    analysis,
    valuation=replace(analysis.valuation, positions=pd.DataFrame()),
    ledger_snapshot=LedgerSnapshot((), (), (), (), (), ()),
)
st.session_state.portfolio_workspace_positions = positions
st.session_state.portfolio_workspace_snapshot = service._snapshot_from_positions(positions)
st.session_state.price_data = prices
st.session_state.portfolio_workspace_analysis = analysis
render_portfolio_workspace(st, service=service)
""").run(timeout=20)
    assert not app.exception
    assert app.subheader


def test_native_workspace_renders_analysis_without_missing_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path / "runtime"))
    app = AppTest.from_string("""
import streamlit as st
import pandas as pd
from dataclasses import replace
from stock_tool.application.portfolio_workspace import PortfolioWorkspaceApplicationService
from stock_tool.dashboard.pages.portfolio_workspace import render_portfolio_workspace

positions = pd.DataFrame([{
    "symbol": "2330", "market": "TWSE", "currency": "TWD",
    "quantity": 1.0, "average_cost": 500.0, "note": ""
}])
prices = pd.DataFrame([{
    "symbol": "2330", "market": "TWSE", "date": "2026-08-01", "close": 600.0
}])
service = PortfolioWorkspaceApplicationService()
analysis = service.analyze(positions=positions, prices=prices)
analysis = replace(
    analysis,
    valuation=replace(analysis.valuation, positions=pd.DataFrame()),
    risk=replace(analysis.risk, missing_data=()),
)
st.session_state.portfolio_workspace_positions = positions
st.session_state.portfolio_workspace_snapshot = service._snapshot_from_positions(positions)
st.session_state.price_data = prices
st.session_state.portfolio_workspace_analysis = analysis
render_portfolio_workspace(st, service=service)
""").run(timeout=20)
    assert not app.exception


def test_native_workspace_apptest_consumes_research_focus_with_visible_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path / "runtime"))
    app = AppTest.from_string("""
import streamlit as st
import pandas as pd
from stock_tool.application.portfolio_workspace import PortfolioWorkspaceApplicationService
from stock_tool.dashboard.pages.portfolio_workspace import render_portfolio_workspace

positions = pd.DataFrame([
    {"symbol": "2330", "market": "TWSE", "currency": "TWD", "quantity": 1.0, "average_cost": 500.0, "note": ""},
    {"symbol": "2330", "market": "TPEX", "currency": "TWD", "quantity": 2.0, "average_cost": 80.0, "note": ""},
])
st.session_state.portfolio_workspace_positions = positions
st.session_state.portfolio_workspace_focus = {"symbol": "2330", "market": "TPEX"}
st.session_state.price_data = pd.DataFrame()
render_portfolio_workspace(st, service=PortfolioWorkspaceApplicationService(), on_research=lambda *_: None)
""").run(timeout=20)
    assert not app.exception
    assert app.session_state["portfolio_workspace_research_identity"] == "2330 / TPEX"
    assert "portfolio_workspace_focus" not in app.session_state
    assert any("已聚焦持股：2330 / TPEX" in str(item.value) for item in app.success)
