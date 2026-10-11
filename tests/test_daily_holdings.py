from datetime import UTC, datetime, timedelta
import json

import pandas as pd
import pytest

from stock_tool.application.daily_holdings import (
    load_report,
    publish_holdings,
    report_path,
    positions_fingerprint,
    due_key,
)
from stock_tool.application.daily_holdings_job import attempt_path, refresh_needed
from stock_tool.application.holding_identity import save_identity_state
from stock_tool.portfolio_valuation import FxQuote
from stock_tool.runtime_paths import RuntimePaths

NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)


def inputs(tmp_path):
    paths = RuntimePaths(tmp_path)
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    positions = pd.DataFrame(
        [
            dict(
                symbol="MU",
                market="US",
                currency="USD",
                quantity=2.0,
                average_cost=90.0,
                note="private-canary",
            ),
            dict(
                symbol="00935",
                market="TWSE",
                currency="TWD",
                quantity=100.0,
                average_cost=20.0,
                note="",
            ),
        ]
    )
    positions.to_csv(paths.portfolio_file, index=False)
    save_identity_state(
        paths.data_dir / "holding_identity.json",
        {
            "profiles": {
                "MU|US": {"instrument_type": "股票", "currency": "USD"},
                "00935|TWSE": {"instrument_type": "ETF", "currency": "TWD"},
            },
            "overrides": {},
        },
    )
    return paths, positions


def prices(now=NOW, jump=False):
    return pd.DataFrame(
        [
            dict(
                symbol=symbol,
                market=market,
                date=(now.date() - timedelta(days=20 - i)).isoformat(),
                open=100.0,
                high=110.0,
                low=99.0,
                close=110.0 if jump and symbol == "MU" and i == 19 else 100.0,
                adjusted_close=110.0 if jump and symbol == "MU" and i == 19 else 100.0,
                volume=1000.0,
                provider="synthetic",
                fetched_at=now.isoformat(),
                checked_at=now.isoformat(),
            )
            for symbol, market in (("MU", "US"), ("00935", "TWSE"))
            for i in range(20)
        ]
    )


def quote(now=NOW):
    return FxQuote("USD", "TWD", 32.0, "synthetic", now.isoformat(), now.isoformat())


def test_baseline_change_duplicate_and_restart(tmp_path):
    paths, positions = inputs(tmp_path)
    original = paths.portfolio_file.read_bytes()
    first = publish_holdings(paths, positions, prices(), now=NOW, fx_quote=quote(), failed=set())
    assert all(
        not row["events"] and row["status"] == "首次基準" for row in first["holdings"].values()
    )
    second = publish_holdings(
        paths, positions, prices(jump=True), now=NOW, fx_quote=quote(), failed=set()
    )
    mu = second["holdings"]["US:MU"]
    assert any(e["code"] == "daily_move" for e in mu["events"])
    assert mu["weight"] is not None
    third = publish_holdings(
        paths,
        positions,
        prices(NOW + timedelta(minutes=1), jump=True),
        now=NOW + timedelta(minutes=1),
        fx_quote=quote(),
        failed=set(),
    )
    assert third["holdings"]["US:MU"]["events"] == mu["events"]
    assert load_report(paths) == third
    assert paths.portfolio_file.read_bytes() == original
    assert "private-canary" not in report_path(paths).read_text(encoding="utf-8")


def test_partial_does_not_resolve_failed_symbol_or_erase_other_result(tmp_path):
    paths, positions = inputs(tmp_path)
    publish_holdings(paths, positions, prices(), now=NOW, fx_quote=quote(), failed=set())
    changed = publish_holdings(
        paths, positions, prices(jump=True), now=NOW, fx_quote=quote(), failed=set()
    )
    partial = publish_holdings(paths, positions, prices(), now=NOW, fx_quote=None, failed={"US:MU"})
    mu = partial["holdings"]["US:MU"]
    assert mu["status"] == "保留前次結果"
    assert mu["baseline"] == changed["holdings"]["US:MU"]["baseline"]
    assert mu["previous_events"] and not mu["events"]
    assert partial["holdings"]["TWSE:00935"]["status"] == "無新變化"
    assert mu["weight"] is None
    assert partial["fx"] is None


@pytest.mark.parametrize("fault", ["expired", "source", "future", "conflict"])
def test_untrusted_price_excluded_from_valuation(tmp_path, fault):
    paths, positions = inputs(tmp_path)
    frame = prices()
    if fault == "expired":
        frame["fetched_at"] = (NOW - timedelta(days=2)).isoformat()
    elif fault == "source":
        frame["provider"] = ""
    elif fault == "future":
        frame["fetched_at"] = (NOW + timedelta(days=2)).isoformat()
    else:
        extra = frame.iloc[19].copy()
        extra["close"] = 999.0
        frame = pd.concat([frame, pd.DataFrame([extra])], ignore_index=True)
    result = publish_holdings(paths, positions, frame, now=NOW, fx_quote=quote(), failed=set())
    mu = result["holdings"]["US:MU"]
    assert mu["status"] == "資料不足"
    assert mu["weight"] is None
    assert not any(d["label"] == "原幣市值" for d in mu["data"])


