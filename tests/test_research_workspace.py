from __future__ import annotations

from typing import cast

import pandas as pd
import pandas.testing as pdt

from stock_tool.application.research_snapshot import (
    EvidenceKind,
    ResearchSnapshotStatus,
    ResearchSourceMetadata,
    ResearchWorkspaceService,
)
from stock_tool.company_research import CompanyResearchProfile
from stock_tool.dashboard.components.research_chart import ChartKind, build_research_chart
from stock_tool.dashboard.components.evidence_panel import render_evidence_panel
from stock_tool.dashboard.components.research_chart import render_research_chart
from stock_tool.dashboard.components.research_header import render_research_header
from stock_tool.dashboard.components.risk_summary import render_risk_summary
from stock_tool.dashboard.components.scorecard import render_scorecard
from stock_tool.dashboard.pages import research as research_page
from stock_tool.dashboard.pages.research import SCENARIO_REFERENCE_HEADING
from stock_tool.domain.models import Market, MissingData, MissingDataState, Symbol
from stock_tool.entry_reference import EntryReference
from stock_tool.stock_scoring import (
    FUNDAMENTAL_WEIGHT,
    RISK_WEIGHT,
    TECHNICAL_WEIGHT,
    VALUATION_WEIGHT,
    ScoreComponent,
    StockScoreResult,
)


def _prices(
    *, symbol: str = "2330", include_ohlc: bool = True, include_volume: bool = True
) -> pd.DataFrame:
    rows = 80
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=rows, freq="D"),
            "symbol": [symbol] * rows,
            "close": [100.0 + index for index in range(rows)],
        }
    )
    if include_ohlc:
        frame["open"] = frame["close"] - 1.0
        frame["high"] = frame["close"] + 2.0
        frame["low"] = frame["close"] - 2.0
    if include_volume:
        frame["volume"] = [1_000.0 + index for index in range(rows)]
    return frame


def _score(*, complete: bool = True) -> StockScoreResult:
    components = (
        ScoreComponent("技術面", 24.0, TECHNICAL_WEIGHT, ("趨勢資料可計算",)),
        ScoreComponent("基本面", 24.0 if complete else "unknown", FUNDAMENTAL_WEIGHT),
        ScoreComponent("估值面", 16.0 if complete else "unknown", VALUATION_WEIGHT),
        ScoreComponent("風險面", 16.0, RISK_WEIGHT, ("波動率可計算",)),
    )
    return StockScoreResult(
        symbol="2330",
        total_score=80.0 if complete else "unknown",
        available_score=80.0,
        coverage=1.0 if complete else 0.5,
        technical_score=24.0,
        fundamental_score=24.0 if complete else "unknown",
        valuation_score=16.0 if complete else "unknown",
        risk_score=16.0,
        rating_label="研究參考",
        summary=("分數為研究用途。",),
        strengths=("趨勢資料可計算",),
        weaknesses=("需持續檢查資料來源。",),
        strategy_health=(),
        missing_data=() if complete else ("fundamental_data", "valuation_data"),
        risk_notes=("歷史資料不代表未來報酬。",),
        components=components,
    )


def _profile(*, factual: bool = True) -> CompanyResearchProfile:
    return CompanyResearchProfile(
        symbol="2330",
        provider_symbol="2330.TW" if factual else None,
        company_name="測試公司" if factual else "2330",
        sector="科技" if factual else "資料不足",
        industry="半導體" if factual else "資料不足",
        website="",
        main_business=("影像感測相關服務。",),
        technical_features=("製程與光學整合。",),
        linked_industries=("半導體",),
        current_applications=("行動裝置。",),
        future_applications=("待查證。",),
        bottlenecks=("客戶集中與需求循環。",),
        additional_checks=("確認產品營收占比。",),
        data_sources=("provider company data",),
        limitations=("公司資料可能不完整。",),
        fact_fields=("company_name", "sector", "industry") if factual else (),
    )


def _scenario() -> EntryReference:
    return EntryReference(
        symbol="2330",
        as_of_date="2024-03-20",
        method="趨勢回檔觀察",
        latest_close=179.0,
        reference_price=175.0,
        zone_low=170.0,
        zone_high=180.0,
        breakout_trigger=185.0,
        stop_loss_reference=160.0,
        notes=("僅使用已載入日線資料。",),
        risk_notes=("不構成投資建議。",),
    )


def _source(*, source_type: str = "online") -> ResearchSourceMetadata:
    return ResearchSourceMetadata(
        provider="fixture-provider",
        query_symbol="2330.TW",
        market="TWSE",
        source_type=source_type,
        fetched_at="2024-03-20T10:00:00+00:00",
        last_data_date="2024-03-20",
        row_count=80,
    )


