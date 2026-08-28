"""Deterministic, evidence-linked daily research brief orchestration.

The service in this module is deliberately small: it adapts the existing
``DailyBriefService``, ``DailyResearchLoopService``, assistant notes and local
market-monitor cache into one immutable, privacy-safe brief contract.  It never
fetches data and never mutates portfolio, watchlist or research-library inputs.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, cast

import pandas as pd

from stock_tool.application.daily_brief import DailyBrief
from stock_tool.application.daily_research_loop import (
    DailyResearchEvent,
    DailyResearchLoopResult,
)
from stock_tool.application.market_monitor import MarketRefreshResult
from stock_tool.data.contracts import sanitize_provider_text
from stock_tool.domain.models import Market, Symbol
from stock_tool.research.assistant import ClaimKind, DailyResearchAssistantBrief

DAILY_RESEARCH_BRIEF_SCHEMA_VERSION = 2
DailyBriefItemStatus = Literal["fresh", "stale", "partial", "missing"]
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _text(value: object) -> str:
    """Bound untrusted source text and keep prompt-injection text as data only."""

    return sanitize_provider_text(str(value)).strip()[:600]


def _optional_text(value: object) -> str | None:
    text = _text(value) if value is not None else ""
    return text or None


@dataclass(frozen=True, slots=True)
class DailyBriefSource:
    """Secret-free provenance summary for one source or local cache."""

    market: str | None
    source: str | None
    data_date: str | None
    fetched_at: str | None
    status: str
    coverage: float | None
    payload_sha256: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    """A stable, non-sensitive reference for one displayed evidence claim."""

    reference_id: str
    provider: str | None
    market: str | None
    symbol: str | None
    field: str | None
    as_of: str | None
    fetched_at: str | None
    payload_sha256: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: object) -> "EvidenceReference":
        if not isinstance(payload, Mapping):
            raise ValueError("evidence reference must be an object")
        reference_id = _optional_text(payload.get("reference_id"))
        if reference_id is None:
            raise ValueError("evidence reference id is missing")
        return cls(
            reference_id=reference_id,
            provider=_optional_text(payload.get("provider")),
            market=_optional_text(payload.get("market")),
            symbol=_optional_text(payload.get("symbol")),
            field=_optional_text(payload.get("field")),
            as_of=_optional_text(payload.get("as_of")),
            fetched_at=_optional_text(payload.get("fetched_at")),
            payload_sha256=_optional_text(payload.get("payload_sha256")),
        )


@dataclass(frozen=True, slots=True)
class EvidenceChainItem:
    """One bounded, labelled fact/inference/risk bundle."""

    symbol: str | None
    name: str | None
    market: str | None
    priority: int
    reason: str
    facts: tuple[str, ...]
    inferences: tuple[str, ...]
    risks: tuple[str, ...]
    data_as_of: str | None
    source: str | None
    reference_labels: tuple[str, ...]
    confidence: Literal["high", "medium", "low"]
    completeness: float | None
    status: DailyBriefItemStatus
    fact_reference_ids: tuple[tuple[str, ...], ...] = ()
    inference_reference_ids: tuple[tuple[str, ...], ...] = ()
    risk_reference_ids: tuple[tuple[str, ...], ...] = ()

    @property
    def identity(self) -> str:
        if self.symbol and self.market:
            return f"{self.market}:{self.symbol}"
        return "portfolio"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["facts"] = list(self.facts)
        payload["inferences"] = list(self.inferences)
        payload["risks"] = list(self.risks)
        payload["reference_labels"] = list(self.reference_labels)
        payload["fact_reference_ids"] = [list(item) for item in self.fact_reference_ids]
        payload["inference_reference_ids"] = [list(item) for item in self.inference_reference_ids]
        payload["risk_reference_ids"] = [list(item) for item in self.risk_reference_ids]
        return payload

    @classmethod
    def from_dict(cls, payload: object) -> "EvidenceChainItem":
        if not isinstance(payload, Mapping):
            raise ValueError("brief item must be an object")
        status = str(payload.get("status") or "")
        if status not in {"fresh", "stale", "partial", "missing"}:
            raise ValueError("brief item status is invalid")
        confidence = str(payload.get("confidence") or "")
        if confidence not in {"high", "medium", "low"}:
            raise ValueError("brief item confidence is invalid")
        priority = payload.get("priority")
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise ValueError("brief item priority is invalid")

        def _list(name: str) -> tuple[str, ...]:
            value = payload.get(name, ())
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise ValueError(f"brief item {name} is invalid")
            return tuple(_text(item) for item in value if _text(item))

        def _reference_lists(name: str, count: int) -> tuple[tuple[str, ...], ...]:
            value = payload.get(name, [])
            if not isinstance(value, list) or len(value) != count:
                raise ValueError(f"brief item {name} is invalid")
            result: list[tuple[str, ...]] = []
            for refs in value:
                if (
                    not isinstance(refs, list)
                    or not refs
                    or any(
                        not isinstance(reference_id, str) or not reference_id.strip()
                        for reference_id in refs
                    )
                ):
                    raise ValueError(f"brief item {name} is invalid")
                result.append(tuple(dict.fromkeys(reference_id.strip() for reference_id in refs)))
            return tuple(result)

        facts = _list("facts")
        inferences = _list("inferences")
        risks = _list("risks")

        completeness = payload.get("completeness")
        if completeness is not None:
            if isinstance(completeness, bool) or not isinstance(completeness, (int, float)):
                raise ValueError("brief item completeness is invalid")
            completeness = float(completeness)
            if not 0.0 <= completeness <= 1.0:
                raise ValueError("brief item completeness is out of range")
        return cls(
            symbol=_optional_text(payload.get("symbol")),
            name=_optional_text(payload.get("name")),
            market=_optional_text(payload.get("market")),
            priority=priority,
            reason=_text(payload.get("reason")),
            facts=facts,
            inferences=inferences,
            risks=risks,
            data_as_of=_optional_text(payload.get("data_as_of")),
            source=_optional_text(payload.get("source")),
            reference_labels=_list("reference_labels"),
            confidence=cast(Literal["high", "medium", "low"], confidence),
            completeness=completeness,
            status=cast(DailyBriefItemStatus, status),
            fact_reference_ids=_reference_lists("fact_reference_ids", len(facts)),
            inference_reference_ids=_reference_lists("inference_reference_ids", len(inferences)),
            risk_reference_ids=_reference_lists("risk_reference_ids", len(risks)),
        )


@dataclass(frozen=True, slots=True)
class DailyResearchBriefManifest:
    """Schema-versioned, replayable evidence manifest."""

    schema_version: int
    brief_date: str
    as_of_date: str | None
    input_snapshot_id: str
    input_snapshot_hash: str
    processed_count: int
    source_summaries: tuple[DailyBriefSource, ...]
    missing_or_stale: tuple[str, ...]
    warnings: tuple[str, ...]
    content_fingerprint: str
    references: tuple[EvidenceReference, ...] = ()

    def core_dict(self, items: Sequence[EvidenceChainItem]) -> dict[str, object]:
        """Return the deterministic portion, excluding generated-at and paths."""

        return {
            "schema_version": self.schema_version,
            "brief_date": self.brief_date,
            "as_of_date": self.as_of_date,
            "input_snapshot_id": self.input_snapshot_id,
            "input_snapshot_hash": self.input_snapshot_hash,
            "processed_count": self.processed_count,
            "source_summaries": [item.to_dict() for item in self.source_summaries],
            "missing_or_stale": list(self.missing_or_stale),
            "warnings": list(self.warnings),
            "references": [item.to_dict() for item in self.references],
            "items": [item.to_dict() for item in items],
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "brief_date": self.brief_date,
            "as_of_date": self.as_of_date,
            "input_snapshot_id": self.input_snapshot_id,
            "input_snapshot_hash": self.input_snapshot_hash,
            "processed_count": self.processed_count,
            "source_summaries": [item.to_dict() for item in self.source_summaries],
            "missing_or_stale": list(self.missing_or_stale),
            "warnings": list(self.warnings),
            "content_fingerprint": self.content_fingerprint,
            "references": [item.to_dict() for item in self.references],
        }


@dataclass(frozen=True, slots=True)
class DailyResearchBrief:
    """Immutable brief result suitable for session state, JSON, or HTML export."""

    generated_at: str
    status: Literal["success", "partial", "unavailable"]
    manifest: DailyResearchBriefManifest
    items: tuple[EvidenceChainItem, ...]
    message: str
    # Optional macro projection is appended for schema-v2 compatibility.  An
    # empty tuple preserves the historical fingerprint for existing briefs.
    macro_context: tuple[Mapping[str, object], ...] = ()

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": DAILY_RESEARCH_BRIEF_SCHEMA_VERSION,
            "generated_at": self.generated_at,
            "status": self.status,
            "manifest": self.manifest.to_dict(),
            "items": [item.to_dict() for item in self.items],
            "message": self.message,
        }
        if self.macro_context:
            payload["macro_context"] = [dict(item) for item in self.macro_context]
        return payload

    @classmethod
    def from_dict(cls, payload: object) -> "DailyResearchBrief":
        if not isinstance(payload, Mapping):
            raise ValueError("daily research brief must be an object")
        if payload.get("schema_version") != DAILY_RESEARCH_BRIEF_SCHEMA_VERSION:
            raise ValueError("daily research brief schema is unsupported")
        status = str(payload.get("status") or "")
        if status not in {"success", "partial", "unavailable"}:
            raise ValueError("daily research brief status is invalid")
        generated_at = _optional_text(payload.get("generated_at"))
        if generated_at is None:
            raise ValueError("daily research brief lacks generated_at")
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise ValueError("daily research brief items are invalid")
        items = tuple(EvidenceChainItem.from_dict(item) for item in raw_items)
        raw_macro_context = payload.get("macro_context", [])
        if not isinstance(raw_macro_context, list) or any(
            not isinstance(item, Mapping) for item in raw_macro_context
        ):
            raise ValueError("daily research brief macro context is invalid")
        macro_context = tuple(dict(item) for item in raw_macro_context)
        raw_manifest = payload.get("manifest")
        if not isinstance(raw_manifest, Mapping):
            raise ValueError("daily research brief manifest is invalid")
        raw_sources = raw_manifest.get("source_summaries", [])
        if not isinstance(raw_sources, list):
            raise ValueError("brief source summaries are invalid")
        sources: list[DailyBriefSource] = []
        for item in raw_sources:
            if not isinstance(item, Mapping):
                raise ValueError("brief source summary is invalid")
            coverage = item.get("coverage")
            if coverage is not None and (
                isinstance(coverage, bool) or not isinstance(coverage, (int, float))
            ):
                raise ValueError("brief source coverage is invalid")
            sources.append(
                DailyBriefSource(
                    market=_optional_text(item.get("market")),
                    source=_optional_text(item.get("source")),
                    data_date=_optional_text(item.get("data_date")),
                    fetched_at=_optional_text(item.get("fetched_at")),
                    status=_text(item.get("status")),
                    coverage=float(coverage) if coverage is not None else None,
                    payload_sha256=_optional_text(item.get("payload_sha256")),
                )
            )
        raw_missing = raw_manifest.get("missing_or_stale", [])
        raw_warnings = raw_manifest.get("warnings", [])
        raw_references = raw_manifest.get("references", [])
        if (
            not isinstance(raw_missing, list)
            or not isinstance(raw_warnings, list)
            or not isinstance(raw_references, list)
        ):
            raise ValueError("brief manifest lists are invalid")
        manifest = DailyResearchBriefManifest(
            schema_version=int(raw_manifest.get("schema_version", 0)),
            brief_date=_text(raw_manifest.get("brief_date")),
            as_of_date=_optional_text(raw_manifest.get("as_of_date")),
            input_snapshot_id=_text(raw_manifest.get("input_snapshot_id")),
            input_snapshot_hash=_text(raw_manifest.get("input_snapshot_hash")),
            processed_count=int(raw_manifest.get("processed_count", -1)),
            source_summaries=tuple(sources),
            missing_or_stale=tuple(_text(item) for item in raw_missing if _text(item)),
            warnings=tuple(_text(item) for item in raw_warnings if _text(item)),
            content_fingerprint=_text(raw_manifest.get("content_fingerprint")),
            references=tuple(EvidenceReference.from_dict(item) for item in raw_references),
        )
        if manifest.schema_version != DAILY_RESEARCH_BRIEF_SCHEMA_VERSION:
            raise ValueError("brief manifest schema is unsupported")
        if (
            manifest.processed_count < 0
            or SHA256_RE.fullmatch(manifest.content_fingerprint) is None
        ):
            raise ValueError("brief manifest is incomplete")
        _validate_reference_contract(manifest, items)
        _validate_macro_context(manifest, macro_context)
        message = _text(payload.get("message"))
        if _content_fingerprint(
            manifest, items, status=status, message=message, macro_context=macro_context
        ) != (manifest.content_fingerprint):
            raise ValueError("daily research brief fingerprint mismatch")
        return cls(
            generated_at=generated_at,
            status=cast(Literal["success", "partial", "unavailable"], status),
            manifest=manifest,
            items=items,
            message=message,
            macro_context=macro_context,
        )


def _content_fingerprint(
    manifest: DailyResearchBriefManifest,
    items: Sequence[EvidenceChainItem],
    *,
    status: str = "",
    message: str = "",
    macro_context: Sequence[Mapping[str, object]] = (),
) -> str:
    payload: dict[str, object] = {
        "status": status,
        "message": message,
        **manifest.core_dict(items),
    }
    if macro_context:
        payload["macro_context"] = [dict(item) for item in macro_context]
    return _sha256(payload)


def _validate_reference_contract(
    manifest: DailyResearchBriefManifest, items: Sequence[EvidenceChainItem]
) -> None:
    references = {item.reference_id: item for item in manifest.references}
    if len(references) != len(manifest.references):
        raise ValueError("duplicate evidence reference id")
    for item in items:
        for texts, ref_lists in (
            (item.facts, item.fact_reference_ids),
            (item.inferences, item.inference_reference_ids),
            (item.risks, item.risk_reference_ids),
        ):
            if len(texts) != len(ref_lists):
                raise ValueError("evidence claim reference count mismatch")
            for claim_refs in ref_lists:
                if not claim_refs or any(
                    reference_id not in references for reference_id in claim_refs
                ):
                    raise ValueError("unresolved evidence reference")


def _validate_macro_context(
    manifest: DailyResearchBriefManifest,
    macro_context: Sequence[Mapping[str, object]],
) -> None:
    """Validate the optional macro projection's reference closure."""

    references = {item.reference_id for item in manifest.references}
    used: set[str] = set()
    seen_identities: set[str] = set()
    for item in macro_context:
        kind = item.get("kind", "series")
        if kind == "identity_link":
            identity = item.get("identity")
            if not isinstance(identity, str) or not identity.strip() or identity in seen_identities:
                raise ValueError("macro context identity is invalid")
            seen_identities.add(identity)
            rule_version = item.get("rule_version")
            if not isinstance(rule_version, str) or not rule_version.strip():
                raise ValueError("macro context rule version is invalid")
            limitations = item.get("limitations")
            if not isinstance(limitations, list) or any(
                not isinstance(value, str) for value in limitations
            ):
                raise ValueError("macro context limitations are invalid")
        elif kind == "series":
            series_id = item.get("series_id")
            if not isinstance(series_id, str) or not series_id.strip():
                raise ValueError("macro context series id is invalid")
        else:
            raise ValueError("macro context kind is invalid")
        ref_ids = item.get("reference_ids")
        if not isinstance(ref_ids, list) or any(
            not isinstance(ref_id, str) or not ref_id.strip() for ref_id in ref_ids
        ):
            raise ValueError("macro context references are invalid")
        for ref_id in ref_ids:
            if ref_id not in references:
                raise ValueError("unresolved macro context reference")
            used.add(ref_id)
    if not used.issubset(references):
        raise ValueError("macro context reference closure is invalid")


