"""Deterministic, UI-independent daily research summaries and refresh batching."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

import pandas as pd

from stock_tool.domain.models import Market, Symbol
from stock_tool.portfolio_valuation import PortfolioValuationResult

DailySeverity = Literal["attention", "warning", "info"]
DailyAction = Literal["open_research", "update_data", "view_holdings", "complete_data"]


@dataclass(frozen=True, slots=True)
class DailyBriefItem:
    """One evidence-backed, non-advisory research item for the home screen."""

    code: str
    severity: DailySeverity
    title: str
    detail: str
    evidence: str
    as_of_date: str | None
    action: DailyAction
    symbol: Symbol | None = None
    field: str | None = None


@dataclass(frozen=True, slots=True)
class PortfolioPulse:
    """Read-only portfolio coverage and concentration snapshot."""

    position_count: int
    priced_position_count: int
    price_coverage: float | None
    max_position_weight: float | None
    risk_alert_count: int
    priority_issue: DailyBriefItem | None
    unavailable_reason: str | None = None


@dataclass(frozen=True, slots=True)
class WatchlistPulse:
    """Local watchlist movement, freshness, and research continuation summary."""

    item_count: int
    largest_move: DailyBriefItem | None
    stale_count: int
    unresearched_count: int
    unavailable_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ResearchContinuation:
    """A market-qualified research session available to reopen from the home screen."""

    symbol: Symbol
    researched_at: str | None
    data_as_of_date: str | None
    coverage: float | None
    status: str = "available"


@dataclass(frozen=True, slots=True)
class ActionRequired:
    """A recoverable data or coverage gap with one concrete next step."""

    field: str
    title: str
    detail: str
    action: DailyAction
    symbol: Symbol | None = None
    as_of_date: str | None = None


@dataclass(frozen=True, slots=True)
class DailyBrief:
    """Complete deterministic home-screen state derived from existing local evidence."""

    data_as_of_date: str | None
    attention_items: tuple[DailyBriefItem, ...]
    portfolio: PortfolioPulse
    watchlist: WatchlistPulse
    continuations: tuple[ResearchContinuation, ...]
    action_required: tuple[ActionRequired, ...]
    first_use: bool


@dataclass(frozen=True, slots=True)
class DailyRefreshRecord:
    """One secret-safe outcome from a user-initiated daily data refresh."""

    symbol: Symbol
    status: Literal["success", "partial", "failure", "unavailable"]
    provider: str | None = None
    query_symbol: str | None = None
    last_data_date: str | None = None
    source_type: str | None = None
    reason: str | None = None
    row_count: int | None = None


@dataclass(frozen=True, slots=True)
class DailyRefreshResult:
    """Bounded batch-refresh result that retains both successful and failed rows."""

    requested_count: int
    limited_count: int
    records: tuple[DailyRefreshRecord, ...]

    @property
    def success_count(self) -> int:
        """Return successful record count without treating partial results as failures."""

        return sum(item.status in {"success", "partial"} for item in self.records)

    @property
    def failure_count(self) -> int:
        """Return the number of refreshes that did not yield usable data."""

        return sum(item.status in {"failure", "unavailable"} for item in self.records)


class DailyBriefService:
    """Build evidence-backed research prompts without Streamlit, network, or advice logic."""

    def __init__(
        self,
        *,
        stale_after_days: int = 7,
        significant_move_pct: float = 0.05,
        volume_multiple: float = 1.5,
        max_attention_items: int = 5,
    ) -> None:
        if stale_after_days < 0:
            raise ValueError("stale_after_days must be zero or positive.")
        if significant_move_pct <= 0:
            raise ValueError("significant_move_pct must be greater than zero.")
        if volume_multiple <= 1:
            raise ValueError("volume_multiple must be greater than one.")
        if max_attention_items <= 0:
            raise ValueError("max_attention_items must be greater than zero.")
        self._stale_after_days = stale_after_days
        self._significant_move_pct = significant_move_pct
        self._volume_multiple = volume_multiple
        self._max_attention_items = max_attention_items

    def build(
        self,
        *,
        portfolio: pd.DataFrame | None,
        watchlist: pd.DataFrame | None,
        prices: pd.DataFrame | None,
        valuation: PortfolioValuationResult | None,
        continuations: Sequence[ResearchContinuation],
        reference_at: str | None,
        fundamental_scores: pd.DataFrame | None = None,
        risk_alert_count: int = 0,
    ) -> DailyBrief:
        """Return a stable home brief from existing local frames and explicit evidence dates."""

        portfolio_ids = _identities_from_frame(portfolio)
        watchlist_ids = _identities_from_frame(watchlist)
        price_history = _normalize_prices(prices)
        data_as_of_date = _latest_data_date(price_history)
        reference_date = _parse_optional_date(reference_at)
        fundamentals = _fundamental_identities(fundamental_scores)
        continuation_rows = _dedupe_continuations(continuations)
        continuation_ids = {item.symbol.canonical for item in continuation_rows}
        attention: list[DailyBriefItem] = []
        required: list[ActionRequired] = []

        identities = _dedupe_symbols((*portfolio_ids, *watchlist_ids))
        price_by_identity = _price_slices(price_history)
        for identity in identities:
            history = price_by_identity.get(identity.canonical)
            latest = _latest_price(history)
            if latest is None:
                missing_item = _missing_price_item(identity, checked_as_of_date=data_as_of_date)
                attention.append(missing_item)
                required.append(
                    ActionRequired(
                        field="price_data",
                        title=f"{identity.code} 缺少價格資料",
                        detail="尚無可用的市場別收盤價，無法完成價格相關研究。",
                        action="update_data",
                        symbol=identity,
                    )
                )
                continue

            freshness_reference = _freshness_reference_date(history) or reference_date
            if freshness_reference is None:
                required.append(
                    ActionRequired(
                        field="price_freshness",
                        title=f"{identity.code} 無法判斷資料新鮮度",
                        detail="已有市場別價格，但未保留可驗證的更新檢查時間。",
                        action="update_data",
                        symbol=identity,
                        as_of_date=str(latest["date"]),
                    )
                )
            attention.extend(
                _price_events(
                    identity,
                    history,
                    reference_date=freshness_reference,
                    stale_after_days=self._stale_after_days,
                    significant_move_pct=self._significant_move_pct,
                    volume_multiple=self._volume_multiple,
                )
            )
            if identity.canonical not in fundamentals:
                required.append(
                    ActionRequired(
                        field="fundamentals",
                        title=f"{identity.code} 基本面資料不足",
                        detail="尚未取得這檔股票的市場別基本面評分資料。",
                        action="complete_data",
                        symbol=identity,
                        as_of_date=str(latest["date"]),
                    )
                )

        if valuation is not None:
            for missing in valuation.missing_data:
                if missing.field == "fx_rate_to_base":
                    required.append(
                        ActionRequired(
                            field="fx_rate_to_base",
                            title="缺少匯率資料",
                            detail="跨幣別持股無法安全換算為同一基準幣別。",
                            action="complete_data",
                            as_of_date=data_as_of_date,
                        )
                    )

        portfolio_pulse = _portfolio_pulse(
            portfolio_ids=portfolio_ids,
            price_by_identity=price_by_identity,
            valuation=valuation,
            risk_alert_count=max(0, int(risk_alert_count)),
            attention=attention,
        )
        if portfolio_pulse.unavailable_reason is not None:
            required.append(
                ActionRequired(
                    field="portfolio_valuation",
                    title="持倉估值資料不足",
                    detail=portfolio_pulse.unavailable_reason,
                    action="view_holdings",
                    as_of_date=data_as_of_date,
                )
            )

        watchlist_pulse = _watchlist_pulse(
            watchlist_ids=watchlist_ids,
            price_by_identity=price_by_identity,
            reference_date=reference_date,
            stale_after_days=self._stale_after_days,
            continuations=continuation_ids,
            significant_move_pct=self._significant_move_pct,
        )
        if watchlist_pulse.item_count and watchlist_pulse.unresearched_count:
            required.append(
                ActionRequired(
                    field="research_snapshot",
                    title="自選股尚未完成研究",
                    detail=f"有 {watchlist_pulse.unresearched_count} 檔自選股尚無近期研究快照。",
                    action="open_research",
                    as_of_date=data_as_of_date,
                )
            )

        if risk_alert_count > 0:
            required.append(
                ActionRequired(
                    field="risk_alerts",
                    title="有待查看的風險提醒",
                    detail=f"目前有 {risk_alert_count} 項既有風險提醒，請查看持倉風險頁。",
                    action="view_holdings",
                    as_of_date=data_as_of_date,
                )
            )

        attention_rows = _dedupe_items(attention)[: self._max_attention_items]
        required_rows = _dedupe_actions(required)
        return DailyBrief(
            data_as_of_date=data_as_of_date,
            attention_items=attention_rows,
            portfolio=portfolio_pulse,
            watchlist=watchlist_pulse,
            continuations=continuation_rows[:5],
            action_required=required_rows,
            first_use=not portfolio_ids and not watchlist_ids and not continuation_rows,
        )


class DailyRefreshService:
    """Run a bounded, user-triggered batch through an injected hydration boundary."""

    def __init__(self, *, max_symbols: int = 20) -> None:
        if max_symbols <= 0:
            raise ValueError("max_symbols must be greater than zero.")
        self._max_symbols = max_symbols

    def refresh(
        self,
        *,
        symbols: Sequence[Symbol],
        hydrate: Callable[[Symbol], DailyRefreshRecord],
    ) -> DailyRefreshResult:
        """Refresh unique canonical identities while preserving each independent outcome."""

        requested = _dedupe_symbols(symbols)
        selected = requested[: self._max_symbols]
        rows: list[DailyRefreshRecord] = []
        for symbol in selected:
            try:
                record = hydrate(symbol)
            except Exception:
                rows.append(
                    DailyRefreshRecord(
                        symbol=symbol,
                        status="failure",
                        reason="資料更新失敗；請確認網路或稍後再試。",
                    )
                )
                continue
            if record.symbol != symbol:
                rows.append(
                    DailyRefreshRecord(
                        symbol=symbol,
                        status="failure",
                        reason="資料更新回傳的股票身分不一致。",
                    )
                )
                continue
            rows.append(record)
        return DailyRefreshResult(
            requested_count=len(requested),
            limited_count=len(selected),
            records=tuple(rows),
        )


def _identities_from_frame(frame: pd.DataFrame | None) -> tuple[Symbol, ...]:
    """Read canonical identities from a frame without inferring missing markets."""

    if frame is None or frame.empty or not {"symbol", "market"}.issubset(frame.columns):
        return ()
    identities: list[Symbol] = []
    for row in frame.loc[:, ["symbol", "market"]].itertuples(index=False):
        try:
            identities.append(Symbol.parse(str(row.symbol), market=str(row.market)))
        except ValueError:
            continue
    return _dedupe_symbols(identities)


def _dedupe_symbols(symbols: Iterable[Symbol]) -> tuple[Symbol, ...]:
    """Keep the first occurrence of each explicit market-qualified identity."""

    output: list[Symbol] = []
    seen: set[str] = set()
    for symbol in symbols:
        if symbol.market not in {Market.TWSE, Market.TPEX, Market.US}:
            continue
        if symbol.canonical in seen:
            continue
        seen.add(symbol.canonical)
        output.append(symbol)
    return tuple(output)


def _normalize_prices(prices: pd.DataFrame | None) -> pd.DataFrame:
    """Copy and validate local price rows; invalid rows are not used as evidence."""

    required = {"symbol", "market", "date", "close"}
    if prices is None or prices.empty or not required.issubset(prices.columns):
        return pd.DataFrame(columns=["symbol", "market", "date", "close", "volume"])
    columns = [
        item
        for item in (
            "symbol",
            "market",
            "date",
            "close",
            "volume",
            "last_data_date",
            "checked_at",
            "fetched_at",
        )
        if item in prices
    ]
    output = prices.loc[:, columns].copy(deep=True)
    canonical: list[str | None] = []
    codes: list[str | None] = []
    for row in output[["symbol", "market"]].itertuples(index=False):
        try:
            symbol = Symbol.parse(str(row.symbol), market=str(row.market))
        except ValueError:
            codes.append(None)
            canonical.append(None)
        else:
            codes.append(symbol.code)
            canonical.append(symbol.canonical)
    output["symbol"] = codes
    output["identity"] = canonical
    output["date"] = pd.to_datetime(output["date"], errors="coerce").dt.normalize()
    output["close"] = pd.to_numeric(output["close"], errors="coerce")
    if "volume" in output.columns:
        output["volume"] = pd.to_numeric(output["volume"], errors="coerce")
    else:
        output["volume"] = pd.NA
    output = output.loc[
        output["identity"].notna() & output["date"].notna() & output["close"].notna()
    ].copy()
    if output.empty:
        return output
    return output.sort_values(["identity", "date"], kind="stable").drop_duplicates(
        ["identity", "date"], keep="last"
    )


def _price_slices(prices: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Return copied, sorted local histories keyed by canonical identity."""

    if prices.empty:
        return {}
    return {
        str(identity): group.copy(deep=True).reset_index(drop=True)
        for identity, group in prices.groupby("identity", sort=True)
    }


