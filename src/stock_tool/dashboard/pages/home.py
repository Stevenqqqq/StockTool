"""Daily Research Home presentation built on the UI-independent Daily Brief."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from stock_tool.application.daily_brief import (
    ActionRequired,
    DailyBrief,
    DailyBriefItem,
    ResearchContinuation,
)
from stock_tool.application.daily_research_loop import DailyResearchEvent, DailyResearchLoopResult
from stock_tool.application.daily_research_brief import (
    DailyResearchBrief,
    render_daily_brief_html,
)
from stock_tool.application.daily_research_changes import DailyResearchChangeSet
from stock_tool.application.macro_snapshot import MacroSignal, MacroSnapshot
from stock_tool.application.daily_research_inbox import ResearchInboxEntry
from stock_tool.application.prediction_lab import PredictionLabSummary
from stock_tool.application.daily_research_runner import DailyResearchRunManifest
from stock_tool.domain import Symbol
from stock_tool.dashboard.components.search import render_global_search
from stock_tool.dashboard.components.ui_primitives import (
    CompactStatistic,
    outcome_matrix_markup,
    render_ui_markup,
    section_header_markup,
    state_panel_markup,
    statistic_group_markup,
    workspace_header_markup,
)
from stock_tool.dashboard.components.research_assistant import (
    ResearchAssistantAction,
    render_research_assistant,
)
from stock_tool.research.assistant import DailyResearchAssistantBrief
from stock_tool.dashboard.state import DashboardStatus, SearchPreparation, SearchRequest

HomeActionKind = Literal[
    "search",
    "refresh",
    "workspace",
    "ai_research",
    "daily_evidence_brief",
    "macro_refresh",
    "daily_research_run",
    "prediction_outcome_evaluation",
]


@dataclass(frozen=True, slots=True)
class HomeContext:
    """Safe, non-sensitive state adapted by the Dashboard shell."""

    status: DashboardStatus
    active_symbol: str | None
    recent_searches: tuple[SearchRequest, ...]
    watchlist_count: int | None
    portfolio_count: int | None
    source_label: str | None
    updated_at: str | None
    summary_warnings: tuple[str, ...] = ()
    daily_brief: DailyBrief | None = None
    daily_research_loop: DailyResearchLoopResult | None = None
    research_assistant_brief: DailyResearchAssistantBrief | None = None
    research_assistant_available: bool = False
    daily_evidence_brief: DailyResearchBrief | None = None
    daily_evidence_available: bool = True
    daily_research_inbox: tuple[ResearchInboxEntry, ...] = ()
    daily_research_inbox_brief: DailyResearchBrief | None = None
    daily_research_changes: DailyResearchChangeSet | None = None
    macro_snapshot: MacroSnapshot | None = None
    macro_signals: tuple[MacroSignal, ...] = ()
    macro_links: tuple[dict[str, object], ...] = ()
    macro_revisions: tuple[dict[str, object], ...] = ()
    prediction_lab: PredictionLabSummary | None = None
    prediction_lab_evaluation_available: bool = False
    daily_research_run: DailyResearchRunManifest | None = None


@dataclass(frozen=True, slots=True)
class HomeAction:
    """One explicit user action emitted by the home presentation."""

    kind: HomeActionKind
    preparation: SearchPreparation | None = None
    workspace: str | None = None
    legacy_page: str | None = None
    force_regenerate: bool = False


@dataclass(frozen=True, slots=True)
class _DailyLoopRenderState:
    """Visible Daily Loop identities used to avoid duplicate legacy cards and CTAs."""

    action: HomeAction | None
    represented_keys: frozenset[str]
    represented_actions: frozenset[str]


def _home_status_label(status: DashboardStatus) -> str:
    """Return a short Traditional Chinese status label for the overview header."""

    return {
        DashboardStatus.FIRST_USE: "尚未開始",
        DashboardStatus.LOADING: "載入中",
        DashboardStatus.PARTIAL: "部分可用",
        DashboardStatus.READY: "資料就緒",
        DashboardStatus.STALE: "可能過期",
        DashboardStatus.ERROR: "需要檢查",
    }.get(status, "資料不足")


def _home_status_tone(status: DashboardStatus) -> str:
    """Map dashboard state to the fixed visual-semantic tone contract."""

    return {
        DashboardStatus.FIRST_USE: "info",
        DashboardStatus.LOADING: "info",
        DashboardStatus.PARTIAL: "warning",
        DashboardStatus.READY: "success",
        DashboardStatus.STALE: "warning",
        DashboardStatus.ERROR: "error",
    }.get(status, "neutral")


def _home_state_copy(status: DashboardStatus) -> tuple[str, str, str] | None:
    """Return concise visible state guidance without provider implementation detail."""

    return {
        DashboardStatus.FIRST_USE: (
            "從第一家公司開始",
            "目前沒有既有研究資料；先選擇市場與股票代號。",
            "完成第一份研究後，首頁會整理可繼續的項目。",
        ),
        DashboardStatus.LOADING: (
            "正在整理資料",
            "目前查詢仍在進行，既有內容會保留。",
            "請等待完成後再提交下一次研究。",
        ),
        DashboardStatus.PARTIAL: (
            "部分資料可用",
            "可先查看已取得的內容；缺少欄位不會以推測值補齊。",
            "檢查可見警告，必要時再明確更新資料。",
        ),
        DashboardStatus.STALE: (
            "資料可能過期",
            "目前內容來自較早的已驗證資料。",
            "確認資料日期後，再決定是否更新。",
        ),
        DashboardStatus.ERROR: (
            "資料更新未完成",
            "既有研究內容仍保留，未驗證資料不會取代它。",
            "確認股票代號、市場與連線後再試。",
        ),
    }.get(status)


def _render_home_overview_header(
    st: Any,
    context: HomeContext,
    brief: DailyBrief | None,
) -> None:
    """Render the compact first-screen summary without changing any data flow."""

    data_as_of = (
        brief.data_as_of_date if brief is not None and brief.data_as_of_date else context.updated_at
    )
    render_ui_markup(
        st,
        workspace_header_markup(
            title="今天先看這些",
            subtitle="先掌握資料狀態，再決定今天需要研究什麼。",
            status_label=_home_status_label(context.status),
            status_tone=_home_status_tone(context.status),
            data_as_of=data_as_of or "資料不足",
        ),
    )
    state_copy = _home_state_copy(context.status)
    if state_copy is not None:
        title, message, next_step = state_copy
        render_ui_markup(
            st,
            state_panel_markup(
                tone=_home_status_tone(context.status),
                title=title,
                message=message,
                next_step=next_step,
            ),
        )


def _home_summary_statistics(context: HomeContext) -> tuple[CompactStatistic, ...]:
    """Build the bounded first-screen summary without inventing missing counts."""

    sample_count = (
        context.prediction_lab.registered_today if context.prediction_lab is not None else None
    )
    return (
        CompactStatistic(
            "持股",
            str(context.portfolio_count) if context.portfolio_count is not None else "資料不足",
            "目前載入筆數",
            "success" if context.portfolio_count else "neutral",
        ),
        CompactStatistic(
            "自選股",
            str(context.watchlist_count) if context.watchlist_count is not None else "資料不足",
            "目前追蹤筆數",
            "info" if context.watchlist_count else "neutral",
        ),
        CompactStatistic(
            "今日實驗樣本",
            str(sample_count) if sample_count is not None else "資料不足",
            "唯讀評估樣本",
            "warning" if sample_count else "neutral",
        ),
    )


def render_home(st: Any, context: HomeContext) -> HomeAction | None:
    """Render the daily research entry point without calculating or fetching data."""

    brief = context.daily_brief
    _render_home_overview_header(st, context, brief)

    with st.container(border=False, key="home_command_panel"):
        render_ui_markup(
            st,
            '<div class="st-ui-command-panel">'
            + section_header_markup(
                eyebrow="研究指令",
                title="研究一家公司",
                description="選擇市場與代號後進入研究；更新資料只會在你明確操作時執行。",
            )
            + "</div>",
        )
        preparation = render_global_search(
            st,
            key_prefix="home",
            disabled=context.status is DashboardStatus.LOADING,
            default_symbol=context.active_symbol or "",
            submit_label="研究一家公司",
        )
        if st.button(
            "執行今日研究",
            key="home_run_daily_research",
            type="primary",
            disabled=context.status is DashboardStatus.LOADING,
        ):
            return HomeAction(kind="daily_research_run")
        if st.button(
            "更新今日資料",
            key="home_refresh_today",
            disabled=context.status is DashboardStatus.LOADING,
        ):
            return HomeAction(kind="refresh")
        render_ui_markup(
            st,
            statistic_group_markup(
                title="研究狀態摘要",
                statistics=_home_summary_statistics(context),
                variant="summary",
            ),
        )
        if context.source_label:
            st.caption(
                f"目前來源：{context.source_label}｜更新資訊：{context.updated_at or '資料不足'}"
            )
    if preparation is not None:
        return HomeAction(kind="search", preparation=preparation)

    _render_daily_research_run(st, context.daily_research_run)

    _render_daily_changes(st, context.daily_research_changes)

    lab_action = _render_prediction_lab(
        st,
        context.prediction_lab,
        evaluate_available=context.prediction_lab_evaluation_available,
    )
    if lab_action is not None:
        return lab_action

    macro_action = _render_macro_background(
        st,
        context.macro_snapshot,
        context.macro_signals,
        context.macro_links,
        context.macro_revisions,
    )
    if macro_action is not None:
        return macro_action

    evidence_action = _render_daily_evidence_brief(
        st,
        context.daily_evidence_brief,
        available=context.daily_evidence_available,
    )
    if evidence_action is not None:
        return evidence_action

    _render_daily_research_inbox(
        st,
        context.daily_research_inbox,
        context.daily_research_inbox_brief,
    )

    if brief is None:
        return _render_legacy_fallback(st, context)
    if brief.first_use:
        return _render_first_use(st, context)

    loop_state = _render_daily_research_loop(st, context.daily_research_loop)
    if loop_state.action is not None:
        return loop_state.action
    assistant_action = render_research_assistant(
        st,
        context.research_assistant_brief,
        can_generate=context.research_assistant_available,
    )
    if assistant_action is not None:
        return _home_action_from_assistant(assistant_action)
    action = _render_attention(
        st,
        brief.attention_items,
        suppressed_keys=loop_state.represented_keys,
    )
    if action is not None:
        return action
    action = _render_portfolio_pulse(
        st,
        brief,
        suppress_view_holdings="view_holdings" in loop_state.represented_actions,
        suppressed_keys=loop_state.represented_keys,
    )
    if action is not None:
        return action
    action = _render_watchlist_pulse(st, brief)
    if action is not None:
        return action
    action = _render_continuations(st, brief.continuations)
    if action is not None:
        return action
    action = _render_action_required(
        st,
        brief.action_required,
        suppressed_keys=loop_state.represented_keys,
    )
    if action is not None:
        return action

    for warning in context.summary_warnings:
        st.info(warning)
    st.warning("本工具僅供研究、學習與風險分析；不構成個人化投資建議。")
    return None


def _render_prediction_lab(
    st: Any,
    summary: PredictionLabSummary | None,
    *,
    evaluate_available: bool = False,
) -> HomeAction | None:
    """Render the read-only Phase 0 experiment without implying a forecast."""

    with st.container(border=False, key="home_prediction_lab"):
        render_ui_markup(
            st,
            '<div class="st-ui-prediction-lab">'
            + section_header_markup(
                eyebrow="唯讀實驗",
                title="預測評估實驗室（實驗）",
                description="用既有盤後樣本檢查研究規則；不是投資建議，也不產生買賣訊號。",
            )
            + "</div>",
        )
        if summary is None or summary.status == "unavailable":
            render_ui_markup(
                st,
                state_panel_markup(
                    tone="info",
                    title="尚無可驗證樣本",
                    message="資料不足時不會建立樣本，也不會顯示假績效。",
                    next_step="先更新盤後研究資料，再回來查看樣本登錄狀態。",
                ),
            )
            return None
        render_ui_markup(
            st,
            state_panel_markup(
                tone="success" if summary.status == "ready" else "warning",
                title="實驗狀態",
                message=summary.message,
                next_step=(
                    f"最近交易日：{summary.last_trading_date}"
                    if summary.last_trading_date
                    else "最近交易日資料不足"
                ),
            ),
        )
        render_ui_markup(
            st,
            statistic_group_markup(
                title="樣本進度",
                statistics=(
                    CompactStatistic(
                        "今日登錄", str(summary.registered_today), "本次新增", "success"
                    ),
                    CompactStatistic(
                        "累積樣本", str(summary.prediction_count), "不可變研究紀錄", "info"
                    ),
                ),
                variant="primary",
            ),
        )
        render_ui_markup(
            st,
            '<div class="st-ui-prediction-buckets">'
            + statistic_group_markup(
                title="分桶分布",
                statistics=(
                    CompactStatistic("Top", str(summary.bucket_counts.get("top", 0)), "相對高分桶"),
                    CompactStatistic(
                        "Middle", str(summary.bucket_counts.get("middle", 0)), "中間樣本桶"
                    ),
                    CompactStatistic(
                        "Bottom", str(summary.bucket_counts.get("bottom", 0)), "相對低分桶"
                    ),
                ),
                variant="buckets",
            )
            + "</div>",
        )
        render_ui_markup(st, outcome_matrix_markup(summary.outcome_counts))
        if evaluate_available and st.button(
            "更新到期結果",
            key="home_evaluate_prediction_outcomes",
            help="只使用已載入的本機價格與來源證據；不會在畫面 render 時連線。",
        ):
            return HomeAction(kind="prediction_outcome_evaluation")
        if summary.evaluated_count:

            def _pct(value: object) -> str:
                if value is None or not isinstance(value, (int, float)):
                    return "尚無"
                return f"{float(value) * 100:+.2f}%"

            render_ui_markup(
                st,
                statistic_group_markup(
                    title="可信結算摘要",
                    statistics=(
                        CompactStatistic(
                            "5 日覆蓋率",
                            f"{summary.coverage_by_horizon.get('5', 0.0) * 100:.0f}%",
                            "已到期且證據完整",
                            "success",
                        ),
                        CompactStatistic(
                            "20 日覆蓋率",
                            f"{summary.coverage_by_horizon.get('20', 0.0) * 100:.0f}%",
                            "已到期且證據完整",
                            "success",
                        ),
                        CompactStatistic(
                            "中位淨報酬",
                            _pct(summary.median_net_return),
                            "歷史樣本，不是預測",
                            "info",
                        ),
                        CompactStatistic(
                            "中位超額",
                            _pct(summary.median_net_excess_return),
                            "相對基準的歷史差異",
                            "info",
                        ),
                    ),
                    variant="summary",
                ),
            )
            if summary.top_bottom_spread is not None:
                st.caption(
                    f"Top／Bottom 歷史中位淨報酬差：{summary.top_bottom_spread * 100:+.2f}%；"
                    "僅供研究驗證，不代表未來表現。"
                )
            bucket_statistics: list[CompactStatistic] = []
            for bucket in ("top", "middle", "bottom"):
                metrics = summary.bucket_metrics.get(bucket, {})
                label = {"top": "Top", "middle": "Middle", "bottom": "Bottom"}[bucket]
                bucket_statistics.extend(
                    (
                        CompactStatistic(
                            f"{label} 淨報酬",
                            _pct(metrics.get("median_net_return")),
                            "已結算樣本中位數",
                            "info",
                        ),
                        CompactStatistic(
                            f"{label} 超額",
                            _pct(metrics.get("median_net_excess_return")),
                            "相對基準中位數",
                            "info",
                        ),
                    )
                )
            render_ui_markup(
                st,
                statistic_group_markup(
                    title="各分桶結算摘要",
                    statistics=tuple(bucket_statistics),
                    variant="summary",
                ),
            )
        for warning in summary.warnings:
            st.warning(warning)
        if summary.limitations:
            expander = getattr(st, "expander", None)
            if callable(expander):
                with expander("實驗限制與資料說明"):
                    for limitation in summary.limitations:
                        st.caption(limitation)
            else:
                for limitation in summary.limitations:
                    st.caption(limitation)
        return None


def _render_daily_research_run(st: Any, manifest: DailyResearchRunManifest | None) -> None:
    """Show the latest one-click run without exposing implementation details."""

    if manifest is None:
        return
    st.subheader("今日研究執行狀態")
    status_labels = {
        "success": "完成",
        "partial": "部分完成",
        "failed": "未完成",
        "already_running": "已有執行中流程",
    }
    st.caption(
        f"最近一次：{manifest.completed_at}｜狀態：{status_labels.get(manifest.status, '已略過')}"
    )
    stage_labels = {
        "target_refresh": "研究標的",
        "market_refresh": "市場資料",
        "brief": "研究簡報",
        "change": "變化摘要",
        "prediction_registration": "實驗樣本",
        "prediction_outcome_evaluation": "到期結算",
        "notification": "通知",
    }

    def user_reason(stage_name: str, status: str) -> str:
        """Translate provider/engine diagnostics into short user guidance.

        The raw reason remains in the run manifest/evidence; the home page only
        exposes a stable, non-technical next step so provider details cannot
        leak into the primary workflow.
        """

        if stage_name == "market_refresh":
            return "部分市場資料暫時無法更新，已保留上一份成功結果。"
        if stage_name == "brief":
            return "研究簡報未完成，上一份成功結果仍可使用。"
        if stage_name == "change":
            return "變化摘要未完成，上一份成功摘要仍可使用。"
        if stage_name == "prediction_registration":
            return "市場資料未達完整條件，本次不建立實驗樣本。"
        if stage_name == "notification":
            return "研究成果已保留；通知目前不可用。"
        if stage_name == "target_refresh":
            return "研究標的資料未完成更新，請確認來源後再試。"
        return "此階段未完成，請稍後再試。"

    for stage in manifest.stages:
        labels = {
            "success": "完成",
            "partial": "部分可用",
            "skipped": "略過",
            "unavailable": "不可用",
            "failure": "失敗",
        }
        st.write(f"{stage_labels.get(stage.name, stage.name)}：{labels[stage.status]}")
        if stage.reason and stage.status not in {"success", "skipped"}:
            st.caption(user_reason(stage.name, stage.status))
    if manifest.status != "success":
        st.info("未完成的階段不會建立新的實驗樣本；可確認資料後再次執行。")


def _render_macro_background(
    st: Any,
    snapshot: MacroSnapshot | None,
    signals: tuple[MacroSignal, ...],
    links: tuple[dict[str, object], ...] = (),
    revisions: tuple[dict[str, object], ...] = (),
) -> HomeAction | None:
    """Render validated macro context without triggering network activity."""

    st.subheader("今日總經背景")
    st.caption("僅呈現官方資料與可重播規則結果，不是即時行情、預測或投資建議。")
    if snapshot is None:
        st.info("尚未載入總經背景；按下更新後才會取得官方資料。")
    else:
        labels = {
            "ready": "可用",
            "partial": "部分資料",
            "stale": "沿用過期快照",
            "unavailable": "目前不可用",
        }
        latest_period = max(
            (signal.observation_period for signal in signals if signal.observation_period),
            default=snapshot.as_of_date,
        )
        st.caption(
            f"各指標資料期間不同；最新一項截至 {latest_period or '無資料'}｜"
            f"狀態：{labels.get(snapshot.status, '資料不足')}｜來源：{snapshot.source}"
        )
        if snapshot.status in {"stale", "partial", "unavailable"}:
            st.warning("官方總經資料不完整或過期；以下內容僅供研究脈絡參考。")
        for signal in signals[:3]:
            current = "無資料" if signal.current_value is None else f"{signal.current_value:g}"
            delta = "無資料" if signal.delta is None else f"{signal.delta:+g}"
            st.write(
                f"{signal.title}｜{signal.status}｜目前 {current}｜變化 {delta}｜"
                f"下一條件：{signal.next_condition}"
            )
            st.caption(
                f"資料期間：{signal.observation_period or '無資料'}｜"
                f"觀測日：{signal.observed_date or '無資料'}｜"
                f"取得時間：{signal.fetched_at or '無資料'}｜"
                f"發布日：{signal.release_date or '未提供'}"
            )
            if signal.limitations:
                st.caption("限制：" + "、".join(signal.limitations))
        if revisions:
            st.caption("重要修訂")
            for revision in revisions[:5]:
                st.write(
                    f"{revision.get('series_id')}／{revision.get('observation_period')}："
                    f"{revision.get('first_seen_value')} → {revision.get('latest_value')}"
                )
        if links:
            st.caption("持股／自選股總經關聯")
            for link in links:
                identity = link.get("identity", "未知身分")
                classification = link.get("sector") or link.get("industry") or "尚無可驗證對應"
                st.write(
                    f"{identity}｜分類：{classification}｜規則：{link.get('rule_version', '未知')}"
                )
                st.caption(str(link.get("macro_relation_message", "尚無可驗證總經關聯")))
        if snapshot.warnings:
            for warning in snapshot.warnings[:3]:
                st.warning(warning)
    if st.button("更新總經資料", key="home_refresh_macro"):
        return HomeAction(kind="macro_refresh")
    return None


def _render_daily_changes(st: Any, summary: DailyResearchChangeSet | None) -> None:
    """Render the deterministic change projection without refreshing data."""

    st.subheader("今天的重點變化")
    if summary is None:
        st.info("尚未有可驗證的前後研究簡報；請在資料更新後產生簡報。")
        return
    status_labels = {
        "baseline": "已建立基準",
        "updated": "有新的可驗證變化",
        "no_change": "沒有重大變化",
        "insufficient": "資料不足",
        "unavailable": "目前無法取得",
    }
    st.caption(
        f"{status_labels.get(summary.status, '狀態未知')}；目前簡報 {summary.current_brief_fingerprint[:12]}"
    )
    for index, change in enumerate(summary.changes):
        with st.expander(f"{change.title}｜{change.identity}｜優先級 {change.priority}"):
            st.write(change.description)
            st.write(f"原因：{change.reason}")
            if change.current_value:
                st.write(f"目前：{'；'.join(change.current_value[:3])}")
            if change.previous_value:
                st.write(f"先前：{'；'.join(change.previous_value[:3])}")
            st.caption(
                f"資料截至：{change.current_data_as_of or '無資料'}；"
                f"引用：{', '.join(change.reference_ids) if change.reference_ids else '無'}"
            )
            if change.ai_allowed:
                st.caption("可由既有 AI 協助改寫，但不得新增未引用事實。")
    for warning in summary.warnings:
        st.warning(warning)


def _render_daily_research_inbox(
    st: Any,
    entries: tuple[ResearchInboxEntry, ...],
    latest_brief: DailyResearchBrief | None,
) -> None:
    """Render the read-only scheduler history without exposing local paths."""

    st.subheader("每日研究收件匣")
    if not entries:
        st.info("尚無每日研究執行紀錄；排程或手動執行後會顯示在這裡。")
        return
    for index, entry in enumerate(entries):
        label = f"{entry.completed_at} · {entry.status}"
        expander = getattr(st, "expander", None)
        context = expander(label) if callable(expander) else None
        if context is None:
            st.write(label)
            target = st
        else:
            target = context
        with context if context is not None else _null_context():
            target.write(f"資料來源：{entry.source_mode}")
            target.write(f"原因：{entry.reason}")
            target.write(f"下一步：{entry.next_step}")
            if (
                entry.brief_available
                and latest_brief is not None
                and entry.brief_fingerprint == latest_brief.manifest.content_fingerprint
            ):
                download = getattr(target, "download_button", None)
                if callable(download):
                    download(
                        "開啟已驗證 JSON 簡報",
                        data=json.dumps(
                            latest_brief.to_dict(), ensure_ascii=False, sort_keys=True, indent=2
                        ),
                        file_name="daily-research-brief.json",
                        mime="application/json",
                        key=f"home_inbox_json_{index}",
                    )
                    download(
                        "開啟已驗證 HTML 簡報",
                        data=render_daily_brief_html(latest_brief),
                        file_name="daily-research-brief.html",
                        mime="text/html",
                        key=f"home_inbox_html_{index}",
                    )


class _null_context:
    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _render_daily_evidence_brief(
    st: Any,
    brief: DailyResearchBrief | None,
    *,
    available: bool,
) -> HomeAction | None:
    """Render the explicit evidence-chain brief action and latest safe result."""

    st.subheader("每日證據鏈研究簡報")
    st.caption("只整理已有資料與來源；不預測股價、不提供買賣指令，也不會自動刷新。")
    if brief is None:
        st.info("尚未產生今日研究簡報；按下按鈕後才會整理目前本機證據。")
    else:
        st.caption(
            f"狀態：{brief.status}；簡報日期：{brief.manifest.brief_date}；"
            f"資料截至：{brief.manifest.as_of_date or '無資料'}；"
            f"處理標的：{brief.manifest.processed_count}"
        )
        st.write(brief.message)
        if brief.items:
            st.markdown("#### 今日關注變化")
            for item in brief.items:
                st.markdown(
                    f"**{item.identity}**｜優先級 {item.priority}｜{item.status}｜"
                    f"信心 {item.confidence}"
                )
                st.write(f"入選原因：{item.reason}")
                if item.facts:
                    st.caption("事實：" + "；".join(item.facts[:3]))
                if item.inferences:
                    st.caption("推論：" + "；".join(item.inferences[:3]))
                if item.risks:
                    st.warning("風險／資料缺口：" + "；".join(item.risks[:3]))
        else:
            st.info("目前沒有值得關注的變化，或尚無可用證據。")
        download = getattr(st, "download_button", None)
        if callable(download):
            download(
                "下載 JSON 證據",
                data=json.dumps(brief.to_dict(), ensure_ascii=False, sort_keys=True, indent=2),
                file_name="daily-research-brief.json",
                mime="application/json",
                key="home_daily_evidence_json",
            )
            download(
                "下載 HTML 報告",
                data=render_daily_brief_html(brief),
                file_name="daily-research-brief.html",
                mime="text/html",
                key="home_daily_evidence_html",
            )
    if available and st.button("產生今日研究簡報", key="home_generate_daily_evidence_brief"):
        return HomeAction(kind="daily_evidence_brief")
    if (
        brief is not None
        and available
        and st.button("重新產生今日研究簡報", key="home_regenerate_daily_evidence_brief")
    ):
        return HomeAction(kind="daily_evidence_brief", force_regenerate=True)
    return None


def _home_action_from_assistant(action: ResearchAssistantAction) -> HomeAction:
    """Adapt the assistant component's explicit action to existing home routing."""

    if action.kind == "generate":
        return HomeAction(kind="ai_research", force_regenerate=action.force_regenerate)
    if action.symbol is not None and action.market is not None:
        return HomeAction(
            kind="search",
            preparation=SearchPreparation(
                SearchRequest(symbol=action.symbol, market=action.market)
            ),
        )
    return HomeAction(kind="workspace", workspace="settings")