def _macro_link_list(value: object) -> list[object]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _identity_rows(*frames: pd.DataFrame | None) -> tuple[Symbol, ...]:
    found: dict[str, Symbol] = {}
    for frame in frames:
        if frame is None or frame.empty or not {"symbol", "market"}.issubset(frame.columns):
            continue
        for row in frame.loc[:, ["symbol", "market"]].itertuples(index=False):
            try:
                symbol = Symbol.parse(str(row.symbol), market=str(row.market))
            except (TypeError, ValueError):
                continue
            if symbol.market in {Market.TWSE, Market.TPEX, Market.US}:
                found.setdefault(symbol.canonical, symbol)
    return tuple(found[key] for key in sorted(found))


def _status_for_event(event: DailyResearchEvent) -> DailyBriefItemStatus:
    source_type = (event.source.source_type or "").lower()
    if event.category == "data_repair":
        return "missing"
    if "stale" in source_type or "cache" in source_type and "offline" in source_type:
        return "stale"
    if event.category == "persistent_state":
        # A persistent event is still backed by the current validated source;
        # it is not itself a missing-data signal.  This matters for a first
        # headless cache-fallback run that starts from a prior loop snapshot.
        return "fresh"
    if event.category == "resolved":
        return "partial"
    return "fresh"


def _event_item(
    event: DailyResearchEvent,
    *,
    ai_inferences: Mapping[str, tuple[tuple[str, tuple[str, ...]], ...]],
    event_reference_id: str,
    confidence_override: str | None = None,
) -> EvidenceChainItem:
    symbol: str | None = None
    market: str | None = None
    if event.identity and ":" in event.identity:
        market, symbol = event.identity.split(":", maxsplit=1)
    status = _status_for_event(event)
    risk_values: tuple[str, ...] = ()
    if status != "fresh":
        risk_values = (_text(event.why_important),)
    references = (
        ":".join(
            part
            for part in (
                event.identity or "portfolio",
                event.code,
                event.as_of_date or event.source.last_data_date or "unknown-date",
            )
            if part
        ),
    )
    confidence = confidence_override or (
        "high"
        if status == "fresh" and event.source.provider
        else "medium" if status in {"fresh", "partial"} else "low"
    )
    inference_values = tuple(
        value for value, _ in ai_inferences.get(event.identity or "portfolio", ())
    )
    inference_refs = tuple(refs for _, refs in ai_inferences.get(event.identity or "portfolio", ()))
    return EvidenceChainItem(
        symbol=symbol,
        name=None,
        market=market,
        priority=max(0, int(event.priority)),
        reason=_text(event.why_important or event.title),
        facts=(_text(event.current_value),) if _text(event.current_value) else (),
        inferences=inference_values,
        risks=tuple(value for value in risk_values if value),
        data_as_of=_optional_text(event.as_of_date or event.source.last_data_date),
        source=_optional_text(event.source.label),
        reference_labels=references,
        confidence=cast(Literal["high", "medium", "low"], confidence),
        completeness=1.0 if status == "fresh" else 0.5 if status == "partial" else 0.0,
        status=status,
        fact_reference_ids=((event_reference_id,),) if event.current_value else (),
        inference_reference_ids=inference_refs,
        risk_reference_ids=((event_reference_id,),) if risk_values else (),
    )


