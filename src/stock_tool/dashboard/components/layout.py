"""Layout primitives for the six-workspace Dashboard shell."""

from __future__ import annotations

from typing import Any

from stock_tool.dashboard.navigation import PRIMARY_NAVIGATION, NavigationItem

_SIDEBAR_BRAND_LINK = (
    '<a class="stocktool-brand-link" href="#stocktool-main" '
    'aria-label="StockTool 主內容">StockTool</a>'
)
_MAIN_ANCHOR = '<span id="stocktool-main" class="stocktool-main-anchor"></span>'


def render_dashboard_shell(st: Any, *, active_key: str) -> NavigationItem:
    """Render exactly six primary navigation options in the sidebar."""

    labels = [item.label for item in PRIMARY_NAVIGATION]
    active_index = next(
        (index for index, item in enumerate(PRIMARY_NAVIGATION) if item.key == active_key),
        0,
    )
    sidebar_markdown = getattr(st.sidebar, "markdown", None)
    if callable(sidebar_markdown):
        sidebar_markdown(_SIDEBAR_BRAND_LINK, unsafe_allow_html=True)
    else:
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

    markdown = getattr(st, "markdown", None)
    if callable(markdown):
        markdown(_MAIN_ANCHOR, unsafe_allow_html=True)
    st.title(item.label)
    st.caption(item.description)