def _render_daily_research_loop(
    st: Any,
    result: DailyResearchLoopResult | None,
) -> _DailyLoopRenderState:
    """Render saved successful changes before the existing present-state Daily Brief."""

    if result is None:
        return _DailyLoopRenderState(None, frozenset(), frozenset())
    st.subheader("每日研究更新")
    if result.last_successful_at:
        st.caption(f"上次成功檢查：{result.last_successful_at}")
    if result.snapshot is not None:
        st.caption(f"上次成功資料截至：{result.snapshot.data_as_of_date or '資料不足'}")

    if result.status == "updated":
        st.success(result.message)
    elif result.status in {"baseline_created", "no_change", "previous_success"}:
        st.info(result.message)
    else:
        st.warning(result.message)
    if result.warning:
        st.warning(result.warning)

    priority_events, persistent_events, repair_events = _visible_loop_event_groups(result)
    represented = (*priority_events, *persistent_events, *repair_events)
    render_state = _DailyLoopRenderState(
        action=None,
        represented_keys=frozenset(item.display_key for item in represented),
        represented_actions=frozenset(item.action for item in represented),
    )
    rendered_actions: set[str] = set()
    action = _render_loop_events(
        st,
        "今日優先變化",
        priority_events,
        key_prefix="priority",
        rendered_actions=rendered_actions,
    )
    if action is not None:
        return _DailyLoopRenderState(
            action, render_state.represented_keys, render_state.represented_actions
        )
    action = _render_loop_events(
        st,
        "持續存在的狀態",
        persistent_events,
        key_prefix="persistent",
        rendered_actions=rendered_actions,
    )
    if action is not None:
        return _DailyLoopRenderState(
            action, render_state.represented_keys, render_state.represented_actions
        )
    action = _render_loop_events(
        st,
        "待修復的資料問題",
        repair_events,
        key_prefix="repair",
        rendered_actions=rendered_actions,
    )
    if action is not None:
        return _DailyLoopRenderState(
            action, render_state.represented_keys, render_state.represented_actions
        )
    return render_state


