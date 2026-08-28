"""Immutable, bounded evidence assembled from existing research snapshots."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import StrEnum
import pandas as pd

from stock_tool.application.research_snapshot import EvidenceKind, ResearchSnapshot
from stock_tool.data.contracts import sanitize_provider_text


class ClaimKind(StrEnum):
    """Labels shown to users and enforced by the assistant citation policy."""

    FACT = "fact"
    CALCULATION = "calculation"
    INFERENCE = "inference"
    MISSING = "missing"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """One display-safe, market-qualified evidence item.

    The record deliberately stores a local evidence identifier rather than
    arbitrary model-provided URLs.  Citations can only refer to these records.
    """

    evidence_id: str
    kind: ClaimKind
    label: str
    text: str
    source: str | None
    provider: str | None
    symbol: str
    market: str
    field: str | None = None
    url: str | None = None
    publisher: str | None = None
    available_at: str | None = None
    fetched_at: str | None = None

    def __post_init__(self) -> None:
        """Normalize externally supplied display fields without changing evidence meaning."""

        object.__setattr__(self, "evidence_id", _text(self.evidence_id))
        object.__setattr__(self, "label", _bounded(self.label, 180))
        object.__setattr__(self, "text", _bounded(self.text, 700))
        object.__setattr__(self, "source", _optional(self.source))
        object.__setattr__(self, "provider", _optional(self.provider))
        object.__setattr__(self, "symbol", _text(self.symbol).upper())
        object.__setattr__(self, "market", _text(self.market).upper())
        object.__setattr__(self, "field", _optional(self.field))
        object.__setattr__(self, "url", _safe_url(self.url))
        object.__setattr__(self, "publisher", _optional(self.publisher))
        object.__setattr__(self, "available_at", _optional(self.available_at))
        object.__setattr__(self, "fetched_at", _optional(self.fetched_at))
        if not self.evidence_id or not self.symbol or not self.market:
            raise ValueError("EvidenceRecord requires evidence_id, symbol, and market.")

    def to_dict(self) -> dict[str, object]:
        """Serialize only bounded display-safe metadata."""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """A bounded evidence payload for one canonical research identity."""

    symbol: str
    market: str
    snapshot_fingerprint: str
    evidence: tuple[EvidenceRecord, ...]

    def __post_init__(self) -> None:
        """Validate that all evidence belongs to this one canonical identity."""

        symbol = _text(self.symbol).upper()
        market = _text(self.market).upper()
        records = tuple(self.evidence)
        if not symbol or not market or not self.snapshot_fingerprint:
            raise ValueError("EvidenceBundle requires symbol, market, and snapshot_fingerprint.")
        if any(record.symbol != symbol or record.market != market for record in records):
            raise ValueError("EvidenceBundle cannot mix market-qualified identities.")
        if len({record.evidence_id for record in records}) != len(records):
            raise ValueError("EvidenceBundle evidence IDs must be unique.")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "market", market)
        object.__setattr__(self, "evidence", records)

    @property
    def fingerprint(self) -> str:
        """Return a deterministic cache key for snapshot plus bounded evidence."""

        return _fingerprint(
            {
                "symbol": self.symbol,
                "market": self.market,
                "snapshot_fingerprint": self.snapshot_fingerprint,
                "evidence": [record.to_dict() for record in self.evidence],
            }
        )

    def evidence_by_id(self) -> dict[str, EvidenceRecord]:
        """Return the one allowed citation registry for model outputs."""

        return {record.evidence_id: record for record in self.evidence}


def build_evidence_bundle(snapshot: ResearchSnapshot) -> EvidenceBundle:
    """Create citation-ready evidence without mutating deterministic snapshot data."""

    symbol = snapshot.symbol.code
    market = snapshot.symbol.market.value
    metadata = snapshot.source_metadata
    records: list[EvidenceRecord] = []
    provider = _optional(metadata.provider)
    source = provider or _optional(metadata.source_type)
    available_at = _optional(metadata.last_data_date)
    fetched_at = _optional(metadata.fetched_at)

    if snapshot.price is not None and snapshot.price.latest_close is not None:
        records.append(
            EvidenceRecord(
                evidence_id="price.latest_close",
                kind=ClaimKind.FACT,
                label="最新收盤價",
                text=f"已載入最新收盤價：{snapshot.price.latest_close:.4g}。",
                source=source,
                provider=provider,
                symbol=symbol,
                market=market,
                field="close",
                available_at=snapshot.price.last_data_date or available_at,
                fetched_at=fetched_at,
            )
        )
    if snapshot.price is not None and snapshot.price.change_pct is not None:
        records.append(
            EvidenceRecord(
                evidence_id="price.change_pct",
                kind=ClaimKind.CALCULATION,
                label="最新價格變化",
                text=f"依已載入相鄰價格計算，最新變化為 {snapshot.price.change_pct:.2%}。",
                source=source,
                provider=provider,
                symbol=symbol,
                market=market,
                field="change_pct",
                available_at=snapshot.price.last_data_date or available_at,
                fetched_at=fetched_at,
            )
        )
    if snapshot.composite_score is not None:
        records.append(
            EvidenceRecord(
                evidence_id="score.composite",
                kind=ClaimKind.CALCULATION,
                label="綜合研究分數",
                text=(
                    f"StockTool 既有確定性綜合分數為 {snapshot.composite_score:.2f}，"
                    f"資料覆蓋率為 {_percent(snapshot.score_coverage)}。"
                ),
                source="StockTool deterministic scoring",
                provider=None,
                symbol=symbol,
                market=market,
                field="composite_score",
                available_at=available_at,
                fetched_at=snapshot.updated_at or fetched_at,
            )
        )
    if snapshot.fundamental_results is not None and not snapshot.fundamental_results.empty:
        records.append(
            EvidenceRecord(
                evidence_id="fundamentals.available",
                kind=ClaimKind.CALCULATION,
                label="基本面可用性",
                text=f"已載入 {len(snapshot.fundamental_results)} 筆市場限定基本面結果。",
                source="StockTool fundamentals",
                provider=None,
                symbol=symbol,
                market=market,
                field="fundamental_results",
                available_at=available_at,
                fetched_at=snapshot.updated_at or fetched_at,
            )
        )
    records.extend(_profile_evidence(snapshot, source, provider, available_at, fetched_at))
    records.extend(
        _snapshot_evidence(snapshot, symbol, market, source, provider, available_at, fetched_at)
    )
    records.extend(_serenity_evidence(snapshot, source, available_at, fetched_at))
    records.extend(
        _missing_and_warnings(snapshot, symbol, market, source, provider, available_at, fetched_at)
    )

    return EvidenceBundle(
        symbol=symbol,
        market=market,
        snapshot_fingerprint=_snapshot_fingerprint(snapshot),
        evidence=tuple(records[:48]),
    )


def _profile_evidence(
    snapshot: ResearchSnapshot,
    source: str | None,
    provider: str | None,
    available_at: str | None,
    fetched_at: str | None,
) -> list[EvidenceRecord]:
    profile = snapshot.company_profile
    if profile is None:
        return []
    rows: list[EvidenceRecord] = []
    fact_map = {
        "company_name": ("公司名稱", profile.company_name),
        "sector": ("產業 sector", profile.sector),
        "industry": ("產業分類", profile.industry),
    }
    profile_source = _optional("；".join(profile.data_sources)) or source
    for field in profile.fact_fields:
        if field not in fact_map:
            continue
        label, value = fact_map[field]
        if not _text(value) or not profile_source:
            continue
        rows.append(
            EvidenceRecord(
                evidence_id=f"profile.{field}",
                kind=ClaimKind.FACT,
                label=label,
                text=f"{label}：{_bounded(value, 320)}。",
                source=profile_source,
                provider=provider,
                symbol=snapshot.symbol.code,
                market=snapshot.symbol.market.value,
                field=field,
                available_at=available_at,
                fetched_at=fetched_at,
            )
        )
    return rows


def _serenity_evidence(
    snapshot: ResearchSnapshot,
    source: str | None,
    available_at: str | None,
    fetched_at: str | None,
) -> list[EvidenceRecord]:
    """Add existing deterministic Serenity observations only as labelled inference."""

    if snapshot.price_history is None or snapshot.price_history.empty:
        return []
    try:
        from stock_tool.serenity_agent import run_serenity_agent

        result = run_serenity_agent(
            symbol=snapshot.symbol.code,
            market=snapshot.symbol.market.value,
            price_data=snapshot.price_history,
            technical_indicators=snapshot.indicators,
            company_profile=snapshot.company_profile,
        )
    except (ValueError, TypeError, KeyError):
        return []
    text = "；".join((*result.chokepoint_map[:2], *result.evidence_gaps[:1]))
    if not text:
        return []
    return [
        EvidenceRecord(
            evidence_id="serenity.chokepoint",
            kind=ClaimKind.INFERENCE,
            label="Serenity 供應鏈瓶頸觀察",
            text=text,
            source="StockTool deterministic Serenity agent",
            provider=None,
            symbol=snapshot.symbol.code,
            market=snapshot.symbol.market.value,
            field="serenity_chokepoint",
            available_at=available_at,
            fetched_at=fetched_at,
        )
    ]


def _snapshot_evidence(
    snapshot: ResearchSnapshot,
    symbol: str,
    market: str,
    source: str | None,
    provider: str | None,
    available_at: str | None,
    fetched_at: str | None,
) -> list[EvidenceRecord]:
    kind_map = {
        EvidenceKind.FACT: ClaimKind.FACT,
        EvidenceKind.CALCULATION: ClaimKind.CALCULATION,
        EvidenceKind.RESEARCH_INFERENCE: ClaimKind.INFERENCE,
    }
    rows: list[EvidenceRecord] = []
    for index, item in enumerate(snapshot.evidence_items[:16]):
        kind = kind_map[item.kind]
        item_source = _optional(item.source) or source
        if kind is ClaimKind.FACT and item_source is None:
            continue
        rows.append(
            EvidenceRecord(
                evidence_id=f"snapshot.{index}",
                kind=kind,
                label=item.label,
                text=item.text,
                source=item_source,
                provider=provider,
                symbol=symbol,
                market=market,
                available_at=available_at,
                fetched_at=fetched_at,
            )
        )
    return rows


def _missing_and_warnings(
    snapshot: ResearchSnapshot,
    symbol: str,
    market: str,
    source: str | None,
    provider: str | None,
    available_at: str | None,
    fetched_at: str | None,
) -> list[EvidenceRecord]:
    rows: list[EvidenceRecord] = []
    for index, item in enumerate(snapshot.missing_data[:16]):
        rows.append(
            EvidenceRecord(
                evidence_id=f"missing.{index}",
                kind=ClaimKind.MISSING,
                label=item.field,
                text=item.reason,
                source="StockTool missing-data contract",
                provider=None,
                symbol=symbol,
                market=market,
                field=item.field,
                available_at=available_at,
                fetched_at=fetched_at,
            )
        )
    for index, warning in enumerate((*snapshot.warnings, *snapshot.source_metadata.warnings)[:16]):
        rows.append(
            EvidenceRecord(
                evidence_id=f"warning.{index}",
                kind=ClaimKind.WARNING,
                label="資料警告",
                text=warning,
                source=source or "StockTool data quality",
                provider=provider,
                symbol=symbol,
                market=market,
                available_at=available_at,
                fetched_at=fetched_at,
            )
        )
    return rows


def _snapshot_fingerprint(snapshot: ResearchSnapshot) -> str:
    return _fingerprint(
        {
            "symbol": snapshot.symbol.canonical,
            "status": snapshot.status.value,
            "price": asdict(snapshot.price) if snapshot.price is not None else None,
            "source": asdict(snapshot.source_metadata),
            "score": snapshot.composite_score,
            "coverage": snapshot.score_coverage,
            "warnings": snapshot.warnings,
            "missing": [
                {"field": item.field, "state": item.state.value, "reason": item.reason}
                for item in snapshot.missing_data
            ],
            "profile": (
                {
                    "company_name": snapshot.company_profile.company_name,
                    "sector": snapshot.company_profile.sector,
                    "industry": snapshot.company_profile.industry,
                    "fact_fields": snapshot.company_profile.fact_fields,
                    "sources": snapshot.company_profile.data_sources,
                }
                if snapshot.company_profile is not None
                else None
            ),
            "indicators": _frame_fingerprint(snapshot.indicators),
            "fundamentals": _frame_fingerprint(snapshot.fundamental_results),
        }
    )


def _frame_fingerprint(frame: pd.DataFrame | None) -> list[dict[str, object]]:
    if frame is None or frame.empty:
        return []
    normalized = frame.copy(deep=True)
    normalized.columns = [str(column) for column in normalized.columns]
    rows = [
        {column: _canonical_value(value) for column, value in row.items()}
        for row in normalized.to_dict(orient="records")[:200]
    ]
    return sorted(rows, key=lambda row: _canonical_json(row))


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(
        _canonical_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _canonical_value(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda row: str(row[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, set):
        return sorted((_canonical_value(item) for item in value), key=_canonical_json)
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    if pd.isna(value):
        return None
    return str(value)


def _percent(value: float | None) -> str:
    return "資料不足" if value is None else f"{value:.0%}"


def _text(value: object) -> str:
    return sanitize_provider_text(value).strip()


def _optional(value: object) -> str | None:
    text = _text(value)
    return text or None


def _bounded(value: object, length: int) -> str:
    text = _text(value)
    return text[:length].strip()


def _safe_url(value: object) -> str | None:
    text = _optional(value)
    if text is None:
        return None
    if not text.lower().startswith(("https://", "http://", "file://", "local://")):
        return None
    return text[:500]
