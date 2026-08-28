"""Action-oriented overviews for the Sprint 4 Dashboard workspaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class WorkspaceAction:
    """One safe entry into an existing legacy renderer or diagnostic mode."""

    key: str
    title: str
    purpose: str
    data_requirement: str
    button_label: str
    legacy_page: str | None
    diagnostic_mode: bool = False


_WORKSPACE_ACTIONS: dict[str, tuple[WorkspaceAction, ...]] = {
    "explore": (
        WorkspaceAction(
            "concept_lookup",
            "產業／概念股查詢",
            "以公開資料探索產業、技術與概念關聯的候選公司。",
            "需要產業或概念關鍵字；結果可能受公開資料覆蓋限制。",
            "開始查詢",
            "產業 / 概念股查詢",
        ),
        WorkspaceAction(
            "screener",
            "股票篩選器",
            "依既有技術、基本面與風險條件建立研究清單。",
            "需要已載入且欄位完整的研究資料。",
            "開始篩選",
            "股票篩選器",
        ),
        WorkspaceAction(
            "watchlist",
            "自選股清單",
            "整理要持續追蹤的市場與股票代號。",
            "不需要價格資料；清單僅儲存在本機使用者資料區。",
            "管理自選股",
            "自選股清單",
        ),
    ),
    "strategy": (
        WorkspaceAction(
            "backtest",
            "策略回測",
            "檢查策略訊號、benchmark、交易成本、滑價與 risk gate 的歷史表現。",
            "需要足夠長度且已排序的歷史價格資料。",
            "執行回測",
            "策略回測",
        ),
    ),
    "holdings": (
        WorkspaceAction(
            "portfolio",
            "投資組合管理",
            "管理手動持股，查看跨幣別估值與未實現損益。",
            "需要本機持股檔；價格不足時會清楚標示。",
            "管理持股",
            "投資組合管理",
        ),
        WorkspaceAction(
            "portfolio_risk",
            "投資組合風險",
            "查看持股健康度、集中度、跨幣別估值與壓力測試。",
            "需要已載入持股及可用的市場價格；資料不足時不計分。",
            "檢查投資組合風險",
            "投資組合風險",
        ),
    ),
    "library": (
        WorkspaceAction(
            "research_reports",
            "研究報告摘要",
            "匯入或查看研究報告摘要與其資料限制。",
            "需要使用者選擇可讀取的 PDF 或既有摘要。",
            "查看研究報告",
            "研究報告摘要",
        ),
        WorkspaceAction(
            "reports",
            "報表下載",
            "輸出既有研究、回測與風險結果為本機報表。",
            "需要已產生可用研究結果；資料不足時不建立假報表。",
            "建立報表",
            "報表下載",
        ),
    ),
    "settings": (
        WorkspaceAction(
            "import",
            "資料匯入",
            "匯入 CSV 或 Excel，並套用既有資料清理規則。",
            "需要符合標準 OHLCV 欄位的來源檔。",
            "匯入資料",
            "資料匯入",
        ),
        WorkspaceAction(
            "auto_fetch",
            "自動抓資料",
            "管理市場、資料來源、快取與既有自動更新流程。",
            "需要網路或有效本機快取；失敗時不會產生假資料。",
            "更新資料",
            "自動抓資料",
        ),
        WorkspaceAction(
            "legacy_diagnostics",
            "Legacy dashboard／診斷模式",
            "僅在新版工作區發生問題時，使用完整舊版頁面清單協助診斷。",
            "不需要額外資料；可隨時返回新版工作區。",
            "開啟診斷模式",
            None,
            diagnostic_mode=True,
        ),
    ),
}


def workspace_actions(workspace_key: str) -> tuple[WorkspaceAction, ...]:
    """Return the fixed, non-data-generating actions for one workspace."""

    return _WORKSPACE_ACTIONS.get(workspace_key, ())


def render_workspace_overview(st: Any, workspace_key: str) -> WorkspaceAction | None:
    """Render native Streamlit action cards and return one selected action, if any."""

    actions = workspace_actions(workspace_key)
    if not actions:
        return None
    st.subheader("從一項工作開始")
    st.caption("選擇下方入口；系統只開啟既有工具，不會建立假資料、報告或警報。")
    columns = st.columns(2)
    for index, action in enumerate(actions):
        with columns[index % len(columns)].container(border=True):
            st.markdown(f"#### {action.title}")
            st.write(action.purpose)
            st.caption(f"使用前：{action.data_requirement}")
            if st.button(
                action.button_label,
                key=f"workspace_action_{workspace_key}_{action.key}",
                type="primary" if index == 0 else "secondary",
                width="stretch",
            ):
                return action
    return None