def _latest_data_date(prices: pd.DataFrame) -> str | None:
    """Return the latest actual local market-data date, never the wall-clock date."""

    if prices.empty:
        return None
    latest = prices["date"].max()
    return None if pd.isna(latest) else pd.Timestamp(latest).date().isoformat()


def _latest_price(history: pd.DataFrame | None) -> pd.Series | None:
    """Return the latest valid row for one already-normalized identity."""

    if history is None or history.empty:
        return None
    return history.iloc[-1].copy(deep=True)


def _parse_optional_date(value: str | None) -> pd.Timestamp | None:
    """Parse an explicit freshness reference without substituting the current date."""

    if value is None or not str(value).strip():
        return None
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).tz_localize(None).normalize()


def _freshness_reference_date(history: pd.DataFrame | None) -> pd.Timestamp | None:
    """Read a persisted check time without substituting a market-data or wall-clock date."""

    latest = _latest_price(history)
    if latest is None:
        return None
    for column in ("checked_at", "fetched_at"):
        if column not in latest.index:
            continue
        parsed = _parse_optional_date(str(latest.get(column) or ""))
        if parsed is not None:
            return parsed
    return None


def _price_events(
    symbol: Symbol,
    history: pd.DataFrame | None,
    *,
    reference_date: pd.Timestamp | None,
    stale_after_days: int,
    significant_move_pct: float,
    volume_multiple: float,
) -> tuple[DailyBriefItem, ...]:
    """Create explainable price events using only adjacent and prior rows."""

    latest = _latest_price(history)
    if latest is None:
        return ()
    rows: list[DailyBriefItem] = []
    as_of_date = pd.Timestamp(latest["date"]).date().isoformat()
    if reference_date is not None:
        age = (reference_date - pd.Timestamp(latest["date"])).days
        if age > stale_after_days:
            rows.append(
                DailyBriefItem(
                    code="stale_price",
                    severity="warning",
                    title=f"{symbol.code} 價格資料可能過期",
                    detail="本機最新資料落後於已知更新檢查日期。",
                    evidence=f"最後資料日 {as_of_date}；更新檢查日 {reference_date.date().isoformat()}。",
                    as_of_date=as_of_date,
                    action="update_data",
                    symbol=symbol,
                    field="price_data",
                )
            )
    if history is None or len(history) < 2:
        return tuple(rows)
    previous = history.iloc[-2]
    previous_close = float(previous["close"])
    latest_close = float(latest["close"])
    if previous_close > 0:
        change_pct = (latest_close - previous_close) / previous_close
        if abs(change_pct) >= significant_move_pct:
            direction = "上漲" if change_pct > 0 else "下跌"
            rows.append(
                DailyBriefItem(
                    code="daily_move",
                    severity="attention",
                    title=f"{symbol.code} 單日變動明顯",
                    detail=f"相較前一個可用交易日{direction}。",
                    evidence=(
                        f"前一交易日收盤 {previous_close:.2f}；最新收盤 {latest_close:.2f}；"
                        f"變動 {change_pct:+.2%}。"
                    ),
                    as_of_date=as_of_date,
                    action="open_research",
                    symbol=symbol,
                    field="price_data",
                )
            )
    prior = history.iloc[:-1]
    if len(prior) >= 20:
        recent = prior.iloc[-20:]
        highest = float(recent["close"].max())
        lowest = float(recent["close"].min())
        if latest_close > highest:
            rows.append(
                DailyBriefItem(
                    code="range_breakout_high",
                    severity="info",
                    title=f"{symbol.code} 突破近期收盤高點",
                    detail="最新收盤高於前 20 個可用交易日的收盤區間。",
                    evidence=f"最新收盤 {latest_close:.2f}；前 20 日最高收盤 {highest:.2f}。",
                    as_of_date=as_of_date,
                    action="open_research",
                    symbol=symbol,
                    field="price_data",
                )
            )
        elif latest_close < lowest:
            rows.append(
                DailyBriefItem(
                    code="range_breakout_low",
                    severity="info",
                    title=f"{symbol.code} 跌破近期收盤低點",
                    detail="最新收盤低於前 20 個可用交易日的收盤區間。",
                    evidence=f"最新收盤 {latest_close:.2f}；前 20 日最低收盤 {lowest:.2f}。",
                    as_of_date=as_of_date,
                    action="open_research",
                    symbol=symbol,
                    field="price_data",
                )
            )
        latest_volume = pd.to_numeric(latest.get("volume"), errors="coerce")
        average_volume = pd.to_numeric(recent["volume"], errors="coerce").mean()
        if pd.notna(latest_volume) and pd.notna(average_volume) and average_volume > 0:
            if float(latest_volume) >= float(average_volume) * volume_multiple:
                rows.append(
                    DailyBriefItem(
                        code="volume_spike",
                        severity="info",
                        title=f"{symbol.code} 成交量高於近期平均",
                        detail="最新成交量明顯高於前 20 個可用交易日平均。",
                        evidence=(
                            f"最新成交量 {float(latest_volume):,.0f}；"
                            f"前 20 日均量 {float(average_volume):,.0f}。"
                        ),
                        as_of_date=as_of_date,
                        action="open_research",
                        symbol=symbol,
                        field="price_data",
                    )
                )
    return tuple(rows)


