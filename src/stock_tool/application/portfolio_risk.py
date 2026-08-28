"""Portfolio Risk v2 application contract built from existing bounded services.

This module intentionally does not value positions, replay ledger entries, or
calculate stress arithmetic itself.  It composes the existing explicit
boundaries into one serializable research result without inventing unavailable
inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Callable, Iterable, Mapping, Sequence

import pandas as pd

from stock_tool.data.contracts import sanitize_provider_text
from stock_tool.domain.models import MissingData, MissingDataState
from stock_tool.portfolio.ledger import LedgerSnapshot
from stock_tool.portfolio_health import PortfolioHealthResult
from stock_tool.portfolio_stress import (
    PortfolioStressResult,
    PortfolioStressService,
    StressScenario,
    StressScenarioType,
)
from stock_tool.portfolio_valuation import PortfolioValuationResult


@dataclass(frozen=True, slots=True)
class ExposureItem:
    """One evidence-backed portfolio exposure bucket."""

    identity: str
    weight: float
    source: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "identity", sanitize_provider_text(self.identity))
        object.__setattr__(self, "source", sanitize_provider_text(self.source))

    def to_dict(self) -> dict[str, object]:
        """Serialize the public exposure representation."""

        return {"identity": self.identity, "weight": self.weight, "source": self.source}


@dataclass(frozen=True, slots=True)
class ExposureResult:
    """Classified and unclassified base-value weights for one dimension."""

    dimension: str
    status: str
    items: tuple[ExposureItem, ...]
    classified_weight: float | None
    unclassified_weight: float | None
    missing_data: tuple[MissingData, ...] = ()
    conflicts: tuple[dict[str, object], ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Serialize an exposure without caller-owned input frames."""

        return {
            "dimension": self.dimension,
            "status": self.status,
            "items": [item.to_dict() for item in self.items],
            "classified_weight": self.classified_weight,
            "unclassified_weight": self.unclassified_weight,
            "missing_data": [item.to_dict() for item in self.missing_data],
            "conflicts": [dict(item) for item in self.conflicts],
        }


@dataclass(frozen=True, slots=True)
class FactorExposureResult:
    """Explicitly unsupported factor output rather than an invented coefficient."""

    status: str
    missing_data: tuple[MissingData, ...]

    def to_dict(self) -> dict[str, object]:
        """Serialize the honest unsupported-factor state."""

        return {
            "status": self.status,
            "missing_data": [item.to_dict() for item in self.missing_data],
        }


