"""Regression coverage for Sprint 5.1 research-workspace integrity fixes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import stock_tool.dashboard.app as dashboard_app
from stock_tool.application.research_snapshot import (
    ResearchSourceMetadata,
    ResearchWorkspaceService,
)
from stock_tool.dashboard.components.evidence_panel import render_evidence_panel
from stock_tool.dashboard.components.research_header import render_research_header
from stock_tool.dashboard.components.scorecard import render_scorecard
from stock_tool.data.auto_fetch import FetchResult
from stock_tool.domain.models import Market, Symbol
from stock_tool.stock_scoring import (
    FUNDAMENTAL_WEIGHT,
    RISK_WEIGHT,
    TECHNICAL_WEIGHT,
    VALUATION_WEIGHT,
    ScoreComponent,
    StockScoreResult,
)


class _SessionState(dict):
    def __getattr__(self, name: str) -> object:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: object) -> None:
        self[name] = value


class _FakeStreamlit:
    def __init__(self, state: dict[str, object] | None = None) -> None:
        self.session_state = _SessionState(state or {})
        self.events: list[tuple[str, object]] = []

    def __enter__(self) -> _FakeStreamlit:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def title(self, value: str) -> None:
        self.events.append(("title", value))

    def subheader(self, value: str) -> None:
        self.events.append(("subheader", value))

    def caption(self, value: str) -> None:
        self.events.append(("caption", value))

    def info(self, value: str) -> None:
        self.events.append(("info", value))

    def warning(self, value: str) -> None:
        self.events.append(("warning", value))

    def markdown(self, value: str) -> None:
        self.events.append(("markdown", value))

    def write(self, value: object) -> None:
        self.events.append(("write", value))

    def metric(self, label: str, value: object) -> None:
        self.events.append(("metric", (label, value)))

    def dataframe(self, value: object, **_: object) -> None:
        self.events.append(("dataframe", value))

    def columns(self, count: int) -> list[_FakeStreamlit]:
        return [self for _ in range(count)]

    def container(self, **_: object) -> _FakeStreamlit:
        return self


def _prices(symbol: str = "2330") -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=80, freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": [symbol] * len(dates),
            "market": ["TWSE"] * len(dates),
            "open": [100.0] * len(dates),
            "high": [105.0] * len(dates),
            "low": [99.0] * len(dates),
            "close": [104.0] * len(dates),
            "volume": [1_000.0] * len(dates),
            "adjusted_close": [104.0] * len(dates),
        }
    )


def _workspace_state(
    *,
    backtest_result: object | None = None,
    last_parameters: dict[str, object] | None = None,
) -> _FakeStreamlit:
    prices = _prices()
    return _FakeStreamlit(
        {
            "price_data": prices,
            "technical_indicators": prices.copy(deep=True),
            "fundamental_scores": None,
            "backtest_result": backtest_result,
            "last_parameters": last_parameters or {},
            "price_data_source": {
                "provider": "yfinance",
                "query_symbol": "2330.TW",
                "source_type": "online",
                "market": "TWSE",
            },
            "dashboard_status": "ready",
            "company_research_cache": {},
        }
    )


@pytest.mark.parametrize(
    ("source", "source_type", "provider_symbol", "cache_file"),
    [
        ("yfinance", "online", "2330.TW", None),
        ("finmind", "online", "2330", None),
        ("yfinance", "cache", "2330.TW", Path("cache/yfinance_2330.TW.csv")),
    ],
)
def test_ensure_symbol_data_preserves_actual_fetch_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    source_type: str,
    provider_symbol: str,
    cache_file: Path | None,
) -> None:
    prices = _prices().drop(columns="market")
    prices["date"] = prices["date"].dt.strftime("%Y-%m-%d")
    fake_st = _FakeStreamlit(
        {
            "price_data": None,
            "technical_indicators": None,
            "fundamentals": pd.DataFrame({"symbol": ["2330"], "market": ["TWSE"]}),
            "fundamental_scores": None,
            "price_data_source": None,
            "company_research_cache": {},
            "dashboard_status": "ready",
            "backtest_result": None,
            "last_parameters": {},
        }
    )
    monkeypatch.setattr(dashboard_app, "DEFAULT_DATABASE", tmp_path / "prices.sqlite")
    monkeypatch.setattr(dashboard_app, "AUTO_FUNDAMENTAL_FILE", tmp_path / "fundamentals_auto.csv")

    def fail_unexpected_fundamental_fetch(*_args, **_kwargs):
        raise AssertionError("price provenance test must not fetch fundamentals")

    monkeypatch.setattr(
        dashboard_app, "fetch_yfinance_fundamentals", fail_unexpected_fundamental_fetch
    )
    monkeypatch.setattr(
        dashboard_app,
        "fetch_prices",
        lambda *_args, **_kwargs: FetchResult(
            data=prices,
            source=source,
            symbol="2330",
            provider_symbol=provider_symbol,
            from_cache=source_type == "cache",
            cache_file=cache_file,
            market="TWSE",
            start_date="2024-01-01",
            end_date="2024-03-20",
            source_type=source_type,
        ),
    )
    monkeypatch.setattr(dashboard_app, "_get_company_research_profile", lambda *_: None)

    dashboard_app._ensure_symbol_data(fake_st, symbol="2330", market="TWSE")
    metadata = fake_st.session_state.price_data_source
    snapshot = dashboard_app._build_research_snapshot(fake_st, symbol="2330", market="TWSE")

    assert metadata["provider"] == source
    assert metadata["source_type"] == source_type
    assert metadata["cache_file"] == (str(cache_file) if cache_file else None)
    assert metadata["query_symbol"] == provider_symbol
    assert metadata["start_date"] == "2024-01-01"
    assert metadata["end_date"] == "2024-03-20"
    assert snapshot.source_metadata.provider == source
    assert snapshot.source_metadata.source_type == source_type
    assert snapshot.source_metadata.query_symbol == provider_symbol
    rendered = _FakeStreamlit()
    render_research_header(rendered, snapshot)
    rendered_text = "\n".join(str(value) for _, value in rendered.events)
    assert (
        f"資料來源：{source}；類型：{source_type}；實際查詢代號：{provider_symbol}" in rendered_text
    )


def test_unrelated_backtest_is_not_passed_to_current_research_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_backtest = SimpleNamespace(metrics=SimpleNamespace(max_drawdown=-0.60))
    parameters = {"symbol": "AAPL", "market": "US"}
    fake_st = _workspace_state(backtest_result=old_backtest, last_parameters=parameters)
    captured: dict[str, object] = {}
    real_score_stock = dashboard_app.score_stock

    def capture_score(**kwargs: object) -> StockScoreResult:
        captured["backtest_result"] = kwargs["backtest_result"]
        return real_score_stock(**kwargs)

    monkeypatch.setattr(dashboard_app, "score_stock", capture_score)
    monkeypatch.setattr(dashboard_app, "_get_company_research_profile", lambda *_: None)

    dashboard_app._build_research_snapshot(fake_st, symbol="2330", market="TWSE")

    assert captured["backtest_result"] is None
    assert fake_st.session_state.backtest_result is old_backtest
    assert fake_st.session_state.last_parameters == parameters


def test_matching_backtest_identity_is_passed_without_modifying_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matching_backtest = SimpleNamespace(metrics=SimpleNamespace(max_drawdown=-0.10))
    parameters = {"symbol": "2330.TW", "market": "TWSE"}
    fake_st = _workspace_state(backtest_result=matching_backtest, last_parameters=parameters)
    captured: dict[str, object] = {}
    real_score_stock = dashboard_app.score_stock

    def capture_score(**kwargs: object) -> StockScoreResult:
        captured["backtest_result"] = kwargs["backtest_result"]
        return real_score_stock(**kwargs)

    monkeypatch.setattr(dashboard_app, "score_stock", capture_score)
    monkeypatch.setattr(dashboard_app, "_get_company_research_profile", lambda *_: None)

    dashboard_app._build_research_snapshot(fake_st, symbol="2330", market="TWSE")

    assert captured["backtest_result"] is matching_backtest
    assert fake_st.session_state.backtest_result is matching_backtest
    assert fake_st.session_state.last_parameters == parameters


def test_missing_or_unconfirmed_backtest_identity_is_not_eligible() -> None:
    result = object()
    for parameters in ({}, {"symbol": "2330"}, {"symbol": "2330", "market": "US"}):
        fake_st = _workspace_state(backtest_result=result, last_parameters=parameters)
        assert (
            dashboard_app._research_backtest_result(fake_st, symbol="2330", market="TWSE") is None
        )


def test_partial_snapshot_user_visible_score_text_never_exposes_unknown_or_zero() -> None:
    score = StockScoreResult(
        symbol="2330",
        total_score="unknown",
        available_score=80.0,
        coverage=0.5,
        technical_score=24.0,
        fundamental_score="unknown",
        valuation_score="unknown",
        risk_score=16.0,
        rating_label="資料不足",
        summary=(),
        strengths=(),
        weaknesses=(),
        strategy_health=(),
        missing_data=("fundamental_data", "valuation_data"),
        risk_notes=(),
        components=(
            ScoreComponent("技術面", 24.0, TECHNICAL_WEIGHT),
            ScoreComponent("基本面", "unknown", FUNDAMENTAL_WEIGHT),
            ScoreComponent("估值面", "unknown", VALUATION_WEIGHT),
            ScoreComponent("風險面", 16.0, RISK_WEIGHT),
        ),
    )
    snapshot = ResearchWorkspaceService().build(
        symbol=Symbol("2330", Market.TWSE),
        price_data=_prices(),
        indicators=_prices(),
        fundamental_results=None,
        stock_score=score,
        company_profile=None,
        scenario_reference=None,
        source_metadata=ResearchSourceMetadata(
            provider="yfinance",
            query_symbol="2330.TW",
            market="TWSE",
            source_type="online",
            fetched_at=None,
            last_data_date="2024-03-20",
            row_count=80,
        ),
    )
    fake_st = _FakeStreamlit()

    render_research_header(fake_st, snapshot)
    render_scorecard(fake_st, snapshot)
    render_evidence_panel(fake_st, snapshot)

    visible = "\n".join(str(value) for _, value in fake_st.events)
    assert "unknown" not in visible.casefold()
    assert "完整總分：資料不足" in visible
    assert "50%" in visible
    assert "基本面" not in snapshot.component_contributions
    assert "估值面" not in snapshot.component_contributions