class _FakeContainer:
    def __init__(self, events: list[tuple[str, object]]) -> None:
        self.events = events

    def __enter__(self) -> _FakeContainer:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def metric(self, label: str, value: object) -> None:
        self.events.append(("metric", (label, value)))

    def markdown(self, value: str) -> None:
        self.events.append(("markdown", value))

    def write(self, value: object) -> None:
        self.events.append(("write", value))

    def caption(self, value: str) -> None:
        self.events.append(("caption", value))

    def checkbox(self, _label: str, *, value: bool = False, **_: object) -> bool:
        return value


class _FakeStreamlit(_FakeContainer):
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []
        super().__init__(self.events)

    def title(self, value: str) -> None:
        self.events.append(("title", value))

    def subheader(self, value: str) -> None:
        self.events.append(("subheader", value))

    def columns(self, count: int | tuple[int, ...]) -> list[_FakeContainer]:
        return [
            _FakeContainer(self.events)
            for _ in range(count if isinstance(count, int) else len(count))
        ]

    def tabs(self, labels: tuple[str, ...]) -> list[_FakeContainer]:
        self.events.append(("tabs", labels))
        return [_FakeContainer(self.events) for _ in labels]

    def container(self, **_: object) -> _FakeContainer:
        return _FakeContainer(self.events)

    def expander(self, *_: object, **__: object) -> _FakeContainer:
        return _FakeContainer(self.events)

    def info(self, value: str) -> None:
        self.events.append(("info", value))

    def warning(self, value: str) -> None:
        self.events.append(("warning", value))

    def dataframe(self, value: object, **_: object) -> None:
        self.events.append(("dataframe", value))

    def line_chart(self, value: object, **_: object) -> None:
        self.events.append(("line", value))

    def bar_chart(self, value: object, **_: object) -> None:
        self.events.append(("bar", value))

    def selectbox(
        self, _label: str, options: tuple[str, ...], *, index: int = 0, **_: object
    ) -> str:
        return options[index]

    def checkbox(self, _label: str, *, value: bool = False, **_: object) -> bool:
        return value


def _ready_snapshot():
    return ResearchWorkspaceService().build(
        symbol=Symbol("2330", Market.TWSE),
        price_data=_prices(),
        indicators=_prices(),
        fundamental_results=pd.DataFrame({"symbol": ["2330"], "market": ["TWSE"]}),
        stock_score=_score(),
        company_profile=_profile(),
        scenario_reference=_scenario(),
        source_metadata=_source(),
        warnings=("資料來源有延遲風險。",),
    )


def test_complete_snapshot_keeps_facts_inferences_score_and_source_metadata() -> None:
    snapshot = ResearchWorkspaceService().build(
        symbol=Symbol("2330", Market.TWSE),
        price_data=_prices(),
        indicators=_prices(),
        fundamental_results=pd.DataFrame({"symbol": ["2330"], "market": ["TWSE"]}),
        stock_score=_score(),
        company_profile=_profile(),
        scenario_reference=_scenario(),
        source_metadata=_source(),
    )

    assert snapshot.status is ResearchSnapshotStatus.READY
    assert snapshot.price is not None
    assert snapshot.price.latest_close == 179.0
    assert snapshot.score_coverage == 1.0
    assert snapshot.component_contributions == {
        "技術面": 24.0,
        "基本面": 24.0,
        "估值面": 16.0,
        "風險面": 16.0,
    }
    assert snapshot.source_metadata.provider == "fixture-provider"
    assert any(item.kind is EvidenceKind.FACT for item in snapshot.evidence_items)
    assert any(item.kind is EvidenceKind.RESEARCH_INFERENCE for item in snapshot.evidence_items)


def test_partial_snapshot_does_not_turn_missing_score_components_into_zero() -> None:
    snapshot = ResearchWorkspaceService().build(
        symbol=Symbol("2330", Market.TWSE),
        price_data=_prices(),
        indicators=_prices(),
        fundamental_results=None,
        stock_score=_score(complete=False),
        company_profile=_profile(),
        scenario_reference=_scenario(),
        source_metadata=_source(),
    )

    assert snapshot.status is ResearchSnapshotStatus.PARTIAL
    assert snapshot.composite_score is None
    assert snapshot.score_coverage == 0.5
    assert {item.field for item in snapshot.missing_data} >= {
        "fundamental_data",
        "valuation_data",
    }
    assert "基本面" not in snapshot.component_contributions


