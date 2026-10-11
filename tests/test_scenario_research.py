"""Synthetic-only deterministic contract tests; never real qualification evidence."""

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json

import pandas as pd
import pytest

from stock_tool.application.scenario_research import (
    ALGORITHM,
    BreakoutConfirmationAdapter,
    Rules,
    ScenarioBlocked,
    canonical,
    digest,
    evaluate,
    qualify,
    run,
    run_windows,
)
from stock_tool.application.scenario_store import copy_package, load, replay, save


def fixture_request(*, allocation=0.25, extra=0, offset=0, rules=None):
    rules = rules or Rules()
    closes = [100 + i * 0.1 for i in range(24)] + [
        105,
        106,
        106,
        100,
        100,
        100,
        104,
        108,
        109,
        100,
        100,
        100,
    ]
    closes += [100] * extra
    days = pd.bdate_range("2020-01-01", periods=len(closes) + offset)[offset:]
    prices = [
        {
            "date": day.strftime("%Y-%m-%d"),
            "market": "TWSE",
            "symbol": "SYNTH_A",
            "open": c,
            "high": c + 0.5,
            "low": c - 0.5,
            "close": c,
            "volume": 200 if i in (24, 31) else 100,
        }
        for i, (day, c) in enumerate(zip(days, closes))
    ]
    request = {
        "purpose": "synthetic_validation",
        "identity": {"market": "TWSE", "symbol": "SYNTH_A", "type": "ordinary_share"},
        "prices": prices,
        "rules": asdict(rules),
        "evaluation_start": prices[24]["date"],
        "evaluation_end": prices[-1]["date"],
        "allocation": allocation,
        "initial_cash": 100000.0,
        "costs": {
            "commission_rate": 0.001425,
            "tax_rate": 0.003,
            "slippage_rate": 0.001,
            "min_commission": 1.0,
        },
    }
    return bind(request)


def bind(request):
    request["qualification"] = {
        "binding": {
            "identity": deepcopy(request["identity"]),
            "warmup_start": request["prices"][0]["date"],
            "evaluation_start": request["evaluation_start"],
            "evaluation_end": request["evaluation_end"],
            "prices_digest": digest(request["prices"]),
            "algorithm": ALGORITHM,
        },
        "status": "synthetic_only",
        "coverage": "synthetic_only",
        "source": "deterministic_fixture",
        "calendar": [p["date"] for p in request["prices"]],
        "initial_state": "listed_unrestricted",
        "actions": [],
    }
    return request


@pytest.mark.parametrize("allocation", [0.25, 0.60])
def test_full_exit_actual_engine(allocation):
    result = run(fixture_request(allocation=allocation))
    for variant in result["variants"].values():
        e = variant["execution"]
        assert e["portfolio"]["positions"] == {}
        assert e["metrics"]["closed_round_trip_count"] == 2
        assert len(e["trades"]) == 4
        for buy, sell in zip(e["trades"][::2], e["trades"][1::2]):
            assert buy["quantity"] == sell["quantity"]
            assert sell["realized_pnl"] == pytest.approx(
                buy["net_cash_flow"] + sell["net_cash_flow"]
            )
            assert sell["tax"] > 0 and buy["commission"] > 0
        for o in e["orders"]:
            if o["side"] == "sell":
                assert o["quantity"] is o["cash_amount"] is o["target_percent"] is None


def test_atr_frozen_and_filtered_population():
    req = fixture_request()
    base = evaluate(req)
    assert len(base["cases"]) == 2
    case = base["cases"][0]
    assert case["ATR0"] == 1 and case["P0"] == 102.8
    assert case["L0"] == 101.8
    assert case["status"] == "BREAKOUT_FAILED"
    req["rules"]["M"] = 3
    other = evaluate(req)
    assert [c["case_id"] for c in base["cases"]] == [c["case_id"] for c in other["cases"]]
    assert all(c["condition"] == "FILTERED_OUT" for c in other["cases"])
    executed = run(req)["variants"]["confirmation"]["execution"]
    assert executed["trades"] == []
    assert executed["metrics"]["closed_round_trip_count"] == 0


