"""Fundamental scoring model for research analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

import pandas as pd

from stock_tool.fundamentals.loader import normalize_fundamental_market

ScoreValue = float | Literal["unknown"]
MetricDirection = Literal["higher", "lower", "positive"]

OUTPUT_COLUMNS = (
    "symbol",
    "market",
    "fiscal_period",
    "period_type",
    "as_of_date",
    "total_score",
    "growth_score",
    "profitability_score",
    "financial_safety_score",
    "valuation_score",
    "cashflow_score",
    "strengths",
    "weaknesses",
    "missing_data",
    "risk_notes",
)


@dataclass(frozen=True)
class MetricRule:
    """Scoring rule for one fundamental metric."""

    column: str
    label: str
    weight: float
    direction: MetricDirection
    strong: float | None = None
    acceptable: float | None = None
    weak: float | None = None


@dataclass(frozen=True)
class IndustryScoringProfile:
    """Optional industry-specific overrides for metric rules."""

    name: str
    metric_rules: Mapping[str, MetricRule] = field(default_factory=dict)
    risk_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ComponentResult:
    """Result for one score component."""

    score: ScoreValue
    strengths: tuple[str, ...]
    weaknesses: tuple[str, ...]
    missing_data: tuple[str, ...]


DEFAULT_RISK_NOTES = (
    "分數僅供研究參考，不構成個人化投資建議。",
    "歷史財報與估值比率不一定能反映未來營運狀況。",
    "不同產業的合理標準可能不同，跨產業直接比較可能造成誤判。",
    "缺漏或過期資料需要先確認，不能直接下結論。",
)


DEFAULT_RULES: dict[str, MetricRule] = {
    "revenue_growth_yoy": MetricRule(
        column="revenue_growth_yoy",
        label="營收年增率",
        weight=12.5,
        direction="higher",
        strong=0.15,
        acceptable=0.05,
        weak=0.0,
    ),
    "eps_growth_yoy": MetricRule(
        column="eps_growth_yoy",
        label="EPS 年增率",
        weight=12.5,
        direction="higher",
        strong=0.15,
        acceptable=0.05,
        weak=0.0,
    ),
    "gross_margin": MetricRule(
        column="gross_margin",
        label="毛利率",
        weight=5.0,
        direction="higher",
        strong=0.45,
        acceptable=0.30,
        weak=0.15,
    ),
    "operating_margin": MetricRule(
        column="operating_margin",
        label="營業利益率",
        weight=5.0,
        direction="higher",
        strong=0.25,
        acceptable=0.15,
        weak=0.05,
    ),
    "net_margin": MetricRule(
        column="net_margin",
        label="淨利率",
        weight=5.0,
        direction="higher",
        strong=0.20,
        acceptable=0.10,
        weak=0.03,
    ),
    "roe": MetricRule(
        column="roe",
        label="ROE 股東權益報酬率",
        weight=7.0,
        direction="higher",
        strong=0.18,
        acceptable=0.10,
        weak=0.05,
    ),
    "roa": MetricRule(
        column="roa",
        label="ROA 資產報酬率",
        weight=3.0,
        direction="higher",
        strong=0.08,
        acceptable=0.04,
        weak=0.01,
    ),
    "debt_ratio": MetricRule(
        column="debt_ratio",
        label="負債比",
        weight=20.0,
        direction="lower",
        strong=0.35,
        acceptable=0.55,
        weak=0.75,
    ),
    "pe_ratio": MetricRule(
        column="pe_ratio",
        label="本益比",
        weight=8.0,
        direction="lower",
        strong=15.0,
        acceptable=25.0,
        weak=40.0,
    ),
    "pb_ratio": MetricRule(
        column="pb_ratio",
        label="股價淨值比",
        weight=6.0,
        direction="lower",
        strong=1.5,
        acceptable=3.0,
        weak=5.0,
    ),
    "dividend_yield": MetricRule(
        column="dividend_yield",
        label="股利殖利率",
        weight=6.0,
        direction="higher",
        strong=0.04,
        acceptable=0.02,
        weak=0.005,
    ),
    "operating_cash_flow": MetricRule(
        column="operating_cash_flow",
        label="營業現金流",
        weight=5.0,
        direction="positive",
    ),
    "free_cash_flow": MetricRule(
        column="free_cash_flow",
        label="自由現金流",
        weight=5.0,
        direction="positive",
    ),
}

COMPONENT_RULES = {
    "growth_score": ("revenue_growth_yoy", "eps_growth_yoy"),
    "profitability_score": ("gross_margin", "operating_margin", "net_margin", "roe", "roa"),
    "financial_safety_score": ("debt_ratio",),
    "valuation_score": ("pe_ratio", "pb_ratio", "dividend_yield"),
    "cashflow_score": ("operating_cash_flow", "free_cash_flow"),
}


def score_fundamentals(
    fundamentals: pd.DataFrame,
    *,
    industry_profiles: Mapping[str, IndustryScoringProfile] | None = None,
    industry_col: str = "industry",
) -> pd.DataFrame:
    """Score standardized fundamental records.

    Missing data is marked as ``unknown`` at the component level and prevents a
    total score from being calculated. This conservative behavior avoids
    presenting incomplete data as a precise 100-point score.
    """

    if fundamentals.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    if "symbol" not in fundamentals.columns:
        raise ValueError("fundamentals must contain a symbol column.")

    rows: list[dict[str, Any]] = []
    for _, row in fundamentals.iterrows():
        industry = (
            str(row.get(industry_col, "default"))
            if industry_col in fundamentals.columns
            else "default"
        )
        profile = (industry_profiles or {}).get(industry)
        rows.append(_score_one_row(row, profile=profile))

    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def _score_one_row(
    row: pd.Series,
    *,
    profile: IndustryScoringProfile | None,
) -> dict[str, Any]:
    component_results = {
        component: _score_component(component, row, rule_keys, profile=profile)
        for component, rule_keys in COMPONENT_RULES.items()
    }
    component_scores = {component: result.score for component, result in component_results.items()}
    if any(score == "unknown" for score in component_scores.values()):
        total_score: ScoreValue = "unknown"
    else:
        total_score = round(sum(float(score) for score in component_scores.values()), 2)

    strengths: list[str] = []
    weaknesses: list[str] = []
    missing_data: list[str] = []
    for result in component_results.values():
        strengths.extend(result.strengths)
        weaknesses.extend(result.weaknesses)
        missing_data.extend(result.missing_data)

    risk_notes = list(DEFAULT_RISK_NOTES)
    if profile is not None:
        risk_notes.extend(profile.risk_notes)

    return {
        "symbol": str(row["symbol"]),
        "market": normalize_fundamental_market(row.get("market")),
        "fiscal_period": row.get("fiscal_period", pd.NA),
        "period_type": row.get("period_type", "unknown"),
        "as_of_date": row.get("as_of_date", pd.NA),
        "total_score": total_score,
        "growth_score": component_scores["growth_score"],
        "profitability_score": component_scores["profitability_score"],
        "financial_safety_score": component_scores["financial_safety_score"],
        "valuation_score": component_scores["valuation_score"],
        "cashflow_score": component_scores["cashflow_score"],
        "strengths": "；".join(strengths) if strengths else "目前沒有足夠資料列出優勢",
        "weaknesses": "；".join(weaknesses) if weaknesses else "目前沒有足夠資料列出弱項",
        "missing_data": "；".join(sorted(set(missing_data))) if missing_data else "",
        "risk_notes": "；".join(risk_notes),
    }


def _score_component(
    component: str,
    row: pd.Series,
    rule_keys: tuple[str, ...],
    *,
    profile: IndustryScoringProfile | None,
) -> ComponentResult:
    rules = [_rule_for(key, profile) for key in rule_keys]
    available_rules = [rule for rule in rules if not _is_missing(row.get(rule.column))]
    missing = [rule.column for rule in rules if rule not in available_rules]
    if missing and not _can_score_partial_component(component, available_rules):
        return ComponentResult(
            score="unknown",
            strengths=(),
            weaknesses=(),
            missing_data=tuple(missing),
        )

    score = 0.0
    strengths: list[str] = []
    weaknesses: list[str] = []
    for rule in available_rules:
        value = float(row[rule.column])
        points, reason, is_strength = _score_metric(value, rule)
        score += points
        if is_strength:
            strengths.append(reason)
        else:
            weaknesses.append(reason)
    for column in missing:
        weaknesses.append(f"{DEFAULT_RULES[column].label} 缺漏，該項未納入分數。")

    return ComponentResult(
        score=round(score, 2),
        strengths=tuple(strengths),
        weaknesses=tuple(weaknesses),
        missing_data=tuple(missing),
    )


def _can_score_partial_component(component: str, available_rules: list[MetricRule]) -> bool:
    """Return whether a component can be scored with a conservative partial input set."""

    if not available_rules:
        return False
    if component != "valuation_score":
        return False
    available_columns = {rule.column for rule in available_rules}
    return bool(available_columns & {"pe_ratio", "pb_ratio"})


def _rule_for(key: str, profile: IndustryScoringProfile | None) -> MetricRule:
    if profile is not None and key in profile.metric_rules:
        return profile.metric_rules[key]
    return DEFAULT_RULES[key]


def _score_metric(value: float, rule: MetricRule) -> tuple[float, str, bool]:
    if rule.direction == "positive":
        if value > 0:
            return rule.weight, f"{rule.label} 為正值", True
        return 0.0, f"{rule.label} 不是正值", False

    if rule.strong is None or rule.acceptable is None or rule.weak is None:
        raise ValueError(f"指標規則 {rule.column} 缺少門檻設定。")

    if rule.direction == "higher":
        if value >= rule.strong:
            return rule.weight, f"{rule.label} 表現強 ({_format_value(value)})", True
        if value >= rule.acceptable:
            return rule.weight * 0.75, f"{rule.label} 尚可接受 ({_format_value(value)})", True
        if value >= rule.weak:
            return rule.weight * 0.40, f"{rule.label} 偏弱 ({_format_value(value)})", False
        return 0.0, f"{rule.label} 低於門檻 ({_format_value(value)})", False

    if value <= rule.strong:
        return rule.weight, f"{rule.label} 保守 ({_format_value(value)})", True
    if value <= rule.acceptable:
        return rule.weight * 0.75, f"{rule.label} 尚可接受 ({_format_value(value)})", True
    if value <= rule.weak:
        return rule.weight * 0.40, f"{rule.label} 偏高 ({_format_value(value)})", False
    return 0.0, f"{rule.label} 過高 ({_format_value(value)})", False


def _is_missing(value: Any) -> bool:
    return value is None or pd.isna(value)


def _format_value(value: float) -> str:
    return f"{value:.4g}"