def test_corrupt_report_not_overwritten_as_new_baseline(tmp_path):
    paths, positions = inputs(tmp_path)
    report_path(paths).write_text('{"schema":1}', encoding="utf-8")
    before = report_path(paths).read_bytes()
    with pytest.raises(ValueError):
        publish_holdings(paths, positions, prices(), now=NOW, fx_quote=None, failed=set())
    assert report_path(paths).read_bytes() == before


def test_identity_type_change_resets_comparison_without_company_model(tmp_path):
    paths, positions = inputs(tmp_path)
    publish_holdings(paths, positions, prices(), now=NOW, fx_quote=quote(), failed=set())
    save_identity_state(
        paths.data_dir / "holding_identity.json", {"profiles": {}, "overrides": {"MU|US": "ETF"}}
    )
    result = publish_holdings(
        paths, positions, prices(jump=True), now=NOW, fx_quote=quote(), failed=set()
    )
    mu = result["holdings"]["US:MU"]
    assert mu["status"] == "首次基準" and not mu["events"]
    assert "ETF" in mu["company_scope"]


def test_auto_refresh_throttle_and_position_change(tmp_path):
    paths, positions = inputs(tmp_path)
    assert refresh_needed(paths, NOW)
    attempt_path(paths).write_text(
        json.dumps(
            {
                "at": NOW.isoformat(),
                "status": "failed",
                "positions": positions_fingerprint(positions),
                "due_key": due_key(list(positions.market), NOW),
            }
        ),
        encoding="utf-8",
    )
    assert not refresh_needed(paths, NOW + timedelta(minutes=1))
    assert refresh_needed(paths, NOW + timedelta(hours=2))
    positions.loc[0, "quantity"] = 3.0
    positions.to_csv(paths.portfolio_file, index=False)
    assert refresh_needed(paths, NOW + timedelta(minutes=1))


def test_actual_runner_publishes_holdings_even_when_market_refresh_fails(tmp_path):
    from stock_tool.application.daily_research_runner import DailyResearchRunner
    from stock_tool.data.storage import SQLitePriceStorage, PersistedPriceProvenance
    from stock_tool.domain.models import Symbol
    from stock_tool.portfolio_fx import JsonFxQuoteCache

    paths, positions = inputs(tmp_path)
    paths.processed_dir.mkdir(parents=True, exist_ok=True)
    JsonFxQuoteCache(paths.cache_dir / "usd_twd_fx.json").save(quote())

    def refresh(identities, target):
        storage = SQLitePriceStorage(target.processed_dir / "stock_data.sqlite")
        frame = prices()
        for identity in identities:
            selected = frame.loc[
                (frame.symbol == identity.code) & (frame.market == identity.market.value)
            ]
            storage.save_market_qualified_price_data(
                selected.to_dict("records"),
                provenance=PersistedPriceProvenance(
                    Symbol.parse(identity.code, market=identity.market),
                    "synthetic",
                    identity.code,
                    "local_file",
                    selected.date.max(),
                    NOW.isoformat(),
                    NOW.isoformat(),
                ),
            )
        return ()

    def market_failure():
        raise RuntimeError("synthetic market unavailable")

    before = paths.portfolio_file.read_bytes()
    outcome = DailyResearchRunner(
        paths, now_fn=lambda: NOW, refresh_callback=refresh, market_refresh_callback=market_failure
    ).run(trigger="manual")
    assert outcome.status == "failed"  # Market trace stays honest.
    report = load_report(paths)
    assert report is not None
    assert all(row["status"] == "首次基準" for row in report["holdings"].values())
    assert report["holdings"]["US:MU"]["weight"] is not None
    assert paths.portfolio_file.read_bytes() == before


def test_background_job_does_not_block_or_duplicate(tmp_path):
    from threading import Event
    from types import SimpleNamespace
    from time import monotonic, sleep
    from stock_tool.application.daily_holdings_job import start_refresh

    paths, _ = inputs(tmp_path)
    entered, release = Event(), Event()
    calls = []

    def run():
        calls.append(1)
        entered.set()
        release.wait(3)
        return SimpleNamespace(status="success")

    begin = monotonic()
    job = start_refresh(paths, run=run, now=NOW)
    assert monotonic() - begin < 1
    assert entered.wait(1)
    assert start_refresh(paths, force=True, run=run, now=NOW) is job
    assert calls == [1]
    release.set()
    for _ in range(100):
        if not job.running:
            break
        sleep(0.01)
    assert not job.running
    assert not refresh_needed(paths, NOW + timedelta(minutes=1))