def _notes_inferences(
    assistant_brief: DailyResearchAssistantBrief | None,
) -> tuple[
    dict[str, tuple[tuple[str, tuple[str, ...]], ...]],
    tuple[EvidenceReference, ...],
]:
    if assistant_brief is None:
        return {}, ()
    result: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
    references: dict[str, EvidenceReference] = {}
    for note in assistant_brief.notes:
        citation_ids = {citation.evidence_id for citation in note.citations}
        if len(citation_ids) != len(note.citations):
            raise ValueError("duplicate AI citation id")
        for citation in note.citations:
            if citation.evidence_id in references:
                raise ValueError("inconsistent duplicate AI citation id")
            references[citation.evidence_id] = EvidenceReference(
                reference_id=citation.evidence_id,
                provider=citation.provider,
                market=citation.market,
                symbol=citation.symbol,
                field=citation.field,
                as_of=citation.available_at,
                fetched_at=citation.fetched_at,
                payload_sha256=_sha256({"source": citation.source, "excerpt": citation.excerpt}),
            )
        for claim in note.claims:
            claim_ids = tuple(dict.fromkeys(claim.citation_ids))
            if len(claim_ids) != len(claim.citation_ids):
                raise ValueError("duplicate AI citation id in claim")
            if claim.citation_ids and not set(claim.citation_ids).issubset(citation_ids):
                raise ValueError("unresolved AI citation id")
            # Facts without citations are deliberately ignored.  Inferences may
            # be carried only when their citation IDs resolve to note citations.
            if claim.kind is not ClaimKind.INFERENCE or not claim.citation_ids:
                continue
            result.setdefault(f"{note.market}:{note.symbol}", []).append(
                (_text(claim.text), tuple(dict.fromkeys(claim.citation_ids)))
            )
    return {key: tuple(values) for key, values in result.items()}, tuple(references.values())


