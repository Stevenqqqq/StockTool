"""Native Settings and Data Health workspace renderer."""

from __future__ import annotations

import json
from typing import Any, Callable

from stock_tool.application.settings_workspace import (
    SettingsComponentStatus,
    SettingsWorkspaceApplicationService,
    SettingsWorkspaceSnapshot,
)
from stock_tool.application.daily_research_scheduler import format_next_scheduled_for

_STATUS_LABELS = {
    "healthy": "健康正常",
    "partial": "部分可用",
    "missing": "缺少資料",
    "stale": "資料過期",
    "error": "檢查異常",
}
_FRESHNESS_LABELS = {
    "fresh": "最新",
    "stale": "已過期",
    "missing": "無資料",
    "error": "錯誤",
    "not_applicable": "不適用",
}


def _safe_expander(st: Any, label: str, expanded: bool = False) -> Any:
    expander = getattr(st, "expander", None)
    if callable(expander):
        try:
            return expander(label, expanded=expanded)
        except TypeError:
            return expander(label)
    return _null_context()


class _null_context:
    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def render_settings_workspace(
    st: Any,
    *,
    service: SettingsWorkspaceApplicationService,
    refresh_callback: Callable[[], SettingsWorkspaceSnapshot] | None = None,
    daily_schedule_service: Any | None = None,
    daily_notification_service: Any | None = None,
) -> SettingsWorkspaceSnapshot:
    """Render diagnostics from a supplied service without network or writes."""

    st.caption("查看本機設定與資料狀態；此頁不會自動連線、下載或修改資料。")
    snapshot = st.session_state.get("settings_workspace_snapshot")
    if not isinstance(snapshot, SettingsWorkspaceSnapshot):
        snapshot = service.inspect()
        st.session_state["settings_workspace_snapshot"] = snapshot

    if st.button("重新檢查本機狀態", key="settings_workspace_refresh", width="stretch"):
        try:
            refreshed = refresh_callback() if refresh_callback is not None else service.refresh()
        except Exception:
            st.error("本機狀態檢查失敗；既有檢查結果未被改寫。")
        else:
            st.session_state["settings_workspace_snapshot"] = refreshed
            snapshot = refreshed
            st.success("已重新讀取本機狀態；未修改任何資料。")

    status_label = _STATUS_LABELS.get(snapshot.status, "未知")
    version = str(snapshot.manifest.core.get("application_version", "無資料"))
    cols = st.columns(3)
    cols[0].metric("StockTool 版本", version)
    cols[1].metric("資料健康狀態", status_label)
    cols[2].metric("元件項目數", str(len(snapshot.components)))

    if snapshot.status == "healthy":
        st.success("本機資料健康檢查完成，目前沒有需要處理的缺口。")
    elif snapshot.status == "error":
        st.error("本機資料檢查發現錯誤；請依下方缺口逐項處理。")
    else:
        st.warning("本機資料尚未完整；下方列出最重要的缺口與安全下一步。")

    st.subheader("資料元件狀態")
    for component in snapshot.components:
        _render_component(st, component)

    # Merge and deduplicate actionable gaps and warnings into a single prioritized block
    seen_issues: set[str] = set()
    combined_issues: list[tuple[str, str]] = []
    component_names = {
        "設定檔",
        "持股",
        "持股清單",
        "自選股",
        "自選股清單",
        "研究庫",
        "帳本",
        "持倉帳本",
        "資料庫",
        "本機行情資料庫",
        "快取",
        "本機行情快取",
        "外部資料來源",
        "金鑰",
        "settings",
        "portfolio",
        "watchlist",
        "research_library",
        "ledger",
        "sqlite",
        "cache",
        "provider_settings",
    }
    for c in snapshot.components:
        component_names.add(c.label)
        component_names.add(c.key)

    def _is_component_gap(text: str) -> bool:
        lower = text.lower()
        for name in component_names:
            if name.lower() in lower:
                return True
        return False

    def _translate_issue(text: str) -> str:
        return (
            text.replace("missing", "缺少資料")
            .replace("online", "線上來源")
            .replace("fingerprint", "數位指紋")
            .replace("canonical", "標準代號")
        )

    for gap in snapshot.gaps:
        text = _translate_issue(str(gap).strip())
        if _is_component_gap(text):
            continue
        if text and text not in seen_issues:
            seen_issues.add(text)
            combined_issues.append(("gap", text))
    for warning in snapshot.warnings:
        text = _translate_issue(str(warning).strip())
        if _is_component_gap(text):
            continue
        if text and text not in seen_issues:
            seen_issues.add(text)
            combined_issues.append(("warning", text))
    for component in snapshot.components:
        for c_warning in component.warnings:
            text = _translate_issue(str(c_warning).strip())
            if _is_component_gap(text):
                continue
            if text and text not in seen_issues:
                seen_issues.add(text)
                combined_issues.append(("warning", text))

    if combined_issues:
        st.subheader("待處理缺口與檢查警告")
        for kind, issue in combined_issues:
            if kind == "gap":
                st.warning(issue)
            else:
                st.info(issue)

    if daily_schedule_service is not None:
        _render_daily_schedule(st, daily_schedule_service)
    if daily_notification_service is not None:
        _render_daily_notifications(st, daily_notification_service)

    with _safe_expander(st, "詳細技術診斷與匯出", expanded=False):
        st.caption(f"診斷 manifest digest：{snapshot.digest}")
        manifest_json = json.dumps(
            snapshot.to_manifest_dict(), ensure_ascii=False, indent=2, sort_keys=True
        )
        st.download_button(
            "下載隱私安全診斷 manifest",
            data=manifest_json,
            file_name="stocktool-settings-health-manifest.json",
            mime="application/json",
            key="settings_workspace_manifest_download",
            width="stretch",
        )
        st.caption(
            "診斷 manifest 不包含私人絕對路徑、持股明細、研究文件內容、token、API key 或 credential 值。"
        )
        if st.button("開啟診斷模式", key="settings_workspace_legacy_mode", width="stretch"):
            st.session_state.legacy_dashboard = True
            st.rerun()

    return snapshot


