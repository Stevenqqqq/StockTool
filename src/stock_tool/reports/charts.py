"""Small self-contained SVG chart helpers for HTML reports."""

from __future__ import annotations

import html
from typing import Sequence

import pandas as pd

from stock_tool.reports.models import INSUFFICIENT_DATA


def equity_curve_chart(equity_curve: pd.DataFrame | None) -> str:
    """Return an SVG line chart for total equity."""

    if equity_curve is None or equity_curve.empty or "total_equity" not in equity_curve.columns:
        return _empty_chart("資金曲線", INSUFFICIENT_DATA)
    frame = equity_curve.copy(deep=True)
    frame["date"] = frame.get("date", pd.RangeIndex(len(frame))).astype(str)
    values = frame["total_equity"].astype(float).tolist()
    labels = frame["date"].tolist()
    return _line_chart(values, labels, title="資金曲線", color="#2563eb")


def drawdown_chart(equity_curve: pd.DataFrame | None) -> str:
    """Return an SVG area chart for drawdowns."""

    if equity_curve is None or equity_curve.empty or "total_equity" not in equity_curve.columns:
        return _empty_chart("最大回撤", INSUFFICIENT_DATA)
    equity = equity_curve["total_equity"].astype(float)
    peak = equity.cummax()
    drawdown = ((equity / peak.where(peak != 0)) - 1.0).fillna(0.0)
    labels = equity_curve.get("date", pd.RangeIndex(len(equity_curve))).astype(str).tolist()
    return _line_chart(drawdown.tolist(), labels, title="回撤曲線", color="#dc2626", percent_axis=True)


def price_chart(price_data: pd.DataFrame | None) -> str:
    """Return an SVG line chart for close prices."""

    if price_data is None or price_data.empty or "close" not in price_data.columns:
        return _empty_chart("價格走勢", INSUFFICIENT_DATA)
    frame = price_data.copy(deep=True)
    frame["date"] = frame.get("date", pd.RangeIndex(len(frame))).astype(str)
    return _line_chart(
        frame["close"].astype(float).tolist(),
        frame["date"].tolist(),
        title="收盤價走勢",
        color="#16a34a",
    )


def _line_chart(
    values: Sequence[float],
    labels: Sequence[str],
    *,
    title: str,
    color: str,
    percent_axis: bool = False,
    width: int = 760,
    height: int = 260,
) -> str:
    if not values:
        return _empty_chart(title, INSUFFICIENT_DATA)

    min_value = min(values)
    max_value = max(values)
    if min_value == max_value:
        min_value -= 1
        max_value += 1

    padding_left = 56
    padding_right = 24
    padding_top = 36
    padding_bottom = 34
    plot_width = width - padding_left - padding_right
    plot_height = height - padding_top - padding_bottom

    points: list[str] = []
    for index, value in enumerate(values):
        x = padding_left + (plot_width * index / max(len(values) - 1, 1))
        y = padding_top + plot_height - ((value - min_value) / (max_value - min_value) * plot_height)
        points.append(f"{x:.2f},{y:.2f}")

    y_top = _axis_label(max_value, percent_axis)
    y_bottom = _axis_label(min_value, percent_axis)
    first_label = html.escape(labels[0]) if labels else ""
    last_label = html.escape(labels[-1]) if labels else ""
    title_text = html.escape(title)
    polyline = " ".join(points)

    return f"""
<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{title_text}">
  <rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff" rx="8"></rect>
  <text x="{padding_left}" y="24" class="chart-title">{title_text}</text>
  <line x1="{padding_left}" y1="{padding_top}" x2="{padding_left}" y2="{padding_top + plot_height}" stroke="#d1d5db"></line>
  <line x1="{padding_left}" y1="{padding_top + plot_height}" x2="{padding_left + plot_width}" y2="{padding_top + plot_height}" stroke="#d1d5db"></line>
  <text x="8" y="{padding_top + 5}" class="axis-label">{html.escape(y_top)}</text>
  <text x="8" y="{padding_top + plot_height}" class="axis-label">{html.escape(y_bottom)}</text>
  <text x="{padding_left}" y="{height - 8}" class="axis-label">{first_label}</text>
  <text x="{padding_left + plot_width - 80}" y="{height - 8}" class="axis-label">{last_label}</text>
  <polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="2.2"></polyline>
</svg>
"""


def _empty_chart(title: str, message: str) -> str:
    title_text = html.escape(title)
    message_text = html.escape(message)
    return f"""
<svg class="chart" viewBox="0 0 760 160" role="img" aria-label="{title_text}">
  <rect x="0" y="0" width="760" height="160" fill="#ffffff" rx="8"></rect>
  <text x="24" y="36" class="chart-title">{title_text}</text>
  <text x="24" y="84" class="muted">{message_text}</text>
</svg>
"""


def _axis_label(value: float, percent_axis: bool) -> str:
    if percent_axis:
        return f"{value * 100:.1f}%"
    return f"{value:,.2f}"