def _event_reference(event: DailyResearchEvent) -> EvidenceReference:
    market: str | None = None
    symbol: str | None = None
    if event.identity and ":" in event.identity:
        market, symbol = event.identity.split(":", maxsplit=1)
    payload = {
        "identity": event.identity,
        "code": event.code,
        "field": event.field,
        "as_of": event.as_of_date or event.source.last_data_date,
    }
    return EvidenceReference(
        reference_id=f"event-{_sha256(payload)[:16]}",
        provider=event.source.provider,
        market=market,
        symbol=symbol,
        field=event.field or event.code,
        as_of=event.as_of_date or event.source.last_data_date,
        fetched_at=event.source.checked_at,
        payload_sha256=_sha256(payload),
    )


def _sources_from_market_result(
    market_result: MarketRefreshResult | None,
) -> tuple[DailyBriefSource, ...]:
    if market_result is None or market_result.snapshot is None:
        return ()
    snapshot = market_result.snapshot
    rows = snapshot.source_metadata
    if not rows:
        rows = ()
    return tuple(
        DailyBriefSource(
            market=row.market,
            source=row.source,
            data_date=row.data_date,
            fetched_at=row.fetched_at,
            status=market_result.status,
            coverage=row.coverage,
            payload_sha256=row.payload_sha256,
        )
        for row in sorted(rows, key=lambda item: item.market)
    )