@dataclass(frozen=True, slots=True)
class PriceDataStatus:
    """Market-qualified price freshness for the current portfolio positions."""

    status: str
    data_as_of: str | None
    latest_by_identity: tuple[dict[str, str], ...]
    stale_identities: tuple[str, ...]
    missing_identities: tuple[str, ...]
    missing_data: tuple[MissingData, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Serialize per-holding price evidence without source price rows."""

        return {
            "status": self.status,
            "data_as_of": self.data_as_of,
            "latest_by_identity": [dict(item) for item in self.latest_by_identity],
            "stale_identities": list(self.stale_identities),
            "missing_identities": list(self.missing_identities),
            "missing_data": [item.to_dict() for item in self.missing_data],
        }


@dataclass(frozen=True, slots=True)
class EvidenceStressResult:
    """A stress result calculated only from caller-provided sensitivity evidence."""

    name: str
    status: str
    shock_pct: float | None
    base_currency: str
    base_value_before: float | None
    base_value_after: float | None
    base_impact: float | None
    assumptions: tuple[str, ...]
    missing_data: tuple[MissingData, ...]
    evidence: tuple[dict[str, object], ...]
    disclaimer: str

    def to_dict(self) -> dict[str, object]:
        """Serialize an evidence-backed or explicitly unavailable scenario."""

        return {
            "name": self.name,
            "status": self.status,
            "shock_pct": self.shock_pct,
            "base_currency": self.base_currency,
            "base_value_before": self.base_value_before,
            "base_value_after": self.base_value_after,
            "base_impact": self.base_impact,
            "assumptions": list(self.assumptions),
            "missing_data": [item.to_dict() for item in self.missing_data],
            "evidence": [dict(item) for item in self.evidence],
            "disclaimer": self.disclaimer,
        }


@dataclass(frozen=True, slots=True)
class PortfolioRiskResult:
    """A deterministic, non-prescriptive consolidated portfolio risk result."""

    base_currency: str
    total_portfolio_value: float | None
    realized_pnl: float | None
    unrealized_pnl: float | None
    position_concentration: float | None
    top_three_concentration: float | None
    market_exposure: ExposureResult
    currency_exposure: ExposureResult
    sector_exposure: ExposureResult
    industry_exposure: ExposureResult
    factor_exposure: FactorExposureResult
    stress_results: tuple[PortfolioStressResult, ...]
    evidence_stress_results: tuple[EvidenceStressResult, ...]
    price_data_status: PriceDataStatus
    coverage_pct: float | None
    missing_data: tuple[MissingData, ...]
    warnings: tuple[str, ...]
    assumptions: tuple[str, ...]
    evidence: tuple[dict[str, object], ...]
    calculated_at: str
    data_as_of: str | None
    disclaimer: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible public contract with sanitized text."""

        return {
            "base_currency": self.base_currency,
            "total_portfolio_value": self.total_portfolio_value,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "position_concentration": self.position_concentration,
            "top_three_concentration": self.top_three_concentration,
            "market_exposure": self.market_exposure.to_dict(),
            "currency_exposure": self.currency_exposure.to_dict(),
            "sector_exposure": self.sector_exposure.to_dict(),
            "industry_exposure": self.industry_exposure.to_dict(),
            "factor_exposure": self.factor_exposure.to_dict(),
            "stress_results": [_stress_to_dict(item) for item in self.stress_results],
            "evidence_stress_results": [item.to_dict() for item in self.evidence_stress_results],
            "price_data_status": self.price_data_status.to_dict(),
            "coverage_pct": self.coverage_pct,
            "missing_data": [item.to_dict() for item in self.missing_data],
            "warnings": list(self.warnings),
            "assumptions": list(self.assumptions),
            "evidence": [dict(item) for item in self.evidence],
            "calculated_at": self.calculated_at,
            "data_as_of": self.data_as_of,
            "disclaimer": self.disclaimer,
        }


class PortfolioRiskService:
    """Compose existing ledger, valuation, health, and stress services safely."""

    def __init__(
        self,
        *,
        stress_service: PortfolioStressService | None = None,
        now: Callable[[], datetime] | None = None,
        price_stale_after: timedelta = timedelta(days=7),
    ) -> None:
        self._stress_service = stress_service or PortfolioStressService()
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._price_stale_after = price_stale_after

    def assess(
        self,
        *,
        portfolio: pd.DataFrame,
        prices: pd.DataFrame | None,
        valuation: PortfolioValuationResult,
        health: PortfolioHealthResult,
        classifications: pd.DataFrame | None = None,
        ledger_snapshot: LedgerSnapshot | None = None,
        warnings: Sequence[str] = (),
        scenario_inputs: pd.DataFrame | None = None,
    ) -> PortfolioRiskResult:
        """Return one non-mutating risk snapshot from caller-provided evidence.

        Combined weights are available only if the existing valuation has a
        complete base-currency total and per-position weights.  Classification
        values are used only when their market-qualified identity and source
        are present; neither ticker shapes nor company names are inferred.
        """

        del portfolio  # Valuation already contains normalized position identity and value evidence.
        positions = valuation.positions.copy(deep=True)
        checked_at = self._now().astimezone(timezone.utc)
        price_data_status = _price_data_status(
            prices,
            positions,
            checked_at=checked_at,
            stale_after=self._price_stale_after,
        )
        complete_weights = _complete_base_weights(valuation, positions)
        market = _native_exposure(positions, "market", complete_weights)
        currency = _native_exposure(positions, "native_currency", complete_weights)
        classification_index = _classification_index(classifications)
        sector = _classified_exposure(positions, "sector", classification_index, complete_weights)
        industry = _classified_exposure(
            positions, "industry", classification_index, complete_weights
        )
        factor = FactorExposureResult(
            status="unknown",
            missing_data=(
                MissingData(
                    field="portfolio_factor_exposure",
                    state=MissingDataState.NOT_APPLICABLE,
                    reason=(
                        "No evidence-backed factor sensitivity input is available; "
                        "value, growth, momentum, beta, volatility, and rate exposures are not inferred."
                    ),
                ),
            ),
        )
        realized, ledger_missing = _realized_pnl(ledger_snapshot, valuation)
        stress_results = tuple(
            self._stress_service.run(valuation=valuation, scenario=scenario)
            for scenario in _preset_scenarios()
        )
        evidence_stress_results = _evidence_stress_results(
            valuation=valuation,
            positions=positions,
            scenario_inputs=scenario_inputs,
        )
        missing = _unique_missing(
            (
                *valuation.missing_data,
                *health.missing_data,
                *market.missing_data,
                *currency.missing_data,
                *sector.missing_data,
                *industry.missing_data,
                *factor.missing_data,
                *price_data_status.missing_data,
                *ledger_missing,
                *(item for result in stress_results for item in result.missing_data),
                *(item for result in evidence_stress_results for item in result.missing_data),
            )
        )
        sanitized_warnings = tuple(
            dict.fromkeys(
                sanitize_provider_text(item)
                for item in (*valuation.warnings, *health.warnings, *warnings)
            )
        )
        weights = _weights(positions) if complete_weights else pd.Series(dtype=float)
        evidence = _evidence(valuation, positions, classifications)
        timestamp = checked_at.isoformat()
        return PortfolioRiskResult(
            base_currency=valuation.base_currency.value,
            total_portfolio_value=valuation.base_market_value,
            realized_pnl=realized,
            unrealized_pnl=valuation.base_unrealized_pnl,
            position_concentration=float(weights.max()) if not weights.empty else None,
            top_three_concentration=float(weights.nlargest(3).sum()) if not weights.empty else None,
            market_exposure=market,
            currency_exposure=currency,
            sector_exposure=sector,
            industry_exposure=industry,
            factor_exposure=factor,
            stress_results=stress_results,
            evidence_stress_results=evidence_stress_results,
            price_data_status=price_data_status,
            coverage_pct=health.coverage.coverage_pct,
            missing_data=missing,
            warnings=sanitized_warnings,
            assumptions=(
                "Consolidated weights require complete market prices and explicit FX conversion evidence.",
                "Sector and industry exposure uses only market-qualified classification rows with a source.",
                "Stress scenarios are deterministic assumptions, not forecasts, VaR estimates, or trading instructions.",
            ),
            evidence=evidence,
            calculated_at=timestamp,
            data_as_of=price_data_status.data_as_of,
            disclaimer=(
                "此投資組合風險中心僅供研究、學習與風險檢視，不構成投資建議、交易指令或報酬保證。"
            ),
        )


def _complete_base_weights(valuation: PortfolioValuationResult, positions: pd.DataFrame) -> bool:
    if valuation.base_market_value is None or valuation.base_market_value <= 0 or positions.empty:
        return False
    if "weight" not in positions.columns:
        return False
    weights = _weights(positions)
    return len(weights) == len(positions) and bool(weights.notna().all())


def _weights(positions: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(positions.get("weight"), errors="coerce")


def _unknown_exposure(dimension: str, reason: str) -> ExposureResult:
    missing = MissingData(
        field="portfolio_risk.exposure",
        state=MissingDataState.UNKNOWN,
        reason=reason,
    )
    return ExposureResult(dimension, "unknown", (), None, None, (missing,))


def _native_exposure(
    positions: pd.DataFrame,
    column: str,
    complete_weights: bool,
) -> ExposureResult:
    if not complete_weights:
        return _unknown_exposure(
            column,
            f"{column} exposure requires a complete base-currency valuation; partial positions are not re-normalized.",
        )
    if positions.empty:
        return ExposureResult(column, "not_applicable", (), 0.0, 0.0)
    work = positions.loc[:, [column, "weight"]].copy(deep=True)
    work[column] = work[column].fillna("").astype(str).str.strip().str.upper()
    grouped = work.groupby(column, sort=True)["weight"].sum()
    items = tuple(
        ExposureItem(identity=str(identity), weight=float(weight), source="valuation")
        for identity, weight in sorted(grouped.items(), key=lambda item: (-item[1], item[0]))
        if str(identity)
    )
    return ExposureResult(column, "available", items, float(grouped.sum()), 0.0)


def _classification_index(
    classifications: pd.DataFrame | None,
) -> dict[tuple[str, str], dict[str, object]]:
    required = {"symbol", "market", "source"}
    if (
        classifications is None
        or classifications.empty
        or not required.issubset(classifications.columns)
    ):
        return {}
    work = classifications.copy(deep=True)
    work["symbol"] = work["symbol"].fillna("").astype(str).str.strip().str.upper()
    work["market"] = work["market"].fillna("").astype(str).str.strip().str.upper()
    work["source"] = work["source"].fillna("").astype(str).str.strip()
    work = work.loc[
        work["symbol"].ne("") & work["market"].isin({"TWSE", "TPEX", "US"}) & work["source"].ne("")
    ]
    output: dict[tuple[str, str], dict[str, object]] = {}
    for identity, rows in work.groupby(["symbol", "market"], sort=True):
        sources = tuple(sorted({sanitize_provider_text(value) for value in rows["source"]}))
        sector_values = tuple(
            sorted(
                {
                    sanitize_provider_text(value).strip()
                    for value in rows.get("sector", pd.Series(dtype=str)).dropna().astype(str)
                    if sanitize_provider_text(value).strip()
                }
            )
        )
        industry_values = tuple(
            sorted(
                {
                    sanitize_provider_text(value).strip()
                    for value in rows.get("industry", pd.Series(dtype=str)).dropna().astype(str)
                    if sanitize_provider_text(value).strip()
                }
            )
        )
        output[(str(identity[0]), str(identity[1]))] = {
            "sector_values": sector_values,
            "industry_values": industry_values,
            "sources": sources,
        }
    return output


def _classified_exposure(
    positions: pd.DataFrame,
    dimension: str,
    index: Mapping[tuple[str, str], Mapping[str, object]],
    complete_weights: bool,
) -> ExposureResult:
    if not complete_weights:
        return _unknown_exposure(
            dimension,
            f"{dimension} exposure requires a complete base-currency valuation; partial positions are not re-normalized.",
        )
    if positions.empty:
        return ExposureResult(dimension, "not_applicable", (), 0.0, 0.0)
    buckets: dict[str, float] = {}
    unclassified = 0.0
    sources: dict[str, set[str]] = {}
    conflicts: list[dict[str, object]] = []
    for row in positions.itertuples(index=False):
        identity = (str(row.symbol).strip().upper(), str(row.market).strip().upper())
        detail = index.get(identity)
        weight = float(getattr(row, "weight"))
        if detail is None:
            values: tuple[str, ...] = ()
            detail_sources: tuple[str, ...] = ()
        else:
            values = _text_tuple(detail.get(f"{dimension}_values", ()))
            detail_sources = _text_tuple(detail.get("sources", ()))
        if len(values) != 1:
            unclassified += weight
            if len(values) > 1:
                conflicts.append(
                    {
                        "identity": f"{identity[0]}|{identity[1]}",
                        "field": dimension,
                        "values": list(values),
                        "sources": list(detail_sources),
                    }
                )
            continue
        value = str(values[0])
        buckets[value] = buckets.get(value, 0.0) + weight
        sources.setdefault(value, set()).update(detail_sources)
    items = tuple(
        ExposureItem(identity=name, weight=weight, source=", ".join(sorted(sources[name])))
        for name, weight in sorted(buckets.items(), key=lambda item: (-item[1], item[0]))
    )
    missing: list[MissingData] = []
    if conflicts:
        missing.append(
            MissingData(
                field=f"portfolio_{dimension}_classification",
                state=MissingDataState.UNKNOWN,
                reason=(
                    f"{len(conflicts)} market-qualified {dimension} classification conflict(s) "
                    "lack an approved source-priority policy."
                ),
            )
        )
    if not items:
        missing_item = MissingData(
            field=f"portfolio_{dimension}_exposure",
            state=MissingDataState.UNKNOWN,
            reason=f"No source-backed {dimension} classifications are available for valued positions.",
        )
        return ExposureResult(
            dimension,
            "unknown",
            (),
            0.0,
            float(unclassified),
            tuple((*missing, missing_item)),
            tuple(conflicts),
        )
    status = "available" if unclassified == 0.0 else "partial"
    if unclassified:
        missing.append(
            MissingData(
                field=f"portfolio_{dimension}_exposure",
                state=MissingDataState.UNKNOWN,
                reason=f"{unclassified:.1%} of valued positions lack source-backed {dimension} classification.",
            )
        )
    return ExposureResult(
        dimension,
        status,
        items,
        1.0 - unclassified,
        unclassified,
        tuple(missing),
        tuple(conflicts),
    )


def _text_tuple(value: object) -> tuple[str, ...]:
    """Return a deterministic text tuple from structured classification evidence."""

    if not isinstance(value, (tuple, list, set, frozenset)):
        return ()
    return tuple(str(item) for item in value)


def _realized_pnl(
    ledger: LedgerSnapshot | None, valuation: PortfolioValuationResult
) -> tuple[float | None, tuple[MissingData, ...]]:
    if ledger is None:
        return None, (
            MissingData(
                field="realized_pnl",
                state=MissingDataState.UNKNOWN,
                reason="No ledger snapshot was supplied; realized P/L is unavailable.",
            ),
        )
    rates = {valuation.base_currency.value: 1.0}
    for row in valuation.positions.itertuples(index=False):
        currency = str(getattr(row, "native_currency", "")).upper()
        rate = getattr(row, "fx_rate_to_base", None)
        if currency and rate is not None:
            rates[currency] = float(rate)
    total = 0.0
    for amount in ledger.realized_pnl_by_currency:
        if (
            amount.currency in ledger.unavailable_realized_currencies
            or amount.currency not in rates
        ):
            return None, (
                MissingData(
                    field="realized_pnl",
                    state=MissingDataState.UNKNOWN,
                    reason=f"No explicit conversion evidence is available for realized P/L currency {amount.currency}.",
                ),
            )
        total += float(amount.amount) * rates[amount.currency]
    return total, ()


def _preset_scenarios() -> tuple[StressScenario, ...]:
    return (
        StressScenario("all_holdings_correction_10", StressScenarioType.ALL_HOLDINGS_DECLINE, 0.10),
        StressScenario("all_holdings_stress_20", StressScenarioType.ALL_HOLDINGS_DECLINE, 0.20),
        StressScenario(
            "largest_holding_decline_25", StressScenarioType.LARGEST_HOLDING_DECLINE, 0.25
        ),
        StressScenario("twse_market_decline_15", StressScenarioType.MARKET_DECLINE, 0.15, "TWSE"),
        StressScenario("tpex_market_decline_15", StressScenarioType.MARKET_DECLINE, 0.15, "TPEX"),
        StressScenario("us_market_decline_15", StressScenarioType.MARKET_DECLINE, 0.15, "US"),
        StressScenario("usd_twd_plus_5", StressScenarioType.USD_TWD_MOVE, 0.05),
        StressScenario("usd_twd_minus_5", StressScenarioType.USD_TWD_MOVE, -0.05),
        StressScenario("usd_twd_plus_10", StressScenarioType.USD_TWD_MOVE, 0.10),
        StressScenario("usd_twd_minus_10", StressScenarioType.USD_TWD_MOVE, -0.10),
    )


def _price_data_status(
    prices: pd.DataFrame | None,
    positions: pd.DataFrame,
    *,
    checked_at: datetime,
    stale_after: timedelta,
) -> PriceDataStatus:
    """Return per-holding date evidence without inferring a missing market."""

    identities = tuple(
        sorted(
            {
                (str(row.symbol).strip().upper(), str(row.market).strip().upper())
                for row in positions.itertuples(index=False)
            }
        )
    )
    latest: dict[tuple[str, str], datetime] = {}
    if (
        prices is not None
        and not prices.empty
        and {"date", "symbol", "market"}.issubset(prices.columns)
    ):
        work = prices.loc[:, ["date", "symbol", "market"]].copy(deep=True)
        work["symbol"] = work["symbol"].fillna("").astype(str).str.strip().str.upper()
        work["market"] = work["market"].fillna("").astype(str).str.strip().str.upper()
        work["date"] = pd.to_datetime(work["date"], errors="coerce", utc=True)
        work = work.dropna(subset=["date"])
        for row in work.itertuples(index=False):
            identity = (str(row.symbol), str(row.market))
            if identity not in identities:
                continue
            current = latest.get(identity)
            if current is None or row.date.to_pydatetime() > current:
                latest[identity] = row.date.to_pydatetime()

    stale_cutoff = checked_at - stale_after
    missing_identities = tuple(
        f"{symbol}|{market}" for symbol, market in identities if (symbol, market) not in latest
    )
    stale_identities = tuple(
        f"{symbol}|{market}"
        for symbol, market in identities
        if (date := latest.get((symbol, market))) is not None and date < stale_cutoff
    )
    latest_by_identity = tuple(
        {
            "identity": f"{symbol}|{market}",
            "last_price_date": latest[(symbol, market)].date().isoformat(),
        }
        for symbol, market in identities
        if (symbol, market) in latest
    )
    missing_data: list[MissingData] = []
    if missing_identities:
        missing_data.append(
            MissingData(
                field="portfolio_risk.price_data",
                state=MissingDataState.MISSING,
                reason="Missing market-qualified prices for: "
                + ", ".join(missing_identities)
                + ".",
            )
        )
    if stale_identities:
        missing_data.append(
            MissingData(
                field="portfolio_risk.price_freshness",
                state=MissingDataState.STALE,
                reason="Stale market-qualified prices for: " + ", ".join(stale_identities) + ".",
            )
        )
    if missing_identities:
        status = "partial" if latest else "unknown"
    elif stale_identities:
        status = "stale"
    else:
        status = "available"
    data_as_of = min(latest.values()).date().isoformat() if latest else None
    return PriceDataStatus(
        status=status,
        data_as_of=data_as_of,
        latest_by_identity=latest_by_identity,
        stale_identities=stale_identities,
        missing_identities=missing_identities,
        missing_data=tuple(missing_data),
    )


def _evidence_stress_results(
    *,
    valuation: PortfolioValuationResult,
    positions: pd.DataFrame,
    scenario_inputs: pd.DataFrame | None,
) -> tuple[EvidenceStressResult, ...]:
    """Calculate only explicitly supplied volatility/rate sensitivity scenarios."""

    return tuple(
        _evidence_stress_result(
            name=name,
            valuation=valuation,
            positions=positions,
            scenario_inputs=scenario_inputs,
        )
        for name in ("volatility_spike", "interest_rate_shock")
    )


def _evidence_stress_result(
    *,
    name: str,
    valuation: PortfolioValuationResult,
    positions: pd.DataFrame,
    scenario_inputs: pd.DataFrame | None,
) -> EvidenceStressResult:
    """Fail closed when explicit position sensitivity evidence is incomplete."""

    required = {"symbol", "market", "scenario_type", "shock_pct", "sensitivity", "source"}
    unavailable_reason = (
        f"{name} requires explicit market-qualified shock_pct, sensitivity, and source "
        "for every valued position; no beta, duration, or rate sensitivity is inferred."
    )
    if (
        valuation.base_market_value is None
        or scenario_inputs is None
        or not required.issubset(scenario_inputs.columns)
    ):
        return _unknown_evidence_stress(name, valuation.base_currency.value, unavailable_reason)
    work = scenario_inputs.loc[:, sorted(required)].copy(deep=True)
    work["symbol"] = work["symbol"].fillna("").astype(str).str.strip().str.upper()
    work["market"] = work["market"].fillna("").astype(str).str.strip().str.upper()
    work["scenario_type"] = work["scenario_type"].fillna("").astype(str).str.strip().str.lower()
    work["source"] = work["source"].fillna("").astype(str).str.strip()
    work = work.loc[work["scenario_type"].eq(name)].copy()
    expected = {
        (str(row.symbol).strip().upper(), str(row.market).strip().upper())
        for row in positions.itertuples(index=False)
        if pd.notna(getattr(row, "base_market_value", None))
    }
    provided = {(str(row.symbol), str(row.market)) for row in work.itertuples(index=False)}
    if (
        not expected
        or expected != provided
        or work["source"].eq("").any()
        or work.duplicated(["symbol", "market"], keep=False).any()
    ):
        return _unknown_evidence_stress(name, valuation.base_currency.value, unavailable_reason)
    work["shock_pct"] = pd.to_numeric(work["shock_pct"], errors="coerce")
    work["sensitivity"] = pd.to_numeric(work["sensitivity"], errors="coerce")
    if work[["shock_pct", "sensitivity"]].isna().any().any() or not all(
        isfinite(float(value)) for value in work[["shock_pct", "sensitivity"]].to_numpy().ravel()
    ):
        return _unknown_evidence_stress(name, valuation.base_currency.value, unavailable_reason)
    values = positions.loc[:, ["symbol", "market", "base_market_value"]].copy(deep=True)
    values["symbol"] = values["symbol"].astype(str).str.strip().str.upper()
    values["market"] = values["market"].astype(str).str.strip().str.upper()
    merged = values.merge(work, on=["symbol", "market"], how="inner", validate="one_to_one")
    impact = float(
        (merged["base_market_value"] * merged["sensitivity"] * merged["shock_pct"]).sum()
    )
    before = float(valuation.base_market_value)
    sources = tuple(sorted({sanitize_provider_text(value) for value in merged["source"]}))
    return EvidenceStressResult(
        name=name,
        status="available",
        shock_pct=(
            float(merged["shock_pct"].iloc[0]) if merged["shock_pct"].nunique() == 1 else None
        ),
        base_currency=valuation.base_currency.value,
        base_value_before=before,
        base_value_after=before + impact,
        base_impact=impact,
        assumptions=(
            "Uses caller-supplied position sensitivities only; values are not inferred.",
            "This deterministic scenario is an assumption, not a forecast or VaR estimate.",
        ),
        missing_data=(),
        evidence=tuple({"source": source} for source in sources),
        disclaimer="This scenario is not a forecast, VaR estimate, or investment recommendation.",
    )


def _unknown_evidence_stress(name: str, base_currency: str, reason: str) -> EvidenceStressResult:
    return EvidenceStressResult(
        name=name,
        status="unknown",
        shock_pct=None,
        base_currency=base_currency,
        base_value_before=None,
        base_value_after=None,
        base_impact=None,
        assumptions=("No stock sensitivity, beta, duration, or rate exposure is inferred.",),
        missing_data=(
            MissingData(
                field=f"portfolio_risk.{name}",
                state=MissingDataState.UNKNOWN,
                reason=reason,
            ),
        ),
        evidence=(),
        disclaimer="This scenario is unavailable, not a forecast, VaR estimate, or investment recommendation.",
    )


def _evidence(
    valuation: PortfolioValuationResult,
    positions: pd.DataFrame,
    classifications: pd.DataFrame | None,
) -> tuple[dict[str, object], ...]:
    output: list[dict[str, object]] = [
        {
            "source": "portfolio_valuation",
            "base_currency": valuation.base_currency.value,
            "valued_positions": (
                int(positions["base_market_value"].notna().sum())
                if "base_market_value" in positions
                else 0
            ),
        }
    ]
    if (
        classifications is not None
        and not classifications.empty
        and "source" in classifications.columns
    ):
        output.append(
            {
                "source": "classification",
                "providers": sorted(
                    {
                        sanitize_provider_text(value)
                        for value in classifications["source"].dropna().astype(str)
                        if value.strip()
                    }
                ),
            }
        )
    return tuple(output)


def _stress_to_dict(result: PortfolioStressResult) -> dict[str, object]:
    return {
        "name": result.scenario.name,
        "scenario_type": result.scenario.scenario_type.value,
        "shock_pct": result.scenario.shock_pct,
        "market": result.scenario.market,
        "base_currency": result.base_currency,
        "base_value_before": result.base_value_before,
        "base_value_after": result.base_value_after,
        "base_impact": result.base_impact,
        "assumptions": [sanitize_provider_text(item) for item in result.assumptions],
        "missing_data": [item.to_dict() for item in result.missing_data],
        "disclaimer": sanitize_provider_text(result.disclaimer),
    }


def _unique_missing(items: Iterable[MissingData]) -> tuple[MissingData, ...]:
    return tuple(dict.fromkeys(items))