def test_future_append_preserves_causal_id():
    before, after = fixture_request(), fixture_request(extra=8)
    assert evaluate(before)["cases"] == evaluate(after)["cases"]
    assert digest(before) != digest(after)
    changed = deepcopy(after)
    changed["prices"][0]["high"] += 0.1
    bind(changed)
    assert evaluate(before)["cases"][0]["case_id"] != evaluate(changed)["cases"][0]["case_id"]


@pytest.mark.parametrize(
    "key,value", [("N", True), ("A", "14"), ("H", 1), ("M", 0), ("K", -1), ("B", float("nan"))]
)
def test_parameter_rejection(key, value):
    with pytest.raises(ScenarioBlocked):
        Rules(**{key: value})


@pytest.mark.parametrize(
    "change",
    [
        "real",
        "verified",
        "identity",
        "range",
        "hash",
        "calendar",
        "initial",
        "actions",
        "coverage",
        "source",
        "version",
    ],
)
def test_gate_fail_closed_all_entries(change, tmp_path):
    req = fixture_request()
    if change == "real":
        req["purpose"] = "formal_research"
    elif change == "verified":
        req["qualification"]["status"] = "verified"
    elif change == "identity":
        req["identity"]["symbol"] = "3006"
    elif change == "range":
        req["evaluation_start"] = req["prices"][25]["date"]
    elif change == "hash":
        req["prices"][10]["volume"] = 110
    elif change == "calendar":
        req["qualification"]["calendar"].pop()
    elif change == "initial":
        req["qualification"]["initial_state"] = "unknown"
    elif change == "actions":
        req["qualification"]["actions"] = [{"effective_date": "2020-01-01"}]
    elif change == "coverage":
        req["qualification"]["coverage"] = "unknown"
    elif change == "source":
        req["qualification"]["source"] = "HTTP 200"
    elif change == "version":
        req["qualification"]["binding"]["algorithm"] = "other"
    for call in [
        lambda: qualify(req),
        lambda: evaluate(req),
        lambda: run(req),
        lambda: run_windows([req]),
        lambda: save(tmp_path, req),
        lambda: BreakoutConfirmationAdapter(req, "control"),
    ]:
        with pytest.raises(ScenarioBlocked):
            call()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "sort", "zero", "ohlc", "jump", "etf", "warmup"]
)
def test_data_quality(change):
    req = fixture_request()
    if change == "missing":
        req["prices"][0].pop("high")
    elif change == "duplicate":
        req["prices"][1]["date"] = req["prices"][0]["date"]
    elif change == "sort":
        req["prices"][0], req["prices"][1] = req["prices"][1], req["prices"][0]
    elif change == "zero":
        req["prices"][0]["volume"] = 0
    elif change == "ohlc":
        req["prices"][0]["high"] = 1
    elif change == "jump":
        for k in ["open", "close", "high", "low"]:
            req["prices"][24][k] *= 2
    elif change == "etf":
        req["identity"]["type"] = "ETF"
    elif change == "warmup":
        req["prices"].pop(0)
    bind(req)
    with pytest.raises(ScenarioBlocked):
        run(req)


@pytest.mark.parametrize("k", [102.8, 102.9])
def test_invalid_scale_and_reset(k):
    req = fixture_request(rules=Rules(K=k))
    result = run(req)
    assert result["evidence"]["cases"][0]["status"] == "INVALID_SCALE"
    assert result["evidence"]["cases"][0]["condition"] == "INVALID"
    assert result["variants"]["control"]["execution"]["orders"] == []
    assert result["evidence"]["timeline"][1]["state_before"] == "RESET_WAIT"