def _missing_price_item(
    symbol: Symbol,
    *,
    checked_as_of_date: str | None,
) -> DailyBriefItem:
    """Return an explicit, actionable missing-price item without fabricating a date."""

    return DailyBriefItem(
        code="missing_price",
        severity="warning",
        title=f"{symbol.code} 缺少價格資料",
        detail="尚未找到可用的市場別收盤價。",
        evidence=f"未找到 {symbol.market.value}:{symbol.code} 的可用本機價格資料。",
        as_of_date=checked_as_of_date,
        action="update_data",
        symbol=symbol,
        field="price_data",
    )


def _portfolio_pulse(
    *,
    portfolio_ids: tuple[Symbol, ...],
    price_by_identity: dict[str, pd.DataFrame],
    valuation: PortfolioValuationResult | None,
    risk_alert_count: int,
    attention: Sequence[DailyBriefItem],
) -> PortfolioPulse:
    """Use only existing canonical valuation weights and explicit price availability."""

    count = len(portfolio_ids)
    if count == 0:
        return PortfolioPulse(0, 0, None, None, risk_alert_count, None, "尚未建立持股。")
    priced = sum(
        _latest_price(price_by_identity.get(item.canonical)) is not None for item in portfolio_ids
    )
    coverage = priced / count
    max_weight: float | None = None
    unavailable: str | None = None
    if valuation is None:
        unavailable = "尚未取得既有投資組合估值結果。"
    else:
        weights = pd.to_numeric(valuation.positions.get("weight"), errors="coerce")
        if weights.notna().any() and valuation.base_market_value is not None:
            max_weight = float(weights.max())
        else:
            unavailable = "缺少價格或匯率，無法安全計算整體持股權重。"
    priority = next(
        (
            item
            for item in attention
            if item.symbol is not None
            and item.symbol.canonical in {row.canonical for row in portfolio_ids}
        ),
        None,
    )
    return PortfolioPulse(
        position_count=count,
        priced_position_count=priced,
        price_coverage=coverage,
        max_position_weight=max_weight,
        risk_alert_count=risk_alert_count,
        priority_issue=priority,
        unavailable_reason=unavailable,
    )


