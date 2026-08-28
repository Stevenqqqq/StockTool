"""Deterministic portfolio-health assessment built on existing research outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from stock_tool.domain.models import MissingData, MissingDataState
from stock_tool.portfolio_analytics import PortfolioRiskInputResult
from stock_tool.portfolio_valuation import PortfolioValuationResult


@dataclass(frozen=True, slots=True)
class PortfolioHealthConfig:
    """All scoring thresholds for the deterministic health model."""

    diversification_weight: float = 0.30
    risk_weight: float = 0.25
    position_quality_weight: float = 0.25
    data_quality_weight: float = 0.20
    minimum_coverage_pct: float = 0.70
    maximum_position_weight: float = 0.35
    maximum_top_three_weight: float = 0.75
    maximum_market_weight: float = 0.80
    maximum_currency_weight: float = 0.80
    maximum_industry_weight: float = 0.60
    target_volatility: float = 0.35
    target_drawdown: float = 0.30

    def __post_init__(self) -> None:
        total = (
            self.diversification_weight
            + self.risk_weight
            + self.position_quality_weight
            + self.data_quality_weight
        )
        if abs(total - 1.0) > 1e-9:
            raise ValueError("Portfolio health component weights must sum to 1.0.")
        if not 0 <= self.minimum_coverage_pct <= 1:
            raise ValueError("minimum_coverage_pct must be between 0 and 1.")


@dataclass(frozen=True, slots=True)
class PortfolioHealthComponent:
    """One transparent health-score component."""

    name: str
    score: float | None
    weight: float
    contribution: float | None
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    missing_data: tuple[MissingData, ...]
    evidence: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class PortfolioAlert:
    """Non-prescriptive portfolio observation from the health assessment."""

    severity: str
    message: str
    evidence: dict[str, object]


@dataclass(frozen=True, slots=True)
class PortfolioCoverageReport:
    """Coverage accounting for prices, FX, fundamentals, indicators, and scores."""

    position_count: int
    price_coverage_pct: float
    fx_coverage_pct: float
    fundamental_coverage_pct: float
    indicator_coverage_pct: float
    composite_score_coverage_pct: float
    coverage_pct: float
    missing_data: tuple[MissingData, ...]
    provenance: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class PortfolioHealthResult:
    """Deterministic portfolio score or an explicit insufficient-data state."""

    overall_score: float | None
    status: str
    coverage: PortfolioCoverageReport
    components: tuple[PortfolioHealthComponent, ...]
    alerts: tuple[PortfolioAlert, ...]
    warnings: tuple[str, ...]
    missing_data: tuple[MissingData, ...]
    evidence: tuple[dict[str, object], ...]
    disclaimer: str


class PortfolioHealthService:
    """Assess portfolio structure without making trade recommendations."""

    def __init__(self, config: PortfolioHealthConfig | None = None) -> None:
        self._config = config or PortfolioHealthConfig()

    def assess(
        self,
        *,
        portfolio: pd.DataFrame,
        valuation: PortfolioValuationResult,
        prices: pd.DataFrame | None = None,
        fundamentals: pd.DataFrame | None = None,
        indicators: pd.DataFrame | None = None,
        stock_scores: pd.DataFrame | None = None,
        risk_inputs: pd.DataFrame | PortfolioRiskInputResult | None = None,
    ) -> PortfolioHealthResult:
        """Build a score from explicit coverage and existing research result frames."""

        positions = valuation.positions.copy(deep=True)
        positions = _attach_optional_identity_columns(positions, portfolio)
        risk_frame, risk_missing = _resolve_risk_inputs(risk_inputs, indicators)
        coverage = _coverage_report(
            positions=positions,
            fundamentals=fundamentals,
            indicators=indicators,
            stock_scores=stock_scores,
            valuation=valuation,
        )
        components = (
            self._diversification_component(positions),
            self._risk_component(risk_frame, positions),
            self._quality_component(stock_scores, positions),
            self._data_quality_component(coverage, valuation),
        )
        all_missing = (
            tuple(item for component in components for item in component.missing_data)
            + risk_missing
            + coverage.missing_data
            + valuation.missing_data
        )
        warnings = tuple(
            dict.fromkeys(
                [
                    *valuation.warnings,
                    *(warning for component in components for warning in component.warnings),
                ]
            )
        )
        score_available = coverage.coverage_pct >= self._config.minimum_coverage_pct and all(
            component.score is not None for component in components
        )
        overall_score = (
            round(sum(component.contribution or 0.0 for component in components), 2)
            if score_available
            else None
        )
        status = "available" if overall_score is not None else "insufficient_data"
        if overall_score is None:
            all_missing = all_missing + (
                MissingData(
                    field="portfolio_health",
                    state=MissingDataState.UNKNOWN,
                    reason="Portfolio coverage is below the configured threshold or a required component is unavailable.",
                ),
            )
        alerts = _alerts(components, coverage)
        evidence = tuple(item for component in components for item in component.evidence)
        return PortfolioHealthResult(
            overall_score=overall_score,
            status=status,
            coverage=coverage,
            components=components,
            alerts=alerts,
            warnings=warnings,
            missing_data=tuple(_unique_missing(all_missing)),
            evidence=evidence,
            disclaimer="Portfolio health is a deterministic research aid, not investment advice or a trading instruction.",
        )

    def _diversification_component(self, positions: pd.DataFrame) -> PortfolioHealthComponent:
        weight = self._config.diversification_weight
        if positions.empty or positions["weight"].isna().any():
            return _missing_component(
                "diversification",
                weight,
                "Market-qualified base-currency weights are required for diversification analysis.",
            )
        weights = positions["weight"].astype(float).sort_values(ascending=False)
        largest = float(weights.iloc[0])
        top_three = float(weights.head(3).sum())
        largest_ratio = min(1.0, self._config.maximum_position_weight / largest) if largest else 1.0
        top_three_ratio = (
            min(1.0, self._config.maximum_top_three_weight / top_three) if top_three else 1.0
        )
        ratios = [largest_ratio, top_three_ratio]
        reasons = [
            f"Largest position weight is {largest:.1%}.",
            f"Top-three position weight is {top_three:.1%}.",
        ]
        warnings: list[str] = []
        if largest > self._config.maximum_position_weight:
            warnings.append("Largest position exceeds the configured diversification threshold.")

        for column, label, limit in (
            ("market", "market", self._config.maximum_market_weight),
            ("native_currency", "currency", self._config.maximum_currency_weight),
            ("industry", "industry", self._config.maximum_industry_weight),
        ):
            if column not in positions.columns or positions[column].fillna("").eq("").all():
                if column == "industry":
                    reasons.append(
                        "Industry concentration is not assessed because industry data is unavailable."
                    )
                continue
            grouped = positions.assign(_weight=positions["weight"]).groupby(column)["_weight"].sum()
            largest_group = float(grouped.max()) if not grouped.empty else 0.0
            ratios.append(min(1.0, limit / largest_group) if largest_group else 1.0)
            group_name = str(grouped.idxmax()) if not grouped.empty else "unknown"
            reasons.append(f"Largest {label} concentration is {group_name} at {largest_group:.1%}.")
            if largest_group > limit:
                warnings.append(f"Largest {label} concentration exceeds the configured threshold.")
        score = round(100.0 * sum(ratios) / len(ratios), 2)
        return _component(
            "diversification",
            score,
            weight,
            tuple(reasons),
            tuple(warnings),
            evidence=(
                {"metric": "largest_position_weight", "value": largest},
                {"metric": "top_three_weight", "value": top_three},
                {"metric": "group_concentration_dimensions", "value": len(ratios)},
            ),
        )

    def _risk_component(
        self, indicators: pd.DataFrame | None, positions: pd.DataFrame
    ) -> PortfolioHealthComponent:
        weight = self._config.risk_weight
        if indicators is None or indicators.empty:
            return _missing_component("risk", weight, "No canonical indicator data was supplied.")
        data = indicators.copy(deep=True)
        volatility = _weighted_numeric(
            data,
            positions,
            ("volatility_20", "rolling_volatility_20", "volatility", "annualized_volatility"),
        )
        drawdown = _weighted_numeric(data, positions, ("max_drawdown", "drawdown"))
        if volatility is None or drawdown is None:
            return _missing_component(
                "risk", weight, "Volatility and drawdown inputs are required for risk analysis."
            )
        volatility_ratio = (
            min(1.0, self._config.target_volatility / volatility) if volatility else 1.0
        )
        drawdown_abs = abs(drawdown)
        drawdown_ratio = (
            min(1.0, self._config.target_drawdown / drawdown_abs) if drawdown_abs else 1.0
        )
        score = round(100.0 * ((volatility_ratio + drawdown_ratio) / 2.0), 2)
        return _component(
            "risk",
            score,
            weight,
            (
                f"Average volatility input is {volatility:.2%}.",
                f"Average drawdown input is {drawdown:.2%}.",
            ),
            (),
            evidence=(
                {"metric": "weighted_volatility", "value": volatility},
                {"metric": "weighted_drawdown", "value": drawdown},
            ),
        )

    def _quality_component(
        self,
        stock_scores: pd.DataFrame | None,
        positions: pd.DataFrame,
    ) -> PortfolioHealthComponent:
        weight = self._config.position_quality_weight
        if (
            stock_scores is None
            or stock_scores.empty
            or "total_score" not in stock_scores.columns
            or not {"symbol", "market"}.issubset(stock_scores.columns)
        ):
            return _missing_component(
                "position_quality", weight, "No existing composite stock scores were supplied."
            )
        scores = _canonical_latest_values(stock_scores, "total_score")
        weighted_positions = _canonical_position_weights(positions)
        if scores.empty or weighted_positions.empty:
            return _missing_component(
                "position_quality", weight, "Existing composite stock scores are unavailable."
            )
        merged = weighted_positions.merge(scores, on=["symbol", "market"], how="left")
        if merged["total_score"].isna().any():
            missing_identities = ", ".join(
                f"{row.symbol}/{row.market}"
                for row in merged.loc[merged["total_score"].isna(), ["symbol", "market"]]
                .itertuples(index=False)
            )
            return _missing_component(
                "position_quality",
                weight,
                "Missing canonical composite stock score for: " + missing_identities,
                state=MissingDataState.MISSING,
            )
        score = round(float((merged["total_score"] * merged["weight"]).sum()), 2)
        return _component(
            "position_quality",
            score,
            weight,
            (
                "Position quality reuses canonical composite stock scores weighted by portfolio value.",
            ),
            (),
            evidence=(
                {
                    "metric": "weighted_composite_stock_score",
                    "value": score,
                    "count": len(merged),
                    "deduplication": "latest valid value per symbol and market",
                },
            ),
        )

    def _data_quality_component(
        self,
        coverage: PortfolioCoverageReport,
        valuation: PortfolioValuationResult,
    ) -> PortfolioHealthComponent:
        warnings = tuple(warning for warning in valuation.warnings if "stale" in warning.lower())
        return _component(
            "data_quality",
            round(coverage.coverage_pct * 100.0, 2),
            self._config.data_quality_weight,
            (f"Research coverage is {coverage.coverage_pct:.1%}.",),
            warnings,
            evidence=coverage.provenance,
        )


def _coverage_report(
    *,
    positions: pd.DataFrame,
    fundamentals: pd.DataFrame | None,
    indicators: pd.DataFrame | None,
    stock_scores: pd.DataFrame | None,
    valuation: PortfolioValuationResult,
) -> PortfolioCoverageReport:
    count = len(positions)
    if count == 0:
        empty_portfolio_missing = MissingData(
            field="portfolio", state=MissingDataState.MISSING, reason="Portfolio has no positions."
        )
        return PortfolioCoverageReport(
            0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            (empty_portfolio_missing,),
            (),
        )
    price_coverage = _non_null_ratio(positions, "latest_price")
    fx_coverage = _non_null_ratio(positions, "fx_rate_to_base")
    fundamental_coverage = _identity_coverage(positions, fundamentals)
    indicator_coverage = _identity_coverage(positions, indicators)
    composite_score_coverage = _score_identity_coverage(positions, stock_scores)
    coverage = (
        price_coverage
        + fx_coverage
        + fundamental_coverage
        + indicator_coverage
        + composite_score_coverage
    ) / 5.0
    missing: list[MissingData] = []
    for field, value in (
        ("portfolio_prices", price_coverage),
        ("portfolio_fx", fx_coverage),
        ("portfolio_fundamentals", fundamental_coverage),
        ("portfolio_indicators", indicator_coverage),
        ("portfolio_composite_scores", composite_score_coverage),
    ):
        if value < 1.0:
            missing.append(
                MissingData(
                    field=field,
                    state=MissingDataState.MISSING,
                    reason=f"Coverage is only {value:.1%}.",
                )
            )
    provenance = (
        {"metric": "price_coverage_pct", "value": price_coverage},
        {"metric": "fx_coverage_pct", "value": fx_coverage},
        {"metric": "fundamental_coverage_pct", "value": fundamental_coverage},
        {"metric": "indicator_coverage_pct", "value": indicator_coverage},
        {"metric": "composite_score_coverage_pct", "value": composite_score_coverage},
    )
    return PortfolioCoverageReport(
        position_count=count,
        price_coverage_pct=price_coverage,
        fx_coverage_pct=fx_coverage,
        fundamental_coverage_pct=fundamental_coverage,
        indicator_coverage_pct=indicator_coverage,
        composite_score_coverage_pct=composite_score_coverage,
        coverage_pct=coverage,
        missing_data=tuple(missing),
        provenance=provenance,
    )


def _resolve_risk_inputs(
    risk_inputs: pd.DataFrame | PortfolioRiskInputResult | None,
    indicators: pd.DataFrame | None,
) -> tuple[pd.DataFrame | None, tuple[MissingData, ...]]:
    """Resolve the canonical risk contract while retaining legacy compatibility."""

    if isinstance(risk_inputs, PortfolioRiskInputResult):
        return risk_inputs.frame.copy(deep=True), risk_inputs.missing_data
    if risk_inputs is not None:
        return risk_inputs.copy(deep=True), ()
    return (indicators.copy(deep=True) if indicators is not None else None), ()


def _attach_optional_identity_columns(
    valuation_positions: pd.DataFrame, portfolio: pd.DataFrame
) -> pd.DataFrame:
    """Carry optional sector/industry labels into the immutable valuation snapshot."""

    output = valuation_positions.copy(deep=True)
    if not {"symbol", "market"}.issubset(portfolio.columns):
        return output
    optional = [column for column in ("industry", "sector") if column in portfolio.columns]
    if not optional:
        return output
    identity = portfolio[["symbol", "market", *optional]].copy(deep=True)
    identity["symbol"] = identity["symbol"].astype(str).str.upper()
    identity["market"] = identity["market"].astype(str).str.upper()
    output["symbol"] = output["symbol"].astype(str).str.upper()
    output["market"] = output["market"].astype(str).str.upper()
    return output.merge(identity, on=["symbol", "market"], how="left", suffixes=("", "_portfolio"))


def _identity_coverage(positions: pd.DataFrame, frame: pd.DataFrame | None) -> float:
    if frame is None or frame.empty or not {"symbol", "market"}.issubset(frame.columns):
        return 0.0
    available = {
        (str(row.symbol).upper(), str(row.market).upper())
        for row in frame[["symbol", "market"]].dropna().itertuples(index=False)
    }
    matches = sum(
        (str(row.symbol).upper(), str(row.market).upper()) in available
        for row in positions[["symbol", "market"]].itertuples(index=False)
    )
    return matches / len(positions) if len(positions) else 0.0


def _score_identity_coverage(positions: pd.DataFrame, scores: pd.DataFrame | None) -> float:
    """Return coverage only for canonical positions with a usable composite score."""

    if scores is None or scores.empty or "total_score" not in scores.columns:
        return 0.0
    canonical = _canonical_latest_values(scores, "total_score")
    return _identity_coverage(positions, canonical)


def _non_null_ratio(frame: pd.DataFrame, column: str) -> float:
    return float(frame[column].notna().mean()) if column in frame.columns and len(frame) else 0.0


def _first_numeric(frame: pd.DataFrame, candidates: Iterable[str]) -> float | None:
    for column in candidates:
        if column in frame.columns:
            values = pd.to_numeric(frame[column], errors="coerce").dropna()
            if not values.empty:
                return float(values.mean())
    return None


def _weighted_numeric(
    frame: pd.DataFrame,
    positions: pd.DataFrame,
    candidates: Iterable[str],
) -> float | None:
    """Use the latest valid value per identity, then weight each position once."""

    column = next((item for item in candidates if item in frame.columns), None)
    if column is None or not {"symbol", "market"}.issubset(frame.columns):
        return None
    values = _canonical_latest_values(frame, column)
    weights = _canonical_position_weights(positions)
    if values.empty or weights.empty:
        return None
    merged = weights.merge(values, on=["symbol", "market"], how="left")
    if merged[column].isna().any():
        return None
    return float((merged[column] * merged["weight"]).sum())


def _canonical_position_weights(positions: pd.DataFrame) -> pd.DataFrame:
    """Return one explicit base-currency weight per canonical portfolio identity."""

    required = {"symbol", "market", "weight"}
    if positions.empty or not required.issubset(positions.columns):
        return pd.DataFrame(columns=["symbol", "market", "weight"])
    output = positions.loc[:, ["symbol", "market", "weight"]].copy(deep=True)
    output["symbol"] = output["symbol"].fillna("").astype(str).str.strip().str.upper()
    output["market"] = output["market"].fillna("").astype(str).str.strip().str.upper()
    output["weight"] = pd.to_numeric(output["weight"], errors="coerce")
    output = output.loc[
        output["symbol"].ne("") & output["market"].ne("") & output["weight"].notna()
    ].copy()
    if output.empty:
        return output
    return (
        output.groupby(["symbol", "market"], as_index=False, sort=True)["weight"]
        .sum()
        .reset_index(drop=True)
    )


def _canonical_latest_values(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    """Select the latest valid value per symbol/market without mutating input."""

    required = {"symbol", "market", column}
    if frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame(columns=["symbol", "market", column])
    selected_columns = [
        item for item in ("symbol", "market", "date", "updated_at", column) if item in frame.columns
    ]
    output = frame.loc[:, selected_columns].copy(deep=True)
    output["symbol"] = output["symbol"].fillna("").astype(str).str.strip().str.upper()
    output["market"] = output["market"].fillna("").astype(str).str.strip().str.upper()
    output[column] = pd.to_numeric(output[column], errors="coerce")
    output = output.loc[
        output["symbol"].ne("") & output["market"].ne("") & output[column].notna()
    ].copy()
    if output.empty:
        return pd.DataFrame(columns=["symbol", "market", column])
    order_columns = [item for item in ("date", "updated_at") if item in output.columns]
    if order_columns:
        output = output.sort_values(["symbol", "market", *order_columns], kind="stable")
    return (
        output.drop_duplicates(subset=["symbol", "market"], keep="last")
        .loc[:, ["symbol", "market", column]]
        .reset_index(drop=True)
    )


def _component(
    name: str,
    score: float,
    weight: float,
    reasons: tuple[str, ...],
    warnings: tuple[str, ...],
    evidence: tuple[dict[str, object], ...],
) -> PortfolioHealthComponent:
    return PortfolioHealthComponent(
        name=name,
        score=score,
        weight=weight,
        contribution=round(score * weight, 2),
        reasons=reasons,
        warnings=warnings,
        missing_data=(),
        evidence=evidence,
    )


def _missing_component(
    name: str,
    weight: float,
    reason: str,
    *,
    state: MissingDataState | None = None,
) -> PortfolioHealthComponent:
    field = {
        "risk": "technical_indicators",
        "position_quality": "composite_score",
    }.get(name, name)
    missing_state = state or MissingDataState.MISSING
    missing = MissingData(field=field, state=missing_state, reason=reason)
    return PortfolioHealthComponent(
        name=name,
        score=None,
        weight=weight,
        contribution=None,
        reasons=(reason,),
        warnings=(),
        missing_data=(missing,),
        evidence=({"metric": name, "state": missing_state.value},),
    )


def _alerts(
    components: tuple[PortfolioHealthComponent, ...], coverage: PortfolioCoverageReport
) -> tuple[PortfolioAlert, ...]:
    alerts: list[PortfolioAlert] = []
    for component in components:
        if component.score is not None and component.score < 50:
            alerts.append(
                PortfolioAlert(
                    severity="warning",
                    message=f"{component.name} has a lower deterministic research score.",
                    evidence=(
                        component.evidence[0]
                        if component.evidence
                        else {"component": component.name, "state": "missing_data"}
                    ),
                )
            )
    if coverage.coverage_pct < 1.0:
        alerts.append(
            PortfolioAlert(
                severity="info",
                message="Portfolio research coverage is incomplete.",
                evidence={"coverage_pct": coverage.coverage_pct},
            )
        )
    return tuple(alerts)


def _unique_missing(items: tuple[MissingData, ...]) -> tuple[MissingData, ...]:
    seen: set[tuple[str, MissingDataState, str]] = set()
    output: list[MissingData] = []
    for item in items:
        key = (item.field, item.state, item.reason)
        if key not in seen:
            seen.add(key)
            output.append(item)
    return tuple(output)