def test_pending_open_rejection_and_censoring():
    req = fixture_request()
    req["prices"] = req["prices"][:25]
    req["evaluation_end"] = req["prices"][-1]["date"]
    bind(req)
    out = run(req)
    assert out["evidence"]["cases"][0]["status"] == "RIGHT_CENSORED"
    assert out["variants"]["control"]["execution"]["orders"][0]["status"] == "pending"
    req = fixture_request()
    req["initial_cash"] = 1
    out = run(req)
    assert out["variants"]["control"]["execution"]["rejected_orders"]
    assert out["variants"]["control"]["execution"]["trades"] == []


def test_oos_new_instances_no_overlap():
    first, second = fixture_request(), fixture_request(offset=80)
    windows = run_windows([first, second])
    for out in windows:
        assert out["evidence"]["timeline"][0]["state_before"] == "READY"
        assert out["variants"]["control"]["execution"]["orders"][0]["order_id"] == 1
    with pytest.raises(ScenarioBlocked, match="overlapping"):
        run_windows([first, first])


def rehash(path):
    m = json.loads((path / "manifest.json").read_bytes())
    for name in m["files"]:
        m["files"][name] = hashlib.sha256((path / name).read_bytes()).hexdigest()
    m.pop("package_digest")
    m["package_digest"] = digest(m)
    (path / "manifest.json").write_bytes(canonical(m))


def test_save_restart_offline_restore(tmp_path, monkeypatch):
    import socket

    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("network"))
    path = save(tmp_path / "runs", fixture_request())
    assert load(path)["result"]["formal_research"] is False
    assert replay(path)["formal_research"] is False
    restored = copy_package(path, tmp_path / "restore")
    assert replay(restored) == replay(path)
    with pytest.raises(ScenarioBlocked):
        copy_package(path, tmp_path / "restore")


@pytest.mark.parametrize("kind", ["order", "fill", "cash", "round_trip", "warning"])
def test_a20_valid_manifest_cannot_hide_tampering(tmp_path, kind):
    path = save(tmp_path, fixture_request())
    data = json.loads((path / "result.json").read_bytes())
    e = data["variants"]["control"]["execution"]
    total = e["metrics"]["total_return"]
    if kind == "order":
        e["orders"][0]["rejection_reason"] = "tampered"
    elif kind == "fill":
        e["trades"][0]["commission"] += 1
    elif kind == "cash":
        e["portfolio"]["cash"] += 1
    elif kind == "round_trip":
        e["metrics"]["round_trips"][0]["excursion_unavailable_reason"] = "tampered"
    else:
        e["warnings"].append("tampered")
    assert e["metrics"]["total_return"] == total
    (path / "result.json").write_bytes(canonical(data))
    rehash(path)
    load(path)
    before = (path / "result.json").read_bytes()
    with pytest.raises(ScenarioBlocked, match="REPLAY_MISMATCH"):
        replay(path)
    assert (path / "result.json").read_bytes() == before


def test_no_load_or_replay_qualification_laundering(tmp_path):
    path = save(tmp_path, fixture_request())
    req = json.loads((path / "input.json").read_bytes())
    req["qualification"]["status"] = "verified"
    (path / "input.json").write_bytes(canonical(req))
    rehash(path)
    for call in (load, replay):
        with pytest.raises(ScenarioBlocked):
            call(path)


def test_incompatible_profile_and_corruption(tmp_path):
    path = save(tmp_path, fixture_request())
    meta = json.loads((path / "metadata.json").read_bytes())
    meta["profile"]["python"] = "other"
    (path / "metadata.json").write_bytes(canonical(meta))
    rehash(path)
    load(path)
    with pytest.raises(ScenarioBlocked, match="不相容"):
        replay(path)
    (path / "result.json").write_text("{}")
    with pytest.raises(ScenarioBlocked, match="hash"):
        load(path)


