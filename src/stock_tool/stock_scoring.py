"""Composite stock scoring and local AI-style analysis summaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

ScoreValue = float | Literal["unknown"]

TECHNICAL_WEIGHT = 30.0
FUNDAMENTAL_WEIGHT = 30.0
VALUATION_WEIGHT = 20.0
RISK_WEIGHT = 20.0
TOTAL_WEIGHT = TECHNICAL_WEIGHT + FUNDAMENTAL_WEIGHT + VALUATION_WEIGHT + RISK_WEIGHT

FORBIDDEN_PHRASES = ("保證獲利", "必漲", "穩賺", "歐印", "一定買進", "一定賣出")
DEFAULT_RISK_NOTES = (
    "本摘要僅供研究、學習與風險分析，不構成個人化投資建議。",
    "分數依目前載入資料計算；資料缺漏、資料延遲或來源錯誤會影響結果。",
    "歷史績效與歷史指標不代表未來報酬。",
    "請搭配交易成本、流動性、基準比較與樣本外測試檢查策略。",
)


@dataclass(frozen=True)
class ScoreComponent:
    """One weighted component in the 0-100 composite score."""

    name: str
    score: ScoreValue
    weight: float
    reasons: tuple[str, ...] = ()
    missing_data: tuple[str, ...] = ()


@dataclass(frozen=True)
class StockScoreResult:
    """Composite score and generated research notes for one symbol."""

    symbol: str
    total_score: ScoreValue
    available_score: ScoreValue
    coverage: float
    technical_score: ScoreValue
    fundamental_score: ScoreValue
    valuation_score: ScoreValue
    risk_score: ScoreValue
    rating_label: str
    summary: tuple[str, ...]
    strengths: tuple[str, ...]
    weaknesses: tuple[str, ...]
    strategy_health: tuple[str, ...]
    missing_data: tuple[str, ...]
    risk_notes: tuple[str, ...]
    components: tuple[ScoreComponent, ...]


def score_stock(
    *,
    symbol: str,
    price_data: pd.DataFrame,
    technical_indicators: pd.DataFrame | None = None,
    fundamental_scores: pd.DataFrame | None = None,
    backtest_result: Any | None = None,
) -> StockScoreResult:
    """Return a composite 0-100 research score for one stock.

    The full ``total_score`` is available only when all four weighted
    components can be calculated. If fundamentals or valuation are missing, the
    function returns ``total_score='unknown'`` and provides ``available_score``
    with a coverage ratio so missing data is not hidden.
    """

    symbol_text = str(symbol)
    indicator_frame = technical_indicators if technical_indicators is not None else price_data
    symbol_prices = _filter_symbol(price_data, symbol_text)
    symbol_indicators = _filter_symbol(indicator_frame, symbol_text)
    symbol_fundamentals = _filter_symbol(fundamental_scores, symbol_text)

    technical = _score_technical(symbol_indicators)
    fundamental = _score_fundamental(symbol_fundamentals)
    valuation = _score_valuation(symbol_fundamentals)
    risk = _score_risk(symbol_prices, symbol_indicators, backtest_result=backtest_result)
    components = (technical, fundamental, valuation, risk)

    known_components = [component for component in components if component.score != "unknown"]
    known_weight = sum(component.weight for component in known_components)
    known_score = sum(float(component.score) for component in known_components)
    coverage = round(known_weight / TOTAL_WEIGHT, 4)
    total_score: ScoreValue = round(known_score, 2) if known_weight == TOTAL_WEIGHT else "unknown"
    available_score: ScoreValue = (
        round((known_score / known_weight) * 100.0, 2) if known_weight > 0 else "unknown"
    )

    missing_data = tuple(
        sorted({item for component in components for item in component.missing_data})
    )
    strengths, weaknesses = _split_reasons(components)
    strategy_health = strategy_health_check(backtest_result)
    rating_label = _rating_label(total_score if total_score != "unknown" else available_score, coverage)
    summary = _build_summary(
        symbol=symbol_text,
        total_score=total_score,
        available_score=available_score,
        coverage=coverage,
        components=components,
        rating_label=rating_label,
        missing_data=missing_data,
    )
    risk_notes = _sanitize_notes((*DEFAULT_RISK_NOTES, *strategy_health))

    return StockScoreResult(
        symbol=symbol_text,
        total_score=total_score,
        available_score=available_score,
        coverage=coverage,
        technical_score=technical.score,
        fundamental_score=fundamental.score,
        valuation_score=valuation.score,
        risk_score=risk.score,
        rating_label=rating_label,
        summary=_sanitize_notes(summary),
        strengths=_sanitize_notes(strengths),
        weaknesses=_sanitize_notes(weaknesses),
        strategy_health=_sanitize_notes(strategy_health),
        missing_data=missing_data,
        risk_notes=risk_notes,
        components=components,
    )


def score_components_frame(result: StockScoreResult) -> pd.DataFrame:
    """Convert score components into a dashboard-friendly DataFrame."""

    rows = []
    for component in result.components:
        rows.append(
            {
                "component": component.name,
                "score": component.score,
                "weight": component.weight,
                "coverage": 0.0 if component.score == "unknown" else component.weight,
                "reasons": "；".join(component.reasons) if component.reasons else "",
                "missing_data": "；".join(component.missing_data) if component.missing_data else "",
            }
        )
    return pd.DataFrame(rows)


def strategy_health_check(backtest_result: Any | None) -> tuple[str, ...]:
    """Generate a rule-based strategy health check from a backtest result."""

    if backtest_result is None:
        return (
            "尚未執行回測，策略健檢資料不足。",
            "建議先用相同資料期間加入基準比較、交易成本與滑價後再評估策略。",
        )

    metrics = getattr(backtest_result, "metrics", None)
    if metrics is None:
        return ("回測結果缺少績效指標，策略健檢資料不足。",)

    notes: list[str] = []
    trades = int(getattr(metrics, "number_of_trades", 0) or 0)
    max_drawdown = float(getattr(metrics, "max_drawdown", 0.0) or 0.0)
    sharpe = getattr(metrics, "sharpe_ratio", None)
    profit_factor = getattr(metrics, "profit_factor", None)
    benchmark_excess = getattr(metrics, "benchmark_excess_return", None)

    if trades == 0:
        notes.append("回測期間沒有成交，策略有效性無法從交易紀錄驗證。")
    elif trades < 5:
        notes.append("交易次數偏少，勝率、盈虧比與夏普比率可能不穩定。")
    else:
        notes.append(f"回測交易次數為 {trades} 筆，可作為初步樣本，但仍需樣本外測試。")

    if max_drawdown <= -0.30:
        notes.append(f"最大回撤約 {_percent(abs(max_drawdown))}，策略風險壓力偏高。")
    elif max_drawdown <= -0.15:
        notes.append(f"最大回撤約 {_percent(abs(max_drawdown))}，需要檢查停損與部位控管。")
    else:
        notes.append(f"最大回撤約 {_percent(abs(max_drawdown))}，歷史回撤相對可控但不代表未來。")

    if sharpe is None:
        notes.append("夏普比率無法計算，可能是資料不足或報酬波動為零。")
    elif sharpe >= 1.0:
        notes.append(f"夏普比率約 {sharpe:.2f}，歷史風險調整後表現較佳。")
    elif sharpe >= 0.5:
        notes.append(f"夏普比率約 {sharpe:.2f}，歷史風險調整後表現普通。")
    else:
        notes.append(f"夏普比率約 {sharpe:.2f}，策略穩定性需要再驗證。")

    if profit_factor is None:
        notes.append("盈虧比無法計算，可能缺少已平倉交易。")
    elif profit_factor >= 1.5:
        notes.append(f"盈虧比約 {profit_factor:.2f}，歷史盈虧結構較健康。")
    elif profit_factor >= 1.0:
        notes.append(f"盈虧比約 {profit_factor:.2f}，歷史盈虧結構接近平衡。")
    else:
        notes.append(f"盈虧比約 {profit_factor:.2f}，虧損交易壓力偏高。")

    if benchmark_excess is None:
        notes.append("尚未提供基準資料，或基準資料無法對齊相同期間。")
    elif benchmark_excess > 0:
        notes.append(f"相對基準超額報酬約 {_percent(benchmark_excess)}。")
    else:
        notes.append(f"相對基準超額報酬約 {_percent(benchmark_excess)}，需要檢查策略是否值得承擔風險。")

    return tuple(notes)


def _score_technical(indicators: pd.DataFrame) -> ScoreComponent:
    latest = _latest_row(indicators)
    if latest is None:
        return ScoreComponent(
            name="技術面",
            score="unknown",
            weight=TECHNICAL_WEIGHT,
            missing_data=("technical_indicators",),
        )

    reasons: list[str] = []
    missing: list[str] = []
    score = 0.0

    close = _number(latest.get("close"))
    sma20 = _number(latest.get("sma_20"))
    sma60 = _number(latest.get("sma_60"))
    rsi = _number(latest.get("rsi_14"))
    macd_dif = _number(latest.get("macd_dif"))
    macd_dea = _number(latest.get("macd_dea"))
    return20 = _number(latest.get("return_20"))

    if close is None:
        missing.append("close")
    if close is not None and sma20 is not None:
        if close >= sma20:
            score += 6.0
            reasons.append("收盤價高於 20 日均線，短期趨勢偏正向。")
        else:
            reasons.append("收盤價低於 20 日均線，短期趨勢需要觀察。")
    else:
        missing.append("sma_20")

    if close is not None and sma60 is not None:
        if close >= sma60:
            score += 6.0
            reasons.append("收盤價高於 60 日均線，中期趨勢偏正向。")
        else:
            reasons.append("收盤價低於 60 日均線，中期趨勢偏弱。")
    else:
        missing.append("sma_60")

    if sma20 is not None and sma60 is not None:
        if sma20 >= sma60:
            score += 6.0
            reasons.append("20 日均線高於 60 日均線，趨勢結構相對有利。")
        else:
            reasons.append("20 日均線低於 60 日均線，趨勢結構尚未轉強。")

    if macd_dif is not None and macd_dea is not None:
        if macd_dif >= macd_dea:
            score += 5.0
            reasons.append("MACD DIF 高於 DEA，動能訊號偏正向。")
        else:
            reasons.append("MACD DIF 低於 DEA，動能訊號偏保守。")
    else:
        missing.append("macd")

    if rsi is not None:
        if 45 <= rsi <= 70:
            score += 4.0
            reasons.append("RSI 位於相對健康區間，未呈現極端過熱。")
        elif 30 <= rsi < 45 or 70 < rsi <= 80:
            score += 2.0
            reasons.append("RSI 位於需觀察區間，動能尚未失控但不算理想。")
        else:
            reasons.append("RSI 處於偏極端區間，需注意反轉或過熱風險。")
    else:
        missing.append("rsi_14")

    if return20 is not None:
        if return20 > 0:
            score += 3.0
            reasons.append("20 日報酬率為正，近期價格表現偏強。")
        else:
            reasons.append("20 日報酬率不佳，近期價格表現偏弱。")
    else:
        missing.append("return_20")

    if close is None or len(set(missing)) >= 5:
        return ScoreComponent("技術面", "unknown", TECHNICAL_WEIGHT, tuple(reasons), tuple(sorted(set(missing))))
    return ScoreComponent("技術面", round(min(score, TECHNICAL_WEIGHT), 2), TECHNICAL_WEIGHT, tuple(reasons), tuple(sorted(set(missing))))


def _score_fundamental(fundamental_scores: pd.DataFrame) -> ScoreComponent:
    latest = _latest_row(fundamental_scores)
    if latest is None:
        return ScoreComponent(
            name="基本面",
            score="unknown",
            weight=FUNDAMENTAL_WEIGHT,
            missing_data=("fundamental_scores",),
        )

    columns = ("growth_score", "profitability_score", "financial_safety_score", "cashflow_score")
    values = [_number(latest.get(column)) for column in columns]
    missing = [column for column, value in zip(columns, values) if value is None]
    if missing:
        return ScoreComponent("基本面", "unknown", FUNDAMENTAL_WEIGHT, missing_data=tuple(missing))

    raw_score = sum(float(value) for value in values if value is not None)
    score = min((raw_score / 80.0) * FUNDAMENTAL_WEIGHT, FUNDAMENTAL_WEIGHT)
    reasons = (
        f"基本面原始分數合計 {raw_score:.2f}/80，換算為綜合權重 {score:.2f}/30。",
        str(latest.get("strengths") or "基本面優勢需由原始資料確認。"),
        str(latest.get("weaknesses") or "未列出明確弱項，但仍需檢查資料品質。"),
    )
    return ScoreComponent("基本面", round(score, 2), FUNDAMENTAL_WEIGHT, reasons)


def _score_valuation(fundamental_scores: pd.DataFrame) -> ScoreComponent:
    latest = _latest_row(fundamental_scores)
    if latest is None:
        return ScoreComponent(
            name="估值面",
            score="unknown",
            weight=VALUATION_WEIGHT,
            missing_data=("valuation_score",),
        )
    source_missing = _split_missing_fields(latest.get("missing_data"))
    valuation_missing = tuple(
        item for item in source_missing if item in {"pe_ratio", "pb_ratio", "dividend_yield", "valuation_score"}
    )
    valuation = _number(latest.get("valuation_score"))
    if valuation is None:
        return ScoreComponent("估值面", "unknown", VALUATION_WEIGHT, missing_data=("valuation_score",))
    reasons = [f"估值分數 {valuation:.2f}/20，分數越高代表估值風險相對較低。"]
    if valuation_missing:
        reasons.append(f"估值欄位仍有缺漏：{', '.join(valuation_missing)}，分數需保守解讀。")
    return ScoreComponent(
        "估值面",
        round(min(valuation, VALUATION_WEIGHT), 2),
        VALUATION_WEIGHT,
        tuple(reasons),
        valuation_missing,
    )


def _score_risk(
    prices: pd.DataFrame,
    indicators: pd.DataFrame,
    *,
    backtest_result: Any | None,
) -> ScoreComponent:
    source = indicators if not indicators.empty else prices
    if source.empty or "close" not in source.columns:
        return ScoreComponent("風險面", "unknown", RISK_WEIGHT, missing_data=("price_data",))

    data = source.copy(deep=True)
    if "date" in data.columns:
        data = data.sort_values("date")
    close = pd.to_numeric(data["close"], errors="coerce").dropna()
    if len(close) < 20:
        return ScoreComponent("風險面", "unknown", RISK_WEIGHT, missing_data=("at_least_20_price_rows",))

    returns = close.pct_change().dropna()
    running_peak = close.cummax()
    max_drawdown = float(((close / running_peak.where(running_peak != 0)) - 1.0).min())
    latest = data.iloc[-1]
    vol20 = _number(latest.get("volatility_20"))
    if vol20 is None and len(returns) >= 20:
        vol20 = float(returns.tail(20).std(ddof=0))
    atr = _number(latest.get("atr_14"))
    latest_close = float(close.iloc[-1])
    atr_pct = (atr / latest_close) if atr is not None and latest_close > 0 else None

    score = 0.0
    reasons: list[str] = []
    if max_drawdown >= -0.10:
        score += 8.0
        reasons.append(f"載入期間最大回撤約 {_percent(abs(max_drawdown))}，歷史價格回撤較低。")
    elif max_drawdown >= -0.20:
        score += 5.0
        reasons.append(f"載入期間最大回撤約 {_percent(abs(max_drawdown))}，需要搭配停損與部位控管。")
    elif max_drawdown >= -0.35:
        score += 2.0
        reasons.append(f"載入期間最大回撤約 {_percent(abs(max_drawdown))}，回撤壓力偏高。")
    else:
        reasons.append(f"載入期間最大回撤約 {_percent(abs(max_drawdown))}，價格風險壓力高。")

    if vol20 is not None:
        if vol20 <= 0.02:
            score += 7.0
            reasons.append(f"20 日波動率約 {_percent(vol20)}，短期波動相對低。")
        elif vol20 <= 0.04:
            score += 4.0
            reasons.append(f"20 日波動率約 {_percent(vol20)}，短期波動中等。")
        else:
            score += 1.0
            reasons.append(f"20 日波動率約 {_percent(vol20)}，短期波動偏高。")
    else:
        reasons.append("缺少 20 日波動率，風險分數未納入此項。")

    if atr_pct is not None:
        if atr_pct <= 0.03:
            score += 3.0
            reasons.append(f"ATR/收盤價約 {_percent(atr_pct)}，日線價格振幅相對可控。")
        elif atr_pct <= 0.06:
            score += 1.5
            reasons.append(f"ATR/收盤價約 {_percent(atr_pct)}，日線價格振幅中等偏高。")
        else:
            reasons.append(f"ATR/收盤價約 {_percent(atr_pct)}，日線價格振幅偏高。")

    metrics = getattr(backtest_result, "metrics", None) if backtest_result is not None else None
    if metrics is not None:
        strategy_mdd = float(getattr(metrics, "max_drawdown", 0.0) or 0.0)
        if strategy_mdd >= -0.15:
            score += 2.0
            reasons.append("最近回測最大回撤未超過 15%，策略風險初步可控。")
        else:
            reasons.append("最近回測最大回撤超過 15%，策略部位與停損需再檢查。")
    else:
        reasons.append("尚未執行回測，風險分數未納入策略資金曲線。")

    return ScoreComponent("風險面", round(min(score, RISK_WEIGHT), 2), RISK_WEIGHT, tuple(reasons))


def _filter_symbol(frame: pd.DataFrame | None, symbol: str) -> pd.DataFrame:
    if frame is None or frame.empty or "symbol" not in frame.columns:
        return pd.DataFrame()
    return frame.loc[frame["symbol"].astype(str) == str(symbol)].copy(deep=True)


def _latest_row(frame: pd.DataFrame) -> pd.Series | None:
    if frame.empty:
        return None
    output = frame.copy(deep=True)
    if "date" in output.columns:
        output = output.sort_values("date")
    return output.iloc[-1]


def _number(value: Any) -> float | None:
    if value is None or pd.isna(value) or value == "unknown":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _split_missing_fields(value: Any) -> tuple[str, ...]:
    """Split persisted missing-data text into normalized field names."""

    if value is None or pd.isna(value):
        return ()
    text = str(value).strip()
    if not text:
        return ()
    normalized = text.replace("；", ",").replace(";", ",")
    return tuple(item.strip() for item in normalized.split(",") if item.strip())


def _split_reasons(components: tuple[ScoreComponent, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    strengths: list[str] = []
    weaknesses: list[str] = []
    for component in components:
        if component.score == "unknown":
            weaknesses.append(f"{component.name}資料不足：{', '.join(component.missing_data)}")
            continue
        ratio = float(component.score) / component.weight if component.weight else 0.0
        target = strengths if ratio >= 0.65 else weaknesses
        target.extend(component.reasons[:3])
    return tuple(strengths[:8]), tuple(weaknesses[:8])


def _rating_label(score: ScoreValue, coverage: float) -> str:
    if score == "unknown":
        return "資料不足"
    value = float(score)
    if coverage < 1.0:
        prefix = "部分資料"
    else:
        prefix = "完整資料"
    if value >= 75:
        return f"{prefix}：研究條件偏強"
    if value >= 60:
        return f"{prefix}：研究條件中性偏正"
    if value >= 45:
        return f"{prefix}：研究條件中性"
    return f"{prefix}：需要保守檢查"


def _build_summary(
    *,
    symbol: str,
    total_score: ScoreValue,
    available_score: ScoreValue,
    coverage: float,
    components: tuple[ScoreComponent, ...],
    rating_label: str,
    missing_data: tuple[str, ...],
) -> tuple[str, ...]:
    if total_score == "unknown":
        first = (
            f"{symbol} 的完整綜合分數暫時無法計算；目前可用資料分數為 "
            f"{available_score}/100，資料覆蓋率約 {_percent(coverage)}。"
        )
    else:
        first = f"{symbol} 的綜合研究分數為 {total_score}/100，評級摘要：{rating_label}。"

    component_text = "；".join(
        f"{component.name} {component.score}/{component.weight}" for component in components
    )
    notes = [
        first,
        f"分項狀態：{component_text}。",
        "此摘要偏向研究與策略健檢，不代表個人化買賣建議。",
    ]
    if missing_data:
        notes.append(f"資料限制：缺少 {', '.join(missing_data)}，請補齊後再解讀總分。")
    else:
        notes.append("四大分項資料皆可計算，但仍需檢查資料來源、日期與成本假設。")
    return tuple(notes)


def _sanitize_notes(notes: tuple[str, ...]) -> tuple[str, ...]:
    cleaned: list[str] = []
    for note in notes:
        text = str(note)
        for phrase in FORBIDDEN_PHRASES:
            text = text.replace(phrase, "不適當保證語句")
        cleaned.append(text)
    return tuple(cleaned)


def _percent(value: float) -> str:
    return f"{value * 100:.2f}%"
