"""Canonical, evidence-first concept dataset adapter backed by ResearchRepository."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlparse

from stock_tool.data.repositories import (
    ConceptKnowledgeRecord,
    ConceptRelationRecord,
    ResearchIdentity,
    ResearchProvenance,
    ResearchRepository,
    RepositoryDataError,
)

RELATION_TYPES = frozenset(
    {
        "core_manufacturing",
        "equipment_materials",
        "design_platform",
        "downstream_demand",
        "indirect_beneficiary",
    }
)
RELATION_TYPE_LABELS = {
    "core_manufacturing": "核心製造",
    "equipment_materials": "設備／材料",
    "design_platform": "設計／平台",
    "downstream_demand": "下游需求",
    "indirect_beneficiary": "間接受益",
}


@dataclass(frozen=True, slots=True)
class DatasetImportResult:
    """Deterministic result of importing one versioned local evidence dataset."""

    dataset_version: str
    imported_concepts: int
    imported_relations: int


class ConceptRepository:
    """Validated concept loader and query adapter; SQL remains in ResearchRepository."""

    def __init__(self, repository: ResearchRepository) -> None:
        self._repository = repository

    def initialize(self) -> None:
        """Initialize the shared repository before canonical concept access."""

        self._repository.initialize()

    def has_concepts(self) -> bool:
        """Return whether any canonical concept metadata has already been stored."""

        return bool(self._repository.list_concepts())

    def concepts(self) -> tuple[ConceptKnowledgeRecord, ...]:
        """Return stored concept metadata for exact relation traversal."""

        return self._repository.list_concepts()

    def import_dataset(self, directory: str | Path) -> DatasetImportResult:
        """Validate an entire dataset before atomically persisting it."""

        root = Path(directory)
        concepts_payload = _load_json(root / "concepts.json")
        relations_payload = _load_json(root / "relations.json")
        version = _required_text(
            relations_payload.get("dataset_version") or concepts_payload.get("dataset_version"),
            "dataset_version",
        )
        now = datetime.now(timezone.utc).isoformat()
        concepts = concepts_payload.get("concepts")
        relations = relations_payload.get("relations")
        if not isinstance(concepts, list) or not isinstance(relations, list):
            raise RepositoryDataError("Concept dataset requires concepts and relations lists.")

        concept_records, known_keys = _validated_concepts(concepts, now=now, version=version)
        relation_records = _validated_relations(
            relations,
            known_concept_keys=known_keys,
            now=now,
            version=version,
        )
        self._repository.upsert_concept_dataset(concept_records, relation_records)
        return DatasetImportResult(version, len(concepts), len(relations))

    def concept(self, concept_key: str) -> ConceptKnowledgeRecord:
        """Return one verified concept node or raise a domain-level missing-data error."""

        record = self._repository.get_concept(concept_key)
        if record is None:
            raise RepositoryDataError("No verified concept metadata is available.")
        return record

    def relations_for(
        self, concept_key: str, *, symbol: str | None = None, market: str | None = None
    ) -> tuple[ConceptRelationRecord, ...]:
        """Return only explicit, market-qualified evidence relations for a concept."""

        identity = None
        if symbol is not None or market is not None:
            if not symbol or not market:
                raise RepositoryDataError(
                    "Concept relation lookup requires symbol and market together."
                )
            identity = ResearchIdentity(symbol, market)
        return self._repository.list_concept_relations(concept_key, identity=identity)

    def resolve_concept_key(self, query: str) -> str | None:
        """Resolve a dataset alias exactly; it intentionally does not use fuzzy matching."""

        needle = str(query or "").strip().casefold()
        if not needle:
            return None
        for record in self._repository.list_concepts():
            candidates = (record.concept_key, record.display_name, *record.aliases)
            if any(needle == candidate.casefold() for candidate in candidates):
                return record.concept_key
        return None


def _validated_concepts(
    concepts: list[object], *, now: str, version: str
) -> tuple[tuple[ConceptKnowledgeRecord, ...], frozenset[str]]:
    """Construct all concept records and reject duplicate exact-match aliases."""

    records: list[ConceptKnowledgeRecord] = []
    claimed_aliases: dict[str, str] = {}
    concept_keys: set[str] = set()
    for raw in concepts:
        if not isinstance(raw, dict):
            raise RepositoryDataError("Concept metadata entry must be an object.")
        key = _required_text(raw.get("concept_key"), "concept_key").lower()
        display_name = _required_text(raw.get("display_name"), "display_name")
        if key in concept_keys:
            raise RepositoryDataError(f"Concept dataset contains duplicate concept_key: {key}")
        aliases = _string_tuple(raw.get("aliases", ()), "aliases")
        for candidate in (key, display_name, *aliases):
            normalized = _alias_key(candidate)
            owner = claimed_aliases.get(normalized)
            if owner is not None and owner != key:
                raise RepositoryDataError(
                    f"Concept dataset contains ambiguous alias: {candidate!r} belongs to {owner} and {key}."
                )
            claimed_aliases[normalized] = key
        concept_keys.add(key)
        records.append(
            ConceptKnowledgeRecord(
                concept_key=key,
                display_name=display_name,
                description=str(raw.get("description") or ""),
                as_of_date=_optional_iso_date(raw.get("as_of_date")),
                provenance=_dataset_provenance(now, version),
                aliases=aliases,
                dataset_version=version,
            )
        )
    return tuple(records), frozenset(concept_keys)


def _validated_relations(
    relations: list[object],
    *,
    known_concept_keys: frozenset[str],
    now: str,
    version: str,
) -> tuple[ConceptRelationRecord, ...]:
    """Construct all relation records before any dataset write begins."""

    records: list[ConceptRelationRecord] = []
    seen_keys: set[tuple[str, str, str, str]] = set()
    for raw in relations:
        if not isinstance(raw, dict):
            raise RepositoryDataError("Concept relation entry must be an object.")
        concept_key = _required_text(raw.get("concept_key"), "concept_key").lower()
        if concept_key not in known_concept_keys:
            raise RepositoryDataError(
                f"Concept relation references unknown concept_key: {concept_key}"
            )
        relation_type = _required_text(raw.get("relation_type"), "relation_type")
        if relation_type not in RELATION_TYPES:
            raise RepositoryDataError(f"Unsupported relation_type: {relation_type}")
        identity = ResearchIdentity(
            _required_text(raw.get("symbol"), "symbol"),
            _required_text(raw.get("market"), "market"),
        )
        relation_key = (concept_key, identity.symbol, identity.market, relation_type)
        if relation_key in seen_keys:
            raise RepositoryDataError(
                "Concept dataset contains duplicate canonical relation identity."
            )
        seen_keys.add(relation_key)
        source_name = _required_text(raw.get("source_name"), "source_name")
        source_url = _safe_source_url(raw.get("source_url"))
        evidence = str(raw.get("evidence") or "").strip()
        confidence = _safe_confidence(raw.get("confidence"), evidence, source_url, source_name)
        records.append(
            ConceptRelationRecord(
                concept_key=concept_key,
                identity=identity,
                relation_type=relation_type,
                evidence=evidence,
                as_of_date=_optional_iso_date(raw.get("as_of_date")),
                provenance=ResearchProvenance(
                    provider=source_name,
                    source_type=(
                        "manual_seed" if source_name == "manual_seed" else "evidence_dataset"
                    ),
                    provider_symbol=None,
                    source_url=source_url,
                    fetched_at=now,
                    updated_at=now,
                    state="complete" if evidence else "partial",
                ),
                confidence=confidence,
                verified_at=_optional_iso_date(raw.get("verified_at")),
                dataset_version=version,
            )
        )
    return tuple(records)


def bundled_dataset_directory() -> Path | None:
    """Locate the allowlisted bundled concept dataset for source and EXE runs."""

    candidates = (
        Path.cwd() / "data" / "sample" / "concepts",
        Path(__file__).resolve().parents[2] / "data" / "sample" / "concepts",
    )
    return next(
        (
            candidate
            for candidate in candidates
            if (candidate / "concepts.json").is_file() and (candidate / "relations.json").is_file()
        ),
        None,
    )


def seed_bundled_dataset(repository: ConceptRepository) -> DatasetImportResult | None:
    """Import the bundled dataset only when no canonical concepts are stored yet.

    The bundled content is explicitly marked as manual seed data. It never replaces
    a user's existing canonical concept records or promotes unsupported relations.
    """

    repository.initialize()
    if repository.has_concepts():
        return None
    directory = bundled_dataset_directory()
    if directory is None:
        return None
    return repository.import_dataset(directory)


def legacy_unverified_concept_hints(
    *, symbol: str, provider_symbol: str | None, text: str
) -> tuple[str, ...]:
    """Return compatibility-only legacy hints, never verified evidence relations.

    The hard-coded profile table remains available to preserve legacy screens while
    the versioned dataset is rolled out. Callers must present these as rule-based
    hints and must not persist them as canonical supply-chain evidence.
    """

    from stock_tool.concepts import CONCEPT_PROFILES

    normalized = _legacy_normalize(text)
    requested = str(symbol).strip().upper()
    provider_base = str(provider_symbol or "").strip().upper().split(".", maxsplit=1)[0]
    matches: list[str] = []
    for concept, profile in CONCEPT_PROFILES.items():
        symbols = {
            str(item).upper()
            for item in (*profile.get("tw_symbols", ()), *profile.get("us_symbols", ()))
        }
        alias = _legacy_normalize(concept)
        if requested in symbols or provider_base in symbols:
            matches.append(concept)
        elif alias and (not alias.isascii() or len(alias) >= 3) and alias in normalized:
            matches.append(concept)
    return tuple(dict.fromkeys(matches))


def confidence_label(confidence: float) -> str:
    """Map the single canonical confidence value to its Chinese presentation label."""

    if confidence >= 0.75:
        return "高"
    if confidence >= 0.50:
        return "中"
    return "低"


def _dataset_provenance(now: str, version: str) -> ResearchProvenance:
    return ResearchProvenance(
        provider="evidence_dataset",
        source_type="local_fixture",
        provider_symbol=None,
        source_url=None,
        fetched_at=now,
        updated_at=now,
        state="complete",
        warnings=(f"dataset_version={version}",),
    )


def _load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RepositoryDataError(f"Cannot load concept dataset: {path.name}") from exc
    if not isinstance(value, dict):
        raise RepositoryDataError("Concept dataset root must be an object.")
    return value


def _safe_source_url(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RepositoryDataError("Concept evidence source_url must use http or https.")
    return text


def _safe_confidence(
    value: object, evidence: str, source_url: str | None, source_name: str
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise RepositoryDataError("Concept relation confidence must be numeric.")
    try:
        confidence = float(value)
    except (TypeError, ValueError) as exc:
        raise RepositoryDataError("Concept relation confidence must be numeric.") from exc
    if not 0.0 <= confidence <= 1.0:
        raise RepositoryDataError("Concept relation confidence must be between 0 and 1.")
    if not evidence or not source_url or source_name == "manual_seed":
        return min(confidence, 0.749)
    return confidence


def _optional_iso_date(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise RepositoryDataError("verified_at must use ISO YYYY-MM-DD format.") from exc


def _alias_key(value: object) -> str:
    """Normalize an exact lookup term without introducing fuzzy matching."""

    return _required_text(value, "alias").casefold()


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        raise RepositoryDataError(f"Concept {field} must be a list.")
    return tuple(_required_text(item, field) for item in value)


def _required_text(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise RepositoryDataError(f"Concept dataset requires {field}.")
    return text


def _legacy_normalize(value: object) -> str:
    return "".join(character for character in str(value or "").casefold() if character.isalnum())
