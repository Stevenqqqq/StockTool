"""Shared date eligibility for scenario presentation; no range calculation."""

from typing import Any

import pandas as pd

from stock_tool.application.research_snapshot import ResearchSnapshot


def normalized_date(value: Any) -> pd.Timestamp | None:
    try:
        stamp = pd.Timestamp(value)
        return None if pd.isna(stamp) else stamp.tz_localize(None).normalize()
    except (TypeError, ValueError):
        return None


def scenario_date_status(snapshot: ResearchSnapshot) -> tuple[bool, str]:
    """Return whether dates permit display, plus the visible reason/date label."""
    scenario = snapshot.scenario_reference
    if scenario is None or not scenario.available:
        return False, "尚無可用情境參考區間。"
    observed = normalized_date(snapshot.price.last_data_date) if snapshot.price else None
    reference = normalized_date(scenario.as_of_date)
    if observed is None or reference is None or reference > observed:
        return False, "情境日期或觀測日未確認，或情境日期晚於觀測日。"
    label = f"基準日 {reference.date()}"
    if reference < observed:
        label += "（歷史參考：早於觀測日，非當日區間）"
    return True, label
