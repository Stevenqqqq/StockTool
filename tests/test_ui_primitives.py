"""Presentation-only contracts for the StockTool UI primitives."""

from __future__ import annotations

import pytest

from stock_tool.dashboard.components.ui_primitives import (
    CompactStatistic,
    outcome_matrix_markup,
    state_panel_markup,
    statistic_group_markup,
    workspace_header_markup,
)


def test_ui_primitives_escape_every_dynamic_value() -> None:
    hostile = '<script>alert("x")</script><img src=x onerror=alert(1)>'

    markup = "".join(
        (
            workspace_header_markup(
                title=hostile,
                subtitle=hostile,
                status_label=hostile,
                status_tone="warning",
                data_as_of=hostile,
            ),
            state_panel_markup(
                tone="error",
                title=hostile,
                message=hostile,
                next_step=hostile,
            ),
            statistic_group_markup(
                title=hostile,
                statistics=(CompactStatistic(hostile, hostile, hostile, "info"),),
                variant="summary",
            ),
        )
    )

    assert hostile not in markup
    assert "<script>" not in markup
    assert "<img" not in markup
    assert "&lt;script&gt;" in markup
    assert "&quot;x&quot;" in markup


@pytest.mark.parametrize("tone", ("neutral", "info", "success", "warning", "error"))
def test_ui_primitives_accept_only_named_semantic_tones(tone: str) -> None:
    markup = state_panel_markup(tone=tone, title="狀態", message="說明")
    assert f"st-ui-tone--{tone}" in markup


def test_ui_primitives_reject_unknown_tone_and_variant() -> None:
    with pytest.raises(ValueError, match="tone"):
        state_panel_markup(tone="purple", title="狀態", message="說明")
    with pytest.raises(ValueError, match="variant"):
        statistic_group_markup(
            title="狀態",
            statistics=(CompactStatistic("項目", "1"),),
            variant="marketing",
        )


def test_prediction_outcome_matrix_uses_traditional_chinese_labels() -> None:
    markup = outcome_matrix_markup(
        {
            "5": {"pending": 2, "eligible": 1, "evaluated": 3, "unavailable": 0},
            "20": {"pending": 4, "eligible": 0, "evaluated": 1, "unavailable": 1},
        }
    )

    assert "5 日" in markup and "20 日" in markup
    assert "等待到期" in markup
    assert "可評估" in markup
    assert "已評估" in markup
    assert "不可用" in markup
    assert "pending" not in markup
    assert "eligible" not in markup