def _visible_loop_event_groups(
    result: DailyResearchLoopResult,
) -> tuple[
    tuple[DailyResearchEvent, ...],
    tuple[DailyResearchEvent, ...],
    tuple[DailyResearchEvent, ...],
]:
    """Keep each visible Daily Loop event identity in one section and one CTA."""

    seen: set[str] = set()

    def unique(events: tuple[DailyResearchEvent, ...]) -> tuple[DailyResearchEvent, ...]:
        rows: list[DailyResearchEvent] = []
        for event in events:
            if event.display_key in seen:
                continue
            seen.add(event.display_key)
            rows.append(event)
        return tuple(rows)

    return (
        unique(result.priority_events),
        unique(result.persistent_events),
        unique(result.repair_events),
    )


def _render_loop_events(
    st: Any,
    heading: str,
    events: tuple[DailyResearchEvent, ...],
    *,
    key_prefix: str,
    rendered_actions: set[str],
) -> HomeAction | None:
    """Render deterministic evidence cards without turning them into advice."""

    if not events:
        return None
    st.markdown(f"#### {heading}")
    for index, event in enumerate(events):
        with st.container(border=True):
            st.markdown(f"**{event.title}**")
            st.write(event.why_important)
            st.caption(f"目前值：{event.current_value}")
            if event.baseline_value:
                st.caption(f"比較基準：{event.baseline_value}")
            st.caption(f"資料來源：{event.source.label}")
            st.caption(
                "資料截至："
                f"{event.as_of_date or event.source.last_data_date or '資料不足'}；"
                f"更新檢查：{event.source.checked_at or '資料不足'}"
            )
            if event.action not in rendered_actions:
                rendered_actions.add(event.action)
                if st.button(
                    _loop_action_label(event),
                    key=f"home_loop_{key_prefix}_{index}_{event.code}",
                    width="stretch",
                ):
                    return _action_for_loop_event(event)
    return None