def test_repeated_failure_keeps_last_signal_and_recovery_is_not_new_event(tmp_path):
    paths, positions = inputs(tmp_path)
    publish_holdings(paths, positions, prices(), now=NOW, fx_quote=quote(), failed=set())
    changed = publish_holdings(
        paths, positions, prices(jump=True), now=NOW, fx_quote=quote(), failed=set()
    )
    for _ in range(2):
        result = publish_holdings(
            paths, positions, prices(jump=True), now=NOW, fx_quote=None, failed={"US:MU"}
        )
        assert (
            result["holdings"]["US:MU"]["previous_events"] == changed["holdings"]["US:MU"]["events"]
        )
    restored = publish_holdings(
        paths, positions, prices(jump=True), now=NOW, fx_quote=quote(), failed=set()
    )
    assert restored["holdings"]["US:MU"]["status"] == "資料恢復"
    assert not restored["holdings"]["US:MU"]["events"]


def test_observation_save_restart_duplicate_and_corruption(tmp_path):
    from stock_tool.application.daily_holdings import save_observation, load_observations

    paths, positions = inputs(tmp_path)
    publish_holdings(paths, positions, prices(), now=NOW, fx_quote=quote(), failed=set())
    result = publish_holdings(
        paths, positions, prices(jump=True), now=NOW, fx_quote=quote(), failed=set()
    )
    row = result["holdings"]["US:MU"]
    save_observation(paths, row, row["events"][0], now=NOW)
    save_observation(paths, row, row["events"][0], now=NOW + timedelta(minutes=1))
    notes = load_observations(RuntimePaths(paths.root))
    assert len(notes) == 1 and notes[0]["identity"] == "US:MU"
    assert notes[0]["event"] == row["events"][0]
    with pytest.raises(ValueError):
        save_observation(paths, result["holdings"]["TWSE:00935"], row["events"][0], now=NOW)
    path = paths.data_dir / "daily_holdings_observations_v1.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        save_observation(paths, row, row["events"][0], now=NOW)
    assert path.read_text(encoding="utf-8") == "{}"


def test_daily_cards_save_restart_and_identity_navigation(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from stock_tool.dashboard.components import daily_holdings
    from stock_tool.application.daily_holdings_job import DailyJob

    paths, positions = inputs(tmp_path)
    publish_holdings(paths, positions, prices(), now=NOW, fx_quote=quote(), failed=set())
    publish_holdings(paths, positions, prices(jump=True), now=NOW, fx_quote=quote(), failed=set())
    monkeypatch.setenv("STOCK_TOOL_USER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(daily_holdings, "start_refresh", lambda *_a, **_k: DailyJob())
    script = """
import os
from pathlib import Path
import streamlit as st
from stock_tool.runtime_paths import RuntimePaths
from stock_tool.dashboard.components.daily_holdings import render_daily_holdings
action = render_daily_holdings(st, RuntimePaths(Path(os.environ["STOCK_TOOL_USER_DATA_DIR"])))
if action:
    st.write(f"研究目標 {action.preparation.request.market}:{action.preparation.request.symbol}")
"""
    app = AppTest.from_string(script).run()
    assert not app.exception
    assert any("行情本身不能證明漲跌原因" in item.value for item in app.markdown)
    assert any("ETF" in item.value for item in app.markdown)
    next(b for b in app.button if b.label == "記下這個觀察").click().run()
    assert any("已保存在本機" in item.value for item in app.success)
    restart = AppTest.from_string(script).run()
    assert any("已保存 1 筆" in item.label for item in restart.expander)
    next(b for b in restart.button if b.label == "研究這筆持股").click().run()
    assert any("研究目標 US:MU" in item.value for item in restart.markdown)

    publish_holdings(paths, positions, prices(jump=True), now=NOW, fx_quote=None, failed={"US:MU"})
    failure = AppTest.from_string(script).run()
    assert not failure.exception
    assert any("前次訊號不判定解除" in item.value for item in failure.warning)
    assert any("不能完整判斷新變化" in item.value for item in failure.info)
    assert any("前次：MU" in item.value for item in failure.caption)
    assert not any(b.label == "記下這個觀察" for b in failure.button)

    report_path(paths).write_text("{}", encoding="utf-8")
    corrupt = AppTest.from_string(script).run()
    assert any("保留原檔" in item.value for item in corrupt.error)
    assert report_path(paths).read_text() == "{}"


def test_slow_refresh_validates_at_completion_not_start(tmp_path, monkeypatch):
    from stock_tool.application import daily_research_scheduler as scheduler
    from stock_tool.domain.models import Symbol
    from stock_tool.portfolio_fx import JsonFxQuoteCache

    paths, positions = inputs(tmp_path)
    completed = NOW + timedelta(minutes=10)
    JsonFxQuoteCache(paths.cache_dir / "usd_twd_fx.json").save(quote(completed))
    monkeypatch.setattr(scheduler, "_load_price_context", lambda _: (prices(completed), {}))
    scheduler._publish_daily_holdings(
        paths,
        positions,
        (Symbol.parse("MU", market="US"),),
        (),
        NOW,
        lambda: completed,
        fetch_fx=False,
    )
    result = load_report(paths)
    assert result["checked_at"] == completed.isoformat()
    assert result["fx"]["rate"] == 32
    assert result["holdings"]["US:MU"]["status"] == "首次基準"
    assert result["holdings"]["US:MU"]["weight"] is not None