class DailyResearchBriefApplicationService:
    """Build and persist a bounded brief from already available local evidence."""

    def __init__(
        self,
        *,
        max_symbols: int = 20,
        max_items: int = 5,
        now_fn: Any = _utc_now,
    ) -> None:
        if max_symbols <= 0 or max_items <= 0:
            raise ValueError("brief limits must be positive")
        self.max_symbols = max_symbols
        self.max_items = max_items
        self.now_fn = now_fn

    def generate(
        self,
        *,
        portfolio: pd.DataFrame | None,
        watchlist: pd.DataFrame | None,
        daily_brief: DailyBrief | None,
        loop_result: DailyResearchLoopResult | None,
        market_result: MarketRefreshResult | None = None,
        assistant_brief: DailyResearchAssistantBrief | None = None,
        previous_snapshot_id: str | None = None,
        macro_snapshot: Any | None = None,
        macro_links: Sequence[Mapping[str, object]] = (),
    ) -> DailyResearchBrief:
        identities = _identity_rows(portfolio, watchlist)[: self.max_symbols]
        events: list[DailyResearchEvent] = []
        if loop_result is not None:
            events.extend(loop_result.priority_events)
            events.extend(loop_result.persistent_events)
            events.extend(loop_result.repair_events)
        if not events and daily_brief is not None:
            # A first-use/current-data run still exposes explicit local evidence.
            events.extend(_events_from_daily_brief(daily_brief))
        ai_inferences, ai_references = _notes_inferences(assistant_brief)
        unique_events: dict[str, DailyResearchEvent] = {}
        valid_identities = {item.canonical for item in identities}
        for event in events:
            if event.identity and event.identity not in valid_identities:
                continue
            unique_events.setdefault(event.display_key, event)
        event_references = {
            event.display_key: _event_reference(event) for event in unique_events.values()
        }
        items = tuple(
            sorted(
                (
                    _event_item(
                        event,
                        ai_inferences=ai_inferences,
                        event_reference_id=event_references[event.display_key].reference_id,
                    )
                    for event in unique_events.values()
                ),
                key=lambda item: (-item.priority, item.identity, item.reason),
            )[: self.max_items]
        )
        source_summaries = _sources_from_market_result(market_result)
        macro_context: tuple[Mapping[str, object], ...] = ()
        macro_references: tuple[EvidenceReference, ...] = ()
        macro_warnings: tuple[str, ...] = ()
        if macro_snapshot is not None:
            try:
                macro_rows = []
                mapped_references: list[EvidenceReference] = []
                for reference in macro_snapshot.references:
                    mapped_references.append(
                        EvidenceReference(
                            reference_id=reference.reference_id,
                            provider=reference.provider,
                            market=None,
                            symbol=None,
                            field=reference.series_id,
                            as_of=reference.observed_date,
                            fetched_at=reference.fetched_at,
                            payload_sha256=reference.payload_sha256,
                        )
                    )
                for observation in macro_snapshot.observations:
                    title = observation.series_id
                    try:
                        from stock_tool.application.macro_snapshot import FRED_SERIES

                        title = FRED_SERIES.get(
                            observation.series_id, ("", observation.series_id, "")
                        )[1]
                    except Exception:
                        pass
                    macro_rows.append(
                        {
                            "kind": "series",
                            "series_id": observation.series_id,
                            "title": title,
                            "status": macro_snapshot.status,
                            "current_value": observation.value,
                            "unit": observation.unit,
                            "as_of": observation.observation_period,
                            "observation_period": observation.observation_period,
                            "observed_date": observation.observed_date,
                            "release_date": observation.release_date,
                            "fetched_at": observation.fetched_at,
                            "source": observation.source,
                            "reference_ids": [observation.reference_id],
                            "next_condition": "下一期官方資料發布後重新確認",
                        }
                    )
                macro_context = tuple(macro_rows) + tuple(
                    {
                        **dict(link),
                        "kind": "identity_link",
                        "reference_ids": _macro_link_list(link.get("reference_ids")),
                        "limitations": _macro_link_list(link.get("limitations")),
                    }
                    for link in macro_links
                )
                macro_references = tuple(mapped_references)
            except (AttributeError, TypeError, ValueError):
                macro_warnings = ("總經背景無法驗證，已略過",)
        if macro_snapshot is None and macro_links:
            macro_context = tuple(
                {
                    **dict(link),
                    "kind": "identity_link",
                    "reference_ids": _macro_link_list(link.get("reference_ids")),
                    "limitations": _macro_link_list(link.get("limitations")),
                }
                for link in macro_links
            )
        references = tuple(event_references.values()) + ai_references + macro_references
        missing_or_stale = tuple(
            sorted(
                {item.identity for item in items if item.status in {"missing", "stale", "partial"}}
                | set(assistant_brief.unavailable_identities if assistant_brief else ())
            )
        )
        warnings = tuple(
            dict.fromkeys(
                [
                    *(assistant_brief.warnings if assistant_brief else ()),
                    *(market_result.warnings if market_result else ()),
                    *macro_warnings,
                    *(
                        tuple(getattr(macro_snapshot, "warnings", ()) or ())
                        if macro_snapshot is not None
                        else ()
                    ),
                ]
            )
        )
        as_of_dates = [item.data_as_of for item in items if item.data_as_of]
        as_of_date = (
            max(as_of_dates) if as_of_dates else getattr(daily_brief, "data_as_of_date", None)
        )
        input_payload = {
            "identities": [item.canonical for item in identities],
            "previous_snapshot_id": previous_snapshot_id,
            "events": [
                {
                    "key": event.event_identity,
                    "value": event.value_key,
                    "as_of": event.as_of_date,
                    "source": asdict(event.source),
                }
                for event in sorted(unique_events.values(), key=lambda item: item.event_identity)
            ],
            "sources": [item.to_dict() for item in source_summaries],
            "warnings": list(warnings),
            "macro_context": [dict(item) for item in macro_context],
        }
        input_hash = _sha256(input_payload)
        input_id = previous_snapshot_id or input_hash[:16]
        now = self.now_fn()
        generated_at = now.astimezone(timezone.utc).isoformat()
        manifest = DailyResearchBriefManifest(
            schema_version=DAILY_RESEARCH_BRIEF_SCHEMA_VERSION,
            brief_date=now.date().isoformat(),
            as_of_date=as_of_date,
            input_snapshot_id=input_id,
            input_snapshot_hash=input_hash,
            processed_count=len(identities),
            source_summaries=source_summaries,
            missing_or_stale=missing_or_stale,
            warnings=warnings,
            content_fingerprint="",
            references=references,
        )
        status: Literal["success", "partial", "unavailable"] = (
            "unavailable"
            if not identities and not items
            else "partial" if missing_or_stale or warnings else "success"
        )
        message = (
            "目前沒有可供比較的持股、自選股或研究證據。"
            if status == "unavailable"
            else "本次簡報由現有本機證據產生；AI 內容不可用時已採規則式降級。"
        )
        fingerprint = _content_fingerprint(
            manifest,
            items,
            status=status,
            message=message,
            macro_context=macro_context,
        )
        manifest = replace(manifest, content_fingerprint=fingerprint)
        _validate_reference_contract(manifest, items)
        _validate_macro_context(manifest, macro_context)
        return DailyResearchBrief(
            generated_at=generated_at,
            status=status,
            manifest=manifest,
            items=items,
            message=message,
            macro_context=macro_context,
        )