def _loop_action_label(event: DailyResearchEvent) -> str:
    """Return a concrete CTA label for one Daily Research Loop event."""

    return {
        "open_research": "開啟研究",
        "update_data": "更新資料",
        "view_holdings": "查看持倉",
        "complete_data": "補齊資料",
    }[event.action]


def _action_for_loop_event(event: DailyResearchEvent) -> HomeAction:
    """Route an event only through existing search and workspace actions."""

    if event.action == "view_holdings":
        return HomeAction(
            kind="workspace",
            workspace="holdings",
            legacy_page="投資組合管理",
        )
    if event.identity:
        try:
            market, code = event.identity.split(":", maxsplit=1)
            symbol = Symbol.parse(code, market=market)
        except (ValueError, AttributeError):
            return HomeAction(kind="workspace", workspace="settings")
        return HomeAction(
            kind="search",
            preparation=SearchPreparation(
                SearchRequest(symbol=symbol.code, market=symbol.market.value)
            ),
        )
    return HomeAction(kind="workspace", workspace="settings")


def _render_first_use(st: Any, context: HomeContext) -> HomeAction | None:
    """Render a compact, actionable first-use state without empty portfolio tables."""

    st.subheader("從第一份研究開始")
    st.write("輸入代號與市場後，系統會整理可用價格、基本面、評分與資料來源。")
    st.caption("快速開始範例")
    examples = (("2330", "TWSE"), ("6488", "TPEX"), ("AAPL", "US"))
    columns = st.columns(3)
    for column, (symbol, market) in zip(columns, examples, strict=True):
        if column.button(f"研究 {symbol}", key=f"home_example_{symbol}", width="stretch"):
            return HomeAction(
                kind="search",
                preparation=SearchPreparation(SearchRequest(symbol=symbol, market=market)),
            )
    if context.recent_searches:
        st.caption("已保留最近搜尋，可在完成第一份研究後從「繼續研究」回到它。")
    if context.watchlist_count == 0 and context.portfolio_count == 0:
        st.info("尚未建立追蹤清單，可加入自選股或先建立持股。")
    return None


