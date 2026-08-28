"""Evidence-first concept discovery renderer for the existing Explore workspace."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

from stock_tool.concept_repository import (
    RELATION_TYPE_LABELS,
    ConceptRepository,
    confidence_label,
    seed_bundled_dataset,
)
from stock_tool.data.repositories import RepositoryDataError
from stock_tool.application.explore import ExploreApplicationService, ExploreResult
from stock_tool.application.market_monitor import (
    MarketMonitorApplicationService,
    MarketRefreshResult,
    build_industry_heat,
    build_rankings,
    compute_breadth,
)
from stock_tool.domain.models import Symbol


def render_discovery(st: Any, repository: ConceptRepository) -> None:
    """Render canonical concept relations without fuzzy candidate expansion."""

    seeded = seed_bundled_dataset(repository)
    if seeded is not None:
        st.caption("已載入內建題材種子資料。所有關係均標示為人工種子，需補來源後才可視為已驗證。")
    st.subheader("題材證據探索")
    query = st.text_input("題材", key="canonical_concept_query")
    if not query:
        st.caption("輸入資料集中定義的題材或別名；不使用模糊文字比對補滿清單。")
        return
    concept_key = repository.resolve_concept_key(query)
    if concept_key is None:
        st.info("無可信結果：沒有找到可驗證的題材關係。")
        return
    try:
        concept = repository.concept(concept_key)
        relations = repository.relations_for(concept_key)
    except RepositoryDataError:
        st.info("資料不足：目前無法讀取可驗證的題材關係。")
        return
    st.markdown(f"#### {concept.display_name}")
    st.caption(concept.description)
    groups: dict[str, list[Any]] = defaultdict(list)
    for relation in relations:
        groups[relation.relation_type].append(relation)
    for relation_type, label in RELATION_TYPE_LABELS.items():
        if not groups.get(relation_type):
            continue
        st.markdown(f"**{label}**")
        for relation in groups[relation_type]:
            status = (
                "人工種子資料"
                if relation.is_manual_seed
                else ("資料已過期" if relation.is_stale else "已提供來源")
            )
            st.markdown(
                f"- `{relation.identity.symbol} / {relation.identity.market}` · {confidence_label(relation.confidence)}信心 · {status}"
            )
            st.caption(
                f"{relation.evidence or '資料不足'} | 驗證日期：{relation.verified_at or '尚未驗證'}"
            )
            if relation.source_url:
                st.link_button(f"來源：{relation.source_name}", relation.source_url)
            else:
                st.caption("來源：資料不足")


def render_explore_workspace(
    st: Any,
    service: ExploreApplicationService,
    *,
    on_research: Callable[[Symbol], None],
    market_service: MarketMonitorApplicationService | None = None,
) -> None:
    """Render the usable Explore entry without duplicating domain decisions in UI."""

    st.subheader("探索研究入口")
    st.caption("使用目前本機索引尋找標的；結果只供研究整理，不代表推薦、評級或買賣建議。")
    query = st.text_input(
        "股票代號、公司名稱或題材",
        key="explore_query",
        help="可輸入 2330、台積電、半導體或既有題材關鍵字。",
    )
    markets = st.multiselect(
        "市場篩選",
        options=["TWSE", "TPEX", "US"],
        default=["TWSE", "TPEX", "US"],
        format_func=lambda value: {
            "TWSE": "台股上市",
            "TPEX": "台股上櫃",
            "US": "美股",
        }.get(value, value),
        key="explore_markets",
    )
    if market_service is not None:
        _render_market_overview(st, market_service, on_research=on_research)
    if st.button("搜尋探索", key="explore_search", type="primary"):
        st.session_state["explore_result"] = service.search(query, markets=markets)
    result = st.session_state.get("explore_result")
    if not isinstance(result, ExploreResult):
        st.info("尚未搜尋。輸入條件後按「搜尋探索」，查看目前索引中可核對的結果。")
        return
    _render_explore_result(st, service, result, on_research=on_research)


def _market_warning_label(warning: str) -> str:
    """Translate internal market-monitor warnings for the user-facing panel."""

    text = str(warning)
    lower = text.lower()
    if "official breadth date" in lower and "derived only" in lower:
        return "官方廣度日期過期，目前僅為自行推導"
    if "official breadth mismatch" in lower:
        return "官方廣度與自行推導數字不一致。"
    if "breadth is derived only" in lower or "official breadth date missing" in lower:
        return "目前僅為自行推導，沒有可核對的官方廣度。"
    if "official breadth unavailable or malformed" in lower:
        return "官方廣度資料無法解析，目前僅為自行推導。"
    if "source data dates differ" in lower:
        return "來源資料日期不同，合併檢視保留日期落差。"
    if "universe unavailable" in lower:
        return "官方股票清單不可用，已拒絕將商品計入股票統計。"
    if "excluded non-stock" in lower:
        return "已排除非股票商品。"
    if "excluded invalid close" in lower:
        return "已排除無效收盤價。"
    return text


def _render_market_overview(
    st: Any,
    service: MarketMonitorApplicationService,
    *,
    on_research: Callable[[Symbol], None],
) -> None:
    """Render the explicit-update official post-market monitor in Explore."""

    st.subheader("市場總覽")
    st.caption("盤後研究資料，不是即時行情、預測或投資建議。")
    st.caption(
        "股票 universe 規則：只納入官方公司清單中的四碼普通股；ETF、權證、債券及其他商品排除。"
    )
    if st.button("更新盤後市場資料", key="market_monitor_refresh", type="secondary"):
        try:
            result = service.refresh()
        except Exception:
            result = MarketRefreshResult(
                status="unavailable",
                source_state="missing",
                snapshot=None,
                warnings=("官方盤後資料更新失敗；請稍後重試。",),
            )
        st.session_state["market_monitor_result"] = result
    stored = st.session_state.get("market_monitor_result")
    result = stored if isinstance(stored, MarketRefreshResult) else service.load_cached()
    if result.snapshot is None:
        st.info("尚未取得可靠的盤後資料。按下更新按鈕後才會連線官方來源。")
        for warning in result.warnings:
            st.warning(warning)
        return
    snapshot = result.snapshot
    metadata = snapshot.metadata
    source_dates = (
        "；".join(
            f"{source.market}：{source.data_date or '無資料'}"
            for source in snapshot.source_metadata
        )
        or f"{metadata.market}：{metadata.data_date or '無資料'}"
    )
    st.caption(
        f"來源：{metadata.source}；各來源資料日期：{source_dates}；"
        f"更新時間：{metadata.fetched_at}；狀態：{_market_status_label(result.status)}；"
        f"涵蓋率：{metadata.coverage:.2%}"
    )
    warnings = tuple(dict.fromkeys(result.warnings + snapshot.warnings))
    if warnings:
        st.info(f"資料驗證摘要：{len(warnings)} 項警告；可展開查看細節。")
        expander = getattr(st, "expander", None)
        if callable(expander):
            with expander("查看資料驗證細節"):
                for warning in warnings:
                    warning = _market_warning_label(warning)
                    st.caption(f"・{warning}")
        else:
            st.caption("；".join(warnings))
    view = st.selectbox(
        "市場檢視",
        options=("TWSE", "TPEX", "COMBINED"),
        format_func=lambda value: {"TWSE": "台股上市", "TPEX": "台股上櫃", "COMBINED": "合併"}.get(
            value, value
        ),
        key="market_monitor_view",
    )
    rows = tuple(row for row in snapshot.quotes if view == "COMBINED" or row.market == view)
    selected_sources = tuple(
        source for source in snapshot.source_metadata if view == "COMBINED" or source.market == view
    )
    for source in selected_sources:
        breadth_label = {
            "compared": "已與官方數字比對",
            "official_stale": "官方廣度日期過期，目前僅為自行推導",
            "derived_only": "僅為自行推導",
        }.get(source.breadth_status, "僅為自行推導")
        st.caption(
            f"{source.market} 股票 universe：普通股 {source.included_common_stock}；"
            f"排除非股票商品 {source.excluded_non_stock}；"
            f"廣度：{breadth_label}"
        )
    breadth = snapshot.breadth if view == "COMBINED" else compute_breadth(rows)
    st.write(
        f"上漲 {breadth.up}（{breadth.up_ratio:.2%}）／"
        f"下跌 {breadth.down}（{breadth.down_ratio:.2%}）／"
        f"平盤 {breadth.flat}（{breadth.flat_ratio:.2%}）／"
        f"無法判斷 {breadth.unknown}；有效股票 {breadth.valid_total}"
    )
    labels = {
        "gainers": "漲幅排行",
        "losers": "跌幅排行",
        "volume": "成交量排行",
        "value": "成交額排行",
    }
    view_rankings = build_rankings(rows)
    for category, label in labels.items():
        entries = tuple(entry for entry in view_rankings if entry.category == category)
        if not entries:
            continue
        st.markdown(f"#### {label}")
        for entry in entries:
            columns = st.columns((3, 2))
            with columns[0]:
                st.write(
                    f"{entry.rank}. {entry.symbol} / {entry.market} "
                    f"{entry.name or '資料不足'}：{entry.value:g}"
                )
            with columns[1]:
                if st.button(
                    "研究此標的",
                    key=f"market_monitor_research_{category}_{entry.market}_{entry.symbol}",
                ):
                    try:
                        on_research(Symbol.parse(entry.symbol, market=entry.market))
                    except ValueError:
                        st.error("標的市場身分無法確認，已拒絕研究接力。")
    if snapshot.industry_heat:
        st.markdown("#### 產業熱度（已分類股票子集合）")
        industry_rows = build_industry_heat(rows)
        for row in industry_rows:
            average = (
                "無資料" if row.average_change_pct is None else f"{row.average_change_pct:.2f}%"
            )
            st.write(
                f"{row.industry}：成分 {row.total_components}、有效 {row.valid_samples}、"
                f"涵蓋率 {row.coverage:.2%}、等權平均 {average}；"
                f"上漲 {row.up}/下跌 {row.down}/平盤 {row.flat}"
            )


def _market_status_label(status: str) -> str:
    return {
        "fresh": "最新官方快照",
        "stale": "離線快取（已過期）",
        "partial": "部分資料",
        "unavailable": "無法取得",
    }.get(status, "資料不足")


def _render_explore_result(
    st: Any,
    service: ExploreApplicationService,
    result: ExploreResult,
    *,
    on_research: Callable[[Symbol], None],
) -> None:
    """Render one result set with explicit freshness/source and safe actions."""

    if result.source:
        updated = result.updated_at or "無資料"
        time_label = "索引檔更新時間" if result.source_state == "local_index" else "更新時間"
        st.caption(
            f"資料來源：{result.source}；{time_label}：{updated}；"
            f"狀態：{_status_label(result.status)}；來源模式：{_source_state_label(result.source_state)}"
        )
    for warning in result.warnings:
        st.warning(warning)
    if result.matches.empty:
        if result.status == "no_results":
            st.info("沒有符合條件的結果。請換用代號、公司名稱或題材；目前不會補造資料。")
        return
    st.success(f"找到 {len(result.matches)} 筆可核對結果。排序依相關性、市場與代號固定排列。")
    for index, row in result.matches.iterrows():
        symbol = str(row.get("symbol", "")).strip()
        market = str(row.get("market", "")).strip()
        name = str(row.get("name", "")).strip() or "資料不足"
        with st.container(border=True):
            st.markdown(f"#### {symbol or '資料不足'} · {name}")
            st.caption(
                f"市場：{row.get('market_label') or market or '資料不足'}；"
                f"出現原因：{row.get('match_reason') or '資料不足'}"
            )
            st.caption(
                f"來源：{row.get('source') or '資料不足'}；"
                f"狀態：{_status_label(str(row.get('display_status') or result.status))}；"
                f"來源模式：{_source_state_label(result.source_state)}；"
                f"索引檔更新時間：{result.updated_at or '無資料'}"
            )
            if row.get("note"):
                st.caption(str(row["note"]))
            action_columns = st.columns(2)
            try:
                in_watchlist = service.is_in_watchlist(symbol, market)
            except ValueError:
                in_watchlist = False
            with action_columns[0]:
                if st.button(
                    "以此代號研究目前資料",
                    key=f"explore_research_{market}_{symbol}_{index}",
                    disabled=not symbol or not market,
                ):
                    try:
                        on_research(service.canonical_symbol(symbol, market))
                    except ValueError:
                        st.error("此結果的市場或代號無法辨識，請重新搜尋。")
            with action_columns[1]:
                if st.button(
                    "移除自選股" if in_watchlist else "加入自選股",
                    key=f"explore_watchlist_{market}_{symbol}_{index}",
                    disabled=not symbol or not market,
                ):
                    try:
                        if in_watchlist:
                            service.remove_from_watchlist(symbol, market)
                        else:
                            service.add_to_watchlist(
                                symbol,
                                market,
                                note=f"探索：{row.get('match_reason') or '索引相符'}",
                            )
                    except ValueError:
                        st.error("此結果的市場或代號無法更新自選股。")
                    else:
                        st.session_state.watchlist = service.current_watchlist()
                        action = "移除" if in_watchlist else "加入"
                        st.success(f"已{action}自選股：{symbol}（{market}）。")
                        rerun = getattr(st, "rerun", None)
                        if callable(rerun):
                            rerun()


def _status_label(status: str) -> str:
    return {
        "initial": "尚未搜尋",
        "no_results": "無結果",
        "fresh": "最新",
        "stale": "可能過期",
        "partial": "部分資料",
        "missing": "資料不足",
        "offline": "離線／本機資料",
    }.get(status, "資料不足")


def _source_state_label(state: str) -> str:
    return {
        "offline_cache": "離線／本機快取",
        "local_index": "本機索引",
        "missing": "資料不足",
        "provider": "線上來源",
    }.get(state, "資料不足")
