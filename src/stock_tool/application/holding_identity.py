"""Bounded public instrument metadata, never an editor of private positions."""

from __future__ import annotations

from stock_tool.yfinance_runtime import configure_yfinance_cache

from typing import Any, Callable
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import tempfile


def load_identity_state(path: Path) -> dict[str, Any]:
    """Read only the new metadata store; never inspect a portfolio file."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return {}
        profiles = value.get("profiles", {})
        overrides = value.get("overrides", {})
        if not isinstance(profiles, dict) or not isinstance(overrides, dict):
            return {}
        return {
            "profiles": {key: item for key, item in profiles.items() if isinstance(item, dict)},
            "overrides": {
                key: item for key, item in overrides.items() if item in ("未確認", "股票", "ETF")
            },
        }
    except (OSError, ValueError):
        return {}


def save_identity_state(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def resolve_holding_identity(symbol: str) -> dict[str, object]:
    """Use provider matches rather than assume every Taiwan code is listed on TWSE."""
    raw = symbol.strip().upper()
    if raw.endswith(".TWO"):
        return fetch_holding_identity(raw[:-4], "TPEX")
    if raw.endswith(".TW"):
        return fetch_holding_identity(raw[:-3], "TWSE")
    markets = ("TWSE", "TPEX") if raw.isdigit() else ("US",)
    matches = []
    failures = []
    for market in markets:
        try:
            matches.append(fetch_holding_identity(raw, market))
        except Exception as exc:
            failures.append(type(exc).__name__)
            continue
    if len(matches) != 1:
        if not matches and any("SSL" in error for error in failures):
            raise ValueError("資料來源的安全連線驗證失敗；尚未確認標的，請稍後重試或手動選擇市場。")
        raise ValueError("無法唯一確認市場與代號；請選擇市場並核對標的名稱。")
    return matches[0]


def fetch_holding_identity(
    symbol: str, market: str, *, loader: Callable[[str], dict[str, Any]] | None = None
) -> dict[str, object]:
    """Resolve explicit market-qualified identifiers; reject mismatching provider identity."""
    suffix = {"TWSE": ".TW", "TPEX": ".TWO", "US": ""}.get(market)
    if suffix is None:
        raise ValueError("自訂市場需要人工確認標的身份。")
    symbol = symbol.strip().upper()
    query = symbol if symbol.endswith(suffix) and suffix else symbol + suffix
    if loader is None:
        import yfinance as yf

        def loader(value: str) -> dict[str, Any]:
            configure_yfinance_cache()
            return dict(yf.Ticker(value).get_info())

    info = loader(query)
    if str(info.get("symbol", "")).upper() != query:
        raise ValueError("資料來源回傳的標的身份不一致，未採用分類。")
    currency = str(info.get("currency", "")).upper()
    if currency not in {"USD", "TWD"}:
        raise ValueError("資料來源沒有提供可確認的報價幣別。")
    kind = {"ETF": "ETF", "EQUITY": "股票"}.get(str(info.get("quoteType", "")), "未確認")
    return {
        "symbol": symbol,
        "market": market,
        "name": str(info.get("longName") or info.get("shortName") or symbol),
        "currency": currency,
        "instrument_type": kind,
        "sector": str(info.get("sector") or ""),
        "industry": str(info.get("industry") or ""),
        "source": "Yahoo Finance",
        "fetched_at": datetime.now(UTC).isoformat(),
    }
