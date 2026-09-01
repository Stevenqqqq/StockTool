"""Small, escaped presentation primitives for the StockTool dashboard.

The returned markup contains presentation only. Interactive controls remain
native Streamlit widgets, and every caller-supplied value is HTML escaped.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any, Mapping

_TONES = frozenset({"neutral", "info", "success", "warning", "error"})
_STAT_VARIANTS = frozenset({"summary", "primary", "buckets"})
_OUTCOME_LABELS = {
    "pending": "等待到期",
    "eligible": "可評估",
    "evaluated": "已評估",
    "unavailable": "不可用",
}


@dataclass(frozen=True, slots=True)
class CompactStatistic:
    """One concise, non-interactive statistic tile."""

    label: str
    value: str
    detail: str | None = None
    tone: str = "neutral"


def _safe(value: object) -> str:
    return escape(str(value), quote=True)


def _tone_class(tone: str) -> str:
    if tone not in _TONES:
        raise ValueError(f"unsupported UI tone: {tone}")
    return f"st-ui-tone--{tone}"


def render_ui_markup(st: Any, markup: str) -> None:
    """Render markup whose dynamic fields were escaped by this module."""

    st.markdown(markup, unsafe_allow_html=True)


def workspace_header_markup(
    *,
    title: str,
    subtitle: str,
    status_label: str,
    status_tone: str,
    data_as_of: str,
) -> str:
    """Build the compact research-workspace header."""

    tone = _tone_class(status_tone)
    return (
        '<section class="st-ui-workspace-header">'
        '<div class="st-ui-workspace-header__copy">'
        '<p class="st-ui-eyebrow">今日研究</p>'
        f"<h1>{_safe(title)}</h1>"
        f"<p>{_safe(subtitle)}</p>"
        "</div>"
        '<div class="st-ui-workspace-header__meta">'
        f'<span class="st-ui-badge {tone}">{_safe(status_label)}</span>'
        '<span class="st-ui-as-of-label">資料截至</span>'
        f'<strong class="st-ui-as-of-value">{_safe(data_as_of)}</strong>'
        "</div>"
        "</section>"
    )


def section_header_markup(*, title: str, description: str, eyebrow: str | None = None) -> str:
    """Build a reusable section heading with an optional eyebrow label."""

    eyebrow_markup = f'<p class="st-ui-eyebrow">{_safe(eyebrow)}</p>' if eyebrow is not None else ""
    return (
        '<header class="st-ui-section-header">'
        f"{eyebrow_markup}"
        f"<h2>{_safe(title)}</h2>"
        f"<p>{_safe(description)}</p>"
        "</header>"
    )


def state_panel_markup(
    *,
    tone: str,
    title: str,
    message: str,
    next_step: str | None = None,
) -> str:
    """Build an honest loading, empty, partial, or error state panel."""

    tone_class = _tone_class(tone)
    next_markup = (
        '<p class="st-ui-state-panel__next">' f"<span>下一步</span>{_safe(next_step)}" "</p>"
        if next_step
        else ""
    )
    return (
        f'<section class="st-ui-state-panel {tone_class}">'
        '<div class="st-ui-state-panel__marker" aria-hidden="true"></div>'
        '<div class="st-ui-state-panel__copy">'
        f"<strong>{_safe(title)}</strong>"
        f"<p>{_safe(message)}</p>"
        f"{next_markup}"
        "</div>"
        "</section>"
    )


def statistic_group_markup(
    *,
    title: str,
    statistics: tuple[CompactStatistic, ...],
    variant: str,
) -> str:
    """Build a responsive group of concise statistic tiles."""

    if variant not in _STAT_VARIANTS:
        raise ValueError(f"unsupported statistic variant: {variant}")
    rows: list[str] = []
    for statistic in statistics:
        tone = _tone_class(statistic.tone)
        detail = (
            f'<span class="st-ui-stat__detail">{_safe(statistic.detail)}</span>'
            if statistic.detail
            else ""
        )
        rows.append(
            f'<article class="st-ui-stat {tone}">'
            f'<span class="st-ui-stat__label">{_safe(statistic.label)}</span>'
            f'<strong class="st-ui-stat__value">{_safe(statistic.value)}</strong>'
            f"{detail}"
            "</article>"
        )
    return (
        f'<section class="st-ui-stat-group st-ui-stat-group--{variant}">'
        f"<h3>{_safe(title)}</h3>"
        f'<div class="st-ui-stat-grid st-ui-stat-grid--{variant}">{"".join(rows)}</div>'
        "</section>"
    )


def outcome_matrix_markup(outcome_counts: Mapping[str, Mapping[str, int]]) -> str:
    """Build a two-horizon outcome matrix with translated status labels."""

    horizons: list[str] = []
    for horizon in ("5", "20"):
        counts = outcome_counts.get(horizon, {})
        statuses = "".join(
            '<div class="st-ui-outcome-cell">'
            f"<span>{_safe(label)}</span>"
            f"<strong>{_safe(counts.get(key, 0))}</strong>"
            "</div>"
            for key, label in _OUTCOME_LABELS.items()
        )
        horizons.append(
            '<article class="st-ui-outcome-row">'
            f"<h4>{_safe(horizon)} 日</h4>"
            f'<div class="st-ui-outcome-values">{statuses}</div>'
            "</article>"
        )
    return (
        '<section class="st-ui-outcome-matrix">'
        "<h3>到期評估進度</h3>"
        f'<div class="st-ui-outcome-grid">{"".join(horizons)}</div>'
        "</section>"
    )


def danger_panel_markup(*, title: str, message: str, warning_note: str | None = None) -> str:
    """Build a designated dangerous action warning container."""
    warning_html = (
        f'<p class="st-ui-danger-panel__note">{_safe(warning_note)}</p>' if warning_note else ""
    )
    return (
        '<section class="st-ui-danger-panel">'
        '<div class="st-ui-danger-panel__marker" aria-hidden="true"></div>'
        '<div class="st-ui-danger-panel__copy">'
        f"<strong>{_safe(title)}</strong>"
        f"<p>{_safe(message)}</p>"
        f"{warning_html}"
        "</div>"
        "</section>"
    )


def action_banner_markup(*, title: str, description: str, tone: str = "info") -> str:
    """Build a prominent single-action hero banner."""
    tone_class = _tone_class(tone)
    return (
        f'<section class="st-ui-action-banner {tone_class}">'
        f"<h3>{_safe(title)}</h3>"
        f"<p>{_safe(description)}</p>"
        "</section>"
    )