def _render_attention(
    st: Any,
    items: tuple[DailyBriefItem, ...],
    *,
    suppressed_keys: frozenset[str] = frozenset(),
) -> HomeAction | None:
    """Render bounded, evidence-backed attention items without raw tables."""

    visible_items = tuple(item for item in items if _item_display_key(item) not in suppressed_keys)
    if not visible_items:
        if items:
            return None
        st.subheader("今日關注")
        st.info("目前沒有可由本機資料支持的優先提醒。")
        return None
    st.subheader("今日關注")
    for index, item in enumerate(visible_items):
        with st.container(border=True):
            _render_item_status(st, item)
            if st.button(
                _item_action_label(item),
                key=f"home_attention_{index}_{item.code}",
                width="stretch",
            ):
                return _action_for_item(item)
    return None


def _render_portfolio_pulse(
    st: Any,
    brief: DailyBrief,
    *,
    suppress_view_holdings: bool = False,
    suppressed_keys: frozenset[str] = frozenset(),
) -> HomeAction | None:
    """Render the requested holdings snapshot from canonical valuation output only."""

    pulse = brief.portfolio
    st.subheader("持倉快照")
    if pulse.position_count == 0:
        st.info("尚未建立持股。可在「持倉」加入手動持股後，再查看資料覆蓋與集中度。")
        if st.button("前往持倉管理", key="home_empty_portfolio", width="stretch"):
            return HomeAction(
                kind="workspace",
                workspace="holdings",
                legacy_page="投資組合管理",
            )
        return None
    metrics = st.columns(5)
    metrics[0].metric("持股筆數", str(pulse.position_count))
    metrics[1].metric(
        "已有價格資料",
        _ratio(pulse.priced_position_count, pulse.position_count),
    )
    metrics[2].metric("最大單一權重", _percent(pulse.max_position_weight))
    metrics[3].metric("已知風險提醒", str(pulse.risk_alert_count))
    metrics[4].metric("價格覆蓋率", _percent(pulse.price_coverage))
    if (
        pulse.priority_issue is not None
        and _item_display_key(pulse.priority_issue) not in suppressed_keys
    ):
        st.caption(f"優先處理：{pulse.priority_issue.title}。{pulse.priority_issue.evidence}")
    if pulse.unavailable_reason is not None:
        st.info(f"資料不足：{pulse.unavailable_reason}")
    if not suppress_view_holdings and st.button(
        "查看持倉", key="home_view_holdings", width="stretch"
    ):
        return HomeAction(
            kind="workspace",
            workspace="holdings",
            legacy_page="投資組合管理",
        )
    return None


