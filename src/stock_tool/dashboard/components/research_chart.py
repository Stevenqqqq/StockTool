"""Research chart data preparation and rendering without external charting dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any, cast
import pandas as pd


class ChartKind(StrEnum):
    """Safe chart modes based on the columns actually available."""

    CANDLESTICK = "candlestick"
    CLOSE_LINE = "close_line"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ResearchChartModel:
    """Prepared chart data and explicit limitations for one research snapshot."""

    kind: ChartKind
    period: str
    data: pd.DataFrame
    volume_available: bool
    last_data_date: str | None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", self.data.copy(deep=True))
        object.__setattr__(self, "limitations", tuple(self.limitations))


_PERIOD_MONTHS = {"6M": 6, "1Y": 12, "3Y": 36, "MAX": None}


def build_research_chart(
    prices: pd.DataFrame | None,
    *,
    indicators: pd.DataFrame | None,
    period: str,
    show_sma20: bool = True,
    show_sma60: bool = True,
) -> ResearchChartModel:
    """Prepare a date-aligned candle or close chart without filling missing fields."""

    normalized_period = period.upper()
    if normalized_period not in _PERIOD_MONTHS:
        raise ValueError("period must be one of 6M, 1Y, 3Y, or MAX.")
    if prices is None or prices.empty or "date" not in prices.columns:
        return ResearchChartModel(
            kind=ChartKind.UNAVAILABLE,
            period=normalized_period,
            data=pd.DataFrame(),
            volume_available=False,
            last_data_date=None,
            limitations=("缺少日期與價格資料，無法建立研究圖表。",),
        )

    data = prices.copy(deep=True)
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data = data.dropna(subset=["date"]).sort_values("date", kind="stable")
    if data.empty:
        return ResearchChartModel(
            kind=ChartKind.UNAVAILABLE,
            period=normalized_period,
            data=pd.DataFrame(),
            volume_available=False,
            last_data_date=None,
            limitations=("價格日期無法解析，無法建立研究圖表。",),
        )
    data = _restrict_period(data, normalized_period)
    data = _merge_overlays(data, indicators, show_sma20=show_sma20, show_sma60=show_sma60)
    data = _drop_empty_chart_rows(data)
    close_available = bool(
        "close" in data.columns and pd.to_numeric(data["close"], errors="coerce").notna().any()
    )
    ohlc_columns = ("open", "high", "low", "close")
    has_ohlc = all(
        bool(column in data.columns and pd.to_numeric(data[column], errors="coerce").notna().any())
        for column in ohlc_columns
    )
    volume_available = bool(
        "volume" in data.columns and pd.to_numeric(data["volume"], errors="coerce").notna().any()
    )
    limitations: list[str] = []
    if not has_ohlc and close_available:
        limitations.append("缺少完整 OHLC，已安全降級為收盤價走勢。")
    if not volume_available:
        limitations.append("缺少可用成交量，未繪製成交量圖。")
    if not close_available:
        limitations.append("缺少可用收盤價，無法建立價格圖。")
    kind = (
        ChartKind.CANDLESTICK
        if has_ohlc
        else ChartKind.CLOSE_LINE if close_available else ChartKind.UNAVAILABLE
    )
    if not volume_available and "volume" in data.columns:
        data = data.drop(columns="volume")
    return ResearchChartModel(
        kind=kind,
        period=normalized_period,
        data=data.reset_index(drop=True),
        volume_available=volume_available,
        last_data_date=data["date"].max().date().isoformat() if not data.empty else None,
        limitations=tuple(limitations),
    )


def _drop_empty_chart_rows(data: pd.DataFrame) -> pd.DataFrame:
    """Remove rows that cannot contribute to any price layer before Vega sees them."""

    numeric_columns = [column for column in ("open", "high", "low", "close") if column in data]
    if not numeric_columns:
        return data.iloc[0:0].copy(deep=True)
    cleaned = data.copy(deep=True)
    numeric_and_overlay_columns = [
        column
        for column in ("open", "high", "low", "close", "volume", "sma_20", "sma_60")
        if column in cleaned
    ]
    for column in numeric_and_overlay_columns:
        cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce")
        cleaned.loc[~cleaned[column].map(_is_finite_number), column] = float("nan")
    return cleaned.dropna(subset=numeric_columns, how="all").copy(deep=True)


def _is_finite_number(value: object) -> bool:
    """Return whether a chart value is finite before it is handed to Vega."""

    try:
        return bool(pd.notna(value) and float("-inf") < float(cast(Any, value)) < float("inf"))
    except (TypeError, ValueError):
        return False


def render_research_chart(st: Any, model: ResearchChartModel, *, compact: bool = False) -> None:
    """Render one safe research chart using Streamlit's bundled Vega-Lite support."""

    if model.kind is ChartKind.UNAVAILABLE:
        st.info("資料不足，無法顯示研究圖表。")
        _render_limitations(st, model.limitations)
        return
    columns = [
        column
        for column in ("close", "sma_20", "sma_60")
        if column in model.data and model.data[column].map(_is_finite_number).any()
    ]
    if not columns:
        st.info("圖表資料沒有可呈現的有限價格值。")
        _render_limitations(st, model.limitations)
        return
    failed = False
    try:
        for panel in research_chart_panels(model, compact=compact):
            st.vega_lite_chart(spec=panel, width="stretch")
    except Exception:
        # Browser-side errors cannot be caught here; the table remains available
        # on every render, including when the server successfully sent the spec.
        failed = True
        st.warning("圖表暫時無法顯示，請使用下方資料表核對。")
    visible_columns = ["date", *[c for c in ("open", "high", "low") if c in model.data], *columns]
    if model.volume_available and not compact:
        visible_columns.append("volume")
    with st.expander("查看價量資料表（圖表無法顯示時亦可使用）", expanded=failed):
        st.dataframe(
            model.data.loc[:, visible_columns].copy(deep=True),
            width="stretch",
            hide_index=True,
        )
    st.caption(f"資料最後日期：{model.last_data_date or '資料不足'}；期間：{model.period}。")
    _render_limitations(st, model.limitations)


