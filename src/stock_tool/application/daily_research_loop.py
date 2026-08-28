"""Persisted, deterministic Daily Research Loop snapshots and differences.

This module intentionally derives its state from the existing ``DailyBrief``
boundary.  It does not fetch data, infer a market, or mutate holdings.  The
stored snapshot is a small, market-qualified sidecar that lets a later app
session compare a successful user-initiated refresh against the preceding
successful refresh.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast

from stock_tool.application.daily_brief import (
    ActionRequired,
    DailyAction,
    DailyBrief,
    DailyBriefItem,
)

DailyResearchEventCategory = Literal[
    "new_change",
    "changed",
    "resolved",
    "persistent_state",
    "data_repair",
]
DailyResearchLoopStatus = Literal[
    "baseline_created",
    "no_change",
    "updated",
    "partial",
    "previous_success",
    "unavailable",
]

_SNAPSHOT_SCHEMA_VERSION = 1
_GENERIC_SOURCE = "本機投資組合／研究狀態"


@dataclass(frozen=True, slots=True)
class DailyResearchSource:
    """Non-sensitive provenance retained for one market-qualified identity."""

    provider: str | None
    source_type: str | None
    provider_symbol: str | None
    last_data_date: str | None
    checked_at: str | None

    @property
    def label(self) -> str:
        """Return a concise user-visible provenance label without fabricated data."""

        if self.provider is None and self.source_type in {None, "derived"}:
            return _GENERIC_SOURCE
        parts = [part for part in (self.provider, self.source_type) if part]
        return " / ".join(parts) if parts else _GENERIC_SOURCE


@dataclass(frozen=True, slots=True)
class DailyResearchEvent:
    """One evidence-backed, non-advisory change, continuation, or repair item."""

    identity: str | None
    category: DailyResearchEventCategory
    priority: int
    code: str
    title: str
    why_important: str
    current_value: str
    baseline_value: str | None
    baseline_as_of: str | None
    source: DailyResearchSource
    as_of_date: str | None
    action: DailyAction
    field: str | None = None

    @property
    def event_identity(self) -> str:
        """Return a stable event identity, independent of mutable evidence values."""

        payload = {
            "identity": self.identity,
            "code": self.code,
            "action": self.action,
            "field": self.field,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @property
    def display_key(self) -> str:
        """Return the stable UI key used to suppress duplicated cards and CTAs."""

        payload = {
            "identity": self.identity,
            "action": self.action,
            "field": self.field or self.code,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @property
    def comparison_key(self) -> str:
        """Keep the prior public name as an alias for stable event identity."""

        return self.event_identity

    @property
    def value_key(self) -> str:
        """Return only evidence fields that can represent a meaningful update.

        Provider check timestamps are deliberately excluded. Rechecking unchanged
        evidence must not manufacture a Daily Research change.
        """

        payload = {
            "title": self.title,
            "why_important": self.why_important,
            "current_value": self.current_value,
            "as_of_date": self.as_of_date,
            "source": {
                "provider": self.source.provider,
                "source_type": self.source.source_type,
                "provider_symbol": self.source.provider_symbol,
                "last_data_date": self.source.last_data_date,
            },
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def as_persistent(self) -> "DailyResearchEvent":
        """Return a display-only continuing-state version of a saved event."""

        if self.category == "data_repair":
            return self
        return DailyResearchEvent(
            identity=self.identity,
            category="persistent_state",
            priority=self.priority,
            code=self.code,
            title=self.title,
            why_important="此狀態自上次成功檢查後仍持續存在。",
            current_value=self.current_value,
            baseline_value=self.baseline_value,
            baseline_as_of=self.baseline_as_of,
            source=self.source,
            as_of_date=self.as_of_date,
            action=self.action,
            field=self.field,
        )

    def as_changed(
        self, *, previous: "DailyResearchEvent", baseline_as_of: str
    ) -> "DailyResearchEvent":
        """Return an updated presentation event with prior successful evidence."""

        return DailyResearchEvent(
            identity=self.identity,
            category="changed",
            priority=self.priority,
            code=self.code,
            title=self.title,
            why_important=self.why_important,
            current_value=self.current_value,
            baseline_value=previous.current_value,
            baseline_as_of=baseline_as_of,
            source=self.source,
            as_of_date=self.as_of_date,
            action=self.action,
            field=self.field,
        )

    def as_new(self, *, baseline_as_of: str) -> "DailyResearchEvent":
        """Return a first-seen presentation event without fabricating a prior value."""

        return DailyResearchEvent(
            identity=self.identity,
            category=self.category,
            priority=self.priority,
            code=self.code,
            title=self.title,
            why_important=self.why_important,
            current_value=self.current_value,
            baseline_value="上次成功檢查未出現",
            baseline_as_of=baseline_as_of,
            source=self.source,
            as_of_date=self.as_of_date,
            action=self.action,
            field=self.field,
        )

    def as_resolved(
        self, *, current_as_of: str | None, baseline_as_of: str
    ) -> "DailyResearchEvent":
        """Return an evidence-backed resolution for a prior successful event."""

        return DailyResearchEvent(
            identity=self.identity,
            category="resolved",
            priority=self.priority,
            code=self.code,
            title=self.title,
            why_important="此項目未再出現在本次成功摘要，請保留後續研究與風險追蹤。",
            current_value="已不再出現／已解除",
            baseline_value=self.current_value,
            baseline_as_of=baseline_as_of,
            source=self.source,
            as_of_date=current_as_of,
            action=self.action,
            field=self.field,
        )


@dataclass(frozen=True, slots=True)
class DailyResearchSnapshot:
    """A successful, derived Daily Brief state persisted independently of prices."""

    schema_version: int
    successful_at: str
    data_as_of_date: str | None
    events: tuple[DailyResearchEvent, ...]

    def to_dict(self) -> dict[str, object]:
        """Serialize only derived, non-sensitive research-loop state."""

        return {
            "schema_version": self.schema_version,
            "successful_at": self.successful_at,
            "data_as_of_date": self.data_as_of_date,
            "events": [_event_to_dict(event) for event in self.events],
        }

    @classmethod
    def from_dict(cls, payload: object) -> "DailyResearchSnapshot":
        """Read a validated snapshot or raise ``ValueError`` without exposing content."""

        if not isinstance(payload, dict):
            raise ValueError("Daily Research snapshot must be a JSON object.")
        if payload.get("schema_version") != _SNAPSHOT_SCHEMA_VERSION:
            raise ValueError("Daily Research snapshot schema is unsupported.")
        successful_at = _text_or_none(payload.get("successful_at"))
        if successful_at is None:
            raise ValueError("Daily Research snapshot lacks successful_at.")
        raw_events = payload.get("events")
        if not isinstance(raw_events, list):
            raise ValueError("Daily Research snapshot lacks events.")
        return cls(
            schema_version=_SNAPSHOT_SCHEMA_VERSION,
            successful_at=successful_at,
            data_as_of_date=_text_or_none(payload.get("data_as_of_date")),
            events=tuple(_event_from_dict(item) for item in raw_events),
        )


@dataclass(frozen=True, slots=True)
class DailyResearchSnapshotLoad:
    """Safe snapshot-load outcome; malformed sidecars never break the homepage."""

    snapshot: DailyResearchSnapshot | None
    warning: str | None = None


class DailyResearchSnapshotStore:
    """Atomic local storage for the last successful derived Daily Brief snapshot."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> DailyResearchSnapshotLoad:
        """Load one snapshot, returning a safe warning for missing or corrupt state."""

        if not self.path.exists():
            return DailyResearchSnapshotLoad(snapshot=None)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return DailyResearchSnapshotLoad(snapshot=DailyResearchSnapshot.from_dict(payload))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return DailyResearchSnapshotLoad(
                snapshot=None,
                warning="上次 Daily Brief 快照無法讀取，已回退至目前摘要。",
            )

    def save(self, snapshot: DailyResearchSnapshot) -> None:
        """Atomically replace the derived sidecar only after a successful refresh."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(
                    snapshot.to_dict(),
                    handle,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class DailyResearchLoopResult:
    """Read-only Daily Research Loop presentation state for one homepage render."""

    status: DailyResearchLoopStatus
    snapshot: DailyResearchSnapshot | None
    priority_events: tuple[DailyResearchEvent, ...]
    persistent_events: tuple[DailyResearchEvent, ...]
    repair_events: tuple[DailyResearchEvent, ...]
    last_successful_at: str | None
    message: str
    warning: str | None = None


class DailyResearchLoopService:
    """Create deterministic snapshot diffs from existing local Daily Brief evidence."""

    def __init__(self, *, max_priority_events: int = 3) -> None:
        if max_priority_events <= 0:
            raise ValueError("max_priority_events must be greater than zero.")
        self._max_priority_events = max_priority_events

    def complete_success(
        self,
        *,
        brief: DailyBrief,
        previous_snapshot: DailyResearchSnapshot | None,
        successful_at: str,
        sources: Mapping[str, DailyResearchSource] | None = None,
    ) -> DailyResearchLoopResult:
        """Build a new successful state and compare it only to the prior success."""

        current_events = _build_events(brief=brief, sources=sources or {})
        snapshot = DailyResearchSnapshot(
            schema_version=_SNAPSHOT_SCHEMA_VERSION,
            successful_at=successful_at,
            data_as_of_date=brief.data_as_of_date,
            events=current_events,
        )
        if previous_snapshot is None:
            return DailyResearchLoopResult(
                status="baseline_created",
                snapshot=snapshot,
                priority_events=(),
                persistent_events=(),
                repair_events=_repair_events(current_events),
                last_successful_at=successful_at,
                message="今日檢查完成：已建立首次比較基準，下一次成功更新才會顯示新變化。",
            )

        previous_by_identity = {event.event_identity: event for event in previous_snapshot.events}
        current_by_identity = {event.event_identity: event for event in current_events}
        changes: list[DailyResearchEvent] = []
        persistent: list[DailyResearchEvent] = []
        for event in current_events:
            previous = previous_by_identity.get(event.event_identity)
            if previous is None:
                changes.append(event.as_new(baseline_as_of=previous_snapshot.successful_at))
            elif event.value_key != previous.value_key:
                changes.append(
                    event.as_changed(
                        previous=previous,
                        baseline_as_of=previous_snapshot.successful_at,
                    )
                )
            else:
                persistent.append(event.as_persistent())
        changes.extend(
            event.as_resolved(
                current_as_of=brief.data_as_of_date,
                baseline_as_of=previous_snapshot.successful_at,
            )
            for event_identity, event in previous_by_identity.items()
            if event_identity not in current_by_identity
        )
        priority_events = _sorted_events(changes)[: self._max_priority_events]
        if priority_events:
            status: DailyResearchLoopStatus = "updated"
            message = "今日檢查完成：已列出自上次成功更新後最重要的變化。"
        else:
            status = "no_change"
            message = "今日無重大變化；目前顯示最後成功檢查的延續狀態。"
        display_groups = _dedupe_display_groups(
            priority_events=priority_events,
            persistent_events=tuple(
                item for item in persistent if item.category == "persistent_state"
            ),
            repair_events=_repair_events(current_events),
        )
        return DailyResearchLoopResult(
            status=status,
            snapshot=snapshot,
            priority_events=display_groups[0],
            persistent_events=display_groups[1],
            repair_events=display_groups[2],
            last_successful_at=successful_at,
            message=message,
        )

    def complete_partial(
        self,
        *,
        previous_snapshot: DailyResearchSnapshot | None,
        checked_at: str | None,
        reason: str,
    ) -> DailyResearchLoopResult:
        """Retain prior success after a partial/failed refresh without relabelling it current."""

        if previous_snapshot is None:
            return DailyResearchLoopResult(
                status="unavailable",
                snapshot=None,
                priority_events=(),
                persistent_events=(),
                repair_events=(),
                last_successful_at=None,
                message="本次更新未完整成功，且尚無可比較的上次成功 Daily Brief。",
                warning=_partial_warning(reason, checked_at),
            )
        persistent = tuple(event.as_persistent() for event in previous_snapshot.events)
        display_groups = _dedupe_display_groups(
            priority_events=(),
            persistent_events=tuple(
                item for item in persistent if item.category == "persistent_state"
            ),
            repair_events=_repair_events(previous_snapshot.events),
        )
        return DailyResearchLoopResult(
            status="partial",
            snapshot=previous_snapshot,
            priority_events=(),
            persistent_events=display_groups[1],
            repair_events=display_groups[2],
            last_successful_at=previous_snapshot.successful_at,
            message="本次更新部分完成；目前保留上次成功 Daily Brief，不將舊資料標示為最新。",
            warning=_partial_warning(reason, checked_at),
        )

    def restore(self, loaded: DailyResearchSnapshotLoad) -> DailyResearchLoopResult:
        """Return the persisted successful state for an app restart without comparing data."""

        snapshot = loaded.snapshot
        if snapshot is None:
            return DailyResearchLoopResult(
                status="unavailable",
                snapshot=None,
                priority_events=(),
                persistent_events=(),
                repair_events=(),
                last_successful_at=None,
                message="尚無上次成功 Daily Brief；請手動更新今日資料以建立比較基準。",
                warning=loaded.warning,
            )
        persistent = tuple(event.as_persistent() for event in snapshot.events)
        display_groups = _dedupe_display_groups(
            priority_events=(),
            persistent_events=tuple(
                item for item in persistent if item.category == "persistent_state"
            ),
            repair_events=_repair_events(snapshot.events),
        )
        return DailyResearchLoopResult(
            status="previous_success",
            snapshot=snapshot,
            priority_events=(),
            persistent_events=display_groups[1],
            repair_events=display_groups[2],
            last_successful_at=snapshot.successful_at,
            message="已載入上次成功 Daily Brief；按「更新今日資料」後才會比較新變化。",
            warning=loaded.warning,
        )


def _build_events(
    *,
    brief: DailyBrief,
    sources: Mapping[str, DailyResearchSource],
) -> tuple[DailyResearchEvent, ...]:
    events = [_event_from_attention(item, sources=sources) for item in brief.attention_items]
    events.extend(_event_from_action(item, sources=sources) for item in brief.action_required)
    events.extend(_canonical_metric_events(brief=brief, sources=sources))
    deduplicated: dict[str, DailyResearchEvent] = {}
    for event in events:
        existing = deduplicated.get(event.display_key)
        if existing is None or _event_preference_key(event) < _event_preference_key(existing):
            deduplicated[event.display_key] = event
    return _sorted_events(deduplicated.values())


def _event_from_attention(
    item: DailyBriefItem,
    *,
    sources: Mapping[str, DailyResearchSource],
) -> DailyResearchEvent:
    identity = item.symbol.canonical if item.symbol is not None else None
    return DailyResearchEvent(
        identity=identity,
        category="new_change",
        priority=_attention_priority(item),
        code=item.code,
        title=item.title,
        why_important=_attention_reason(item),
        current_value=item.evidence,
        baseline_value=None,
        baseline_as_of=None,
        source=_source_for(identity, sources),
        as_of_date=item.as_of_date,
        action=item.action,
        field=item.field,
    )


def _event_from_action(
    item: ActionRequired,
    *,
    sources: Mapping[str, DailyResearchSource],
) -> DailyResearchEvent:
    identity = item.symbol.canonical if item.symbol is not None else None
    return DailyResearchEvent(
        identity=identity,
        category="data_repair",
        priority=_repair_priority(item.field),
        code=f"repair:{item.field}",
        title=item.title,
        why_important="缺少這項可驗證資料會限制研究、估值或風險判讀。",
        current_value=item.detail,
        baseline_value=None,
        baseline_as_of=None,
        source=_source_for(identity, sources),
        as_of_date=item.as_of_date,
        action=item.action,
        field=item.field,
    )


def _canonical_metric_events(
    *,
    brief: DailyBrief,
    sources: Mapping[str, DailyResearchSource],
) -> tuple[DailyResearchEvent, ...]:
    """Expose only existing structured Daily Brief metrics for snapshot comparison."""

    portfolio = brief.portfolio
    rows: list[DailyResearchEvent] = [
        DailyResearchEvent(
            identity=None,
            category="new_change",
            priority=100,
            code="portfolio_risk_alert_count",
            title="持倉風險警示數",
            why_important="風險警示數量改變，可能影響目前持倉的研究優先順序。",
            current_value=str(portfolio.risk_alert_count),
            baseline_value=None,
            baseline_as_of=None,
            source=_source_for(None, sources),
            as_of_date=brief.data_as_of_date,
            action="view_holdings",
            field="risk_alerts",
        )
    ]
    if portfolio.price_coverage is not None:
        rows.append(
            DailyResearchEvent(
                identity=None,
                category="new_change",
                priority=85,
                code="portfolio_price_coverage",
                title="持倉價格覆蓋率",
                why_important="價格覆蓋率改變會影響持倉估值與風險摘要的完整性。",
                current_value=_format_ratio(portfolio.price_coverage),
                baseline_value=None,
                baseline_as_of=None,
                source=_source_for(None, sources),
                as_of_date=brief.data_as_of_date,
                action="view_holdings",
                field="price_coverage",
            )
        )
    if portfolio.max_position_weight is not None:
        rows.append(
            DailyResearchEvent(
                identity=None,
                category="new_change",
                priority=90,
                code="portfolio_max_position_weight",
                title="最大單一持股比例",
                why_important="最大持股比例改變，可能改變集中度風險的研究優先順序。",
                current_value=_format_ratio(portfolio.max_position_weight),
                baseline_value=None,
                baseline_as_of=None,
                source=_source_for(None, sources),
                as_of_date=brief.data_as_of_date,
                action="view_holdings",
                field="max_position_weight",
            )
        )
    for continuation in brief.continuations:
        if continuation.coverage is None:
            continue
        identity = continuation.symbol.canonical
        rows.append(
            DailyResearchEvent(
                identity=identity,
                category="new_change",
                priority=70,
                code="research_coverage",
                title=f"{continuation.symbol.code} 研究覆蓋率",
                why_important="研究覆蓋率改變，會影響可用研究結論的完整性。",
                current_value=_format_ratio(continuation.coverage),
                baseline_value=None,
                baseline_as_of=None,
                source=_source_for(identity, sources),
                as_of_date=continuation.data_as_of_date,
                action="open_research",
                field="research_coverage",
            )
        )
    return tuple(rows)


def _format_ratio(value: float) -> str:
    """Format a known canonical ratio without deriving data from presentation text."""

    return f"{value:.1%}"


def _source_for(
    identity: str | None,
    sources: Mapping[str, DailyResearchSource],
) -> DailyResearchSource:
    if identity is not None and identity in sources:
        return sources[identity]
    return DailyResearchSource(
        provider=None,
        source_type="derived",
        provider_symbol=None,
        last_data_date=None,
        checked_at=None,
    )


def _attention_priority(item: DailyBriefItem) -> int:
    if item.field in {"risk_alerts", "portfolio_valuation"} or item.code == "risk_alert":
        return 100
    if item.code in {"stale_price", "missing_price"} or item.field in {
        "price_data",
        "price_freshness",
    }:
        return 90
    if item.code in {"daily_move", "volume_move", "range_break"}:
        return 80
    if item.severity == "warning":
        return 70
    if item.severity == "attention":
        return 60
    return 50


def _repair_priority(field: str) -> int:
    if field in {"price_data", "price_freshness", "fx_rate_to_base"}:
        return 85
    if field in {"risk_alerts", "portfolio_valuation"}:
        return 80
    if field in {"fundamentals", "research_snapshot", "composite_score"}:
        return 70
    return 60


def _attention_reason(item: DailyBriefItem) -> str:
    if item.field in {"risk_alerts", "portfolio_valuation"} or item.code == "risk_alert":
        return "這是持倉風險或估值相關的新狀態，值得先檢查部位與資料覆蓋。"
    if item.code in {"stale_price", "missing_price"} or item.field in {
        "price_data",
        "price_freshness",
    }:
        return "價格資料不足或可能過期會降低後續研究與風險判讀的可信度。"
    if item.code in {"daily_move", "volume_move", "range_break"}:
        return "價格、區間或成交量出現可驗證的變化，適合回到研究頁確認脈絡。"
    return "這是自上次成功檢查後新出現的研究注意事項。"


def _sorted_events(events: Iterable[DailyResearchEvent]) -> tuple[DailyResearchEvent, ...]:
    rows = list(events)
    return tuple(
        sorted(
            rows,
            key=lambda item: (
                -item.priority,
                _category_sort_order(item.category),
                item.identity or "",
                item.code,
                item.field or "",
            ),
        )
    )


def _category_sort_order(category: DailyResearchEventCategory) -> int:
    """Prefer current changes, then resolutions, then continuing repairs deterministically."""

    return {
        "changed": 0,
        "new_change": 1,
        "resolved": 2,
        "data_repair": 3,
        "persistent_state": 4,
    }[category]


def _event_preference_key(event: DailyResearchEvent) -> tuple[int, int, str]:
    """Select one deterministic representative for one user-visible issue."""

    return (-event.priority, _category_sort_order(event.category), event.code)


def _repair_events(events: tuple[DailyResearchEvent, ...]) -> tuple[DailyResearchEvent, ...]:
    return tuple(item for item in events if item.category == "data_repair")


def _dedupe_display_groups(
    *,
    priority_events: tuple[DailyResearchEvent, ...],
    persistent_events: tuple[DailyResearchEvent, ...],
    repair_events: tuple[DailyResearchEvent, ...],
) -> tuple[
    tuple[DailyResearchEvent, ...],
    tuple[DailyResearchEvent, ...],
    tuple[DailyResearchEvent, ...],
]:
    """Ensure one user-visible Daily Loop card exists for each display identity."""

    seen: set[str] = set()

    def unique(events: Iterable[DailyResearchEvent]) -> tuple[DailyResearchEvent, ...]:
        rows: list[DailyResearchEvent] = []
        for event in events:
            if event.display_key in seen:
                continue
            seen.add(event.display_key)
            rows.append(event)
        return tuple(rows)

    return unique(priority_events), unique(persistent_events), unique(repair_events)


def _partial_warning(reason: str, checked_at: str | None) -> str:
    suffix = f" 本次檢查時間：{checked_at}。" if checked_at else ""
    return f"{reason}{suffix}"


def _event_to_dict(event: DailyResearchEvent) -> dict[str, object]:
    payload = asdict(event)
    payload["source"] = asdict(event.source)
    return payload


def _event_from_dict(payload: object) -> DailyResearchEvent:
    if not isinstance(payload, dict):
        raise ValueError("Daily Research event must be a JSON object.")
    source_payload = payload.get("source")
    if not isinstance(source_payload, dict):
        raise ValueError("Daily Research event lacks source.")
    category = _text_or_none(payload.get("category"))
    if category not in {
        "new_change",
        "changed",
        "resolved",
        "persistent_state",
        "data_repair",
    }:
        raise ValueError("Daily Research event has invalid category.")
    action = _text_or_none(payload.get("action"))
    if action not in {"open_research", "update_data", "view_holdings", "complete_data"}:
        raise ValueError("Daily Research event has invalid action.")
    priority = payload.get("priority")
    if not isinstance(priority, int):
        raise ValueError("Daily Research event has invalid priority.")
    required = ("code", "title", "why_important", "current_value")
    values = {name: _text_or_none(payload.get(name)) for name in required}
    if any(value is None for value in values.values()):
        raise ValueError("Daily Research event lacks required text.")
    return DailyResearchEvent(
        identity=_text_or_none(payload.get("identity")),
        category=cast(DailyResearchEventCategory, category),
        priority=priority,
        code=str(values["code"]),
        title=str(values["title"]),
        why_important=str(values["why_important"]),
        current_value=str(values["current_value"]),
        baseline_value=_text_or_none(payload.get("baseline_value")),
        baseline_as_of=_text_or_none(payload.get("baseline_as_of")),
        source=DailyResearchSource(
            provider=_text_or_none(source_payload.get("provider")),
            source_type=_text_or_none(source_payload.get("source_type")),
            provider_symbol=_text_or_none(source_payload.get("provider_symbol")),
            last_data_date=_text_or_none(source_payload.get("last_data_date")),
            checked_at=_text_or_none(source_payload.get("checked_at")),
        ),
        as_of_date=_text_or_none(payload.get("as_of_date")),
        action=cast(DailyAction, action),
        field=_text_or_none(payload.get("field")),
    )


def _text_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
