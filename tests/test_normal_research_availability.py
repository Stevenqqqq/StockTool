from dataclasses import replace
from pathlib import Path

from stock_tool import yfinance_runtime as runtime
from stock_tool.dashboard.components.research_header import render_research_header
from stock_tool.dashboard.components.company_dossier import render_company_dossier
from test_research_header_completeness import _snapshot, _profile, _dossier
from test_research_workspace import _FakeStreamlit


def test_unicode_ca_copy_is_identical_and_verification_not_disabled(tmp_path, monkeypatch):
    source = tmp_path / "中文" / "cacert.pem"
    source.parent.mkdir()
    source.write_bytes(b"public certificate fixture")
    target = tmp_path / "provider"
    target.mkdir()
    for key in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    monkeypatch.setattr(runtime.certifi, "where", lambda: str(source))
    runtime._configure_ca_bundle(target)
    copied = Path(runtime.os.environ["REQUESTS_CA_BUNDLE"])
    assert str(copied).isascii()
    assert copied.read_bytes() == source.read_bytes()
    assert copied.parent == target
    copied.write_bytes(b"corrupt")
    monkeypatch.delenv("REQUESTS_CA_BUNDLE")
    runtime._configure_ca_bundle(target)
    assert copied.read_bytes() == source.read_bytes()


def test_custom_ca_setting_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "custom-ca.pem")
    runtime._configure_ca_bundle(tmp_path)
    assert runtime.os.environ["REQUESTS_CA_BUNDLE"] == "custom-ca.pem"
    assert not list(tmp_path.iterdir())


def test_partial_score_stays_visible_without_claiming_complete():
    s = replace(_snapshot(), composite_score=None, available_score=42.7, score_coverage=0.7)
    fake = _FakeStreamlit()
    render_research_header(fake, s)
    text = str(fake.events)
    assert "42.7" in text and "70.00%" in text and "並非完整總分" in text
    assert "最新可用收盤價" in text


def test_company_gap_alert_has_one_owner_in_workspace():
    dossier = _dossier(gaps=("財報期間尚未取得。",), state="stale")
    fake = _FakeStreamlit()
    render_research_header(fake, _snapshot(profile=_profile(dossier=dossier)))
    header_warnings = [str(value) for kind, value in fake.events if kind == "warning"]
    fake.button = lambda *a, **k: False
    render_company_dossier(fake, dossier, show_status=False)
    warnings = [str(value) for kind, value in fake.events if kind == "warning"]
    assert warnings == header_warnings
    assert "過期" in warnings[0]
    assert "財報期間尚未取得" in str(fake.events)


def test_price_acquisition_time_reaches_snapshot(monkeypatch):
    from stock_tool.dashboard import app
    from test_dashboard import _FakeStreamlit as DashboardFake
    from test_research_workspace import _ready_snapshot

    original = _ready_snapshot()
    st = DashboardFake()
    st.session_state.update(
        price_data=original.price_history.assign(market=original.symbol.market.value),
        technical_indicators=original.indicators,
        fundamental_scores=original.fundamental_results,
        backtest_result=None,
        price_data_source={
            "provider": "fixture",
            "source_type": "online",
            "fetched_at": "2026-10-13T12:00:00Z",
            "updated_at": "old",
        },
        dashboard_status="ready",
    )
    monkeypatch.setattr(app, "_get_company_research_profile", lambda *args: None)
    result = app._build_research_snapshot(
        st, symbol=original.symbol.code, market=original.symbol.market.value
    )
    assert result.source_metadata.fetched_at == "2026-10-13T12:00:00Z"
    assert result.updated_at == result.source_metadata.fetched_at
    assert result.price is not None