def _render_watchlist_pulse(st: Any, brief: DailyBrief) -> HomeAction | None:
    """Render watchlist movement or an actionable empty state."""

    pulse = brief.watchlist
    st.subheader("自選股動態")
    if pulse.item_count == 0:
        st.info("尚未建立自選股。研究股票後可加入追蹤。")
        if st.button("管理自選股", key="home_empty_watchlist", width="stretch"):
            return HomeAction(
                kind="workspace",
                workspace="explore",
                legacy_page="自選股清單",
            )
        return None
    metrics = st.columns(3)
    metrics[0].metric("自選股", str(pulse.item_count))
    metrics[1].metric("資料可能過期", str(pulse.stale_count))
    metrics[2].metric("尚未完成研究", str(pulse.unresearched_count))
    if pulse.largest_move is not None:
        with st.container(border=True):
            _render_item_status(st, pulse.largest_move)
            if st.button("開啟研究", key="home_watchlist_largest_move", width="stretch"):
                return _action_for_item(pulse.largest_move)
    if st.button("查看自選股", key="home_view_watchlist", width="stretch"):
        return HomeAction(
            kind="workspace",
            workspace="explore",
            legacy_page="自選股清單",
        )
    return None


def _render_continuations(
    st: Any,
    continuations: tuple[ResearchContinuation, ...],
) -> HomeAction | None:
    """Render recent research as cards, never as a selectbox or raw table."""

    st.subheader("繼續研究")
    if not continuations:
        st.info("尚無可繼續的研究。完成一份研究後會顯示在這裡。")
        return None
    columns = st.columns(min(3, len(continuations)))
    for index, item in enumerate(continuations):
        with columns[index % len(columns)].container(border=True):
            st.markdown(f"#### {item.symbol.code} · {item.symbol.market.value}")
            st.caption(f"上次研究：{_display_optional_text(item.researched_at)}")
            st.caption(f"資料截至：{_display_optional_text(item.data_as_of_date)}")
            st.caption(f"資料覆蓋率：{_percent(item.coverage)}")
            if st.button("開啟研究", key=f"home_continue_{index}", width="stretch"):
                return HomeAction(
                    kind="search",
                    preparation=SearchPreparation(
                        SearchRequest(symbol=item.symbol.code, market=item.symbol.market.value)
                    ),
                )
    return None