def _render_daily_schedule(st: Any, service: Any) -> None:
    """Render explicit, non-background Windows schedule controls."""

    st.subheader("每日研究排程")
    try:
        settings = service.settings()
        state = service.state()
        latest = service.latest_run()
        plan = service.plan()
    except Exception:
        st.error("排程狀態目前無法讀取；既有研究資料未被修改。")
        return
    settings_warning = getattr(service, "settings_warning", lambda: None)()
    if settings_warning:
        st.warning("排程設定無法讀取，已安全停用；請重新儲存設定。")
    labels = {
        "not_installed": "未安裝",
        "disabled": "停用",
        "enabled": "啟用",
        "error": "錯誤",
    }
    st.write(f"目前狀態：{labels.get(state.status, '未知')}")
    st.caption(
        f"預設時間：週一至週五 {settings.local_time}（{settings.timezone}）；"
        f"固定工作名稱：{service.adapter.task_name}"
    )
    st.caption(f"下一次執行：{format_next_scheduled_for(service.now_fn(), settings) or '無'}")

    if latest is not None:
        st.write(
            f"上次結果：{latest.status}；資料截至：{latest.data_as_of or '無資料'}；"
            f"報告數位指紋：{latest.output_brief_fingerprint or '無'}"
        )
    else:
        st.caption("尚無排程執行紀錄。")

    action_cols = st.columns(3)
    with action_cols[0]:
        if st.button("啟用每日研究排程", key="daily_schedule_enable", width="stretch"):
            try:
                service.enable()
            except Exception:
                st.error("排程啟用失敗；請檢查權限與工作名稱。")
            else:
                st.success("每日研究排程已啟用。")
                st.rerun()
    with action_cols[1]:
        if st.button("停用每日研究排程", key="daily_schedule_disable", width="stretch"):
            try:
                service.disable()
            except Exception:
                st.error("排程停用失敗；既有研究資料未被修改。")
            else:
                st.success("每日研究排程已停用。")
                st.rerun()
    with action_cols[2]:
        if st.button("立即執行一次", key="daily_schedule_run_now", width="stretch"):
            try:
                result = service.run_now()
            except Exception:
                st.error("立即執行失敗；請稍後重試。")
            else:
                if getattr(result, "status", "") == "not_installed":
                    st.warning("每日研究排程尚未安裝；請先啟用排程，再執行一次。")
                elif getattr(result, "status", "") == "error":
                    st.error("立即執行失敗；請檢查排程狀態。")
                else:
                    st.success("已送出一次性研究簡報執行。")

    st.markdown("#### 危險操作區")
    confirm_uninstall = st.checkbox(
        "我確認要自 Windows 工作排程器移除此排程工作",
        key="daily_schedule_uninstall_confirm",
    )
    if st.button("移除每日研究排程", key="daily_schedule_uninstall", width="stretch"):
        if not confirm_uninstall:
            st.warning("請先勾選確認方塊，以確認移除排程工作。")
        else:
            try:
                service.uninstall()
            except Exception:
                st.error("排程移除失敗；既有研究資料未被修改。")
            else:
                st.success("每日研究排程已移除。")
                st.rerun()

    with _safe_expander(st, "排程指令技術細節", expanded=False):
        st.caption("Windows 工作排程器指令：")
        st.code(" ".join(plan.command))