def _events_from_daily_brief(brief: DailyBrief) -> tuple[DailyResearchEvent, ...]:
    """Create a conservative first-use event view without duplicating loop logic."""

    from stock_tool.application.daily_research_loop import (
        _build_events,
    )  # local import avoids cycle

    return _build_events(brief=brief, sources={})


class DailyResearchBriefStore:
    """Atomic authoritative JSON store; HTML is always rendered on demand."""

    def __init__(
        self,
        json_path: str | Path,
        html_path: str | Path,
        history_dir: str | Path | None = None,
    ) -> None:
        self.json_path = Path(json_path)
        # Retained as a compatibility/output location for callers, but never
        # participates in persistence or recovery decisions.
        self.html_path = Path(html_path)
        self.history_dir = Path(history_dir) if history_dir is not None else None
        self.last_warning: str | None = None

    def load(self) -> DailyResearchBrief | None:
        self.last_warning = None
        if not self.json_path.is_file():
            return None
        try:
            brief = DailyResearchBrief.from_dict(
                json.loads(self.json_path.read_text(encoding="utf-8"))
            )
            return brief
        except (OSError, UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError):
            self.last_warning = "最近一次研究簡報無法驗證，已安全略過。"
            return None

    def save(self, brief: DailyResearchBrief) -> None:
        """Atomically replace only the validated authoritative JSON."""

        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        validated = DailyResearchBrief.from_dict(brief.to_dict())
        archive_created = False
        if self.history_dir is not None and validated.status == "success":
            archive_created = self._archive_success(validated)
        json_temp: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", newline="\n", dir=self.json_path.parent, delete=False
            ) as handle:
                json.dump(
                    validated.to_dict(),
                    handle,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                handle.flush()
                os.fsync(handle.fileno())
                json_temp = Path(handle.name)
            os.replace(json_temp, self.json_path)
            archive_created = False
            # HTML is a disposable projection of the just-validated JSON.  A
            # projection failure never invalidates or rolls back the authority.
            try:
                self.html_path.parent.mkdir(parents=True, exist_ok=True)
                self.html_path.write_text(
                    render_daily_brief_html(validated), encoding="utf-8", newline="\n"
                )
            except (OSError, UnicodeError, ValueError) as exc:
                self.last_warning = f"derived HTML projection unavailable: {type(exc).__name__}"
        finally:
            if json_temp is not None and json_temp.exists():
                json_temp.unlink(missing_ok=True)
            if archive_created and self.history_dir is not None:
                (self.history_dir / f"brief-{validated.manifest.content_fingerprint}.json").unlink(
                    missing_ok=True
                )

    def _archive_success(self, brief: DailyResearchBrief) -> bool:
        """Publish an immutable successful brief without overwriting history."""

        assert self.history_dir is not None
        self.history_dir.mkdir(parents=True, exist_ok=True)
        target = self.history_dir / f"brief-{brief.manifest.content_fingerprint}.json"
        payload = _canonical_json(brief.to_dict()).encode("utf-8")
        descriptor: int | None = None
        own_created = False
        try:
            try:
                descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if target.read_bytes() != payload:
                    raise ValueError("brief history fingerprint collision")
                return False
            own_created = True
            os.write(descriptor, payload)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            return True
        except Exception:
            if descriptor is not None:
                os.close(descriptor)
            if own_created:
                target.unlink(missing_ok=True)
            raise

    def history(self) -> tuple[DailyResearchBrief, ...]:
        """Load immutable successful briefs in deterministic chronological order."""

        if self.history_dir is None or not self.history_dir.is_dir():
            return ()
        briefs: list[DailyResearchBrief] = []
        for path in sorted(self.history_dir.glob("*.json")):
            if not path.name.startswith("brief-"):
                raise ValueError("brief history contains an unexpected immutable record")
            try:
                brief = DailyResearchBrief.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (
                OSError,
                UnicodeDecodeError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                raise ValueError("brief history is corrupt") from exc
            if (
                brief.status != "success"
                or path.name != f"brief-{brief.manifest.content_fingerprint}.json"
            ):
                raise ValueError("brief history identity is invalid")
            briefs.append(brief)
        return tuple(
            sorted(briefs, key=lambda item: (item.generated_at, item.manifest.content_fingerprint))
        )


def render_daily_brief_html(brief: DailyResearchBrief) -> str:
    """Render safe, escaped HTML suitable for a download without paths or secrets."""

    rows: list[str] = []
    for item in brief.items:
        facts = "<br>".join(html.escape(value) for value in item.facts) or "無資料"
        inferences = "<br>".join(html.escape(value) for value in item.inferences) or "無推論"
        risks = "<br>".join(html.escape(value) for value in item.risks) or "無額外警告"
        rows.append(
            "<article><h2>{identity}</h2>"
            "<p>優先級：{priority}；狀態：{status}；信心：{confidence}</p>"
            "<p>入選原因：{reason}</p><p>事實：{facts}</p>"
            "<p>推論：{inferences}</p><p>風險與資料缺口：{risks}</p>"
            "<p>資料日期：{date}；來源：{source}</p></article>".format(
                identity=html.escape(item.identity),
                priority=item.priority,
                status=html.escape(item.status),
                confidence=html.escape(item.confidence),
                reason=html.escape(item.reason),
                facts=facts,
                inferences=inferences,
                risks=risks,
                date=html.escape(item.data_as_of or "無資料"),
                source=html.escape(item.source or "無資料"),
            )
        )
    return (
        "<!doctype html><meta charset='utf-8'>"
        f"<meta name='content-fingerprint' content='{html.escape(brief.manifest.content_fingerprint)}'>"
        "<title>每日研究簡報</title>"
        f"<h1>每日研究簡報</h1><p>{html.escape(brief.message)}</p>"
        f"<p>簡報日期：{html.escape(brief.manifest.brief_date)}；"
        f"資料截至：{html.escape(brief.manifest.as_of_date or '無資料')}</p>" + "".join(rows)
    )


__all__ = [
    "DAILY_RESEARCH_BRIEF_SCHEMA_VERSION",
    "DailyBriefItemStatus",
    "DailyBriefSource",
    "DailyResearchBrief",
    "DailyResearchBriefManifest",
    "DailyResearchBriefApplicationService",
    "DailyResearchBriefStore",
    "EvidenceReference",
    "EvidenceChainItem",
    "render_daily_brief_html",
]