def research_chart_panels(
    model: ResearchChartModel, *, compact: bool = False
) -> list[dict[str, Any]]:
    """Fit each chart independently; Vega-Lite cannot fit concatenated views.

    Values stay within layers, preserving atomic JSON transport. Both panels
    explicitly use the same date domain, even if some volume rows are missing.
    """
    result = []
    domain = [model.data.date.min().isoformat(), model.data.date.max().isoformat()]
    for view in research_chart_spec(model, compact=compact)["vconcat"]:
        layers = view.get("layer", [{"mark": view.get("mark"), "encoding": view.get("encoding")}])
        for layer in layers:
            layer["data"] = view["data"]
            layer["encoding"]["x"]["scale"] = {"domain": domain}
        result.append(
            {
                "layer": layers,
                "height": view["height"],
                "autosize": {"type": "fit-x", "contains": "padding"},
            }
        )
    return result


def research_chart_spec(model: ResearchChartModel, *, compact: bool = False) -> dict[str, Any]:
    """One self-contained Vega spec, with no separately delivered Arrow datasets.

    Streamlit extracts top-level data/datasets into a separate transport. Keep
    JSON-safe values inside each concatenated view so the spec and its data are
    replaced together on reruns, including hidden-tab and symbol transitions.
    """
    fields = [
        c
        for c in ("date", "open", "high", "low", "close", "sma_20", "sma_60", "volume")
        if c in model.data
    ]
    data = model.data.loc[:, fields].copy(deep=True)
    rows = json.loads(data.to_json(orient="records", date_format="iso"))
    x = {"field": "date", "type": "temporal", "title": "日期"}

    def y(field: str) -> dict[str, Any]:
        return {"field": field, "type": "quantitative", "title": "價格", "scale": {"zero": False}}

    tooltip = [{"field": "date", "type": "temporal", "title": "日期", "format": "%Y-%m-%d"}]
    tooltip += [
        {"field": c, "type": "quantitative", "title": title, "format": ",.2f"}
        for c, title in (
            ("open", "開盤"),
            ("high", "最高"),
            ("low", "最低"),
            ("close", "收盤"),
            ("sma_20", "SMA20"),
            ("sma_60", "SMA60"),
        )
        if c in fields
    ]
    layers: list[dict[str, Any]] = []
    if model.kind is ChartKind.CANDLESTICK:
        valid = data.dropna(subset=["open", "high", "low", "close"])
        if len(valid) != len(data):
            # A close line preserves known prices when individual candles have gaps.
            layers.append(
                {
                    "mark": {"type": "line", "color": "#9ca3af", "opacity": 0.6},
                    "encoding": {"x": x, "y": y("close")},
                }
            )
        color = {
            "condition": {"test": "datum.close >= datum.open", "value": "#ef5350"},
            "value": "#26a69a",
        }
        if not valid.empty:
            transform = [
                {
                    "filter": "isValid(datum.open) && isValid(datum.high) && isValid(datum.low) && isValid(datum.close)"
                }
            ]
            layers.extend(
                [
                    {
                        "transform": transform,
                        "mark": "rule",
                        "encoding": {
                            "x": x,
                            "y": y("low"),
                            "y2": {"field": "high"},
                            "color": color,
                            "tooltip": tooltip,
                        },
                    },
                    {
                        "transform": transform,
                        "mark": {"type": "bar", "size": 4},
                        "encoding": {
                            "x": x,
                            "y": y("open"),
                            "y2": {"field": "close"},
                            "color": color,
                            "tooltip": tooltip,
                        },
                    },
                ]
            )
    else:
        layers.append(
            {
                "mark": {"type": "line", "color": "#60a5fa"},
                "encoding": {"x": x, "y": y("close"), "tooltip": tooltip},
            }
        )
    for column, label in (("sma_20", "SMA20"), ("sma_60", "SMA60")):
        if column in data and data[column].notna().any():
            layers.append(
                {
                    "transform": [{"calculate": json.dumps(label), "as": "series"}],
                    "mark": {"type": "line", "strokeWidth": 1.5},
                    "encoding": {
                        "x": x,
                        "y": y(column),
                        "stroke": {
                            "field": "series",
                            "type": "nominal",
                            "scale": {
                                "domain": ["SMA20", "SMA60"],
                                "range": ["#fbbf24", "#a78bfa"],
                            },
                            "legend": {"title": "均線", "orient": "top"},
                        },
                        "tooltip": tooltip,
                    },
                }
            )
    panels = [{"data": {"values": rows}, "height": 200 if compact else 300, "layer": layers}]
    if model.volume_available and not compact:
        panels.append(
            {
                "data": {"values": [row for row in rows if row.get("volume") is not None]},
                "height": 100,
                "mark": {"type": "bar", "color": "#60a5fa"},
                "encoding": {
                    "x": x,
                    "y": {"field": "volume", "type": "quantitative", "title": "成交量"},
                    "tooltip": [
                        tooltip[0],
                        {
                            "field": "volume",
                            "type": "quantitative",
                            "title": "成交量",
                            "format": ",.0f",
                        },
                    ],
                },
            }
        )
    return {
        "vconcat": panels,
        "resolve": {"scale": {"x": "shared"}},
        "spacing": 8,
    }


