"""Chinese daily holdings cards using the shared headless runner."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from stock_tool.application.daily_holdings import (
    load_report,
    next_observation,
    positions_fingerprint,
    save_observation,
    load_observations,
)
from stock_tool.application.daily_holdings_job import job_for, start_refresh
from stock_tool.dashboard.pages.home import HomeAction
from stock_tool.dashboard.state import SearchRequest, SearchPreparation
from stock_tool.portfolio_management import load_portfolio
from stock_tool.runtime_paths import RuntimePaths
from stock_tool.dashboard.presentation_mapper import format_taiwan_company_display
from stock_tool.dashboard.instrument_names import name_notice


def render_daily_holdings(st: Any, paths: RuntimePaths) -> HomeAction | None:
    positions = load_portfolio(paths.portfolio_file)
    if positions.empty:
        return None
    st.subheader("今天的持股重點")
    st.caption("本機規則整理｜最多三件新變化｜不提供交易指令；市場、匯率與公司文件日期分開核對。")
    try:
        report = load_report(paths)
    except ValueError as exc:
        st.error(str(exc))
        return None
    if report and report["positions_fingerprint"] != positions_fingerprint(positions):
        st.info("持股已變更，舊部位的摘要暫不套用；正在準備新結果。")
        report = None
    job = start_refresh(paths)
    if job.error:
        st.warning(job.error)
    if st.button("重新檢查持股", key="daily_holdings_refresh", disabled=job.running):
        start_refresh(paths, force=True)
        st.rerun()
    if job.running:
        st.session_state["daily_holdings_was_running"] = True
        st.info("背景更新中；你可以先看前次結果或繼續研究。")
    if report:
        st.caption(f"本次檢查：{report['checked_at']}（不是所有資料的共同截至日）")
        if (
            datetime.now(UTC) - datetime.fromisoformat(report["checked_at"])
        ).total_seconds() > 86400:
            st.warning("以下為前次歷史結果，尚未重新確認有效性，不代表目前估值。")
        rows = report["holdings"]
        events = [
            (identity, row, event) for identity, row in rows.items() for event in row["events"]
        ]
        events.sort(
            key=lambda item: (
                -item[2]["priority"],
                -(item[1]["weight"] or 0),
                item[0],
                item[2]["code"],
            )
        )
        if not events:
            if any(row["status"] in {"保留前次結果", "資料不足"} for row in rows.values()):
                st.info(
                    "本次部分或全部持股未完成更新，不能完整判斷新變化；前次結果與日期保留在下方。"
                )
            elif any(row["status"] == "首次基準" for row in rows.values()):
                st.info("已建立首次比較基準；不把既有狀態說成新變化。")
            else:
                st.info("可比資料中沒有新的重要變化；資料不足的持股另列，不代表全部無風險。")
        for identity, row, event in events[:3]:
            with st.container(border=True):
                st.markdown(format_taiwan_company_display(row["symbol"], market=row["market"]))
                notice = name_notice(row["market"], row["symbol"])
                if notice:
                    st.info(notice)
                st.markdown(f"**{event['title']}**")
                if event["baseline_value"] == event["current_value"]:
                    st.write(f"持續符合注意條件：{event['current_value']}")
                else:
                    st.write(
                        f"變化：{event['baseline_value'] or '前次未出現'} → {event['current_value']}"
                    )
                st.write(f"為何注意：{event['why_important']}")
                if row["weight"] is not None:
                    st.write(f"檢查當時的本機持股權重：{row['weight']:.1%}；權重不是交易建議。")
                st.write(f"接下來觀察：{next_observation(event['code'])}")
                source = event["source"]
                st.caption(
                    f"來源：{source['provider'] or '未確認'}｜行情日期：{event['as_of_date']}｜取得：{source['checked_at']}"
                )
                st.caption(row["company_scope"])
                if st.button("記下這個觀察", key=f"daily_note_{identity}_{event['code']}"):
                    try:
                        save_observation(paths, row, event, now=datetime.now(UTC))
                        st.success("已保存在本機；下次開啟仍可接續核對，不代表風險已解除。")
                    except (ValueError, OSError):
                        st.error("觀察未能安全保存；既有紀錄保留。")
                if st.button("研究這筆持股", key=f"daily_research_{identity}_{event['code']}"):
                    return HomeAction(
                        kind="search",
                        preparation=SearchPreparation(
                            SearchRequest(symbol=row["symbol"], market=row["market"])
                        ),
                    )
        with st.expander("全部持股、資料缺口與來源日期"):
            for identity, row in rows.items():
                display_name = format_taiwan_company_display(row["symbol"], market=row["market"])
                st.markdown(
                    f"**{display_name} · {row['market']} · {row['instrument_type']} · {row['status']}**"
                )
                for datum in row["data"]:
                    if datum["label"] in {"收盤價", "匯率", "原幣市值"}:
                        st.write(
                            f"{datum['label']}：{datum['value']}｜{datum['status']}｜{datum['source']}｜資料日期 {datum['as_of']}｜取得 {datum['fetched_at']}"
                        )
                for gap in row["gaps"]:
                    st.caption(gap)
                if row["status"] in {"保留前次結果", "資料不足"}:
                    st.warning("本次未形成可比的新結果；前次訊號不判定解除。")
                    for old in row["previous_events"]:
                        st.caption(
                            f"前次：{old['title']}；{old['as_of_date']}；{old['current_value']}"
                        )
                st.caption(row["company_scope"])
                if st.button("開啟持股研究", key=f"daily_all_{identity}"):
                    return HomeAction(
                        kind="search",
                        preparation=SearchPreparation(
                            SearchRequest(symbol=row["symbol"], market=row["market"])
                        ),
                    )
        if report["fx"]:
            fx = report["fx"]
            st.caption(
                f"USD/TWD：{fx['rate']}｜{fx['source']}｜報價 {fx['effective_at']}｜取得 {fx['fetched_at']}"
            )
        else:
            st.caption("無有效 USD/TWD 時，不計算跨幣別總額或權重。")

    try:
        observations = load_observations(paths)
        with st.expander(f"接續觀察（已保存 {len(observations)} 筆）"):
            for note in reversed(observations[-20:]):
                st.write(
                    f"{note['identity']} · {note['instrument_type']}：{note['next_observation']}"
                )
                st.caption(
                    f"原始依據：{note['event']['current_value']}｜行情日期 {note['event']['as_of_date']}｜保存 {note['saved_at']}"
                )
            if len(observations) > 20:
                st.caption("此處顯示最近 20 筆，較早紀錄仍保留在本機。")
    except ValueError as exc:
        st.error(str(exc))

    # Poll only this small status fragment; provider calls stay in the worker.
    def poll() -> None:
        active = job_for(paths)
        if not active.running:
            # A completed worker needs one app render to load its persisted result.
            if st.session_state.get("daily_holdings_was_running"):
                st.session_state["daily_holdings_was_running"] = False
                st.rerun(scope="app")
        else:
            st.session_state["daily_holdings_was_running"] = True
            st.caption("持股資料更新中…")
        checked = st.session_state.get("daily_holdings_due_check")
        now = datetime.now(UTC)
        if not checked or (now - checked).total_seconds() >= 60:
            st.session_state["daily_holdings_due_check"] = now
            start_refresh(paths)

    st.fragment(run_every="2s" if job.running else "60s")(poll)()
    return None