def test_exit_precedence_expiry_trailing_and_reset():
    trailing = evaluate(fixture_request(rules=Rules(K=10)))
    assert trailing["cases"][0]["status"] == "TRAILING_RANGE_EXIT"
    expired = evaluate(fixture_request(rules=Rules(H=2)))
    assert expired["cases"][0]["status"] == "EXPIRED"
    failed = evaluate(fixture_request(rules=Rules(H=4)))
    assert failed["cases"][0]["status"] == "BREAKOUT_FAILED"
    timeline = failed["timeline"]
    assert timeline[3]["state_after"] == "RESET_WAIT"
    assert timeline[4]["reset_count"] == 1
    assert timeline[5]["state_after"] == "READY"
    assert timeline[5]["control"] == 0  # cannot trigger on reset-completion day


def test_equality_not_breakout_or_failure():
    req = fixture_request()
    req["prices"][24].update(open=102.8, close=102.8, high=103.3, low=102.3)
    bind(req)
    assert evaluate(req)["timeline"][0]["control"] == 0
    req = fixture_request()
    req["prices"][27].update(open=101.8, close=101.8, high=102.3, low=101.3)
    bind(req)
    assert evaluate(req)["cases"][0]["termination_date"] != req["prices"][27]["date"]


def test_open_position_not_closed():
    req = fixture_request()
    req["prices"] = req["prices"][:26]
    req["evaluation_end"] = req["prices"][-1]["date"]
    bind(req)
    out = run(req)["variants"]["control"]
    assert out["counts"]["fill_count"] == 1
    assert out["counts"]["closed_round_trip_count"] == 0
    assert out["case_execution"][0]["position"] == "open"


def test_future_change_cannot_change_past_signals():
    req = fixture_request()
    original = evaluate(req)
    req["prices"][-1].update(open=99, close=99, high=99.5, low=98.5)
    bind(req)
    assert evaluate(req)["timeline"][:-1] == original["timeline"][:-1]


def test_zero_atr_and_changed_adapter_input():
    req = fixture_request()
    for row in req["prices"][:24]:
        row.update(open=100, high=100, low=100, close=100)
    bind(req)
    with pytest.raises(ScenarioBlocked, match="ATR"):
        evaluate(req)
    req = fixture_request()
    adapter = BreakoutConfirmationAdapter(req, "control")
    f = qualify(req)
    f.loc[0, "volume"] = 101
    with pytest.raises(ScenarioBlocked, match="input changed"):
        adapter.generate_signals(f)
    with pytest.raises(ScenarioBlocked, match="fundamentals"):
        adapter.generate_signals(qualify(req), pd.DataFrame())


@pytest.mark.parametrize("kind", ["pending", "reconciliation", "daily_equity", "position"])
def test_a20_daily_execution_records(tmp_path, kind):
    path = save(tmp_path, fixture_request())
    obj = json.loads((path / "result.json").read_bytes())
    e = obj["variants"]["control"]["execution"]
    if kind == "pending":
        e["orders"][0]["status"] = "pending"
    elif kind == "reconciliation":
        e["daily_reconciliation"][0]["cash"] = 123
    elif kind == "daily_equity":
        e["equity_curve"][0]["cash"] += 1
    else:
        e["positions_history"][0]["quantity"] += 1
    (path / "result.json").write_bytes(canonical(obj))
    rehash(path)
    with pytest.raises(ScenarioBlocked, match="REPLAY_MISMATCH"):
        replay(path)


@pytest.mark.parametrize("kind", ["missing", "extra", "traversal", "schema", "digest"])
def test_package_invalid(tmp_path, kind):
    path = save(tmp_path, fixture_request())
    if kind == "missing":
        (path / "input.json").unlink()
    elif kind == "extra":
        (path / "extra.txt").write_text("x")
    else:
        m = json.loads((path / "manifest.json").read_bytes())
        if kind == "traversal":
            m["files"]["../input.json"] = "0" * 64
        elif kind == "schema":
            m["schema"] = "unknown"
        else:
            m["package_digest"] = "0" * 64
        (path / "manifest.json").write_bytes(canonical(m))
    with pytest.raises(ScenarioBlocked):
        load(path)