def _watchlist_pulse(
    *,
    watchlist_ids: tuple[Symbol, ...],
    price_by_identity: dict[str, pd.DataFrame],
    reference_date: pd.Timestamp | None,
    stale_after_days: int,
    continuations: set[str],
    significant_move_pct: float,
) -> WatchlistPulse:
    """Summarize watchlist movement and coverage only from local price histories."""

    if not watchlist_ids:
        return WatchlistPulse(0, None, 0, 0, "尚未建立自選股。")
    candidates: list[DailyBriefItem] = []
    stale_count = 0
    for identity in watchlist_ids:
        history = price_by_identity.get(identity.canonical)
        latest = _latest_price(history)
        if latest is None:
            stale_count += 1
            continue
        events = _price_events(
            identity,
            history,
            reference_date=_freshness_reference_date(history) or reference_date,
            stale_after_days=stale_after_days,
            significant_move_pct=significant_move_pct,
            volume_multiple=1_000_000.0,
        )
        stale_count += sum(item.code == "stale_price" for item in events)
        candidates.extend(item for item in events if item.code == "daily_move")
    largest = None
    if candidates:
        largest = max(candidates, key=lambda item: abs(_percent_from_evidence(item.evidence)))
    return WatchlistPulse(
        item_count=len(watchlist_ids),
        largest_move=largest,
        stale_count=stale_count,
        unresearched_count=sum(item.canonical not in continuations for item in watchlist_ids),
    )


