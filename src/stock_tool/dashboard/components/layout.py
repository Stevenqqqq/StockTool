"""Layout primitives for the six-workspace Dashboard shell."""

from __future__ import annotations

from typing import Any

from stock_tool.dashboard.navigation import PRIMARY_NAVIGATION, NavigationItem


def render_dashboard_shell(st: Any, *, active_key: str) -> NavigationItem:
    """Render exactly six primary navigation options in the sidebar."""

    labels = [item.label for item in PRIMARY_NAVIGATION]
    active_index = next(
        (index for index, item in enumerate(PRIMARY_NAVIGATION) if item.key == active_key),
        0,
    )
    st.sidebar.title("StockTool")
    st.sidebar.caption("股票研究與風險工具")
    selected_label = st.sidebar.radio(
        "主導航",
        labels,
        index=active_index,
        key="dashboard_primary_navigation",
    )
    item = next(item for item in PRIMARY_NAVIGATION if item.label == selected_label)
    st.sidebar.caption(item.description)
    return item


def render_page_header(st: Any, item: NavigationItem) -> None:
    """Render one consistent workspace title and concise next-step description."""

    st.title(item.label)
    st.caption(item.description)
