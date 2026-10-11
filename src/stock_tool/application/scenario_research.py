"""Synthetic-only Scenario Research v1. No formal real-data execution gate is open."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
from math import isfinite
from typing import Any

import pandas as pd

from stock_tool.backtest.broker import BrokerConfig
from stock_tool.backtest.engine import BacktestEngine
from stock_tool.data.corporate_actions import PricePolicy, raw_research_safety_errors
from stock_tool.data.universe import HistoricalUniverse, UniverseMembership
from stock_tool.domain.models import Market, Symbol
from stock_tool.strategies.base import StrategyBase

ALGORITHM = "breakout-confirmation-v1"
LABEL = "合成工程驗證；不是正式研究或策略有效性證據"
FIELDS = ("date", "market", "symbol", "open", "high", "low", "close", "volume")


class ScenarioBlocked(ValueError):
    """An explicit qualification or execution failure; never a zero-return result."""


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


@dataclass(frozen=True)
class Rules:
    N: int = 20
    A: int = 14
    V: int = 20
    F: int = 20
    S: int = 5
    B: float = 0.0
    M: float = 1.5
    K: float = 1.0
    E: int = 10
    H: int = 40
    R: int = 2

    def __post_init__(self) -> None:
        for key in ("N", "A", "V", "F", "S", "E", "H", "R"):
            x = getattr(self, key)
            if type(x) is not int or x < 1 or (key == "H" and x < 2):
                raise ScenarioBlocked(f"invalid integer parameter: {key}")
        for key in ("B", "M", "K"):
            x = getattr(self, key)
            if type(x) not in (int, float) or not isfinite(x) or x < 0:
                raise ScenarioBlocked(f"invalid parameter: {key}")
            if key != "B" and x == 0:
                raise ScenarioBlocked(f"zero parameter: {key}")

    @property
    def warmup(self) -> int:
        return max(self.N, self.A + 1, self.V, self.F + self.S - 1, self.E)


def qualify(request: dict) -> pd.DataFrame:
    """Shared gate for adapter, single/fold execution, save, load and replay.

    A synthetic declaration never grants real qualification. All real execution
    is disabled in this release, even if imported metadata says 'verified'.
    """
    if request.get("purpose") != "synthetic_validation":
        raise ScenarioBlocked("正式研究未開放；真實資料資格仍 incomplete")
    identity = request.get("identity", {})
    if (
        identity.get("type") != "ordinary_share"
        or identity.get("market") not in {"TWSE", "TPEX", "US"}
        or not str(identity.get("symbol", "")).startswith("SYNTH_")
    ):
        raise ScenarioBlocked("僅允許明確 SYNTH_ 合成普通股身分")
    rules = Rules(**request["rules"])
    frame = pd.DataFrame(request["prices"])
    if frame.empty or set(frame.columns) != set(FIELDS):
        raise ScenarioBlocked("缺少完整 OHLCV／身分，或有未授權輸入欄位")
    for x in frame.date:
        if type(x) is not str or date.fromisoformat(x).isoformat() != x:
            raise ScenarioBlocked("invalid date")
    if frame.date.duplicated().any() or not frame.date.is_monotonic_increasing:
        raise ScenarioBlocked("日期重複或未排序")
    if (
        not frame.market.eq(identity["market"]).all()
        or not frame.symbol.eq(identity["symbol"]).all()
    ):
        raise ScenarioBlocked("身分不符")
    for key in ("open", "high", "low", "close", "volume"):
        if not frame[key].map(lambda x: type(x) in (int, float) and isfinite(x) and x > 0).all():
            raise ScenarioBlocked(f"invalid {key}")
    if (frame.high < frame[["open", "close", "low"]].max(axis=1)).any() or (
        frame.low > frame[["open", "close", "high"]].min(axis=1)
    ).any():
        raise ScenarioBlocked("OHLC relationship invalid")
    start, end = request["evaluation_start"], request["evaluation_end"]
    if start > end or end != frame.date.iloc[-1] or start not in set(frame.date):
        raise ScenarioBlocked("評估範圍不符")
    if sum(frame.date < start) != rules.warmup:
        raise ScenarioBlocked("必須提供精確完整暖機")
    q = request.get("qualification", {})
    expected = {
        "identity": identity,
        "warmup_start": frame.date.iloc[0],
        "evaluation_start": start,
        "evaluation_end": end,
        "prices_digest": digest(request["prices"]),
        "algorithm": ALGORITHM,
    }
    if q.get("binding") != expected:
        raise ScenarioBlocked("qualification identity/range/data/version mismatch")
    if q.get("status") != "synthetic_only" or q.get("source") != "deterministic_fixture":
        raise ScenarioBlocked("合成資格不可升格 verified；來源缺漏")
    if q.get("calendar") != frame.date.tolist() or q.get("initial_state") != "listed_unrestricted":
        raise ScenarioBlocked("交易日或期初狀態不足")
    if q.get("actions") != [] or q.get("coverage") != "synthetic_only":
        raise ScenarioBlocked("公司行動資格不足或存在未處理事件")
    errors = raw_research_safety_errors(
        frame, price_policy=PricePolicy.RAW_PRICE_WITH_EXPLICIT_ACTIONS
    )
    if errors:
        raise ScenarioBlocked("; ".join(errors))
    allocation, cash = request["allocation"], request["initial_cash"]
    if (
        type(allocation) not in (int, float)
        or not isfinite(allocation)
        or not 0 < allocation <= 1
        or type(cash) not in (int, float)
        or not isfinite(cash)
        or cash <= 0
    ):
        raise ScenarioBlocked("invalid sizing/cash")
    costs = request["costs"]
    if set(costs) != {"commission_rate", "tax_rate", "slippage_rate", "min_commission"}:
        raise ScenarioBlocked("unsupported execution setting")
    if any(type(x) not in (int, float) or not isfinite(x) or x < 0 for x in costs.values()):
        raise ScenarioBlocked("invalid costs")
    return frame


def evaluate(request: dict) -> dict:
    """Causal common-case builder; deliberately stateless across evaluation windows."""
    f = qualify(request)
    r = Rules(**request["rules"])
    tr = pd.concat(
        [f.high - f.low, (f.high - f.close.shift()).abs(), (f.low - f.close.shift()).abs()], axis=1
    ).max(axis=1)
    atr = tr.rolling(r.A).mean().shift()
    peak = f.high.rolling(r.N).max().shift()
    volume = f.volume.rolling(r.V).mean().shift()
    sma = f.close.rolling(r.F).mean()
    floor = f.low.rolling(r.E).min().shift()
    cases: list[dict] = []
    rows: list[dict] = []
    state, reset, active = "READY", 0, None
    common = asdict(r)
    common.pop("M")
    for i in range(r.warmup, len(f)):
        today, close = f.date.iloc[i], float(f.close.iloc[i])
        row = {
            "date": today,
            "state_before": state,
            "case_id": None,
            "control": 0,
            "confirmation": 0,
            "reason": None,
        }
        if not all(
            isfinite(float(x))
            for x in [
                atr.iloc[i],
                peak.iloc[i],
                volume.iloc[i],
                sma.iloc[i],
                sma.iloc[i - r.S],
                floor.iloc[i],
            ]
        ):
            raise ScenarioBlocked("indicator unavailable")
        if atr.iloc[i] <= 0 or volume.iloc[i] <= 0:
            raise ScenarioBlocked("ATR/volume denominator unavailable")
        if state == "RESET_WAIT":
            assert active is not None
            reset = reset + 1 if close <= active["Q0"] else 0
            if reset >= r.R:
                state = "READY"
        elif state == "ACTIVE":
            assert active is not None
            reason = (
                "BREAKOUT_FAILED"
                if close < active["L0"]
                else (
                    "TRAILING_RANGE_EXIT"
                    if close < floor.iloc[i]
                    else "EXPIRED" if i - active["index"] + 1 >= r.H else None
                )
            )
            row["case_id"] = active["case_id"]
            if reason:
                active.update(status=reason, termination_date=today)
                row.update(control=-1, confirmation=-1 if active["confirmed"] else 0, reason=reason)
                state, reset = "RESET_WAIT", 0
        else:
            q = float(peak.iloc[i] + r.B * atr.iloc[i])
            if f.close.iloc[i - 1] <= q < close:
                frozen = {
                    "P0": float(peak.iloc[i]),
                    "ATR0": float(atr.iloc[i]),
                    "Q0": q,
                    "U0": float(volume.iloc[i]),
                    "L0": float(peak.iloc[i] - r.K * atr.iloc[i]),
                }
                case_id = digest(
                    {
                        "identity": request["identity"],
                        "evaluation_start": request["evaluation_start"],
                        "warmup_start": f.date.iloc[0],
                        "t0": today,
                        "common_rule_version": ALGORITHM,
                        "common_parameters": common,
                        "causal_prefix_digest": digest(request["prices"][: i + 1]),
                    }
                )
                flags = {
                    "volume": bool(f.volume.iloc[i] > r.M * volume.iloc[i]),
                    "above_sma": bool(close > sma.iloc[i]),
                    "rising_sma": bool(sma.iloc[i] > sma.iloc[i - r.S]),
                }
                valid = frozen["L0"] > 0
                confirmed = valid and all(flags.values())
                active = {
                    **frozen,
                    "case_id": case_id,
                    "index": i,
                    "t0": today,
                    "flags": flags,
                    "confirmed": confirmed,
                    "evidence": {
                        "close": close,
                        "previous_close": float(f.close.iloc[i - 1]),
                        "volume": float(f.volume.iloc[i]),
                        "volume_threshold": float(r.M * volume.iloc[i]),
                        "sma": float(sma.iloc[i]),
                        "previous_sma": float(sma.iloc[i - r.S]),
                    },
                    "condition": (
                        "INVALID" if not valid else "PASS" if confirmed else "FILTERED_OUT"
                    ),
                    "status": "ACTIVE" if valid else "INVALID_SCALE",
                    "termination_date": None if valid else today,
                }
                cases.append(active)
                row.update(
                    case_id=case_id,
                    control=int(valid),
                    confirmation=int(confirmed),
                    reason="BREAKOUT" if valid else "INVALID_SCALE",
                )
                state, reset = ("ACTIVE" if valid else "RESET_WAIT"), 0
        row.update(state_after=state, reset_count=reset)
        rows.append(row)
    if state == "ACTIVE":
        assert active is not None
        active["status"] = "RIGHT_CENSORED"
    return {"label": LABEL, "cases": cases, "timeline": rows}


class BreakoutConfirmationAdapter(StrategyBase):
    """Only the gated service creates this adapter; no production registry exposure."""

    name = ALGORITHM

    def __init__(self, request: dict, variant: str):
        self.request = json.loads(canonical(request))
        self.variant = variant
        self.validate_parameters()

    def validate_parameters(self) -> None:
        qualify(self.request)
        if self.variant not in {"control", "confirmation"}:
            raise ScenarioBlocked("unknown variant")

    def generate_signals(
        self, price_data: pd.DataFrame, fundamentals: pd.DataFrame | None = None
    ) -> pd.DataFrame:
        if fundamentals is not None:
            raise ScenarioBlocked("fundamentals outside this scope")
        self.validate_parameters()
        if digest(price_data.to_dict("records")) != digest(
            pd.DataFrame(self.request["prices"]).to_dict("records")
        ):
            raise ScenarioBlocked("adapter input changed")
        evidence = evaluate(self.request)
        return pd.DataFrame(
            [
                {
                    "date": row["date"],
                    "symbol": self.request["identity"]["symbol"],
                    "signal": row[self.variant],
                    "reason": row["reason"] or "no_signal",
                    "quantity": None,
                    "cash_amount": None,
                    "target_percent": (
                        self.request["allocation"] if row[self.variant] == 1 else None
                    ),
                }
                for row in evidence["timeline"]
            ],
            dtype=object,
        )


def serialize(value: Any) -> Any:
    """Serialize exposed engine evidence, retaining legitimate infinite metrics explicitly."""
    if isinstance(value, pd.DataFrame):
        return serialize(value.to_dict("records"))
    if hasattr(value, "__dataclass_fields__"):
        return serialize(asdict(value))
    if isinstance(value, dict):
        return {str(k): serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize(v) for v in value]
    if isinstance(value, float) and not isfinite(value):
        if pd.isna(value):
            raise ScenarioBlocked("NaN in execution evidence")
        return {"metric_infinity": "+" if value > 0 else "-"}
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def run(request: dict) -> dict:
    f = qualify(request)
    evidence = evaluate(request)
    identity = request["identity"]
    universe = HistoricalUniverse(
        (
            UniverseMembership(
                Symbol.parse(identity["symbol"], market=Market.parse(identity["market"])),
                f.date.iloc[0],
                f.date.iloc[-1],
                "listed",
                "deterministic_fixture",
                "complete",
            ),
        ),
        "complete",
        "deterministic_fixture; synthetic only",
    )
    results = {}
    for variant in ("control", "confirmation"):
        signals = BreakoutConfirmationAdapter(request, variant).generate_signals(f)
        engine = BacktestEngine(
            initial_cash=request["initial_cash"],
            broker_config=BrokerConfig(**request["costs"]),
            point_in_time_mode="strict",
            historical_universe=universe,
        )
        result = engine.run(f.loc[f.date >= request["evaluation_start"]], signals)
        # Keep execution and scenario axes separate, linked by actual order IDs.
        case_execution = []
        for case in evidence["cases"]:
            orders = [
                o
                for o in result.orders
                if o.signal_date == case["t0"]
                or (
                    case["termination_date"] is not None
                    and o.signal_date == case["termination_date"]
                )
            ]
            fills = [t for t in result.trades if t.order_id in {o.order_id for o in orders}]
            bought = sum(t.quantity for t in fills if t.side == "buy")
            sold = sum(t.quantity for t in fills if t.side == "sell")
            # A prior position/pending entry reaching another case is not silently pyramided.
            older = [
                t
                for t in result.trades
                if t.execution_date <= case["t0"] and t.signal_date < case["t0"]
            ]
            older_quantity = sum(t.quantity if t.side == "buy" else -t.quantity for t in older)
            if older_quantity != 0:
                raise ScenarioBlocked("執行稽核：新案例開始時仍有前案持倉")
            if any(o.status == "pending" and o.signal_date < case["t0"] for o in result.orders):
                raise ScenarioBlocked("執行稽核：前案訂單仍待成交")
            case_execution.append(
                {
                    "case_id": case["case_id"],
                    "orders": serialize(orders),
                    "fills": serialize(fills),
                    "position": "none" if not bought else "closed" if sold == bought else "open",
                }
            )
        results[variant] = {
            "signals": serialize(signals),
            "execution": serialize(result),
            "case_execution": case_execution,
            "counts": {
                "cases": len(evidence["cases"]),
                "buy_signals": int(signals.signal.eq(1).sum()),
                "sell_signals": int(signals.signal.eq(-1).sum()),
                "fill_count": len(result.trades),
                "closed_round_trip_count": result.metrics.closed_round_trip_count,
                "rejected": len(result.rejected_orders),
                "pending": sum(o.status == "pending" for o in result.orders),
                "open_positions": len(result.portfolio.positions),
            },
        }
    return {
        "label": LABEL,
        "qualification": "synthetic_only",
        "formal_research": False,
        "run_input_digest": digest(request),
        "evidence": evidence,
        "variants": results,
    }


def run_windows(requests: list[dict]) -> list[dict]:
    """Synthetic OOS isolation check only, not formal walk-forward performance."""
    for request in requests:
        qualify(request)
    for previous, current in zip(requests, requests[1:]):
        if previous["evaluation_end"] >= current["evaluation_start"]:
            raise ScenarioBlocked("overlapping or unordered evaluation windows")
        keys = ("identity", "rules", "allocation", "initial_cash", "costs")
        if any(previous[k] != current[k] for k in keys):
            raise ScenarioBlocked("window settings changed")
    return [run(request) for request in requests]
