"""Declarative Dashboard navigation and legacy compatibility mapping."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NavigationItem:
    """One top-level workspace and its reachable legacy pages."""

    key: str
    label: str
    description: str
    legacy_pages: tuple[str, ...]


PRIMARY_NAVIGATION: tuple[NavigationItem, ...] = (
    NavigationItem(
        key="home",
        label="研究首頁",
        description="從股票代號或市場開始，查看目前研究狀態與下一步。",
        legacy_pages=("首頁儀表板", "單檔股票分析", "技術指標", "AI 分析與評分", "基本面評分"),
    ),
    NavigationItem(
        key="explore",
        label="探索",
        description="探索產業題材、篩選條件與自選股。",
        legacy_pages=("產業 / 概念股查詢", "股票篩選器", "自選股清單"),
    ),
    NavigationItem(
        key="strategy",
        label="策略",
        description="檢查策略參數、成本假設、風控規則與回測結果。",
        legacy_pages=("策略回測",),
    ),
    NavigationItem(
        key="holdings",
        label="持倉",
        description="管理持股、檢查跨幣別估值、健康度與壓力測試。",
        legacy_pages=("投資組合管理", "投資組合風險"),
    ),
    NavigationItem(
        key="library",
        label="研究庫",
        description="整理公司研究、報告摘要、匯出與下載紀錄。",
        legacy_pages=("研究報告摘要", "報表下載"),
    ),
    NavigationItem(
        key="settings",
        label="設定",
        description="管理資料匯入、資料來源、快取與診斷相容模式。",
        legacy_pages=("資料匯入", "自動抓資料"),
    ),
)

LEGACY_PAGE_OPTIONS: tuple[str, ...] = tuple(
    page for item in PRIMARY_NAVIGATION for page in item.legacy_pages
)


def navigation_for_key(key: str) -> NavigationItem:
    """Return one workspace by its stable route key."""

    return next(item for item in PRIMARY_NAVIGATION if item.key == key)


def workspace_for_legacy_page(page: str) -> str | None:
    """Return the new workspace containing one legacy page, if known."""

    return next((item.key for item in PRIMARY_NAVIGATION if page in item.legacy_pages), None)


def all_legacy_pages() -> tuple[str, ...]:
    """Return every legacy page reachable from the new information architecture."""

    return LEGACY_PAGE_OPTIONS