def _percent_from_evidence(evidence: str) -> float:
    """Extract a displayed percentage only from this module's fixed evidence template."""

    marker = "變動 "
    suffix = "%"
    if marker not in evidence or suffix not in evidence:
        return 0.0
    raw = evidence.rsplit(marker, 1)[-1].split(suffix, 1)[0].replace("+", "")
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _fundamental_identities(frame: pd.DataFrame | None) -> set[str]:
    """Return only explicit market-qualified fundamental identities."""

    return {item.canonical for item in _identities_from_frame(frame)}


def _dedupe_continuations(
    rows: Sequence[ResearchContinuation],
) -> tuple[ResearchContinuation, ...]:
    """Keep the newest explicit continuation per market-qualified identity."""

    latest: dict[str, ResearchContinuation] = {}
    for row in rows:
        if row.symbol.market not in {Market.TWSE, Market.TPEX, Market.US}:
            continue
        current = latest.get(row.symbol.canonical)
        if current is None or _continuation_sort_key(row) > _continuation_sort_key(current):
            latest[row.symbol.canonical] = row
    return tuple(sorted(latest.values(), key=_continuation_sort_key, reverse=True))


def _continuation_sort_key(row: ResearchContinuation) -> tuple[pd.Timestamp, str]:
    """Use stored research time only; absent times sort behind known records."""

    parsed = _parse_optional_date(row.researched_at)
    return (parsed if parsed is not None else pd.Timestamp.min, row.symbol.canonical)


def _dedupe_items(items: Sequence[DailyBriefItem]) -> tuple[DailyBriefItem, ...]:
    """Deduplicate and sort items deterministically by severity then identity."""

    severity_order = {"attention": 0, "warning": 1, "info": 2}
    rows: dict[tuple[str, str, str], DailyBriefItem] = {}
    for item in items:
        identity = item.symbol.canonical if item.symbol is not None else "portfolio"
        rows[(item.code, identity, item.field or "")] = item
    return tuple(
        sorted(
            rows.values(),
            key=lambda item: (
                severity_order[item.severity],
                item.symbol.canonical if item.symbol is not None else "",
                item.code,
            ),
        )
    )


def _dedupe_actions(items: Sequence[ActionRequired]) -> tuple[ActionRequired, ...]:
    """Keep one concrete remediation action per field and canonical identity."""

    rows: dict[tuple[str, str], ActionRequired] = {}
    for item in items:
        identity = item.symbol.canonical if item.symbol is not None else "portfolio"
        rows.setdefault((item.field, identity), item)
    return tuple(sorted(rows.values(), key=lambda item: (item.field, item.title)))
