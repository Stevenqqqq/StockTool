"""Consistent user-facing state presentation for the Dashboard shell."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from stock_tool.dashboard.state import DashboardStatus


@dataclass(frozen=True, slots=True)
class StatusPresentation:
    """Safe copy and action availability for one Dashboard status."""

    severity: str
    title: str
    message: str
    can_continue: bool


STATUS_PRESENTATIONS: dict[DashboardStatus, StatusPresentation] = {
    DashboardStatus.FIRST_USE: StatusPresentation(
        "info", "從一檔股票開始", "輸入股票代號並選擇市場，系統會整理可用研究資料。", True
    ),
    DashboardStatus.LOADING: StatusPresentation(
        "info", "正在更新資料", "資料更新中，請避免重複提交同一個查詢。", False
    ),
    DashboardStatus.PARTIAL: StatusPresentation(
        "warning", "部分資料可用", "部分研究資料尚未取得；可先查看已載入內容與資料限制。", True
    ),
    DashboardStatus.READY: StatusPresentation(
        "success", "研究資料已就緒", "可繼續查看技術、基本面、評分與既有策略工具。", True
    ),
    DashboardStatus.STALE: StatusPresentation(
        "warning", "資料可能不是最新", "目前使用快取或較早資料；請確認更新時間後再解讀結果。", True
    ),
    DashboardStatus.ERROR: StatusPresentation(
        "error",
        "資料更新未完成",
        "請確認股票代號、市場或網路連線後再試；既有資料會保留並清楚標示。",
        True,
    ),
}


def render_dashboard_status(
    st: Any, *, status: DashboardStatus, message: str | None = None
) -> None:
    """Render state copy without exposing raw provider or exception detail."""

    presentation = STATUS_PRESENTATIONS[status]
    text = message or presentation.message
    renderer = getattr(st, presentation.severity)
    renderer(f"{presentation.title}：{text}")