def _restrict_period(data: pd.DataFrame, period: str) -> pd.DataFrame:
    months = _PERIOD_MONTHS[period]
    if months is None:
        return data.copy(deep=True)
    end = data["date"].max()
    return data.loc[data["date"] >= end - pd.DateOffset(months=months)].copy(deep=True)


def _merge_overlays(
    prices: pd.DataFrame,
    indicators: pd.DataFrame | None,
    *,
    show_sma20: bool,
    show_sma60: bool,
) -> pd.DataFrame:
    overlay_columns = [
        column for column, enabled in (("sma_20", show_sma20), ("sma_60", show_sma60)) if enabled
    ]
    if (
        indicators is None
        or indicators.empty
        or not overlay_columns
        or "date" not in indicators.columns
    ):
        return prices.copy(deep=True)
    overlays = indicators.copy(deep=True)
    overlays["date"] = pd.to_datetime(overlays["date"], errors="coerce")
    available = [column for column in overlay_columns if column in overlays.columns]
    if not available:
        return prices.copy(deep=True)
    overlays = overlays.loc[:, ["date", *available]].dropna(subset=["date"])
    return prices.merge(overlays, on="date", how="left", suffixes=("", "_indicator"))


def _render_limitations(st: Any, limitations: tuple[str, ...]) -> None:
    for limitation in limitations:
        st.caption(f"限制：{limitation}")
