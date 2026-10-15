"""Read-only flat-to-flat evidence from fills; never changes execution/accounting."""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose, isfinite
from statistics import mean, median
from typing import Sequence, cast

import pandas as pd

from stock_tool.backtest.orders import Trade


@dataclass(frozen=True)
class RoundTrip:
    symbol: str
    entry_signal_date: str | None
    entry_execution_date: str
    entry_price: float | None
    exit_signal_date: str | None
    exit_execution_date: str
    exit_price: float | None
    quantity: int
    realized_pnl: float
    trade_return: float
    holding_days: int
    mfe: float | None
    mae: float | None
    excursion_unavailable_reason: str | None
    exit_reason: str


def _excursions(buys, sells, prices, execution_price_col):
    if len(buys) != 1 or len(sells) != 1:
        return None, None, "分批進出沒有單一進出成交價；不推估 MFE／MAE。"
    if execution_price_col != "open":
        return None, None, "尚未驗證此成交時點／調整價格與日線 high／low 的一致性。"
    if prices is None or not {"symbol", "date", "high", "low", "open", "close"}.issubset(
        prices.columns
    ):
        return None, None, "缺少可靠 OHLC；不使用 close 代替 high／low。"
    entry, exit_ = buys[0], sells[0]
    start, end = pd.Timestamp(entry.execution_date), pd.Timestamp(exit_.execution_date)
    if start >= end:
        return None, None, "日線無法分辨同日進出持有區間。"
    frame = prices.loc[prices.symbol.astype(str).eq(entry.symbol)].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    if frame.date.isna().any() or frame.date.duplicated().any():
        return None, None, "日期缺漏或重複，無法確認持有區間。"
    if start not in set(frame.date) or end not in set(frame.date):
        return None, None, "缺進場或出場交易日價格。"
    # Entry at open includes that day's path; exit at open excludes that day's
    # later extrema. Execution prices are the observed interval endpoints.
    window = frame.loc[(frame.date >= start) & (frame.date < end)]
    numeric = window[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    if (
        numeric.empty
        or not numeric.map(lambda x: pd.notna(x) and isfinite(x) and x > 0).all().all()
    ):
        return None, None, "持有期間 OHLC 缺漏或無效。"
    if (numeric.high < numeric[["open", "close", "low"]].max(axis=1)).any() or (
        numeric.low > numeric[["open", "close", "high"]].min(axis=1)
    ).any():
        return None, None, "持有期間 OHLC 高低價關係不一致。"
    highest = max(float(numeric.high.max()), entry.execution_price, exit_.execution_price)
    lowest = min(float(numeric.low.min()), entry.execution_price, exit_.execution_price)
    return highest / entry.execution_price - 1, lowest / entry.execution_price - 1, None


def completed_round_trips(
    trades: Sequence[Trade],
    *,
    prices: pd.DataFrame | None = None,
    execution_price_col: str | None = None,
    has_corporate_actions: bool = False,
) -> tuple[tuple[RoundTrip, ...], str | None]:
    """Flat-to-flat cycles, aggregating existing realized PnL, not inventing lots."""
    if has_corporate_actions:
        return (), "公司行動可能改變股數或產生非成交現金流；完整交易分析尚未支援。"
    active: dict[str, list[Trade]] = {}
    quantities: dict[str, int] = {}
    last_dates: dict[str, str] = {}
    completed: list[RoundTrip] = []
    for fill in trades:
        if (
            fill.quantity <= 0
            or not isfinite(fill.net_cash_flow)
            or not isfinite(fill.execution_price)
            or fill.execution_price <= 0
        ):
            return (), "成交數量／價格／現金流無效。"
        if fill.execution_date < last_dates.get(fill.symbol, ""):
            return (), "成交順序不可靠，未重排猜測。"
        last_dates[fill.symbol] = fill.execution_date
        quantity = quantities.get(fill.symbol, 0)
        if fill.side == "sell" and (fill.quantity > quantity or fill.realized_pnl is None):
            return (), "缺少可對應買進或已實現損益，無法可靠重建。"
        active.setdefault(fill.symbol, []).append(fill)
        quantity += fill.quantity if fill.side == "buy" else -fill.quantity
        quantities[fill.symbol] = quantity
        if quantity:
            continue
        cycle = active.pop(fill.symbol)
        buys = [t for t in cycle if t.side == "buy"]
        sells = [t for t in cycle if t.side == "sell"]
        cost = -sum(t.net_cash_flow for t in buys)
        pnl = sum(cast(float, t.realized_pnl) for t in sells)
        if (
            cost <= 0
            or not isfinite(pnl)
            or not isclose(pnl, sum(t.net_cash_flow for t in cycle), abs_tol=1e-6, rel_tol=1e-9)
        ):
            return (), "已實現損益與完整交易現金流不一致，未重新計價。"
        mfe, mae, reason = _excursions(buys, sells, prices, execution_price_col)
        completed.append(
            RoundTrip(
                symbol=fill.symbol,
                entry_signal_date=buys[0].signal_date if len(buys) == 1 else None,
                entry_execution_date=buys[0].execution_date,
                entry_price=buys[0].execution_price if len(buys) == 1 else None,
                exit_signal_date=sells[0].signal_date if len(sells) == 1 else None,
                exit_execution_date=sells[-1].execution_date,
                exit_price=sells[0].execution_price if len(sells) == 1 else None,
                quantity=sum(t.quantity for t in buys),
                realized_pnl=pnl,
                trade_return=pnl / cost,
                holding_days=(
                    pd.Timestamp(sells[-1].execution_date) - pd.Timestamp(buys[0].execution_date)
                ).days,
                mfe=mfe,
                mae=mae,
                excursion_unavailable_reason=reason,
                exit_reason="；".join(dict.fromkeys(t.reason for t in sells)),
            )
        )
    return tuple(completed), None


def round_trip_statistics(trips: Sequence[RoundTrip]) -> dict:
    pnl = [t.realized_pnl for t in trips]
    wins, losses = [p for p in pnl if p > 0], [p for p in pnl if p < 0]
    mfe, mae = [t.mfe for t in trips if t.mfe is not None], [
        t.mae for t in trips if t.mae is not None
    ]
    return dict(
        closed_round_trip_count=len(trips),
        average_win=mean(wins) if wins else None,
        average_loss=mean(losses) if losses else None,
        payoff_ratio=mean(wins) / abs(mean(losses)) if wins and losses else None,
        expectancy=mean(pnl) if pnl else None,
        median_trade_return=median([t.trade_return for t in trips]) if trips else None,
        average_mfe=mean(mfe) if mfe else None,
        median_mfe=median(mfe) if mfe else None,
        average_mae=mean(mae) if mae else None,
        median_mae=median(mae) if mae else None,
        excursion_count=len(mfe),
        win_rate=len(wins) / len(trips) if trips else 0.0,
        profit_factor=sum(wins) / abs(sum(losses)) if losses else (float("inf") if wins else None),
        average_holding_period=mean([t.holding_days for t in trips]) if trips else None,
    )