def _render_daily_notifications(st: Any, service: Any) -> None:
    """Render opt-in notification controls, separate from Task Scheduler."""

    st.subheader("每日研究通知")
    try:
        settings = service.settings()
        status = service.status()
    except Exception:
        st.error("通知狀態目前無法讀取；站內研究收件匣仍可使用。")
        return
    st.write(f"目前狀態：{'啟用' if settings.enabled else '停用'}")
    capability_value = getattr(status, "capability_available", None)
    capability_reason = getattr(status, "capability_reason", None)
    capability_available = capability_value is not False
    capability_label = "可用" if capability_available else "不可用"
    st.write(f"Windows 通知能力：{capability_label}")
    if capability_value is False:
        st.caption(capability_reason or "Windows 通知目前不可用")
    if status.settings_warning:
        st.warning(status.settings_warning)
    if status.last_status:
        label = {
            "sent": "已發送",
            "unavailable": "Windows 通知目前不可用",
            "failed": "發送失敗",
        }.get(status.last_status, status.last_status)
        st.caption(f"最近一次通知：{label}")
        if status.last_reason:
            st.caption(f"原因：{status.last_reason}")
    if st.button("啟用每日研究通知", key="daily_notifications_enable", width="stretch"):
        if not capability_available:
            st.warning("目前沒有可用的 Windows 應用程式身分，無法啟用通知；站內收件匣仍可使用。")
            return
        try:
            service.set_enabled(True)
        except Exception:
            st.error("通知設定保存失敗，已維持原狀態。")
        else:
            st.success("每日研究通知已啟用。")
            st.rerun()
    if st.button("停用每日研究通知", key="daily_notifications_disable", width="stretch"):
        try:
            service.set_enabled(False)
        except Exception:
            st.error("通知設定保存失敗，已維持原狀態。")
        else:
            st.success("每日研究通知已停用。")
            st.rerun()
    if st.button("發送一次測試通知", key="daily_notifications_test", width="stretch"):
        try:
            result = service.send_test_notification()
        except Exception:
            st.error("測試通知失敗；站內收件匣不受影響。")
        else:
            if getattr(result, "status", "") == "sent":
                st.success("測試通知已送出。")
            elif getattr(result, "status", "") == "unavailable":
                st.info("Windows 通知目前不可用；站內收件匣仍可使用。")
            else:
                st.warning("測試通知未送出；站內收件匣仍可使用。")


def _render_component(st: Any, component: SettingsComponentStatus) -> None:
    status = _STATUS_LABELS.get(component.status, component.status)
    freshness = _FRESHNESS_LABELS.get(component.freshness, component.freshness)
    st.write(f"{component.label}：{status}；項目數 {component.count}；新鮮度 {freshness}")
    presence = dict(component.details).get("presence")
    if presence == "configured":
        st.caption("外部 AI 與金鑰：已設定（僅顯示設定狀態，不儲存或顯示金鑰明文）。")
    elif presence == "not_configured":
        st.caption("外部 AI 與金鑰：未設定；需要時由使用者手動填入。")