def test_insufficient_snapshot_keeps_missing_price_as_missing_not_zero() -> None:
    snapshot = ResearchWorkspaceService().build(
        symbol=Symbol("6488", Market.TPEX),
        price_data=None,
        indicators=None,
        fundamental_results=None,
        stock_score=None,
        company_profile=None,
        scenario_reference=None,
        source_metadata=ResearchSourceMetadata.empty(symbol="6488", market="TPEX"),
    )

    assert snapshot.status is ResearchSnapshotStatus.INSUFFICIENT_DATA
    assert snapshot.price is None
    assert snapshot.composite_score is None
    assert any(item.field == "price_data" for item in snapshot.missing_data)


def test_stale_and_error_snapshot_states_are_never_presented_as_ready() -> None:
    stale = ResearchWorkspaceService().build(
        symbol=Symbol("MU", Market.US),
        price_data=_prices(symbol="MU"),
        indicators=None,
        fundamental_results=None,
        stock_score=None,
        company_profile=None,
        scenario_reference=None,
        source_metadata=_source(source_type="cache"),
        is_stale=True,
    )
    error = ResearchWorkspaceService().build(
        symbol=Symbol("MISSING", Market.US),
        price_data=None,
        indicators=None,
        fundamental_results=None,
        stock_score=None,
        company_profile=None,
        scenario_reference=None,
        source_metadata=ResearchSourceMetadata.empty(symbol="MISSING", market="US"),
        error_message="資料來源未回傳可驗證資料。",
    )

    assert stale.status is ResearchSnapshotStatus.STALE
    assert error.status is ResearchSnapshotStatus.ERROR
    assert error.price is None
    assert error.error_message == "資料來源未回傳可驗證資料。"


def test_snapshot_preserves_input_immutability_and_company_absence_is_not_fabricated() -> None:
    prices = _prices()
    original = prices.copy(deep=True)
    snapshot = ResearchWorkspaceService().build(
        symbol=Symbol("2330", Market.TWSE),
        price_data=prices,
        indicators=None,
        fundamental_results=None,
        stock_score=None,
        company_profile=_profile(factual=False),
        scenario_reference=None,
        source_metadata=_source(),
    )

    assert snapshot.price_history is not None
    snapshot.price_history.loc[:, "close"] = -1.0

    pdt.assert_frame_equal(prices, original)
    assert snapshot.company_profile is None
    assert any(item.field == "company_profile" for item in snapshot.missing_data)


def test_score_weights_and_scenario_copy_remain_research_only() -> None:
    snapshot = ResearchWorkspaceService().build(
        symbol=Symbol("2330", Market.TWSE),
        price_data=_prices(),
        indicators=None,
        fundamental_results=None,
        stock_score=_score(),
        company_profile=_profile(),
        scenario_reference=_scenario(),
        source_metadata=_source(),
    )

    assert [component.weight for component in snapshot.component_scores] == [30.0, 30.0, 20.0, 20.0]
    assert snapshot.scenario_reference is not None
    assert snapshot.scenario_reference.title == SCENARIO_REFERENCE_HEADING
    assert "建議入場價" not in snapshot.scenario_reference.title
    assert "買進價" not in snapshot.scenario_reference.title
    assert "目標買點" not in snapshot.scenario_reference.title


def test_research_chart_uses_candles_or_safe_close_fallback_without_inventing_volume() -> None:
    candle = build_research_chart(_prices(), indicators=None, period="6M")
    close_only = build_research_chart(
        _prices(include_ohlc=False, include_volume=False), indicators=None, period="MAX"
    )

    assert candle.kind is ChartKind.CANDLESTICK
    assert candle.volume_available is True
    assert close_only.kind is ChartKind.CLOSE_LINE
    assert close_only.volume_available is False
    assert "volume" not in close_only.data.columns


def test_research_chart_does_not_mutate_source_frames_or_use_future_period_rows() -> None:
    prices = _prices()
    indicators = prices.loc[:, ["date", "symbol", "close"]].copy(deep=True)
    indicators["sma_20"] = 150.0
    prices_before = prices.copy(deep=True)
    indicators_before = indicators.copy(deep=True)

    chart = build_research_chart(prices, indicators=indicators, period="6M")

    pdt.assert_frame_equal(prices, prices_before)
    pdt.assert_frame_equal(indicators, indicators_before)
    assert chart.data["date"].max() == prices["date"].max()
    assert "sma_20" in chart.data.columns


def test_research_chart_drops_rows_that_would_create_empty_vega_layers() -> None:
    prices = _prices()
    prices.loc[:, ["open", "high", "low", "close"]] = float("nan")
    chart = build_research_chart(prices, indicators=None, period="1Y")

    assert chart.kind is ChartKind.UNAVAILABLE
    assert chart.data.empty


