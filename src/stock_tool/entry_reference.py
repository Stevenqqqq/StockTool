"""Rule-based entry reference prices for research use only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class EntryReference:
    """Transparent entry reference output based only on loaded historical data."""

    symbol: str
    as_of_date: str | None
    method: str
    latest_close: float | None
    reference_price: float | None
    zone_low: float | None
    zone_high: float | None
    breakout_trigger: float | None
    stop_loss_reference: float | None
    notes: tuple[str, ...]
    risk_notes: tuple[str, ...]
    missing_data: tuple[str, ...] = ()

    @property
    def is_available(self) -> bool:
        """Return whether the reference price can be interpreted."""

        return self.reference_price is not None and not self.missing_data


def estimate_entry_reference(
    price_data: pd.DataFrame,
    technical_indicators: pd.DataFrame | None = None,
    *,
    symbol: str,
    as_of_date: str | None = None,
    lookback: int = 20,
    atr_window: int = 14,
    entry_atr_multiplier: float = 0.5,
    stop_atr_multiplier: float = 2.0,
) -> EntryReference:
    """Estimate a rule-based entry reference price without using future rows.

    The result is an observation aid, not a buy recommendation. When
    ``as_of_date`` is provided, rows after that date are ignored. If indicator
    columns are missing, trailing SMA and ATR values are calculated from
    historical OHLC data up to the selected date.
    """

    if lookback <= 1:
        raise ValueError("lookback 必須大於 1。")
    if atr_window <= 1:
        raise ValueError("atr_window 必須大於 1。")
    if entry_atr_multiplier <= 0:
        raise ValueError("entry_atr_multiplier 必須大於 0。")
    if stop_atr_multiplier <= 0:
        raise ValueError("stop_atr_multiplier 必須大於 0。")

    symbol_text = str(symbol).strip()
    prices = _prepare_frame(price_data, symbol=symbol_text, as_of_date=as_of_date)
    indicators = _prepare_frame(technical_indicators, symbol=symbol_text, as_of_date=as_of_date)
    data = _merge_latest_indicators(prices, indicators)

    missing: list[str] = []
    if data.empty:
        return _insufficient(symbol_text, None, ("price_data",))

    if len(data) < lookback:
        latest_date = str(data.iloc[-1].get("date")) if "date" in data.columns else None
        return _insufficient(symbol_text, latest_date, (f"at_least_{lookback}_price_rows",))

    latest = data.iloc[-1]
    latest_date = str(latest.get("date")) if "date" in latest.index else None
    close = _number(latest.get("close"))
    if close is None or close <= 0:
        return _insufficient(symbol_text, latest_date, ("close",))

    sma20 = _number(latest.get("sma_20")) or _rolling_mean(data["close"], 20)
    sma60 = _number(latest.get("sma_60")) or _rolling_mean(data["close"], 60)
    atr = _number(latest.get("atr_14")) or _calculate_atr(data, atr_window)
    recent_high = _rolling_extreme(data.get("high"), lookback, "max")
    recent_low = _rolling_extreme(data.get("low"), lookback, "min")

    if sma20 is None:
        missing.append("sma_20")
    if recent_high is None:
        missing.append("high")
    if recent_low is None:
        missing.append("low")

    buffer = atr if atr is not None and atr > 0 else close * 0.02
    notes: list[str] = [f"計算基準日：{latest_date or '資料最後一列'}，最新收盤價約 {close:.2f}。"]
    if atr is None:
        notes.append("缺少 ATR，觀察區間暫以收盤價 2% 作為保守緩衝。")
    else:
        notes.append(f"ATR 約 {atr:.2f}，用於估算觀察區間與停損參考。")

    breakout_trigger = (
        None
        if recent_high is None
        else _round_price(recent_high + max(buffer * 0.1, close * 0.001))
    )
    method = "區間觀察"

    anchor: float = close
    if sma20 is not None and sma60 is not None and close >= sma20 >= sma60:
        method = "趨勢回檔觀察"
        anchor = float(sma20)
        notes.append("收盤價、20 日均線與 60 日均線呈多頭排列，參考價以 20 日均線附近估算。")
    elif sma20 is not None and close >= sma20:
        method = "短線支撐觀察"
        anchor = float(sma20)
        notes.append("收盤價高於 20 日均線，但中期趨勢條件未完全確認，參考價以短線支撐附近估算。")
    else:
        method = "保守觀察"
        anchor = float(close)
        notes.append(
            "價格尚未站上主要均線，主參考價以最新收盤附近保守觀察；"
            "近高突破價另列為條件觀察，不作為主入場參考。"
        )

    reference_price = _round_price(anchor)
    zone_low = _round_price(max(0.01, anchor - buffer * entry_atr_multiplier))
    zone_high = _round_price(max(zone_low or 0.01, anchor + buffer * entry_atr_multiplier))
    stop_base: float = (
        float(recent_low)
        if (recent_low is not None and recent_low < anchor)
        else (float(zone_low) if zone_low is not None else anchor)
    )
    stop_loss_reference = _round_price(
        max(0.01, stop_base - buffer * min(stop_atr_multiplier, 1.0))
    )

    if recent_low is not None:
        notes.append(f"近 {lookback} 日低點約 {recent_low:.2f}，可用來檢查支撐是否失守。")
    if breakout_trigger is not None:
        notes.append(f"近 {lookback} 日突破觀察價約 {breakout_trigger:.2f}。")
        breakout_distance = (breakout_trigger / close) - 1.0
        if breakout_distance > 0.05:
            notes.append(
                f"突破觀察價高於最新收盤約 {breakout_distance * 100:.2f}%，"
                "屬於條件觸發價，不代表目前應以該價位進場。"
            )

    risk_notes = (
        "情境參考區間僅供研究與情境規劃，不構成個人化買賣建議。",
        "實際成交價可能受開盤跳空、流動性、滑價、手續費與交易稅影響。",
        "請搭配部位大小、停損、最大持股比例與整體資金風險控管使用。",
    )
    return EntryReference(
        symbol=symbol_text,
        as_of_date=latest_date,
        method=method,
        latest_close=_round_price(close),
        reference_price=reference_price,
        zone_low=zone_low,
        zone_high=zone_high,
        breakout_trigger=breakout_trigger,
        stop_loss_reference=stop_loss_reference,
        notes=tuple(notes),
        risk_notes=risk_notes,
        missing_data=tuple(sorted(set(missing))),
    )


def _insufficient(
    symbol: str, as_of_date: str | None, missing_data: tuple[str, ...]
) -> EntryReference:
    return EntryReference(
        symbol=symbol,
        as_of_date=as_of_date,
        method="資料不足",
        latest_close=None,
        reference_price=None,
        zone_low=None,
        zone_high=None,
        breakout_trigger=None,
        stop_loss_reference=None,
        notes=("資料不足，無法產生情境參考區間。",),
        risk_notes=("請先補齊股價資料；系統不會用缺漏資料硬算入場價格。",),
        missing_data=missing_data,
    )


def _prepare_frame(
    frame: pd.DataFrame | None,
    *,
    symbol: str,
    as_of_date: str | None,
) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()

    output = frame.copy(deep=True)
    if "symbol" in output.columns:
        output = output.loc[output["symbol"].astype(str) == symbol]
    if "date" in output.columns:
        output["date"] = pd.to_datetime(output["date"], errors="coerce")
        output = output.dropna(subset=["date"])
        if as_of_date is not None:
            cutoff = pd.to_datetime(as_of_date, errors="coerce")
            if pd.isna(cutoff):
                raise ValueError(f"as_of_date 日期格式無效：{as_of_date}")
            output = output.loc[output["date"] <= cutoff]
        output = output.sort_values("date")
        output["date"] = output["date"].dt.date.astype(str)
    return output.reset_index(drop=True)


def _merge_latest_indicators(prices: pd.DataFrame, indicators: pd.DataFrame) -> pd.DataFrame:
    if (
        prices.empty
        or indicators.empty
        or "date" not in prices.columns
        or "date" not in indicators.columns
    ):
        return prices

    indicator_cols = [
        column
        for column in ("date", "symbol", "sma_20", "sma_60", "atr_14")
        if column in indicators.columns
    ]
    if len(indicator_cols) <= 1:
        return prices

    keys = ["date"]
    if "symbol" in prices.columns and "symbol" in indicators.columns:
        keys.append("symbol")
    merged = prices.merge(
        indicators[indicator_cols], on=keys, how="left", suffixes=("", "_indicator")
    )
    for column in ("sma_20", "sma_60", "atr_14"):
        indicator_col = f"{column}_indicator"
        if indicator_col in merged.columns:
            if column in merged.columns:
                merged[column] = merged[column].where(
                    pd.notna(merged[column]), merged[indicator_col]
                )
            else:
                merged[column] = merged[indicator_col]
            merged = merged.drop(columns=[indicator_col])
    return merged


def _number(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rolling_mean(series: pd.Series, window: int) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if len(values) < window:
        return None
    return float(values.tail(window).mean())


def _rolling_extreme(series: pd.Series | None, window: int, method: str) -> float | None:
    if series is None:
        return None
    values = pd.to_numeric(series, errors="coerce").dropna()
    if len(values) < window:
        return None
    tail = values.tail(window)
    return float(tail.max() if method == "max" else tail.min())


def _calculate_atr(data: pd.DataFrame, window: int) -> float | None:
    required = {"high", "low", "close"}
    if data.empty or not required.issubset(data.columns):
        return None
    high = pd.to_numeric(data["high"], errors="coerce")
    low = pd.to_numeric(data["low"], errors="coerce")
    close = pd.to_numeric(data["close"], errors="coerce")
    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            (high - low).abs(),
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = true_range.rolling(window=window, min_periods=window).mean().dropna()
    if atr.empty:
        return None
    return float(atr.iloc[-1])


def _round_price(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)
