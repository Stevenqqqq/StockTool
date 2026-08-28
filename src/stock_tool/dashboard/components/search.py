"""Safe, reusable global search input for the Dashboard shell."""

from __future__ import annotations

from typing import Any

from stock_tool.dashboard.state import SearchPreparation, prepare_search_request

MARKET_CHOICES: tuple[tuple[str, str | None], ...] = (
    ("請選擇市場", None),
    ("台股上市 TWSE", "TWSE"),
    ("台股上櫃 TPEX", "TPEX"),
    ("美股 US", "US"),
)


def render_global_search(
    st: Any,
    *,
    key_prefix: str,
    disabled: bool = False,
    default_symbol: str = "",
    default_market: str | None = None,
    submit_label: str = "開始研究",
) -> SearchPreparation | None:
    """Render an Enter-submittable form and return validated user intent only."""

    labels = [label for label, _ in MARKET_CHOICES]
    default_index = next(
        (index for index, (_, code) in enumerate(MARKET_CHOICES) if code == default_market),
        0,
    )
    with st.form(key=f"{key_prefix}_global_search", clear_on_submit=False):
        symbol = st.text_input(
            "股票代號",
            value=default_symbol,
            placeholder="例如：2330、6488 或 AAPL",
            key=f"{key_prefix}_global_symbol",
            disabled=disabled,
        )
        market_label = st.selectbox(
            "市場",
            options=labels,
            index=default_index,
            key=f"{key_prefix}_global_market",
            disabled=disabled,
        )
        submitted = st.form_submit_button(
            submit_label,
            type="primary",
            disabled=disabled,
            width="stretch",
        )
    if not submitted:
        return None
    market = dict(MARKET_CHOICES)[market_label]
    return prepare_search_request(symbol, market)
