"""One immutable holding view and its AI evidence, without provider side effects."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
import math

import pandas as pd

from stock_tool.portfolio_valuation import FxQuote
from stock_tool.research.evidence import ClaimKind, EvidenceBundle, EvidenceRecord


@dataclass(frozen=True, slots=True)
class HoldingDatum:
    """Value together with its own time and provenance; unknown is never fresh."""

    label: str
    value: str
    source: str
    as_of: str
    fetched_at: str
    status: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class HoldingAnalysis:
    symbol: str
    market: str
    currency: str
    instrument_type: str
    data: tuple[HoldingDatum, ...]
    observations: tuple[str, ...]
    gaps: tuple[str, ...]

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def evidence_bundle(self) -> EvidenceBundle:
        records = []
        for index, datum in enumerate(self.data):
            records.append(
                EvidenceRecord(
                    evidence_id=f"holding.{index}",
                    kind=ClaimKind.FACT if datum.status == "可用" else ClaimKind.WARNING,
                    label=datum.label,
                    text=f"{datum.label}：{datum.value}；{datum.status}。{datum.reason}",
                    source=datum.source,
                    provider=None,
                    symbol=self.symbol,
                    market=self.market,
                    available_at=datum.as_of,
                    fetched_at=datum.fetched_at,
                )
            )
        for index, gap in enumerate(self.gaps):
            records.append(
                EvidenceRecord(
                    evidence_id=f"gap.{index}",
                    kind=ClaimKind.MISSING,
                    label="待確認",
                    text=gap,
                    source=None,
                    provider=None,
                    symbol=self.symbol,
                    market=self.market,
                )
            )
        for index, observation in enumerate(self.observations):
            records.append(
                EvidenceRecord(
                    evidence_id=f"observation.{index}",
                    kind=ClaimKind.CALCULATION,
                    label="持股影響",
                    text=observation,
                    source="持股與市場資料計算",
                    provider=None,
                    symbol=self.symbol,
                    market=self.market,
                )
            )
        return EvidenceBundle(self.symbol, self.market, self.fingerprint, tuple(records))


def _text(value: object) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


def _number(value: object) -> float | None:
    try:
        result = float(value)  # type: ignore[arg-type]
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _age_status(as_of: str, fetched_at: str, now: datetime) -> str:
    dates = [pd.to_datetime(value, errors="coerce", utc=True) for value in (as_of, fetched_at)]
    if any(pd.isna(value) for value in dates):
        return "日期待確認"
    ages = [(pd.Timestamp(now) - date).total_seconds() for date in dates]
    if min(ages) < -300:
        return "日期衝突"
    # Conservative daily-data policy, explicitly not an exchange calendar.
    return "可能過期" if ages[0] > 7 * 86400 or ages[1] > 86400 else "可用"


def validated_holding_prices(
    positions: pd.DataFrame,
    prices: object,
    profiles: dict[str, object],
    *,
    now: datetime | None = None,
) -> pd.DataFrame | None:
    """Apply the same identity/unit/price gates before computing portfolio totals."""
    if not isinstance(prices, pd.DataFrame):
        return None
    if not {"symbol", "market", "date", "close"}.issubset(prices.columns):
        return None
    result = prices.copy(deep=True)
    for position in positions.to_dict("records"):
        identity = f"{position['symbol']}|{position['market']}"
        profile = profiles.get(identity)
        snapshot = build_holding_analysis(
            position,
            prices=prices,
            fx_quote=None,
            profile=profile if isinstance(profile, dict) else None,
            now=now,
        )
        if not any(datum.label == "原幣市值" for datum in snapshot.data):
            result = result.loc[
                ~((result.symbol == position["symbol"]) & (result.market == position["market"]))
            ]
    return result


def holding_fx_is_usable(quote: FxQuote | None, *, now: datetime | None = None) -> bool:
    """Use the same currency and time gate for portfolio totals and single-holding evidence."""
    return bool(
        quote is not None
        and not quote.stale
        and not quote.unknown
        and quote.currency_pair in {"USD/TWD", "TWD/USD"}
        and _age_status(quote.effective_at, quote.fetched_at, now or datetime.now(UTC)) == "可用"
    )


def build_holding_analysis(
    position: dict[str, object],
    *,
    prices: pd.DataFrame | None,
    fx_quote: FxQuote | None,
    weight: float | None = None,
    profile: dict[str, object] | None = None,
    refresh_failed: bool = False,
    now: datetime | None = None,
) -> HoldingAnalysis:
    """Calculate native values independently of optional fundamentals and FX."""
    now = now or datetime.now(UTC)
    symbol, market = _text(position.get("symbol")), _text(position.get("market"))
    currency = _text(position.get("currency"))
    profile = profile or {}
    if profile and (
        profile.get("symbol", symbol) != symbol or profile.get("market", market) != market
    ):
        profile = {}
    kind = _text(profile.get("instrument_type")) or "未確認"
    gaps: list[str] = []
    observations: list[str] = []
    data: list[HoldingDatum] = []
    for field, label in (("name", "標的名稱"), ("sector", "產業領域"), ("industry", "細分產業")):
        if profile.get(field):
            data.append(
                HoldingDatum(
                    label,
                    str(profile[field]),
                    str(profile.get("source") or "未確認"),
                    "來源未提供生效日期",
                    str(profile.get("fetched_at") or "未提供"),
                    "日期待確認",
                )
            )
    quantity, cost = _number(position.get("quantity")), _number(position.get("average_cost"))
    if quantity is None or quantity <= 0 or cost is None or cost < 0:
        raise ValueError("持股股數與每股成本必須為有效數值。")
    data.append(
        HoldingDatum("股數", f"{quantity:,.4g} 股", "使用者輸入", "不適用", "不適用", "可用")
    )
    data.append(
        HoldingDatum(
            "平均成本（原幣／股）",
            f"{currency} {cost:,.2f}",
            "使用者輸入",
            "不適用",
            "不適用",
            "可用",
        )
    )
    currency_conflict = bool(profile.get("currency") and profile["currency"] != currency)
    if currency_conflict:
        gaps.append("報價幣別與持股幣別不一致；請確認身份與成本幣別，暫停估值。")
    row = None
    price_usable = False
    if isinstance(prices, pd.DataFrame) and {"symbol", "market", "date", "close"}.issubset(
        prices.columns
    ):
        selected = prices.loc[
            (prices.symbol.astype(str) == symbol) & (prices.market.astype(str) == market)
        ].copy()
        selected["_date"] = pd.to_datetime(selected["date"], errors="coerce", utc=True)
        selected = selected.dropna(subset=["_date"]).sort_values("_date")
        if not selected.empty:
            row = selected.iloc[-1]
            latest = selected.loc[selected["_date"] == row["_date"]]
            if latest["close"].nunique(dropna=False) > 1:
                row = None
                gaps.append("同一交易日期出現互相衝突的價格，未任選其中一筆估值。")
    if row is None:
        gaps.append("尚無這筆持股的有效日期價格；市值暫時無法計算。")
    else:
        price = _number(row.get("close"))
        date = _text(row.get("date"))
        fetched = _text(row.get("fetched_at")) or _text(row.get("checked_at"))
        source = _text(row.get("provider")) or "來源未確認"
        status = _age_status(date, fetched, now)
        if source == "來源未確認" and status == "可用":
            status = "來源待確認"
        price_usable = status == "可用" and not currency_conflict
        reason = "" if not refresh_failed else "本次更新失敗，保留前次資料。"
        if refresh_failed and status == "可用":
            status = "保留前次資料"
        if price is None or price <= 0:
            gaps.append("報價不是有效的正數，未計算市值。")
        elif price_usable:
            value, pnl = quantity * price, quantity * (price - cost)
            for label, amount in (("收盤價", price), ("原幣市值", value), ("原幣未實現損益", pnl)):
                data.append(
                    HoldingDatum(
                        label,
                        f"{currency} {amount:,.2f}",
                        source,
                        date,
                        fetched or "未提供",
                        status,
                        reason,
                    )
                )
            rate: float | None
            if currency == "TWD":
                rate = 1.0
            elif fx_quote is not None and holding_fx_is_usable(fx_quote, now=now):
                pair = fx_quote.currency_pair
                rate = (
                    fx_quote.rate
                    if pair == "USD/TWD"
                    else (1 / fx_quote.rate if pair == "TWD/USD" and fx_quote.rate else None)
                )
            else:
                rate = None
            if rate is not None:
                data.append(
                    HoldingDatum(
                        "台幣參考市值",
                        f"TWD {value * rate:,.2f}",
                        source,
                        date,
                        fetched or "未提供",
                        status,
                        reason,
                    )
                )
            else:
                gaps.append("美元／台幣匯率無法確認或已過期；原幣估值仍可查看。")
        else:
            data.append(
                HoldingDatum(
                    "收盤價",
                    f"{currency} {price:,.2f}",
                    source,
                    date,
                    fetched or "未提供",
                    status,
                    reason,
                )
            )
            gaps.append(f"價格{status}或幣別不符，暫停估值；保留報價僅供核對，不計入總市值與權重。")
    if currency == "USD" and fx_quote is not None:
        data.append(
            HoldingDatum(
                "估值換算匯率",
                (
                    f"{fx_quote.currency_pair} {fx_quote.rate:.4f}"
                    if fx_quote.rate is not None
                    else "無可用匯率"
                ),
                fx_quote.source,
                fx_quote.effective_at,
                fx_quote.fetched_at,
                (
                    "可能過期"
                    if fx_quote.stale
                    else _age_status(fx_quote.effective_at, fx_quote.fetched_at, now)
                ),
            )
        )
    if row is not None and price_usable:
        series = pd.to_numeric(selected.drop_duplicates("_date")["close"], errors="coerce").tail(60)
        if (
            len(series) >= 20
            and series.notna().all()
            and (series > 0).all()
            and all(math.isfinite(value) for value in series)
        ):
            drawdown = float((series / series.cummax() - 1).min())
            observations.append(
                f"已載入的最近 {len(series)} 筆收盤資料中，最大回落為 {drawdown:.1%}；這是該觀察區間的歷史價格回落，不是未來跌幅預測。"
            )
    if weight is not None and math.isfinite(weight) and 0 <= weight <= 1 and price_usable:
        observations.append(
            f"這筆持股占已計算組合市值 {weight:.1%}；假設其價格下跌 10%、其他持股與匯率不變，組合市值約下降 {weight * 0.1:.1%}。"
        )
    if kind == "ETF":
        gaps.append(
            "ETF 需查核追蹤指數、成分集中度與費用；目前未取得完整成分資料，不套用公司獲利評分。"
        )
    else:
        gaps.append("尚未核對最新財報期間與重大事件，不能只憑股價或持股損益判斷公司前景。")
    if kind == "未確認":
        gaps.append("股票／ETF 類型尚未確認，暫不作公司或基金專屬判斷。")
    observations.append(
        "台幣參考市值依目前匯率換算；原幣損益不包含歷史換匯損益。報價幣別不等於完整經濟曝險。"
    )
    return HoldingAnalysis(
        symbol, market, currency, kind, tuple(data), tuple(observations), tuple(gaps)
    )
