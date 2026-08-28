"""Application service that composes hydration, indicators, fundamentals, and scores."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from stock_tool.application.data_hydration import DataHydrationService
from stock_tool.application.results import (
    AnalysisRequest,
    AnalysisResult,
    AnalysisStatus,
    DataSnapshot,
)
from stock_tool.domain.models import MissingData, MissingDataState, Symbol
from stock_tool.stock_scoring import StockScoreResult

IndicatorCalculator = Callable[[pd.DataFrame], pd.DataFrame]
FundamentalLoader = Callable[[Symbol], pd.DataFrame]
FundamentalScorer = Callable[[pd.DataFrame], pd.DataFrame]
StockScorer = Callable[..., StockScoreResult]


@dataclass(slots=True)
class AnalysisService:
    """Compose existing research functions without changing their formulas or APIs."""

    hydration_service: DataHydrationService
    indicator_calculator: IndicatorCalculator | None = None
    fundamental_loader: FundamentalLoader | None = None
    fundamental_scorer: FundamentalScorer | None = None
    stock_scorer: StockScorer | None = None

    def analyze(self, request: AnalysisRequest | None = None) -> AnalysisResult:
        """Run one request-bound analysis and return explicit, non-fabricated availability states."""

        hydration = self.hydration_service.hydrate(
            request.data_request if request is not None else None
        )
        if not hydration.has_usable_data:
            return AnalysisResult(
                symbol=hydration.symbol,
                status=(
                    AnalysisStatus.ERROR
                    if hydration.status.value == "error"
                    else AnalysisStatus.INSUFFICIENT_DATA
                ),
                hydration=hydration,
                missing_data=hydration.missing_data,
                warnings=hydration.warnings,
                limitations=(
                    "Price-data analysis was not run because no validated price frame is available.",
                ),
                request=request,
            )

        indicators, indicator_missing, indicator_warnings = self._calculate_indicators(hydration)
        fundamentals, fundamental_missing, fundamental_warnings = self._score_fundamentals(
            hydration.symbol,
            include_fundamentals=request is None or request.include_fundamentals,
        )
        warnings = (*hydration.warnings, *indicator_warnings, *fundamental_warnings)
        missing_data = (*hydration.missing_data, *indicator_missing, *fundamental_missing)

        if indicators is None:
            skipped_composite = MissingData(
                field="composite_score",
                state=MissingDataState.NOT_APPLICABLE,
                reason="Composite scoring was not run because technical indicators are unavailable.",
            )
            return AnalysisResult(
                symbol=hydration.symbol,
                status=AnalysisStatus.PARTIAL,
                hydration=hydration,
                fundamental_scores=fundamentals,
                missing_data=(*missing_data, skipped_composite),
                warnings=warnings,
                limitations=(
                    "Technical indicators were unavailable, so no composite score was calculated.",
                ),
                request=request,
            )

        stock_score, composite_missing, score_warnings = self._score_stock(
            hydration,
            indicators,
            fundamentals,
        )
        missing_data = (*missing_data, *composite_missing)
        warnings = (*warnings, *score_warnings)
        status = self._analysis_status(hydration, stock_score, missing_data)
        limitations = _limitations_for(status, stock_score, composite_missing)
        return AnalysisResult(
            symbol=hydration.symbol,
            status=status,
            hydration=hydration,
            indicators=indicators,
            fundamental_scores=fundamentals,
            stock_score=stock_score,
            missing_data=missing_data,
            warnings=warnings,
            limitations=limitations,
            request=request,
        )

    def _calculate_indicators(
        self,
        hydration: DataSnapshot,
    ) -> tuple[pd.DataFrame | None, tuple[MissingData, ...], tuple[str, ...]]:
        if self.indicator_calculator is None:
            return (
                None,
                (
                    MissingData(
                        field="technical_indicators",
                        state=MissingDataState.NOT_APPLICABLE,
                        reason="No indicator calculator was configured for this analysis.",
                    ),
                ),
                (),
            )
        if hydration.data is None:
            return (
                None,
                (
                    MissingData(
                        field="technical_indicators",
                        state=MissingDataState.UNKNOWN,
                        reason="Validated price data was unavailable for indicator calculation.",
                    ),
                ),
                (),
            )
        try:
            return self.indicator_calculator(hydration.data.copy(deep=True)), (), ()
        except Exception as exc:
            return (
                None,
                (
                    MissingData(
                        field="technical_indicators",
                        state=MissingDataState.UNKNOWN,
                        reason="Technical indicator calculation failed.",
                    ),
                ),
                (f"Indicator calculation failed ({type(exc).__name__}).",),
            )

    def _score_fundamentals(
        self,
        symbol: Symbol,
        *,
        include_fundamentals: bool,
    ) -> tuple[pd.DataFrame | None, tuple[MissingData, ...], tuple[str, ...]]:
        if not include_fundamentals:
            return (
                None,
                (
                    MissingData(
                        field="fundamental_data",
                        state=MissingDataState.NOT_APPLICABLE,
                        reason="Fundamental analysis was not requested for this analysis.",
                    ),
                ),
                (),
            )
        if self.fundamental_loader is None or self.fundamental_scorer is None:
            return (
                None,
                (
                    MissingData(
                        field="fundamental_data",
                        state=MissingDataState.MISSING,
                        reason="No fundamental-data loader and scorer were configured for this analysis.",
                    ),
                ),
                (),
            )
        try:
            fundamentals = self.fundamental_loader(symbol)
            if fundamentals.empty:
                return (
                    None,
                    (
                        MissingData(
                            field="fundamental_data",
                            state=MissingDataState.MISSING,
                            reason="The configured fundamental loader returned no rows for the symbol.",
                        ),
                    ),
                    (),
                )
            scores = self.fundamental_scorer(fundamentals.copy(deep=True))
            return scores.copy(deep=True), (), ()
        except Exception as exc:
            return (
                None,
                (
                    MissingData(
                        field="fundamental_data",
                        state=MissingDataState.UNKNOWN,
                        reason="The configured fundamental data could not be scored.",
                    ),
                ),
                (f"Fundamental scoring failed ({type(exc).__name__}).",),
            )

    def _score_stock(
        self,
        hydration: DataSnapshot,
        indicators: pd.DataFrame,
        fundamentals: pd.DataFrame | None,
    ) -> tuple[StockScoreResult | None, tuple[MissingData, ...], tuple[str, ...]]:
        if self.stock_scorer is None:
            return (
                None,
                (
                    MissingData(
                        field="composite_score",
                        state=MissingDataState.NOT_APPLICABLE,
                        reason="No composite stock scorer was configured for this analysis.",
                    ),
                ),
                (),
            )
        if hydration.data is None:
            return (
                None,
                (
                    MissingData(
                        field="composite_score",
                        state=MissingDataState.UNKNOWN,
                        reason="Validated price data was unavailable for composite scoring.",
                    ),
                ),
                (),
            )
        try:
            score = self.stock_scorer(
                symbol=hydration.symbol.code,
                price_data=hydration.data.copy(deep=True),
                technical_indicators=indicators.copy(deep=True),
                fundamental_scores=(
                    fundamentals.copy(deep=True) if fundamentals is not None else None
                ),
            )
            return score, (), ()
        except Exception as exc:
            return (
                None,
                (
                    MissingData(
                        field="composite_score",
                        state=MissingDataState.UNKNOWN,
                        reason="Composite stock scoring failed.",
                    ),
                ),
                (f"Composite scoring failed ({type(exc).__name__}).",),
            )

    @staticmethod
    def _analysis_status(
        hydration: DataSnapshot,
        stock_score: StockScoreResult | None,
        missing_data: tuple[MissingData, ...],
    ) -> AnalysisStatus:
        if hydration.is_stale:
            return AnalysisStatus.STALE
        if hydration.status.value == "partial":
            return AnalysisStatus.PARTIAL
        if stock_score is None or missing_data:
            return AnalysisStatus.PARTIAL
        if stock_score.total_score == "unknown":
            return AnalysisStatus.INSUFFICIENT_DATA
        return AnalysisStatus.SUCCESS


def _limitations_for(
    status: AnalysisStatus,
    stock_score: StockScoreResult | None,
    composite_missing: tuple[MissingData, ...],
) -> tuple[str, ...]:
    """Explain incomplete results instead of implying a precise unavailable score."""

    if status is AnalysisStatus.STALE:
        return ("Price data is older than the configured freshness policy.",)
    if composite_missing:
        return ("A composite score was not available; review missing-data details.",)
    if status is AnalysisStatus.PARTIAL:
        return ("Provider validation or required analysis inputs are incomplete.",)
    if status is AnalysisStatus.INSUFFICIENT_DATA:
        if stock_score is None:
            return (
                "A composite score was not calculated because required collaborators are missing.",
            )
        return ("A complete composite score requires all weighted components to be available.",)
    return ()