def _display_optional_text(value: object) -> str:
    """Render missing values without exposing Python's None sentinel."""

    if value is None:
        return "無資料"
    text = str(value).strip()
    return text if text and text.casefold() != "none" else "無資料"


def _render_action_required(
    st: Any,
    items: tuple[ActionRequired, ...],
    *,
    suppressed_keys: frozenset[str] = frozenset(),
) -> HomeAction | None:
    """Show repairable issues with user-facing actions and no provider internals."""

    visible_items = tuple(
        item for item in items if _required_display_key(item) not in suppressed_keys
    )
    if not visible_items:
        if items:
            return None
        st.subheader("待處理事項")
        st.info("目前沒有待處理的資料修復事項。")
        return None
    st.subheader("待處理事項")
    for index, item in enumerate(visible_items):
        with st.container(border=True):
            st.markdown(f"#### {item.title}")
            st.write(item.detail)
            st.caption(f"資料日期：{item.as_of_date or '資料不足'}")
            if st.button(
                _required_action_label(item),
                key=f"home_required_{index}_{item.field}",
                width="stretch",
            ):
                if item.action == "view_holdings":
                    return HomeAction(
                        kind="workspace",
                        workspace="holdings",
                        legacy_page="投資組合管理",
                    )
                if item.symbol is not None:
                    return HomeAction(
                        kind="search",
                        preparation=SearchPreparation(
                            SearchRequest(
                                symbol=item.symbol.code,
                                market=item.symbol.market.value,
                            )
                        ),
                    )
                return HomeAction(kind="workspace", workspace="settings")
    return None


