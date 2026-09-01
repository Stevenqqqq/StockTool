"""Pure presentation mapping, natural Traditional Chinese translation, and formatting.

This module is part of the presentation layer. It adapts domain and application
state tokens into human-friendly Traditional Chinese copy, readable numbers,
and aggregated warnings without modifying underlying models, calculations, or
trust boundaries.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

# Map of raw status tokens to natural Traditional Chinese
STATUS_TRANSLATIONS: Mapping[str, str] = {
    "fresh": "最新",
    "ready": "資料已就緒",
    "partial": "部分可用",
    "missing": "資料不足",
    "complete": "已完成",
    "not_run": "尚未執行",
    "stale": "離線快取（已過期）",
    "offline": "離線／本機資料",
    "online": "線上來源",
    "canonical": "標準格式",
    "unknown": "未確認",
    "insufficient_data": "資料不足",
    "insufficient": "資料不足",
    "initial": "尚未搜尋",
    "no_results": "無符合結果",
    "healthy": "健康",
    "blocked": "條件未達成（已阻擋）",
    "error": "錯誤",
    "failed": "未完成",
    "failure": "失敗",
    "success": "完成",
    "skipped": "已略過",
    "unavailable": "資料不足",
    "available": "可用",
    "disabled": "停用",
    "enabled": "啟用",
    "not_installed": "未安裝",
    "baseline": "已建立基準",
    "updated": "有新的可驗證變化",
    "no_change": "沒有重大變化",
    "pending": "等待到期",
    "eligible": "可評估",
    "evaluated": "已完成結算",
    "fact": "事實資料",
    "calculation": "研究計算",
    "opinion": "研究觀點",
    "risk": "主要風險",
}

SOURCE_STATE_TRANSLATIONS: Mapping[str, str] = {
    "offline_cache": "離線／本機快取",
    "local_index": "本機探索索引",
    "missing": "資料不足",
    "provider": "線上來源",
    "online": "線上官方來源",
    "canonical": "標準代號",
    "user_upload": "使用者上傳",
    "sample": "範例資料",
    "manual_seed": "本機種子資料",
}

MARKET_LABELS: Mapping[str, str] = {
    "TWSE": "台股上市",
    "TPEX": "台股上櫃",
    "US": "美股",
    "COMBINED": "合併檢視",
    "CUSTOM": "自訂市場",
}

PARAMETER_LABELS_ZH: Mapping[str, str] = {
    "short_window": "短期均線",
    "long_window": "長期均線",
    "target_percent": "投入比例",
    "rsi_period": "RSI 週期",
    "oversold": "超賣門檻",
    "overbought": "超買門檻",
    "bb_period": "布林週期",
    "bb_std": "標準差倍數",
    "macd_fast": "MACD 快線",
    "macd_slow": "MACD 慢線",
    "macd_signal": "MACD 訊號線",
    "holding_period": "持股週期",
    "stop_loss_pct": "停損比例",
    "take_profit_pct": "停利比例",
    "trailing_stop_pct": "移動停利",
    "growth_rate_min": "最低成長率",
    "pe_max": "最高本益比",
    "pb_max": "最高股價淨值比",
    "roe_min": "最低 ROE",
}

HEALTH_CATEGORY_TRANSLATIONS: Mapping[str, str] = {
    "diversification": "持股分散度",
    "valuation": "估值覆蓋與健康度",
    "fundamental_health": "基本面健康度",
    "volatility": "波動度與風險",
    "liquidity": "流動性與覆蓋",
    "coverage": "資料覆蓋率",
}


def format_status_label(status: object) -> str:
    """Return a natural Traditional Chinese label for a status token."""
    if status is None:
        return "資料不足"
    key = str(status).strip().lower()
    return STATUS_TRANSLATIONS.get(key, str(status).strip() or "資料不足")


def format_source_state_label(state: object) -> str:
    """Return a natural Traditional Chinese label for a source state."""
    if state is None:
        return "資料不足"
    key = str(state).strip().lower()
    return SOURCE_STATE_TRANSLATIONS.get(key, str(state).strip() or "資料不足")


def format_market_label(market: object) -> str:
    """Return a natural Traditional Chinese label for a market identifier."""
    if market is None:
        return "未知市場"
    key = str(market).strip().upper()
    return MARKET_LABELS.get(key, str(market).strip())


def format_percentage(
    value: float | int | None,
    decimals: int = 2,
    *,
    with_sign: bool = False,
    is_ratio: bool = False,
) -> str:
    """Format a numeric percentage into a human-readable string with `%`.

    If ``is_ratio`` is True, ``0.05`` formats as ``5.00%``.
    If ``is_ratio`` is False, ``5.0`` formats as ``5.00%``.
    """
    if value is None:
        return "資料不足"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "資料不足"
    if not math.isfinite(num):
        return "資料不足"
    display_num = num * 100.0 if is_ratio else num
    sign = "+" if with_sign and display_num > 0 else ""
    return f"{sign}{display_num:.{decimals}f}%"


def format_number(
    value: float | int | None,
    decimals: int = 2,
    *,
    with_sign: bool = False,
) -> str:
    """Format a number with comma grouping, avoiding scientific notation."""
    if value is None:
        return "資料不足"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "資料不足"
    if not math.isfinite(num):
        return "資料不足"
    sign = "+" if with_sign and num > 0 else ""
    if decimals == 0 or num.is_integer():
        return f"{sign}{int(num):,}"
    return f"{sign}{num:,.{decimals}f}"


def format_volume(value: float | int | None) -> str:
    """Format trading volume cleanly in shares / thousands / ten-thousands without scientific notation."""
    if value is None:
        return "資料不足"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "資料不足"
    if not math.isfinite(num) or num < 0:
        return "資料不足"
    if num >= 100_000_000:
        return f"{num / 100_000_000:,.2f} 億股"
    if num >= 10_000:
        return f"{num / 10_000:,.1f} 萬股"
    if num >= 1_000:
        return f"{num / 1_000:,.1f} 千股"
    return f"{int(num):,} 股"


def format_turnover_value(value: float | int | None, currency: str = "TWD") -> str:
    """Format turnover amount in 億元 / 萬元 without scientific notation."""
    if value is None:
        return "資料不足"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "資料不足"
    if not math.isfinite(num) or num < 0:
        return "資料不足"
    curr_prefix = f"{currency} " if currency != "TWD" else ""
    if num >= 100_000_000:
        return f"{curr_prefix}{num / 100_000_000:,.2f} 億元"
    if num >= 10_000:
        return f"{curr_prefix}{num / 10_000:,.1f} 萬元"
    return f"{curr_prefix}{num:,.0f} 元"


def format_currency(value: float | int | None, currency: str = "TWD", decimals: int = 2) -> str:
    """Format money with currency prefix and commas."""
    if value is None:
        return "資料不足"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "資料不足"
    if not math.isfinite(num):
        return "資料不足"
    return f"{currency} {num:,.{decimals}f}"


def format_iso_datetime(value: str | None) -> str:
    """Format an ISO timestamp (including microsecond UTC strings) into a clean Traditional Chinese string."""
    if not value or not str(value).strip():
        return "資料不足"
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    try:
        cleaned = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return re.sub(r"\.\d+.*", "", text)


def format_parameters_zh(parameters: Mapping[str, Any]) -> str:
    """Convert a parameter dictionary into readable Traditional Chinese key-value labels."""
    if not parameters:
        return "無自訂參數"
    parts: list[str] = []
    for key, val in parameters.items():
        label = PARAMETER_LABELS_ZH.get(str(key), str(key))
        if isinstance(val, float):
            val_str = (
                f"{val * 100:.0f}%"
                if "percent" in key or "pct" in key or "rate" in key
                else f"{val:g}"
            )
        else:
            val_str = str(val)
        parts.append(f"{label}：{val_str}")
    return "、".join(parts)


def deduplicate_warnings(warnings: Iterable[str]) -> tuple[str, ...]:
    """Preserve order while deduplicating and translating warning messages."""
    seen: set[str] = set()
    result: list[str] = []
    for item in warnings:
        if not item:
            continue
        text = str(item).strip()
        # Translate internal terms and English PIT warnings into natural Traditional Chinese
        text = (
            text.replace("Point-in-time", "歷史切點（PIT）")
            .replace("point-in-time", "歷史切點（PIT）")
            .replace("Point-in-Time", "歷史切點（PIT）")
            .replace("PIT evaluation", "歷史切點評估")
            .replace("online", "線上來源")
            .replace("canonical", "標準格式")
            .replace("sector", "產業類別")
            .replace("missing", "缺少資料")
        )
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return tuple(result)


def aggregate_fold_warnings(warnings: Iterable[str], total_folds: int = 10) -> tuple[str, ...]:
    """Aggregate repeated Walk-forward fold warnings into a single concise notice."""
    raw_warnings = list(warnings)
    if not raw_warnings:
        return ()
    no_trade_matches = [
        w
        for w in raw_warnings
        if "no trade" in w.lower() or "無交易" in w or "0 筆交易" in w or "0 trades" in w.lower()
    ]
    other_warnings = [w for w in raw_warnings if w not in no_trade_matches]
    result: list[str] = []
    if len(no_trade_matches) >= 2:
        result.append(
            f"共 {len(no_trade_matches)} 個 Walk-forward fold 於樣本期間內無交易紀錄；請檢查進出場門檻或資料長度。"
        )
    elif no_trade_matches:
        result.extend(no_trade_matches)
    result.extend(deduplicate_warnings(other_warnings))
    return tuple(result)


def get_next_trading_date(market: str = "TWSE", as_of_date: str | None = None) -> str | None:
    """Derive the next valid trading date strictly from official verified calendars.

    Returns None ('無法判定') if the calendar is insufficient or does not contain
    a subsequent date. Never uses weekday or naive calendar guessing.
    """
    try:
        from stock_tool.application.prediction_lab import MarketTradingCalendar

        calendar = MarketTradingCalendar.default_for(market)
        dates = calendar.dates
        if not dates:
            return None
        target_ref = as_of_date or datetime.now(UTC).strftime("%Y-%m-%d")
        for d in dates:
            if d > target_ref:
                return d
        return None
    except Exception:
        return None


KNOWN_TAIWAN_COMPANIES: Mapping[str, str] = {
    "2330": "台積電",
    "2454": "聯發科",
    "2303": "聯電",
    "3711": "日月光投控",
    "2382": "廣達",
    "3231": "緯創",
    "6669": "緯穎",
    "2317": "鴻海",
    "6488": "環球晶",
    "3105": "穩懋",
    "2308": "台達電",
    "2412": "中華電",
    "2881": "富邦金",
    "2882": "國泰金",
    "2891": "中信金",
    "1301": "台塑",
    "1303": "南亞",
    "2002": "中鋼",
    "2603": "長榮",
    "2609": "陽明",
    "TAIEX": "發行量加權股價指數",
    "OTC": "櫃買指數",
}


def _is_english_or_provider_name(name: str) -> bool:
    """Detect if a company name is an English/provider ASCII name rather than localized Chinese."""
    if not name:
        return True
    for ch in name:
        if "\u4e00" <= ch <= "\u9fff":
            return False
    return True


def format_taiwan_company_display(
    symbol: str,
    company_name: str | None = None,
    market: str = "TWSE",
) -> str:
    """Format Taiwan stock display prioritizing Traditional Chinese company name over English provider names."""
    clean_symbol = str(symbol).strip().upper()
    clean_name = str(company_name or "").strip()
    if (
        not clean_name
        or clean_name == clean_symbol
        or clean_name.lower() == "none"
        or _is_english_or_provider_name(clean_name)
    ):
        known_name = KNOWN_TAIWAN_COMPANIES.get(clean_symbol)
        if known_name:
            return f"{known_name} ({clean_symbol})"

    if clean_name and clean_name != clean_symbol:
        if f"({clean_symbol})" not in clean_name:
            return f"{clean_name} ({clean_symbol})"
        return clean_name
    return clean_symbol


def translate_health_category(category: str) -> str:
    """Translate health evaluation category names into Traditional Chinese."""
    text = str(category).strip().lower()
    categories = {
        "diversification": "持股分散度",
        "valuation": "估值覆蓋與健康度",
        "fundamental_health": "基本面健康度",
        "volatility": "波動度與風險",
        "liquidity": "流動性與覆蓋",
        "coverage": "資料涵蓋率",
        "data_quality": "資料品質",
    }
    return categories.get(text, str(category))


def translate_health_reason(reason: str) -> str:
    """Translate common English risk and health evaluation reasons into Traditional Chinese."""
    text = str(reason).strip()
    translations = {
        "single stock concentration exceeds threshold": "單一持股集中度高於建議門檻",
        "missing price data for position": "部分持股缺少最新價格資料",
        "insufficient historical data for volatility calculation": "歷史資料不足以計算年化波動度",
        "missing fundamental data for valuation": "缺少基本面資料，無法進行完整估值評估",
        "portfolio diversification is low": "持股過度集中於單一產業或標的",
        "fx rate is missing or stale": "缺少最新匯率或匯率已過期",
    }
    for eng, zh in translations.items():
        if eng in text.lower():
            return zh
    return text
