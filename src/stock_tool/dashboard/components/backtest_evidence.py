"""Readable, research-only portfolio and completed-trade evidence."""

from dataclasses import asdict
from statistics import mean

import pandas as pd

from stock_tool.dashboard.presentation_mapper import format_percentage


def render_backtest_evidence(st, metrics):
    def number(value):
        if value is None:
            return "資料不足"
        if value == float("inf"):
            return "無虧損樣本"
        return f"{value:,.2f}"

    def pct(value):
        return format_percentage(value, with_sign=True, is_ratio=True)

    def row(items):
        for column, (label, value) in zip(st.columns(len(items)), items):
            column.metric(label, value)

    st.markdown("### 整體績效")
    row((("總報酬", pct(metrics.total_return)), ("年化報酬 CAGR", pct(metrics.cagr))))
    row((("最大回撤", pct(metrics.max_drawdown)), ("Sharpe Ratio", number(metrics.sharpe_ratio))))
    st.markdown("### 交易品質")
    st.caption(
        f"成交筆數（fills）：{metrics.fill_count}；買進、賣出各算一筆成交，尚未平倉的成交也包含在內。"
    )
    available = metrics.trade_evidence_unavailable_reason is None
    if not available:
        st.warning(metrics.trade_evidence_unavailable_reason)
    count = metrics.closed_round_trip_count
    row(
        (
            ("完整交易（已平倉）", str(count) if count is not None else "資料不足"),
            ("勝率", pct(metrics.win_rate) if available and count else "資料不足"),
            ("每筆期望損益", number(metrics.expectancy)),
        )
    )
    row(
        (
            ("獲利因子", number(metrics.profit_factor)),
            ("賺賠比", number(metrics.payoff_ratio)),
            ("每筆報酬中位數", pct(metrics.median_trade_return)),
        )
    )
    st.caption(
        f"平均獲利：{number(metrics.average_win)}；平均虧損：{number(metrics.average_loss)}。損益採回測帳面貨幣，含既有費稅與成交滑價；期望值是完整交易實際損益的平均。"
    )
    if metrics.round_trips:
        returns = [t.trade_return for t in metrics.round_trips]
        st.caption(
            f"每筆報酬平均 {pct(mean(returns))}，最低 {pct(min(returns))}，最高 {pct(max(returns))}。請與中位數及明細比較，避免只看少數極端結果。"
        )
    st.markdown("### 持倉體感")
    row(
        (
            ("持有期間不利幅度中位數 MAE", pct(metrics.median_mae)),
            ("持有期間有利幅度中位數 MFE", pct(metrics.median_mfe)),
            ("平均持有天數", number(metrics.average_holding_period)),
        )
    )
    st.caption(
        f"MFE／MAE 可計算 {metrics.excursion_count} / {count if count is not None else '未知'} 筆完整交易；平均 MFE {pct(metrics.average_mfe)}、平均 MAE {pct(metrics.average_mae)}。只彙總可計算樣本，不以 0 補缺漏。"
    )
    st.caption(
        "開盤成交：使用進場日至出場日前的 high／low，加上進出成交價端點；不使用出場當日開盤後或其後的高低價。MFE／MAE 是價格路徑比例，不是扣費稅後的投資報酬。"
    )
    if count and metrics.excursion_count < count:
        st.warning("部分完整交易無法可靠計算 MFE／MAE，請查看明細原因；沒有改用 close。")
    with st.expander("完整交易明細與定義"):
        st.write(
            "同一標的從無持倉到全部平倉為一筆完整交易；分批賣出不另增筆數。報酬＝該段已實現損益合計／全部買進現金流出（含買進手續費）。加碼／分批出場無單一價格或訊號日時顯示資料不足。"
        )
        if metrics.round_trips:
            frame = pd.DataFrame(asdict(t) for t in metrics.round_trips)
            for column in ("trade_return", "mfe", "mae"):
                frame[column] = frame[column].map(
                    lambda x: "資料不足" if pd.isna(x) else f"{x:.2%}"
                )
            frame["excursion_unavailable_reason"] = frame["excursion_unavailable_reason"].fillna(
                "可計算"
            )
            frame = frame.astype(object).where(pd.notna(frame), "資料不足")
            frame = frame.rename(
                columns={
                    "symbol": "標的",
                    "entry_signal_date": "進場訊號日",
                    "entry_execution_date": "首次進場成交日",
                    "entry_price": "進場成交價",
                    "exit_signal_date": "出場訊號日",
                    "exit_execution_date": "最後出場成交日",
                    "exit_price": "出場成交價",
                    "quantity": "累計買進股數",
                    "realized_pnl": "已實現損益",
                    "trade_return": "淨報酬率",
                    "holding_days": "持有天數",
                    "mfe": "MFE",
                    "mae": "MAE",
                    "excursion_unavailable_reason": "MFE／MAE 缺口",
                    "exit_reason": "出場原因",
                }
            )
            st.dataframe(frame, width="stretch", hide_index=True)
        else:
            st.info("沒有可可靠重建的完整交易；未平倉部位不計入。")
