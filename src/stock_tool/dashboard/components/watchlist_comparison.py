"""Small comparison view embedded in the existing watchlist."""

from collections.abc import Callable
from html import escape
from typing import Any

import pandas as pd

from stock_tool.application.watchlist_comparison import compare_symbol, comparison_notices
from stock_tool.dashboard.presentation_mapper import format_taiwan_company_display
from stock_tool.domain.models import Market, Symbol

SORT_FIELDS = {
    "選取順序": None,
    "5日表現": "return_5",
    "20日表現": "return_20",
    "相對SMA20": "sma_20_position",
    "相對SMA60": "sma_60_position",
    "量比": "volume_ratio",
}


def sorted_comparison(rows, metric: str, ascending: bool = False):
    """Sort numbers stably with missing values last; never rank different dates."""
    field = SORT_FIELDS.get(metric)
    dates = {row.date for row in rows if row.close is not None}
    if field is None or len(dates) != 1 or None in dates:
        return tuple(rows)
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                getattr(row, field) is None,
                (getattr(row, field) or 0) * (1 if ascending else -1),
            ),
        )
    )


def comparison_html(rows, label) -> str:
    """Display-only, escaped table; signed values remain readable without color."""

    def pct(value):
        if value is None:
            return '<span class="wc-missing">資料不足</span>'
        tone = "up" if value > 0 else "down" if value < 0 else "flat"
        return f'<strong class="wc-{tone}">{value:+.2%}</strong>'

    body = []
    for row in rows:
        currency = "USD" if row.symbol.market is Market.US else "TWD"
        close = "資料不足" if row.close is None else f"{row.close:,.2f}"
        volume = "資料不足" if row.volume_ratio is None else f"{row.volume_ratio:.2f}倍"
        name = label(row.symbol.canonical)
        if name == row.symbol.code:
            name += "（名稱未確認）"
        body.append(
            '<tr><th scope="row">'
            + escape(name)
            + f"<small>{escape(row.symbol.market.value)} · {currency}</small></th>"
            + f'<td class="wc-close">{close}</td><td>{pct(row.return_5)}</td>'
            + f"<td>{pct(row.return_20)}</td><td>{pct(row.sma_20_position)}</td>"
            + f"<td>{pct(row.sma_60_position)}</td><td>{volume}</td></tr>"
        )
    return (
        """<style>
.wc-wrap {overflow-x:auto; margin:12px 0 18px;}
.wc-table {width:100%; min-width:730px; border-collapse:collapse; font-size:17px; font-variant-numeric:tabular-nums;}
.wc-table th,.wc-table td {padding:16px 12px; text-align:right; white-space:nowrap; border-bottom:1px solid #64748b55;}
.wc-table thead th {font-size:14px; font-weight:500; opacity:.8;}
.wc-table th:first-child {text-align:left; min-width:175px;}
.wc-table tbody th {font-size:18px;}
.wc-table small {display:block; font-size:12px; opacity:.7; font-weight:400; margin-top:5px;}
.wc-table .wc-close {font-weight:600;}
.wc-table .wc-up {color:#df5864;} .wc-table .wc-down {color:#179f7b;}
.wc-table .wc-missing {font-size:14px; opacity:.65;}
</style><div class="wc-wrap"><table class="wc-table" aria-label="自選股價量比較">
<thead><tr><th>公司／市場</th><th>最新收盤</th><th>5日表現</th><th>20日表現</th>
<th>相對SMA20</th><th>相對SMA60</th><th>量比</th></tr></thead><tbody>"""
        + "".join(body)
        + "</tbody></table></div>"
    )


