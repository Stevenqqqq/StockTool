"""Official display names, separate from positions, prices and saved research.

Company directories cover stocks only. Raw exchange quote directories supply
security names (including ETFs); they never infer instrument type or valuation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stock_tool.application.market_monitor import OFFICIAL_ENDPOINTS, UNIVERSE_ENDPOINTS


@dataclass(frozen=True)
class InstrumentName:
    market: str
    symbol: str
    name: str
    full_name: str
    source: str
    data_date: str
    fetched_at: str


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or (parsed - datetime.now(timezone.utc)).total_seconds() > 300:
        raise ValueError("名稱快取時間不符")
    return parsed


def parse_names(payload: object, market: str, kind: str, now: str) -> dict[str, InstrumentName]:
    """Reject malformed/ambiguous batches; never accept partial HTTP bodies."""
    if market not in OFFICIAL_ENDPOINTS or kind not in {"companies", "quotes"}:
        raise ValueError("不支援的名稱來源")
    if not isinstance(payload, list) or not payload:
        raise ValueError("官方名稱回應為空或格式不符")
    source = (UNIVERSE_ENDPOINTS if kind == "companies" else OFFICIAL_ENDPOINTS)[market]
    result: dict[str, InstrumentName] = {}
    for row in payload:
        if not isinstance(row, dict):
            raise ValueError("官方名稱列格式不符")
        symbol = (
            str(
                row.get("公司代號", row.get("SecuritiesCompanyCode", row.get("Code", "")))
                if kind == "companies"
                else row.get("Code", row.get("SecuritiesCompanyCode", ""))
            )
            .strip()
            .upper()
        )
        name = str(
            row.get("公司簡稱", row.get("CompanyAbbreviation", row.get("CompanyName", "")))
            if kind == "companies"
            else row.get("Name", row.get("CompanyName", ""))
        ).strip()
        full_name = (
            str(row.get("公司名稱", row.get("CompanyName", ""))).strip()
            if kind == "companies"
            else ""
        )
        if not re.search(r"[\u4e00-\u9fff]", name) and re.search(r"[\u4e00-\u9fff]", full_name):
            name = full_name
        if not re.fullmatch(r"[0-9][0-9A-Z]{3,11}", symbol) or not name:
            raise ValueError("官方名稱缺少代號或名稱")
        declared_market = row.get("Market", market)
        if declared_market != market:
            raise ValueError("官方名稱市場衝突")
        # Some official securities have Latin-only names. Do not translate them.
        if not re.search(r"[\u4e00-\u9fff]", name):
            continue
        record = InstrumentName(
            market,
            symbol,
            name,
            full_name,
            source,
            str(row.get("出表日期", row.get("Date", "未提供"))),
            now,
        )
        if symbol in result and result[symbol] != record:
            raise ValueError("官方名稱重複且衝突")
        result[symbol] = record
    if not result:
        raise ValueError("沒有可確認的中文名稱")
    return result


class NameDirectory:
    """One runtime-scoped cache. Rendering only reads immutable name records."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.records: dict[str, dict[str, InstrumentName]] = {}
        self.errors: dict[str, str] = {}
        self.attempted: dict[str, str] = {}
        self.running = False
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            data = envelope["data"]
            if envelope["sha256"] != _digest(data) or data["version"] != 1:
                raise ValueError("名稱快取驗證失敗")
            loaded: dict[str, dict[str, InstrumentName]] = {}
            for key, rows in data["records"].items():
                market, kind = key.split(":")
                endpoint = (UNIVERSE_ENDPOINTS if kind == "companies" else OFFICIAL_ENDPOINTS)[
                    market
                ]
                if kind not in {"companies", "quotes"}:
                    raise ValueError("名稱來源種類不符")
                loaded[key] = {}
                for symbol, raw in rows.items():
                    item = InstrumentName(**raw)
                    if item.market != market or item.symbol != symbol or item.source != endpoint:
                        raise ValueError("名稱快取身分不符")
                    if not item.name or not re.search(r"[\u4e00-\u9fff]", item.name):
                        raise ValueError("名稱快取內容不符")
                    _timestamp(item.fetched_at)
                    loaded[key][symbol] = item
            if not isinstance(data["errors"], dict) or not isinstance(data["attempted"], dict):
                raise ValueError("名稱快取狀態不符")
            for stamp in data["attempted"].values():
                _timestamp(stamp)
            if not all(isinstance(value, str) for value in data["errors"].values()):
                raise ValueError("名稱快取錯誤內容不符")
            self.records = loaded
            self.errors = data["errors"]
            self.attempted = data["attempted"]
        except FileNotFoundError:
            pass
        except (ValueError, TypeError, KeyError, OSError, AttributeError):
            self.errors["cache"] = "名稱快取無法確認，正在重新取得；不使用損毀內容。"

    def resolve(self, market: str, symbol: str) -> tuple[InstrumentName | None, str]:
        market, symbol = market.strip().upper(), symbol.strip().upper()
        if market not in OFFICIAL_ENDPOINTS:
            return None, ""
        with self.lock:
            company = self.records.get(f"{market}:companies", {}).get(symbol)
            quote = self.records.get(f"{market}:quotes", {}).get(symbol)
            record = company or quote
            if record is None:
                return None, "中文名稱未確認"
            if "cache" in self.errors:
                return record, self.errors["cache"]
            key = f"{market}:{'companies' if company else 'quotes'}"
            if company and quote and company.name != quote.name:
                return company, "官方名稱來源不一致，暫保留公司名單名稱待核對"
            age = (
                datetime.now(timezone.utc) - datetime.fromisoformat(record.fetched_at)
            ).total_seconds()
            if key in self.errors or age > 86400:
                return (
                    record,
                    f"沿用前次確認名稱（取得 {record.fetched_at[:10]}）；不代表行情或研究已更新",
                )
            return record, ""

    def refresh(self, fetch: Any = None, *, force: bool = False) -> None:
        """Update independent sources; failed sources retain their last good names."""
        fetch = fetch or _fetch
        now = datetime.now(timezone.utc)
        for market in OFFICIAL_ENDPOINTS:
            for kind, endpoints in (
                ("companies", UNIVERSE_ENDPOINTS),
                ("quotes", OFFICIAL_ENDPOINTS),
            ):
                key = f"{market}:{kind}"
                with self.lock:
                    last = self.attempted.get(key)
                    delay = 300 if key in self.errors else 86400
                    if (
                        not force
                        and last
                        and (now - datetime.fromisoformat(last)).total_seconds() < delay
                    ):
                        continue
                try:
                    names = parse_names(fetch(endpoints[market]), market, kind, now.isoformat())
                    with self.lock:
                        self.records.setdefault(key, {}).update(names)
                        self.errors.pop(key, None)
                except Exception as exc:
                    with self.lock:
                        self.errors[key] = (
                            f"官方名稱更新失敗（{type(exc).__name__}），保留已確認結果"
                        )
                with self.lock:
                    self.attempted[key] = now.isoformat()
                    try:
                        self.errors.pop("cache", None)
                        self._save()
                    except OSError:
                        self.errors["cache"] = "名稱快取未能保存；目前名稱只在本次開啟有效"

    def _save(self) -> None:
        data = {
            "version": 1,
            "records": {
                key: {s: asdict(r) for s, r in rows.items()} for key, rows in self.records.items()
            },
            "errors": self.errors,
            "attempted": self.attempted,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump({"data": data, "sha256": _digest(data)}, file, ensure_ascii=False)
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def start_refresh(self) -> None:
        with self.lock:
            if self.running:
                return
            now = datetime.now(timezone.utc)
            keys = [f"{m}:{k}" for m in OFFICIAL_ENDPOINTS for k in ("companies", "quotes")]
            if all(
                key in self.attempted
                and 0
                <= (now - datetime.fromisoformat(self.attempted[key])).total_seconds()
                < (300 if key in self.errors else 86400)
                for key in keys
            ):
                return
            self.running = True

        def run() -> None:
            try:
                self.refresh()
            finally:
                self.running = False

        threading.Thread(target=run, daemon=True, name="official-instrument-names").start()


def _fetch(url: str) -> object:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "StockTool/1.4.3",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
    )
    # Default TLS verification stays enabled; truncated responses raise and are rejected.
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read())


_directories: dict[Path, NameDirectory] = {}
_directories_lock = threading.Lock()


def directory_for(path: Path) -> NameDirectory:
    path = path.resolve()
    with _directories_lock:
        if path not in _directories:
            _directories[path] = NameDirectory(path)
        return _directories[path]
