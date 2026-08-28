"""Deterministic comparison of validated daily research briefs.

The comparison is deliberately independent from Streamlit and from any AI
provider.  A change summary is a projection of two immutable, validated
schema-v2 briefs; it never invents a fact and every displayed change keeps the
evidence reference ids that support it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from stock_tool.application.daily_research_brief import (
    DailyResearchBrief,
    EvidenceChainItem,
    EvidenceReference,
)
from stock_tool.domain.models import Market, Symbol

CHANGE_SCHEMA_VERSION = 2
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
ChangeKind = Literal[
    "baseline",
    "new_risk",
    "risk_worsened",
    "improved",
    "new_follow_up",
    "resolved",
]
ChangeStatus = Literal["baseline", "updated", "no_change", "insufficient", "unavailable"]


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _require_sha256(value: object, field: str) -> str:
    """Return one canonical SHA-256 value or reject the record fail-closed."""

    if not isinstance(value, str) or SHA256_RE.fullmatch(value.strip()) is None:
        raise ChangeValidationError(f"{field} must be a 64-character SHA-256")
    return value.strip().lower()


def _parse_time(value: str, *, now: datetime | None = None) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ChangeValidationError("時間戳無法解析") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ChangeValidationError("時間戳必須包含時區")
    parsed_utc = parsed.astimezone(timezone.utc)
    if now is not None and parsed_utc > now.astimezone(timezone.utc):
        raise ChangeValidationError("timestamp must not be in the future")
    return parsed_utc


class ChangeValidationError(ValueError):
    """Raised when a brief or change summary cannot be trusted."""


@dataclass(frozen=True, slots=True)
class ResearchChange:
    identity: str
    market: str | None
    symbol: str | None
    change_type: ChangeKind
    priority: int
    title: str
    description: str
    current_value: tuple[str, ...]
    previous_value: tuple[str, ...]
    current_brief_fingerprint: str
    previous_brief_fingerprint: str | None
    current_data_as_of: str | None
    previous_data_as_of: str | None
    current_fetched_at: str | None
    previous_fetched_at: str | None
    reference_ids: tuple[str, ...]
    reason: str
    confidence: Literal["high", "medium", "low"]
    coverage: float | None
    ai_allowed: bool

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["current_value"] = list(self.current_value)
        payload["previous_value"] = list(self.previous_value)
        payload["reference_ids"] = list(self.reference_ids)
        return payload

    @classmethod
    def from_dict(cls, payload: object) -> "ResearchChange":
        if not isinstance(payload, Mapping):
            raise ChangeValidationError("變化項目格式錯誤")

        def _str(name: str, required: bool = True) -> str | None:
            value = payload.get(name)
            if value is None and not required:
                return None
            if not isinstance(value, str) or (required and not value.strip()):
                raise ChangeValidationError(f"變化項目欄位無效: {name}")
            return value.strip() or None

        def _list(name: str, *, unique: bool = False) -> tuple[str, ...]:
            value = payload.get(name, [])
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise ChangeValidationError(f"變化項目清單無效: {name}")
            normalized = tuple(item.strip() for item in value if item.strip())
            if len(normalized) != len(value) or (
                unique and len(normalized) != len(set(normalized))
            ):
                raise ChangeValidationError(f"{name} must be a non-empty list")
            return normalized

        priority = payload.get("priority")
        coverage = payload.get("coverage")
        if isinstance(priority, bool) or not isinstance(priority, int) or not 1 <= priority <= 5:
            raise ChangeValidationError("變化優先級無效")
        if coverage is not None and (
            isinstance(coverage, bool)
            or not isinstance(coverage, (int, float))
            or not 0 <= coverage <= 1
        ):
            raise ChangeValidationError("變化涵蓋率無效")
        change_type = _str("change_type")
        if change_type not in {
            "baseline",
            "new_risk",
            "risk_worsened",
            "improved",
            "new_follow_up",
            "resolved",
        }:
            raise ChangeValidationError("變化類型無效")
        confidence = _str("confidence")
        if confidence not in {"high", "medium", "low"}:
            raise ChangeValidationError("變化信心無效")
        ai_allowed = payload.get("ai_allowed")
        if not isinstance(ai_allowed, bool):
            raise ChangeValidationError("AI 使用界線無效")
        identity = _str("identity") or ""
        market = _str("market", required=False)
        symbol = _str("symbol", required=False)
        if market is None or symbol is None:
            raise ChangeValidationError("research change must have a market-qualified identity")
        try:
            parsed_symbol = Symbol.parse(symbol, market=market)
        except (TypeError, ValueError) as exc:
            raise ChangeValidationError("research change identity is invalid") from exc
        if parsed_symbol.market not in {Market.TWSE, Market.TPEX, Market.US}:
            raise ChangeValidationError("research change market is unsupported")
        if (
            identity != parsed_symbol.canonical
            or market != parsed_symbol.market.value
            or symbol != parsed_symbol.code
        ):
            raise ChangeValidationError("research change identity fields disagree")
        current_fingerprint = _require_sha256(
            _str("current_brief_fingerprint"), "current_brief_fingerprint"
        )
        raw_previous_fingerprint = _str("previous_brief_fingerprint", required=False)
        previous_fingerprint = (
            _require_sha256(raw_previous_fingerprint, "previous_brief_fingerprint")
            if raw_previous_fingerprint is not None
            else None
        )
        return cls(
            identity=identity,
            market=market,
            symbol=symbol,
            change_type=change_type,  # type: ignore[arg-type]
            priority=priority,
            title=_str("title") or "",
            description=_str("description") or "",
            current_value=_list("current_value"),
            previous_value=_list("previous_value"),
            current_brief_fingerprint=current_fingerprint,
            previous_brief_fingerprint=previous_fingerprint,
            current_data_as_of=_str("current_data_as_of", required=False),
            previous_data_as_of=_str("previous_data_as_of", required=False),
            current_fetched_at=_str("current_fetched_at", required=False),
            previous_fetched_at=_str("previous_fetched_at", required=False),
            reference_ids=_list("reference_ids", unique=True),
            reason=_str("reason") or "",
            confidence=confidence,  # type: ignore[arg-type]
            coverage=float(coverage) if coverage is not None else None,
            ai_allowed=ai_allowed,
        )


@dataclass(frozen=True, slots=True)
class DailyResearchChangeSet:
    generated_at: str
    status: ChangeStatus
    current_brief_fingerprint: str
    previous_brief_fingerprint: str | None
    changes: tuple[ResearchChange, ...]
    references: tuple[EvidenceReference, ...]
    warnings: tuple[str, ...]
    content_fingerprint: str
    schema_version: int = CHANGE_SCHEMA_VERSION

    def core_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "status": self.status,
            "current_brief_fingerprint": self.current_brief_fingerprint,
            "previous_brief_fingerprint": self.previous_brief_fingerprint,
            "changes": [item.to_dict() for item in self.changes],
            "references": [item.to_dict() for item in self.references],
            "warnings": list(self.warnings),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.core_dict(),
            "content_fingerprint": self.content_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: object) -> "DailyResearchChangeSet":
        if not isinstance(payload, Mapping):
            raise ChangeValidationError("變化摘要格式錯誤")
        schema_version = payload.get("schema_version")
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version != CHANGE_SCHEMA_VERSION
        ):
            raise ChangeValidationError("變化摘要 schema 不支援")
        generated_at = payload.get("generated_at")
        if not isinstance(generated_at, str):
            raise ChangeValidationError("變化摘要缺少時間")
        _parse_time(generated_at, now=datetime.now(timezone.utc))
        status = payload.get("status")
        if status not in {"baseline", "updated", "no_change", "insufficient", "unavailable"}:
            raise ChangeValidationError("變化摘要狀態無效")
        raw_changes = payload.get("changes")
        raw_refs = payload.get("references")
        raw_warnings = payload.get("warnings", [])
        if (
            not isinstance(raw_changes, list)
            or not isinstance(raw_refs, list)
            or not isinstance(raw_warnings, list)
        ):
            raise ChangeValidationError("變化摘要清單無效")
        changes = tuple(ResearchChange.from_dict(item) for item in raw_changes)
        references = tuple(EvidenceReference.from_dict(item) for item in raw_refs)
        reference_map: dict[str, EvidenceReference] = {}
        for reference in references:
            if reference.reference_id in reference_map:
                raise ChangeValidationError("變化摘要引用重複")
            reference_map[reference.reference_id] = reference
        used_references = {reference_id for item in changes for reference_id in item.reference_ids}
        if any(reference_id not in reference_map for reference_id in used_references):
            raise ChangeValidationError("變化摘要引用無法解析")
        if set(reference_map) != used_references:
            raise ChangeValidationError("變化摘要包含未被使用的引用")
        current = payload.get("current_brief_fingerprint")
        previous = payload.get("previous_brief_fingerprint")
        current = _require_sha256(current, "current_brief_fingerprint")
        previous = (
            _require_sha256(previous, "previous_brief_fingerprint")
            if previous is not None
            else None
        )
        if any(not isinstance(item, str) or not item.strip() for item in raw_warnings):
            raise ChangeValidationError("變化摘要警告無效")
        warnings = tuple(item.strip() for item in raw_warnings)
        change_keys = [(item.identity, item.change_type) for item in changes]
        if len(change_keys) != len(set(change_keys)):
            raise ChangeValidationError("變化摘要包含重複項目")
        expected_order = tuple(
            sorted(changes, key=lambda item: (-item.priority, item.identity, item.change_type))
        )
        if changes != expected_order:
            raise ChangeValidationError("變化摘要排序不具決定性")
        for item in changes:
            if (
                item.current_brief_fingerprint != current
                or item.previous_brief_fingerprint != previous
            ):
                raise ChangeValidationError("變化項目與摘要 fingerprint 不一致")
        if status == "baseline":
            if previous is not None or any(item.change_type != "baseline" for item in changes):
                raise ChangeValidationError("baseline 狀態不一致")
        elif status == "no_change":
            if previous is None or changes:
                raise ChangeValidationError("no_change 狀態不一致")
        elif status == "updated":
            if previous is None or not changes:
                raise ChangeValidationError("updated 狀態不一致")
        elif changes:
            raise ChangeValidationError("不足或不可用摘要不得包含成功變化")
        expected = _digest(
            {
                "schema_version": CHANGE_SCHEMA_VERSION,
                "generated_at": generated_at,
                "status": status,
                "current_brief_fingerprint": current,
                "previous_brief_fingerprint": previous,
                "changes": [item.to_dict() for item in changes],
                "references": [item.to_dict() for item in references],
                "warnings": list(warnings),
            }
        )
        fingerprint = payload.get("content_fingerprint")
        if _require_sha256(fingerprint, "content_fingerprint") != expected:
            raise ChangeValidationError("變化摘要 fingerprint 不一致")
        return cls(
            generated_at=generated_at,
            status=status,  # type: ignore[arg-type]
            current_brief_fingerprint=current,
            previous_brief_fingerprint=previous,
            changes=changes,
            references=references,
            warnings=warnings,
            content_fingerprint=expected,
        )


def _item_values(item: EvidenceChainItem | None) -> tuple[str, ...]:
    if item is None:
        return ()
    return tuple((*item.facts, *item.inferences, *item.risks))


def _item_refs(item: EvidenceChainItem | None) -> tuple[str, ...]:
    if item is None:
        return ()
    return tuple(
        dict.fromkeys(
            ref
            for groups in (
                item.fact_reference_ids,
                item.inference_reference_ids,
                item.risk_reference_ids,
            )
            for group in groups
            for ref in group
        )
    )


def _source_times(
    brief: DailyResearchBrief, item: EvidenceChainItem | None
) -> tuple[str | None, str | None]:
    market = item.market if item is not None else None
    summaries = [source for source in brief.manifest.source_summaries if source.market == market]
    source = (
        summaries[0]
        if summaries
        else (brief.manifest.source_summaries[0] if brief.manifest.source_summaries else None)
    )
    return (
        source.data_date if source else (item.data_as_of if item else None),
        source.fetched_at if source else None,
    )


def _validate_brief(
    brief: DailyResearchBrief, *, now: datetime | None = None
) -> DailyResearchBrief:
    try:
        validated = DailyResearchBrief.from_dict(brief.to_dict())
    except (TypeError, ValueError) as exc:
        raise ChangeValidationError("研究簡報無法驗證") from exc
    if validated.status != "success":
        raise ChangeValidationError("只允許比較成功研究簡報")
    if any(item.status != "fresh" for item in validated.items):
        raise ChangeValidationError("研究簡報含有 stale、partial 或 missing 資料")
    for item in validated.items:
        if (item.symbol is None) != (item.market is None):
            raise ChangeValidationError("研究簡報 market-qualified identity 不完整")
        if item.symbol is not None and item.market is not None:
            try:
                parsed = Symbol.parse(item.symbol, market=item.market)
            except (TypeError, ValueError) as exc:
                raise ChangeValidationError("研究簡報 market-qualified identity 無效") from exc
            if parsed.market not in {Market.TWSE, Market.TPEX, Market.US}:
                raise ChangeValidationError("研究簡報市場不受支援")
            if (
                item.identity != parsed.canonical
                or item.market != parsed.market.value
                or item.symbol != parsed.code
            ):
                raise ChangeValidationError("研究簡報 identity 欄位不一致")
    _parse_time(validated.generated_at)
    if now is not None and _parse_time(validated.generated_at) > now.astimezone(timezone.utc):
        raise ChangeValidationError("研究簡報時間不可在未來")
    identities = [
        item.identity
        for item in validated.items
        if item.symbol is not None and item.market is not None
    ]
    if len(identities) != len(set(identities)):
        raise ChangeValidationError("研究簡報含有重複 market-qualified identity")
    return validated


class DailyResearchChangeApplicationService:
    """Build deterministic, evidence-linked changes from two valid briefs."""

    def __init__(self, *, now_fn: Callable[[], datetime] | None = None) -> None:
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    def compare(
        self,
        current: DailyResearchBrief,
        previous: DailyResearchBrief | None = None,
    ) -> DailyResearchChangeSet:
        current = _validate_brief(current, now=self.now_fn())
        if previous is not None:
            previous = _validate_brief(previous, now=self.now_fn())
            if _parse_time(previous.generated_at) > _parse_time(current.generated_at):
                raise ChangeValidationError("前一份研究簡報時間較新")
        refs: dict[str, EvidenceReference] = {}
        for brief in (previous, current):
            if brief is None:
                continue
            for reference in brief.manifest.references:
                existing = refs.get(reference.reference_id)
                if existing is None:
                    refs[reference.reference_id] = reference
                    continue
                # A stable event reference may be replayed after its
                # provider/fetched-at provenance is enriched.  Those fields
                # are metadata, not the economic identity of the event.  The
                # identity, field, period and payload hash remain strict;
                # conflicting values still fail closed.
                strict_fields = (
                    "market",
                    "symbol",
                    "field",
                    "as_of",
                    "payload_sha256",
                )
                for field in strict_fields:
                    old_value = getattr(existing, field)
                    new_value = getattr(reference, field)
                    if old_value and new_value and old_value != new_value:
                        raise ChangeValidationError("相同引用 ID 的內容不一致")
                refs[reference.reference_id] = replace(
                    existing,
                    provider=reference.provider or existing.provider,
                    market=reference.market or existing.market,
                    symbol=reference.symbol or existing.symbol,
                    field=reference.field or existing.field,
                    as_of=reference.as_of or existing.as_of,
                    fetched_at=reference.fetched_at or existing.fetched_at,
                    payload_sha256=reference.payload_sha256 or existing.payload_sha256,
                )
        # Daily briefs may contain validated portfolio-level context items
        # without a stock identity.  They remain part of the authoritative
        # brief, but a market-qualified change record cannot be emitted for
        # them; only identity-qualified items participate in the change graph.
        old_by_id = (
            {
                item.identity: item
                for item in previous.items
                if item.symbol is not None and item.market is not None
            }
            if previous
            else {}
        )
        new_by_id = {
            item.identity: item
            for item in current.items
            if item.symbol is not None and item.market is not None
        }
        changes: list[ResearchChange] = []
        if previous is None:
            for item in current.items:
                if item.symbol is None or item.market is None:
                    continue
                changes.append(
                    self._make_change("baseline", item.identity, item, None, current, None, refs)
                )
            status: ChangeStatus = "baseline"
        else:
            for identity in sorted(set(old_by_id) | set(new_by_id)):
                old = old_by_id.get(identity)
                new = new_by_id.get(identity)
                kind = self._kind(old, new)
                if kind is None:
                    continue
                changes.append(self._make_change(kind, identity, new, old, current, previous, refs))
            status = "updated" if changes else "no_change"
        changes.sort(key=lambda item: (-item.priority, item.identity, item.change_type))
        warnings: tuple[str, ...] = ()
        if not changes and status == "no_change":
            warnings = ("目前沒有可驗證的重大變化",)
        used_reference_ids = {
            reference_id for item in changes for reference_id in item.reference_ids
        }
        selected_references = tuple(refs[key] for key in sorted(used_reference_ids))
        # A change summary describes the current immutable brief.  Binding its
        # timestamp to that brief (rather than wall-clock comparison time)
        # makes its signed content deterministic and tamper-evident.
        generated_at = current.generated_at
        core = {
            "schema_version": CHANGE_SCHEMA_VERSION,
            "generated_at": generated_at,
            "status": status,
            "current_brief_fingerprint": current.manifest.content_fingerprint,
            "previous_brief_fingerprint": (
                previous.manifest.content_fingerprint if previous else None
            ),
            "changes": [item.to_dict() for item in changes],
            "references": [item.to_dict() for item in selected_references],
            "warnings": list(warnings),
        }
        return DailyResearchChangeSet(
            generated_at=generated_at,
            status=status,
            current_brief_fingerprint=current.manifest.content_fingerprint,
            previous_brief_fingerprint=previous.manifest.content_fingerprint if previous else None,
            changes=tuple(changes),
            references=selected_references,
            warnings=warnings,
            content_fingerprint=_digest(core),
        )

    @staticmethod
    def _kind(old: EvidenceChainItem | None, new: EvidenceChainItem | None) -> ChangeKind | None:
        if old is None and new is not None:
            return "new_risk" if new.risks else "new_follow_up"
        if old is not None and new is None:
            return "resolved"
        if old is None or new is None:
            return None
        if old.risks != new.risks:
            if new.risks and not old.risks:
                return "risk_worsened"
            if old.risks and not new.risks:
                return "improved"
            return "risk_worsened"
        if _item_values(old) != _item_values(new) or old.status != new.status:
            return "new_follow_up"
        return None

    def _make_change(
        self,
        kind: ChangeKind,
        identity: str,
        current_item: EvidenceChainItem | None,
        previous_item: EvidenceChainItem | None,
        current: DailyResearchBrief,
        previous: DailyResearchBrief | None,
        refs: Mapping[str, EvidenceReference],
    ) -> ResearchChange:
        item = current_item or previous_item
        assert item is not None
        reference_ids = tuple(
            dict.fromkeys((*_item_refs(current_item), *_item_refs(previous_item)))
        )
        if any(reference_id not in refs for reference_id in reference_ids):
            raise ChangeValidationError("變化引用無法解析")
        titles = {
            "baseline": "建立研究基準",
            "new_risk": "新的風險",
            "risk_worsened": "風險惡化",
            "improved": "風險改善",
            "new_follow_up": "新的後續變化",
            "resolved": "先前事件已解除或消失",
        }
        priorities = {
            "baseline": 2,
            "new_risk": 5,
            "risk_worsened": 5,
            "new_follow_up": 3,
            "improved": 2,
            "resolved": 2,
        }
        current_date, current_fetched = _source_times(current, current_item)
        previous_date, previous_fetched = (
            _source_times(previous, previous_item) if previous else (None, None)
        )
        values = _item_values(current_item)
        old_values = _item_values(previous_item)
        coverage = item.completeness
        return ResearchChange(
            identity=identity,
            market=item.market,
            symbol=item.symbol,
            change_type=kind,
            priority=priorities[kind],
            title=titles[kind],
            description=f"{identity}：{titles[kind]}；僅根據已驗證研究證據整理。",
            current_value=values,
            previous_value=old_values,
            current_brief_fingerprint=current.manifest.content_fingerprint,
            previous_brief_fingerprint=previous.manifest.content_fingerprint if previous else None,
            current_data_as_of=current_date,
            previous_data_as_of=previous_date,
            current_fetched_at=current_fetched,
            previous_fetched_at=previous_fetched,
            reference_ids=reference_ids,
            reason=f"比較 market-qualified identity {identity} 的已驗證欄位",
            confidence=item.confidence,
            coverage=coverage,
            ai_allowed=bool(reference_ids),
        )


def _atomic_json_write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class DailyResearchChangeStore:
    """Atomic latest projection backed by immutable content-addressed records."""

    def __init__(self, latest_path: str | Path, history_dir: str | Path) -> None:
        self.latest_path = Path(latest_path)
        self.history_dir = Path(history_dir)
        self.last_warning: str | None = None

    def load(self) -> DailyResearchChangeSet | None:
        self.last_warning = None
        if not self.latest_path.is_file():
            return None
        try:
            return DailyResearchChangeSet.from_dict(
                json.loads(self.latest_path.read_text(encoding="utf-8"))
            )
        except (OSError, UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.last_warning = "每日變化摘要無法驗證"
            raise ChangeValidationError("每日變化摘要無法驗證") from exc

    def save(self, summary: DailyResearchChangeSet) -> None:
        validated = DailyResearchChangeSet.from_dict(summary.to_dict())
        self.history_dir.mkdir(parents=True, exist_ok=True)
        target = self.history_dir / f"change-{validated.content_fingerprint}.json"
        payload = _canonical(validated.to_dict()).encode("utf-8")
        archive_created = False
        own_created = False
        descriptor: int | None = None
        try:
            descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if target.read_bytes() != payload:
                raise ChangeValidationError("變化摘要 history collision")
        else:
            try:
                own_created = True
                os.write(descriptor, payload)
                os.fsync(descriptor)
                archive_created = True
            except Exception:
                if own_created:
                    os.close(descriptor)
                    descriptor = None
                    target.unlink(missing_ok=True)
                raise
            finally:
                if descriptor is not None:
                    os.close(descriptor)
                descriptor = None
        try:
            _atomic_json_write(self.latest_path, validated.to_dict())
        except Exception:
            if archive_created:
                target.unlink(missing_ok=True)
            raise

    def history(self) -> tuple[DailyResearchChangeSet, ...]:
        if not self.history_dir.is_dir():
            return ()
        records: list[DailyResearchChangeSet] = []
        for path in sorted(self.history_dir.glob("*.json")):
            if not path.name.startswith("change-"):
                raise ChangeValidationError("變化摘要 history 含有非 immutable 記錄")
            try:
                record = DailyResearchChangeSet.from_dict(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            except (
                OSError,
                UnicodeDecodeError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                raise ChangeValidationError("變化摘要 history 損壞") from exc
            if path.name != f"change-{record.content_fingerprint}.json":
                raise ChangeValidationError("變化摘要 history identity 無效")
            records.append(record)
        return tuple(sorted(records, key=lambda item: item.generated_at))


__all__ = [
    "CHANGE_SCHEMA_VERSION",
    "ChangeValidationError",
    "DailyResearchChangeApplicationService",
    "DailyResearchChangeSet",
    "DailyResearchChangeStore",
    "ResearchChange",
]