def render_watchlist_comparison(
    st: Any,
    watchlist: pd.DataFrame,
    *,
    load_prices: Callable[[], pd.DataFrame | None],
    refresh: Callable[[Symbol], Any],
    on_research: Callable[[Symbol], None],
) -> None:
    st.subheader("自選股多檔比較")
    identities: dict[str, Symbol] = {}
    unknown = []
    for row in watchlist.itertuples(index=False):
        try:
            symbol = Symbol.parse(str(row.symbol), market=str(row.market))
            if symbol.market not in {Market.TWSE, Market.TPEX, Market.US}:
                raise ValueError("unknown market")
            identities[symbol.canonical] = symbol
        except ValueError:
            unknown.append(str(row.symbol))
    if unknown:
        st.info("市場尚未確認，未加入比較：" + "、".join(unknown) + "。請先確認市場。")
    if len(identities) < 2:
        st.info("請先加入至少兩檔市場明確的自選股（上市／上櫃／美股）。")
        return

    def label(key: str) -> str:
        symbol = identities[key]
        return f"{format_taiwan_company_display(symbol.code, market=symbol.market.value)} · {symbol.market.value}"

    def company_label(key: str) -> str:
        symbol = identities[key]
        return format_taiwan_company_display(symbol.code, market=symbol.market.value)

    key = "watchlist_comparison_selection"
    if key in st.session_state:
        valid_selection = [v for v in st.session_state[key] if v in identities][:5]
        if valid_selection != st.session_state[key]:
            st.session_state[key] = valid_selection
    selected = st.multiselect(
        "比較標的（2～5檔）",
        list(identities),
        default=list(identities)[:3],
        format_func=label,
        max_selections=5,
        key=key,
    )
    if not 2 <= len(selected) <= 5:
        st.info("請選擇2～5檔；選擇只影響畫面，不修改自選股。")
        return
    if st.button("載入／更新比較行情", key="watchlist_comparison_refresh"):
        results = {}
        for identity in selected:
            try:
                result = refresh(identities[identity])
                results[identity] = (
                    "更新失敗；保留原有行情。"
                    if result.status == "failure"
                    else "已載入（可能包含快取回退）；依下方日期與來源核對。"
                )
            except Exception:
                results[identity] = "更新失敗；保留原有行情，請稍後重試。"
        st.session_state["watchlist_comparison_refresh_results"] = results
    prices = load_prices()
    rows = tuple(compare_symbol(prices, identities[item]) for item in selected)
    for notice in comparison_notices(rows):
        st.warning(notice)
    dates = {row.date for row in rows if row.close is not None}
    same_date = len(dates) == 1 and None not in dates
    st.caption(
        f"已完成收盤 · {next(iter(dates))} · 非即時行情"
        if same_date
        else "各檔日期請見下方資料狀態；目前不進行跨檔排序。"
    )
    left, right = st.columns([2, 1])
    metric = left.selectbox(
        "排序指標",
        list(SORT_FIELDS),
        index=2,
        disabled=not same_date,
        key="watchlist_comparison_sort",
    )
    direction = right.selectbox(
        "排序方向",
        ["由高到低", "由低到高"],
        disabled=not same_date,
        key="watchlist_comparison_direction",
    )
    rows = sorted_comparison(rows, metric, direction == "由低到高")
    st.markdown(comparison_html(rows, company_label), unsafe_allow_html=True)
    for row in rows:
        result = st.session_state.get("watchlist_comparison_refresh_results", {}).get(
            row.symbol.canonical
        )
        if result and "失敗" in result:
            st.caption(f"{label(row.symbol.canonical)}：{result}")
        if row.notices:
            st.caption(f"{label(row.symbol.canonical)}：" + "；".join(row.notices))
    st.caption(
        "資料狀態："
        + " ｜ ".join(
            f"{row.symbol.code} {row.date or '日期未確認'} · {row.source or '來源未確認'}"
            for row in rows
        )
    )
    st.caption("以上為各來源已載入的有效收盤，可能落後交易所；同日不代表不同來源的價格基準相同。")
    if any(row.source == "yfinance" for row in rows):
        st.caption(
            "Yahoo 價量使用 Close／OHLC（非 Adj Close）；歷史價格可能已調整分割，"
            "成交量未必等同交易所總量。此處報酬不是含息總報酬。"
        )
    with st.expander("如何閱讀與資料限制"):
        st.write(
            "紅色正值／綠色負值表示漲跌，不是買賣建議。排序只比較所選指標，沒有綜合分數。"
            "5／20日為各市場已載入交易日的價格報酬，非含息總報酬；跨市場交易日及幣別不同。"
            "相對SMA＝收盤／均線−1；正值在均線上方，負值在下方。"
            "量比＝當日量／前20日均量，不含當日；大於1表示放量。"
        )
    research_key = "watchlist_comparison_research"
    if st.session_state.get(research_key) not in selected:
        st.session_state.pop(research_key, None)
    chosen = st.selectbox("開啟個股研究", selected, format_func=label, key=research_key)
    if st.button("進入既有研究頁", key="watchlist_comparison_open"):
        on_research(identities[chosen])
