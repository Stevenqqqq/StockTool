"""Typed, immutable research snapshots assembled from existing research results."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

import pandas as pd

from stock_tool.company_research import CompanyResearchProfile
from stock_tool.domain.models import MissingData, MissingDataState, Symbol
from stock_tool.entry_reference import EntryReference
from stock_tool.stock_scoring import ScoreComponent, StockScoreResult


class ResearchSnapshotStatus(StrEnum):
    """Explicit display state for one immutable research snapshot."""

    READY = "ready"
    PARTIAL = "partial"
    INSUFFICIENT_DATA = "insufficient_data"
    STALE = "stale"
    ERROR = "error"


class EvidenceKind(StrEnum):
    """Classify facts, deterministic calculations, and research inferences."""

    FACT = "fact"
    CALCULATION = "calculation"
    RESEARCH_INFERENCE = "research_inference"


@dataclass(frozen=True, slots=True)
class ResearchSourceMetadata:
    """Safe, display-ready provenance for the price data in a snapshot."""

    provider: str | None
    query_symbol: str | None
    market: str
    source_type: str
    fetched_at: str | None
    last_data_date: str | None
    row_count: int
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    @classmethod
    def empty(cls, *, symbol: str, market: str) -> ResearchSourceMetadata:
        """Create explicit unavailable provenance without inventing a provider."""

        return cls(
            provider=None,
            query_symbol=symbol,
            market=market,
            source_type="unknown",
            fetched_at=None,
            last_data_date=None,
            row_count=0,
            limitations=("尚未取得可驗證的資料來源 metadata。",),
        )


@dataclass(frozen=True, slots=True)
class ResearchEvidenceItem:
    """One source-labelled fact, calculation, or clearly labelled inference."""

    label: str
    text: str
    kind: EvidenceKind
    source: str | None = None


@dataclass(frozen=True, slots=True)
class PriceSnapshot:
    """Latest available quote values without assuming a live market feed."""

    latest_close: float | None
    previous_close: float | None
    change: float | None
    change_pct: float | None
    latest_volume: float | None
    last_data_date: str | None


@dataclass(frozen=True, slots=True)
class ScenarioReferenceRange:
    """Research-only range derived by the existing entry-reference model."""

    title: str
    method: str
    as_of_date: str | None
    latest_close: float | None
    range_low: float | None
    range_high: float | None
    breakout_observation: float | None
    risk_reference: float | None
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    available: bool


@dataclass(frozen=True, slots=True)
class ResearchSnapshot:
    """Read-only application view of one security research request."""

    symbol: Symbol
    status: ResearchSnapshotStatus
    company_name: str | None
    company_profile: CompanyResearchProfile | None
    price: PriceSnapshot | None
    price_history: pd.DataFrame | None
    indicators: pd.DataFrame | None
    fundamental_results: pd.DataFrame | None
    composite_score: float | None
    available_score: float | None
    component_scores: tuple[ScoreComponent, ...]
    component_contributions: dict[str, float]
    score_coverage: float | None
    strengths: tuple[str, ...]
    weaknesses: tuple[str, ...]
    principal_risks: tuple[str, ...]
    scenario_reference: ScenarioReferenceRange | None
    source_metadata: ResearchSourceMetadata
    updated_at: str | None
    missing_data: tuple[MissingData, ...]
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    evidence_items: tuple[ResearchEvidenceItem, ...]
    error_message: str | None = None

    def __post_init__(self) -> None:
        """Defensively copy DataFrames before making the snapshot available to UI code."""

        if self.price_history is not None:
            object.__setattr__(self, "price_history", self.price_history.copy(deep=True))
        if self.indicators is not None:
            object.__setattr__(self, "indicators", self.indicators.copy(deep=True))
        if self.fundamental_results is not None:
            object.__setattr__(
                self, "fundamental_results", self.fundamental_results.copy(deep=True)
            )
        object.__setattr__(self, "component_scores", tuple(self.component_scores))
        object.__setattr__(self, "component_contributions", dict(self.component_contributions))
        object.__setattr__(self, "missing_data", tuple(self.missing_data))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(self, "limitations", tuple(self.limitations))
        object.__setattr__(self, "evidence_items", tuple(self.evidence_items))


@dataclass(frozen=True, slots=True)
class ResearchWorkspaceService:
    """Compose existing research results into a UI-independent snapshot.

    The service deliberately receives a canonical ``StockScoreResult`` instead
    of recalculating it. This keeps the existing 30/30/20/20 score formula as
    the single authority and makes missing data visible rather than synthetic.
    """

    scenario_title: str = "情境參考區間"

    def build(
        self,
        *,
        symbol: Symbol,
        price_data: pd.DataFrame | None,
        indicators: pd.DataFrame | None,
        fundamental_results: pd.DataFrame | None,
        stock_score: StockScoreResult | None,
        company_profile: CompanyResearchProfile | None,
        scenario_reference: EntryReference | None,
        source_metadata: ResearchSourceMetadata,
        missing_data: tuple[MissingData, ...] = (),
        warnings: tuple[str, ...] = (),
        limitations: tuple[str, ...] = (),
        is_stale: bool = False,
        error_message: str | None = None,
    ) -> ResearchSnapshot:
        """Build one status-explicit snapshot without changing input models or frames."""

        prices = _copy_frame(price_data)
        indicator_frame = _copy_frame(indicators)
        fundamental_frame = _copy_frame(fundamental_results)
        price = _price_snapshot(prices)
        canonical_missing = list(missing_data)
        if prices is None or prices.empty or price is None:
            canonical_missing.append(
                MissingData(
                    field="price_data",
                    state=MissingDataState.MISSING,
                    reason="沒有可用的價格資料可建立研究快照。",
                )
            )
        if stock_score is None:
            canonical_missing.append(
                MissingData(
                    field="composite_score",
                    state=MissingDataState.UNKNOWN,
                    reason="尚未取得既有綜合評分結果。",
                )
            )
        else:
            canonical_missing.extend(_score_missing_data(stock_score))
        usable_profile = _usable_company_profile(company_profile)
        if usable_profile is None:
            canonical_missing.append(
                MissingData(
                    field="company_profile",
                    state=MissingDataState.MISSING,
                    reason=(
                        company_profile.retrieval_issue
                        if company_profile is not None and company_profile.retrieval_issue
                        else "沒有可驗證的公司介紹資料；請確認代號、市場或補充公開公司資料。"
                    ),
                )
            )

        deduped_missing = _dedupe_missing(canonical_missing)
        score = stock_score
        composite_score = _score_value(score.total_score) if score is not None else None
        available_score = _score_value(score.available_score) if score is not None else None
        components = score.components if score is not None else ()
        contributions = {
            component.name: float(component.score)
            for component in components
            if isinstance(component.score, int | float)
        }
        scenario = _scenario_range(scenario_reference, title=self.scenario_title)
        evidence = _evidence_items(
            symbol=symbol,
            price=price,
            source=source_metadata,
            score=score,
            profile=usable_profile,
            scenario=scenario,
        )
        profile_limitations = usable_profile.limitations if usable_profile is not None else ()
        score_risks = score.risk_notes if score is not None else ()
        profile_risks = usable_profile.bottlenecks if usable_profile is not None else ()
        status = _snapshot_status(
            price=price,
            score=score,
            missing_data=deduped_missing,
            is_stale=is_stale,
            error_message=error_message,
        )
        return ResearchSnapshot(
            symbol=symbol,
            status=status,
            company_name=(usable_profile.company_name if usable_profile is not None else None),
            company_profile=usable_profile,
            price=price,
            price_history=prices,
            indicators=indicator_frame,
            fundamental_results=fundamental_frame,
            composite_score=composite_score,
            available_score=available_score,
            component_scores=components,
            component_contributions=contributions,
            score_coverage=(score.coverage if score is not None else None),
            strengths=score.strengths if score is not None else (),
            weaknesses=score.weaknesses if score is not None else (),
            principal_risks=tuple(dict.fromkeys((*score_risks, *profile_risks))),
            scenario_reference=scenario,
            source_metadata=source_metadata,
            updated_at=source_metadata.fetched_at,
            missing_data=deduped_missing,
            warnings=tuple(dict.fromkeys((*source_metadata.warnings, *warnings))),
            limitations=tuple(
                dict.fromkeys((*source_metadata.limitations, *profile_limitations, *limitations))
            ),
            evidence_items=evidence,
            error_message=error_message,
        )


def _copy_frame(frame: pd.DataFrame | None) -> pd.DataFrame | None:
    return None if frame is None else frame.copy(deep=True)


def _price_snapshot(prices: pd.DataFrame | None) -> PriceSnapshot | None:
    if prices is None or prices.empty or "date" not in prices.columns:
        return None
    ordered = prices.copy(deep=True)
    ordered["date"] = pd.to_datetime(ordered["date"], errors="coerce")
    ordered = ordered.dropna(subset=["date"]).sort_values("date", kind="stable")
    if ordered.empty:
        return None
    latest = ordered.iloc[-1]
    previous = ordered.iloc[-2] if len(ordered) > 1 else None
    close = _numeric(latest.get("close"))
    previous_close = _numeric(previous.get("close")) if previous is not None else None
    change = close - previous_close if close is not None and previous_close is not None else None
    if change is not None and previous_close is not None and previous_close != 0.0:
        change_pct = change / previous_close
    else:
        change_pct = None
    return PriceSnapshot(
        latest_close=close,
        previous_close=previous_close,
        change=change,
        change_pct=change_pct,
        latest_volume=_numeric(latest.get("volume")),
        last_data_date=latest["date"].date().isoformat(),
    )


def _numeric(value: object) -> float | None:
    converted = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(converted) else float(converted)


def _score_value(value: object) -> float | None:
    if value == "unknown":
        return None
    return _numeric(value)


def _score_missing_data(score: StockScoreResult) -> tuple[MissingData, ...]:
    fields = set(score.missing_data)
    if score.total_score == "unknown":
        fields.add("composite_score")
    return tuple(
        MissingData(
            field=field,
            state=MissingDataState.MISSING,
            reason="既有評分模型缺少此必要資料，未形成完整總分。",
        )
        for field in sorted(fields)
    )


def _usable_company_profile(
    profile: CompanyResearchProfile | None,
) -> CompanyResearchProfile | None:
    if profile is None or not profile.fact_fields:
        return None
    return profile


def _dedupe_missing(items: Iterable[MissingData]) -> tuple[MissingData, ...]:
    seen: set[tuple[str, MissingDataState, str]] = set()
    output: list[MissingData] = []
    for item in items:
        key = (item.field, item.state, item.reason)
        if key not in seen:
            seen.add(key)
            output.append(item)
    return tuple(output)


def _scenario_range(
    entry: EntryReference | None,
    *,
    title: str,
) -> ScenarioReferenceRange | None:
    if entry is None:
        return None
    return ScenarioReferenceRange(
        title=title,
        method=entry.method,
        as_of_date=entry.as_of_date,
        latest_close=entry.latest_close,
        range_low=entry.zone_low,
        range_high=entry.zone_high,
        breakout_observation=entry.breakout_trigger,
        risk_reference=entry.stop_loss_reference,
        assumptions=entry.notes,
        limitations=(*entry.risk_notes, *entry.missing_data),
        available=entry.is_available,
    )


def _evidence_items(
    *,
    symbol: Symbol,
    price: PriceSnapshot | None,
    source: ResearchSourceMetadata,
    score: StockScoreResult | None,
    profile: CompanyResearchProfile | None,
    scenario: ScenarioReferenceRange | None,
) -> tuple[ResearchEvidenceItem, ...]:
    items: list[ResearchEvidenceItem] = [
        ResearchEvidenceItem(
            label="價格資料來源",
            text=(
                f"{source.provider or '資料不足'} / {source.source_type} / "
                f"查詢代號 {source.query_symbol or symbol.code}"
            ),
            kind=EvidenceKind.FACT,
            source=source.provider,
        )
    ]
    if price is not None and price.latest_close is not None:
        items.append(
            ResearchEvidenceItem(
                label="最新可用收盤價",
                text=f"{price.latest_close:.2f}（資料日期 {price.last_data_date or '資料不足'}）",
                kind=EvidenceKind.FACT,
                source=source.provider,
            )
        )
    if score is not None:
        items.append(
            ResearchEvidenceItem(
                label="綜合評分",
                text=_score_evidence_text(score),
                kind=EvidenceKind.CALCULATION,
                source="既有綜合評分模型",
            )
        )
    if profile is not None:
        items.append(
            ResearchEvidenceItem(
                label="公司基本資料",
                text=f"{profile.company_name}；{profile.sector}／{profile.industry}",
                kind=EvidenceKind.FACT,
                source="；".join(profile.data_sources),
            )
        )
        items.append(
            ResearchEvidenceItem(
                label="產業鏈與技術脈絡",
                text="公司業務、技術與應用的規則式整理，需以公司公開資料交叉驗證。",
                kind=EvidenceKind.RESEARCH_INFERENCE,
                source="本機研究規則",
            )
        )
    if scenario is not None:
        items.append(
            ResearchEvidenceItem(
                label=scenario.title,
                text="僅為已載入日線資料的研究計算，不是投資建議。",
                kind=EvidenceKind.CALCULATION,
                source="既有情境參考模型",
            )
        )
    return tuple(items)


def _score_evidence_text(score: StockScoreResult) -> str:
    """Format the complete-score evidence without exposing internal sentinels."""

    total_score = "資料不足" if score.total_score == "unknown" else f"{score.total_score:.2f}"
    return f"完整總分：{total_score}；資料覆蓋率 {score.coverage:.0%}。"


def _snapshot_status(
    *,
    price: PriceSnapshot | None,
    score: StockScoreResult | None,
    missing_data: tuple[MissingData, ...],
    is_stale: bool,
    error_message: str | None,
) -> ResearchSnapshotStatus:
    if error_message:
        return ResearchSnapshotStatus.ERROR
    if price is None:
        return ResearchSnapshotStatus.INSUFFICIENT_DATA
    if is_stale or any(item.state is MissingDataState.STALE for item in missing_data):
        return ResearchSnapshotStatus.STALE
    if score is None or score.total_score == "unknown" or missing_data:
        return ResearchSnapshotStatus.PARTIAL
    return ResearchSnapshotStatus.READY