def _render_item_status(st: Any, item: DailyBriefItem) -> None:
    """Present severity with explicit text as well as the standard status surface."""

    labels = {"attention": "注意", "warning": "警示", "info": "資訊"}
    renderers = {"attention": st.warning, "warning": st.warning, "info": st.info}
    renderer = renderers[item.severity]
    renderer(f"[{labels[item.severity]}] {item.title}")
    st.write(item.detail)
    st.caption(f"依據：{item.evidence}")
    st.caption(f"資料日期：{item.as_of_date or '資料不足'}")


def _action_for_item(item: DailyBriefItem) -> HomeAction:
    """Map one evidence item to its explicit next step."""

    if item.action == "view_holdings":
        return HomeAction(kind="workspace", workspace="holdings")
    if item.symbol is None:
        return HomeAction(kind="workspace", workspace="settings")
    return HomeAction(
        kind="search",
        preparation=SearchPreparation(
            SearchRequest(symbol=item.symbol.code, market=item.symbol.market.value)
        ),
    )


def _item_display_key(item: DailyBriefItem) -> str:
    """Return the same structured display identity used by Daily Research Loop events."""

    identity = item.symbol.canonical if item.symbol is not None else None
    field = item.field or item.code
    return json.dumps(
        {"identity": identity, "action": item.action, "field": field},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _required_display_key(item: ActionRequired) -> str:
    """Return a structured remediation identity without parsing user-visible text."""

    identity = item.symbol.canonical if item.symbol is not None else None
    return json.dumps(
        {"identity": identity, "action": item.action, "field": item.field},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _item_action_label(item: DailyBriefItem) -> str:
    """Return a literal action label instead of a generic card control."""

    return {
        "open_research": "開啟研究",
        "update_data": "更新資料",
        "view_holdings": "查看持倉",
        "complete_data": "補齊資料",
    }[item.action]


def _required_action_label(item: ActionRequired) -> str:
    """Return the matching remediation label for one missing-data item."""

    return {
        "open_research": "開啟研究",
        "update_data": "更新資料",
        "view_holdings": "查看持倉",
        "complete_data": "補齊資料",
    }[item.action]


def _render_legacy_fallback(st: Any, context: HomeContext) -> HomeAction | None:
    """Keep the prior small summary available when no Daily Brief was supplied."""

    st.subheader("研究摘要")
    metrics = st.columns(3)
    metrics[0].metric(
        "自選股", context.watchlist_count if context.watchlist_count is not None else "資料不足"
    )
    metrics[1].metric(
        "持股筆數", context.portfolio_count if context.portfolio_count is not None else "資料不足"
    )
    metrics[2].metric("目前標的", context.active_symbol or "尚未選擇")
    if context.source_label:
        st.caption(
            f"目前資料來源：{context.source_label}；更新資訊：{context.updated_at or '資料不足'}"
        )
    for warning in context.summary_warnings:
        st.info(warning)
    return None


def _percent(value: float | None) -> str:
    """Format an optional ratio without turning unavailable data into zero."""

    return "資料不足" if value is None else f"{value:.1%}"


def _ratio(numerator: int, denominator: int) -> str:
    """Format a count ratio without hidden assumptions."""

    return "資料不足" if denominator <= 0 else f"{numerator}/{denominator}"