def test_research_chart_never_keeps_infinite_ohlc_or_volume_values() -> None:
    prices = _prices()
    prices.loc[0, ["open", "high", "low", "close", "volume"]] = float("inf")

    chart = build_research_chart(prices, indicators=None, period="1Y")

    assert chart.kind is ChartKind.CANDLESTICK
    assert (
        not chart.data.select_dtypes(include="number")
        .map(lambda value: value in (float("inf"), float("-inf")))
        .any()
        .any()
    )
    assert chart.volume_available


def test_complete_ohlc_renders_only_finite_visible_price_data() -> None:
    chart = build_research_chart(_prices(), indicators=None, period="1Y")
    fake = _FakeStreamlit()

    render_research_chart(fake, chart)

    visible_data = cast(
        pd.DataFrame, next(value for kind, value in fake.events if kind == "dataframe")
    )
    assert list(visible_data.columns) == ["date", "close", "volume"]
    assert visible_data["date"].notna().all()
    assert (
        visible_data.select_dtypes(include="number")
        .map(lambda value: value not in (float("inf"), float("-inf")))
        .all()
        .all()
    )


def test_research_chart_omits_empty_sma_and_volume_layers() -> None:
    prices = _prices(include_ohlc=False, include_volume=True)
    prices["volume"] = float("inf")
    indicators = prices.loc[:, ["date", "symbol", "close"]].copy(deep=True)
    indicators["sma_20"] = float("inf")
    indicators["sma_60"] = float("nan")
    chart = build_research_chart(prices, indicators=indicators, period="1Y")
    fake = _FakeStreamlit()

    render_research_chart(fake, chart)

    visible_data = cast(
        pd.DataFrame, next(value for kind, value in fake.events if kind == "dataframe")
    )
    assert list(visible_data.columns) == ["date", "close"]


def test_research_chart_marks_only_infinite_close_data_unavailable() -> None:
    prices = _prices(include_ohlc=False, include_volume=False)
    prices["close"] = float("inf")

    chart = build_research_chart(prices, indicators=None, period="1Y")

    assert chart.kind is ChartKind.UNAVAILABLE
    assert chart.data.empty


def test_missing_data_is_structured_without_parsing_reason_text_for_identity() -> None:
    explicit = MissingData(
        field="company_profile",
        state=MissingDataState.MISSING,
        reason="沒有可驗證的公司介紹資料。",
    )
    snapshot = ResearchWorkspaceService().build(
        symbol=Symbol("2330", Market.TWSE),
        price_data=_prices(),
        indicators=None,
        fundamental_results=None,
        stock_score=None,
        company_profile=None,
        scenario_reference=None,
        source_metadata=_source(),
        missing_data=(explicit,),
    )

    assert explicit in snapshot.missing_data
    assert snapshot.symbol.canonical == "TWSE:2330"


def test_research_workspace_components_render_complete_snapshot_without_raw_html(
    monkeypatch,
) -> None:
    snapshot = _ready_snapshot()
    fake = _FakeStreamlit()
    monkeypatch.setattr(research_page, "render_global_search", lambda *_args, **_kwargs: None)

    returned = research_page.render_research_workspace(fake, snapshot)

    assert returned is None
    assert ("title", "測試公司") in fake.events
    assert any(event[0] == "dataframe" for event in fake.events)
    visible_text = "\n".join(str(value) for _, value in fake.events)
    assert "事實資料" in visible_text
    assert "研究推論" in visible_text
    assert "情境參考區間" in visible_text
    assert "建議入場價" not in visible_text
    assert "買進價" not in visible_text
    assert "目標買點" not in visible_text


def test_research_components_render_partial_and_unavailable_chart_states() -> None:
    snapshot = ResearchWorkspaceService().build(
        symbol=Symbol("6488", Market.TPEX),
        price_data=_prices(symbol="6488", include_ohlc=False, include_volume=False),
        indicators=None,
        fundamental_results=None,
        stock_score=_score(complete=False),
        company_profile=None,
        scenario_reference=None,
        source_metadata=ResearchSourceMetadata.empty(symbol="6488", market="TPEX"),
    )
    fake = _FakeStreamlit()

    render_research_header(fake, snapshot)
    render_scorecard(fake, snapshot)
    render_evidence_panel(fake, snapshot)
    render_risk_summary(fake, snapshot)
    render_research_chart(
        fake,
        build_research_chart(snapshot.price_history, indicators=None, period="MAX"),
    )
    render_research_chart(
        fake,
        build_research_chart(None, indicators=None, period="MAX"),
    )

    assert any(event[0] == "dataframe" for event in fake.events)
    assert any(event[0] == "info" and "未形成完整總分" in str(event[1]) for event in fake.events)
    assert any(event[0] == "info" and "無法顯示研究圖表" in str(event[1]) for event in fake.events)
