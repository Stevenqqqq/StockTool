"""Private daily holdings projection; reuse canonical prices, valuation and signals.

This projection is independent of market-wide brief completeness. Failed symbols
keep their own last successful baseline; they cannot resolve a previous signal.
No model, provider credentials, or user-input mutation belongs to this module.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, time
import hashlib
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from stock_tool.application.completed_daily_prices import completed_daily_prices
from stock_tool.application.daily_brief import DailyBriefService
from stock_tool.application.daily_research_loop import (
    DailyResearchLoopService,
    DailyResearchSnapshot,
    DailyResearchSource,
)
from stock_tool.application.holding_analysis import (
    build_holding_analysis,
    holding_fx_is_usable,
    validated_holding_prices,
)
from stock_tool.application.holding_identity import load_identity_state
from stock_tool.application.prediction_lab import MarketTradingCalendar
from stock_tool.portfolio_valuation import (
    FxQuote,
    PortfolioValuationService,
    StaticFxRateProvider,
)
from stock_tool.runtime_paths import RuntimePaths
from stock_tool.portfolio_management import normalize_portfolio


def fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def positions_fingerprint(positions: pd.DataFrame) -> str:
    normalized = normalize_portfolio(positions)
    normalized[["quantity", "average_cost"]] = normalized[["quantity", "average_cost"]].astype(
        float
    )
    return fingerprint(normalized.fillna("").to_dict("records"))


def report_path(paths: RuntimePaths) -> Path:
    return paths.data_dir / "daily_holdings_v1.json"


def holding_close_is_completed(row: dict[str, Any], *, now: datetime) -> bool:
    """Do not trust a pre-fix saved close merely because its file hash is valid."""
    quotes = [datum for datum in row.get("data", []) if datum.get("label") == "收盤價"]
    if not quotes:
        return True  # An unavailable holding without a quoted close stays visible.
    frame = pd.DataFrame(
        {"date": datum.get("as_of"), "fetched_at": datum.get("fetched_at")} for datum in quotes
    )
    completed, _ = completed_daily_prices(frame, market=row["market"], now=now)
    return len(completed) == len(frame)


def load_report(paths: RuntimePaths) -> dict[str, Any] | None:
    path = report_path(paths)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        digest = payload.pop("fingerprint")
        if payload["schema"] != 1 or fingerprint(payload) != digest:
            raise ValueError("daily holdings integrity mismatch")
        timestamp = datetime.fromisoformat(payload["checked_at"])
        if timestamp.tzinfo is None:
            raise ValueError("daily holdings timestamp lacks timezone")
        for identity, row in payload["holdings"].items():
            if identity != f"{row['market']}:{row['symbol']}":
                raise ValueError("daily holdings identity mismatch")
            if row.get("baseline"):
                snapshot = DailyResearchSnapshot.from_dict(row["baseline"])
                if any(event.identity not in {None, identity} for event in snapshot.events):
                    raise ValueError("daily holdings baseline identity mismatch")
            if any(
                event["identity"] != identity for event in (*row["events"], *row["previous_events"])
            ):
                raise ValueError("daily holdings event identity mismatch")
        return payload
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ValueError("每日持股結果無法驗證；保留原檔，不當成首次基準。") from exc


def due_key(markets: list[str], now: datetime) -> str:
    """Use bundled exchange dates and a conservative post-close publication buffer.

    Calendar gaps stay explicit; a daily fallback requests data without declaring
    the day an exchange session or weakening the quote freshness gate.
    """
    result = {}
    for market in sorted(set(markets)):
        local = now.astimezone(ZoneInfo("America/New_York" if market == "US" else "Asia/Taipei"))
        try:
            dates = MarketTradingCalendar.default_for(market, year=local.year).dates
            cutoff = time(18) if market == "US" else time(18, 30)
            eligible = [
                d
                for d in dates
                if d < local.date().isoformat()
                or (d == local.date().isoformat() and local.time() >= cutoff)
            ]
            result[market] = eligible[-1] if eligible else f"calendar-gap:{local.date()}"
        except ValueError:
            result[market] = f"calendar-gap:{local.date()}"
    return fingerprint(result)


def publish_holdings(
    paths: RuntimePaths,
    positions: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    now: datetime,
    fx_quote: FxQuote | None,
    failed: set[str],
) -> dict[str, Any]:
    """Publish one atomic per-symbol projection after the existing refresh stage."""
    # Import the existing atomic writer lazily to avoid an orchestration cycle.
    from stock_tool.application.daily_research_scheduler import _atomic_json_write

    previous = load_report(paths)
    identities = load_identity_state(paths.data_dir / "holding_identity.json")
    profiles = identities.get("profiles", {})
    profiles = {key: dict(value) for key, value in profiles.items()}
    for key, kind in identities.get("overrides", {}).items():
        profiles.setdefault(key, {})["instrument_type"] = kind
    valid_prices = validated_holding_prices(positions, prices, profiles, now=now)
    quote = fx_quote if holding_fx_is_usable(fx_quote, now=now) else None
    valuation = PortfolioValuationService(StaticFxRateProvider([quote] if quote else [])).value(
        positions=positions,
        prices=valid_prices,
    )
    rows: dict[str, Any] = {}
    for position in positions.to_dict("records"):
        symbol, market = str(position["symbol"]), str(position["market"])
        identity = f"{market}:{symbol}"
        profile = profiles.get(f"{symbol}|{market}", {})
        if profile.get("symbol", symbol) != symbol or profile.get("market", market) != market:
            profile = {}
        kind = profile.get("instrument_type", "未確認")
        prior = (previous or {}).get("holdings", {}).get(identity)
        if prior and not holding_close_is_completed(prior, now=now):
            prior = None  # Never compare a completed close against a saved intraday baseline.
        if prior and prior["instrument_type"] != kind:
            prior = None  # Never compare across an instrument-type correction.
        holding = build_holding_analysis(
            position,
            prices=prices,
            fx_quote=quote,
            profile=profile,
            refresh_failed=identity in failed,
            now=now,
        )
        price = next((d for d in holding.data if d.label == "收盤價" and d.status == "可用"), None)
        selected = (
            valid_prices.loc[(valid_prices.symbol == symbol) & (valid_prices.market == market)]
            if valid_prices is not None and not valid_prices.empty
            else pd.DataFrame()
        )
        events: list[dict[str, Any]] = []
        baseline = prior.get("baseline") if prior else None
        status = "保留前次結果" if prior else "資料不足"
        signal_fingerprint = prior.get("signal_fingerprint") if prior else None
        if price is not None and not selected.empty and identity not in failed:
            # Metadata polling times do not constitute economic changes.
            signal_fingerprint = fingerprint(
                selected[
                    [c for c in ("date", "open", "high", "low", "close", "volume") if c in selected]
                ]
                .astype(str)
                .to_dict("records")
            )
            if prior and prior.get("signal_fingerprint") == signal_fingerprint:
                status = (
                    "資料恢復" if prior["status"] in {"保留前次結果", "資料不足"} else "無新變化"
                )
                events = prior.get("events", [])  # Keep unread daily changes on duplicate refresh.
            else:
                one = pd.DataFrame([position])
                brief = DailyBriefService(max_attention_items=100).build(
                    portfolio=one,
                    watchlist=None,
                    prices=selected,
                    valuation=None,
                    continuations=(),
                    reference_at=now.isoformat(),
                )
                source_type = str(selected.iloc[-1].get("source_type") or "未提供")
                source = DailyResearchSource(
                    price.source, source_type, symbol, price.as_of, price.fetched_at
                )
                result = DailyResearchLoopService(max_priority_events=100).complete_success(
                    brief=brief,
                    previous_snapshot=(
                        DailyResearchSnapshot.from_dict(baseline) if baseline else None
                    ),
                    successful_at=now.isoformat(),
                    sources={identity: source},
                )
                status = "首次基準" if baseline is None else "已更新"
                # Data repair / aggregate completeness is not a company event.
                events = [
                    {**asdict(event), "why_important": signal_reason(event.code)}
                    for event in result.priority_events
                    if event.identity == identity
                    and event.category != "data_repair"
                    and event.code
                    in {"daily_move", "volume_spike", "range_breakout_high", "range_breakout_low"}
                ]
                baseline = result.snapshot.to_dict() if result.snapshot else baseline
        valued = valuation.positions.loc[
            (valuation.positions.symbol == symbol) & (valuation.positions.market == market)
        ]
        weight = valued.iloc[0]["weight"] if not valued.empty else None
        weight = float(weight) if weight is not None and pd.notna(weight) else None
        rows[identity] = {
            "symbol": symbol,
            "market": market,
            "instrument_type": kind,
            "status": status,
            "checked_at": now.isoformat(),
            "baseline": baseline,
            "signal_fingerprint": signal_fingerprint,
            "events": events,
            "previous_events": (
                (prior.get("events") or prior.get("previous_events", []))
                if prior and status in {"保留前次結果", "資料不足"}
                else []
            ),
            "data": [asdict(d) for d in holding.data],
            "gaps": list(holding.gaps),
            "weight": weight,
            "company_scope": (
                "ETF 成分與基金文件未在每日流程更新。"
                if kind == "ETF"
                else "每日流程未重新蒐集公司文件；行情變化不代表營運原因已確認，請進入公司研究核對來源。"
            ),
        }
    payload = {
        "schema": 1,
        "checked_at": now.isoformat(),
        "positions_fingerprint": positions_fingerprint(positions),
        "due_key": due_key([str(v) for v in positions.market], now),
        "holdings": rows,
        "fx": asdict(quote) if quote else None,
    }
    _atomic_json_write(report_path(paths), {**payload, "fingerprint": fingerprint(payload)})
    return payload


def next_observation(code: str) -> str:
    return {
        "daily_move": "觀察下一交易日漲跌與成交量是否延續；原因須另核對公司公告。",
        "volume_spike": "觀察後續成交量是否回落，以及價格方向是否一致。",
        "range_breakout_high": "觀察後續收盤是否仍高於原區間；不等同買進訊號。",
        "range_breakout_low": "觀察後續收盤是否回到原區間，並核對公司最新公開資訊。",
    }.get(code, "回到研究頁核對來源與尚未確認事項。")


def signal_reason(code: str) -> str:
    return {
        "daily_move": "單日漲跌已達既有規則的注意門檻，會影響持股市值；行情本身不能證明漲跌原因。",
        "volume_spike": "成交量達既有規則的放量門檻，交易活躍程度改變；不代表資金流向已確認。",
        "range_breakout_high": "收盤高於近期收盤區間，價格位置改變；不代表漲勢一定延續。",
        "range_breakout_low": "收盤低於近期收盤區間，價格位置改變；不代表公司營運已惡化。",
    }[code]


def load_observations(paths: RuntimePaths) -> list[dict[str, Any]]:
    path = paths.data_dir / "daily_holdings_observations_v1.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        digest = payload.pop("fingerprint")
        if payload["schema"] != 1 or fingerprint(payload) != digest:
            raise ValueError("observation integrity mismatch")
        for row in payload["observations"]:
            if row["identity"] != row["event"]["identity"] or row["id"] != fingerprint(
                {key: value for key, value in row.items() if key not in {"id", "saved_at"}}
            ):
                raise ValueError("observation identity mismatch")
        return payload["observations"]
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ValueError("已保存的觀察無法驗證；保留原檔，不覆寫。") from exc


def save_observation(
    paths: RuntimePaths, row: dict[str, Any], event: dict[str, Any], *, now: datetime
) -> None:
    from stock_tool.application.daily_research_scheduler import _atomic_json_write

    identity = f"{row['market']}:{row['symbol']}"
    if event["identity"] != identity or event not in row["events"]:
        raise ValueError("觀察與持股證據不一致。")
    observation = {
        "identity": identity,
        "instrument_type": row["instrument_type"],
        "event": event,
        "next_observation": next_observation(event["code"]),
    }
    key = fingerprint(observation)
    observations = load_observations(paths)
    if any(item["id"] == key for item in observations):
        return
    observations.append({**observation, "id": key, "saved_at": now.isoformat()})
    payload = {"schema": 1, "observations": observations}
    _atomic_json_write(
        paths.data_dir / "daily_holdings_observations_v1.json",
        {**payload, "fingerprint": fingerprint(payload)},
    )
