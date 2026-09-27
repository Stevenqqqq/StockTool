"""Immutable local research sessions, separate from Research Library v1/v2.

Each content-addressed file contains its full snapshot dependencies. No live
cache, absolute path or mutable 'latest' reference is required to reopen it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import stat
from typing import Any

from stock_tool.application.holding_analysis import HoldingAnalysis
from stock_tool.application.research_snapshot import (
    PriceSnapshot,
    ResearchSnapshot,
    ResearchSourceMetadata,
)
from stock_tool.company_explanation import explain_company
from stock_tool.company_documents import public_url
from stock_tool.company_research import CompanyResearchProfile

MAX_BYTES = 64 * 1024 * 1024


class WorkSessionError(ValueError):
    """Invalid identity, schema, reference or persisted content."""


def canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _keys(value: Any, expected: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise WorkSessionError("研究工作階段格式不符；未載入內容。")


def _time(value: Any) -> None:
    if not isinstance(value, str):
        raise WorkSessionError("工作階段時間格式不符。")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkSessionError("工作階段時間格式不符。") from exc
    if parsed.tzinfo is None:
        raise WorkSessionError("工作階段時間缺少時區。")


@dataclass(frozen=True)
class ResearchIdentity:
    market: str
    symbol: str
    instrument_type: str

    def __post_init__(self) -> None:
        if (
            not all(
                isinstance(value, str) for value in (self.market, self.symbol, self.instrument_type)
            )
            or self.market not in {"TWSE", "TPEX", "US"}
            or not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-^=]{0,19}", self.symbol)
            or self.instrument_type not in {"股票", "ETF"}
        ):
            raise WorkSessionError("市場、代號或標的類型未確認，不能組合研究。")


@dataclass(frozen=True)
class CombinedSnapshot:
    """JSON strings keep nested dependencies immutable, without evidence truncation."""

    identity: ResearchIdentity
    holding_json: str
    company_json: str
    created_at: str

    def __post_init__(self) -> None:
        _time(self.created_at)
        h, c = self.holding, self.company
        _keys(
            h, {"symbol", "market", "currency", "instrument_type", "data", "observations", "gaps"}
        )
        _keys(c, {"identity", "profile", "price", "price_source", "status", "explanations"})
        source = c["price_source"]
        _keys(source, {field.name for field in fields(ResearchSourceMetadata)})
        if source["market"] != self.identity.market:
            raise WorkSessionError("公司行情來源市場不符。")
        for name in ("provider", "query_symbol", "fetched_at", "last_data_date"):
            if source[name] is not None and not isinstance(source[name], str):
                raise WorkSessionError("公司行情來源格式不符。")
        if (
            not isinstance(source["source_type"], str)
            or type(source["row_count"]) is not int
            or source["row_count"] < 0
        ):
            raise WorkSessionError("公司行情來源格式不符。")
        for name in ("warnings", "limitations"):
            if not isinstance(source[name], list) or any(
                not isinstance(v, str) for v in source[name]
            ):
                raise WorkSessionError("公司行情來源格式不符。")
        if c["price"] is not None:
            _keys(c["price"], {field.name for field in fields(PriceSnapshot)})
            for name, value in c["price"].items():
                if value is not None and (
                    not isinstance(value, str)
                    if name == "last_data_date"
                    else type(value) not in (int, float)
                ):
                    raise WorkSessionError("公司行情數值格式不符。")
        if c["status"] not in (
            "ready",
            "partial",
            "insufficient_data",
            "stale",
            "error",
        ) or not isinstance(h["currency"], str):
            raise WorkSessionError("快照狀態格式不符。")
        if {k: h[k] for k in ("market", "symbol", "instrument_type")} != asdict(self.identity) or c[
            "identity"
        ] != asdict(self.identity):
            raise WorkSessionError("持股與公司身分不符，已拒絕組合。")
        if not isinstance(h["data"], list) or not isinstance(c["explanations"], list):
            raise WorkSessionError("快照內容格式不符。")
        for item in h["data"]:
            _keys(item, {"label", "value", "source", "as_of", "fetched_at", "status", "reason"})
            if any(not isinstance(v, str) for v in item.values()):
                raise WorkSessionError("持股證據格式不符。")
        profile = c["profile"]
        _keys(profile, {field.name for field in fields(CompanyResearchProfile)})
        if not isinstance(profile, dict) or profile.get("symbol") != self.identity.symbol:
            raise WorkSessionError("公司快照身分不符。")
        if profile.get("instrument_type") != self.identity.instrument_type:
            raise WorkSessionError("公司快照標的類型不符。")
        dossier = profile.get("dossier")
        if self.identity.instrument_type == "ETF" and (dossier or c["explanations"]):
            raise WorkSessionError("ETF 不得進入公司模型。")
        if dossier is not None:
            if not isinstance(dossier, dict) or (dossier.get("symbol"), dossier.get("market")) != (
                self.identity.symbol,
                self.identity.market,
            ):
                raise WorkSessionError("公司文件身分不符。")
            if not isinstance(dossier.get("documents"), list) or not isinstance(
                dossier.get("facts"), list
            ):
                raise WorkSessionError("公司文件依賴缺失。")
            _keys(
                dossier,
                {
                    "symbol",
                    "market",
                    "website",
                    "industry_lens",
                    "facts",
                    "questions",
                    "gaps",
                    "documents",
                    "checked_at",
                    "state",
                },
            )
            documents: dict[str, Any] = {}
            for doc in dossier["documents"]:
                _keys(doc, {"url", "title", "text", "published_at", "fetched_at", "links"})
                if any(
                    not isinstance(doc[k], str)
                    for k in ("url", "title", "text", "published_at", "fetched_at")
                ):
                    raise WorkSessionError("公司文件欄位不符。")
                public_url(doc["url"], dossier["website"])
                documents[doc["url"]] = doc
            for fact in dossier["facts"]:
                _keys(
                    fact,
                    {
                        "section",
                        "subject",
                        "statement",
                        "stage",
                        "excerpt",
                        "url",
                        "title",
                        "published_at",
                        "fetched_at",
                    },
                )
                if any(not isinstance(value, str) for value in fact.values()):
                    raise WorkSessionError("公司證據欄位不符。")
                document = documents.get(fact["url"])
                if (
                    document is None
                    or not fact["excerpt"]
                    or fact["excerpt"] not in document["text"]
                ):
                    raise WorkSessionError("公司原始文件缺失或無法支持摘錄。")
                if (fact["published_at"], fact["fetched_at"]) != (
                    document["published_at"],
                    document["fetched_at"],
                ):
                    raise WorkSessionError("公司證據與原文日期衝突。")
        for item in c["explanations"]:
            _keys(item, {"heading", "text", "kind", "evidence_indices"})
            if any(not isinstance(item[name], str) for name in ("heading", "text", "kind")):
                raise WorkSessionError("中文解釋格式不符。")
            if not isinstance(item["evidence_indices"], list) or any(
                type(i) is not int or i < 0 or dossier is None or i >= len(dossier["facts"])
                for i in item["evidence_indices"]
            ):
                raise WorkSessionError("中文解釋的證據引用失效。")
        # Reuse the existing immutable datum schema and calculation fingerprint.
        if any(not isinstance(h[key], list) for key in ("observations", "gaps")) or not all(
            isinstance(v, str) for key in ("observations", "gaps") for v in h[key]
        ):
            raise WorkSessionError("持股文字格式不符。")

    @property
    def holding(self) -> dict[str, Any]:
        return json.loads(self.holding_json)

    @property
    def company(self) -> dict[str, Any]:
        return json.loads(self.company_json)

    @property
    def holding_fingerprint(self) -> str:
        # Match HoldingAnalysis.fingerprint exactly, including original JSON spacing.
        return hashlib.sha256(
            json.dumps(self.holding, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()

    @property
    def company_fingerprint(self) -> str:
        return digest(self.company)

    @property
    def fingerprint(self) -> str:
        return digest(
            {
                "identity": asdict(self.identity),
                "holding": self.holding_fingerprint,
                "company": self.company_fingerprint,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "identity": asdict(self.identity),
            "holding": self.holding,
            "company": self.company,
            "holding_fingerprint": self.holding_fingerprint,
            "company_fingerprint": self.company_fingerprint,
            "fingerprint": self.fingerprint,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: Any) -> CombinedSnapshot:
        _keys(
            value,
            {
                "version",
                "identity",
                "holding",
                "company",
                "holding_fingerprint",
                "company_fingerprint",
                "fingerprint",
                "created_at",
            },
        )
        if type(value["version"]) is not int or value["version"] != 1:
            raise WorkSessionError("不支援的組合快照版本。")
        _keys(value["identity"], {"market", "symbol", "instrument_type"})
        result = cls(
            ResearchIdentity(**value["identity"]),
            canonical(value["holding"]),
            canonical(value["company"]),
            value["created_at"],
        )
        for key in ("holding_fingerprint", "company_fingerprint", "fingerprint"):
            if value[key] != getattr(result, key):
                raise WorkSessionError("研究快照指紋不符，內容可能損毀。")
        return result


def combine_snapshots(holding: HoldingAnalysis, company: ResearchSnapshot) -> CombinedSnapshot:
    identity = ResearchIdentity(holding.market, holding.symbol, holding.instrument_type)
    profile = company.company_profile
    if profile is None:
        raise WorkSessionError("尚無公司身分快照，先保留本機持股分析。")
    other = ResearchIdentity(
        company.symbol.market.value, company.symbol.code, profile.instrument_type
    )
    if identity != other:
        raise WorkSessionError("持股與公司身分不符，已拒絕組合。")
    payload = {
        "identity": asdict(other),
        "profile": asdict(profile),
        "price": asdict(company.price) if company.price else None,
        "price_source": asdict(company.source_metadata),
        "status": company.status.value,
        "explanations": (
            [asdict(item) for item in explain_company(profile.dossier)]
            if profile.dossier and identity.instrument_type == "股票"
            else []
        ),
    }
    return CombinedSnapshot(
        identity, canonical(asdict(holding)), canonical(payload), datetime.now(UTC).isoformat()
    )


@dataclass(frozen=True)
class ResearchWorkSession:
    snapshot: CombinedSnapshot
    question: str
    created_at: str
    # Non-null attempts use version 2; local-only version 1 remains byte-compatible.
    ai_attempt_json: str = "null"

    def __post_init__(self) -> None:
        _time(self.created_at)
        if not isinstance(self.question, str) or len(self.question) > 4000:
            raise WorkSessionError("研究問題最多 4000 字。")
        attempt = _decode(self.ai_attempt_json.encode("utf-8"))
        if attempt is not None:
            from stock_tool.research.ai_attempt import validate_attempt

            validate_attempt(attempt, self.snapshot)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": "stocktool.research-work-session",
            "version": 1 if json.loads(self.ai_attempt_json) is None else 2,
            "snapshot": self.snapshot.to_dict(),
            "question": self.question,
            "created_at": self.created_at,
            "ai_attempt": json.loads(self.ai_attempt_json),
        }

    @property
    def fingerprint(self) -> str:
        return digest(self.to_dict())

    @classmethod
    def from_dict(cls, value: Any) -> ResearchWorkSession:
        _keys(value, {"format", "version", "snapshot", "question", "created_at", "ai_attempt"})
        if (
            value["format"] != "stocktool.research-work-session"
            or type(value["version"]) is not int
            or value["version"] not in (1, 2)
        ):
            raise WorkSessionError("不支援的研究工作階段版本。")
        if (value["version"] == 1) != (value["ai_attempt"] is None):
            raise WorkSessionError("研究工作階段版本與 AI 紀錄不符。")
        return cls(
            CombinedSnapshot.from_dict(value["snapshot"]),
            value["question"],
            value["created_at"],
            canonical(value["ai_attempt"]),
        )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WorkSessionError("重複的保存欄位。")
        result[key] = value
    return result


def _decode(data: bytes) -> Any:
    if len(data) > MAX_BYTES:
        raise WorkSessionError("工作階段檔案超過安全讀取上限。")
    try:
        return json.loads(
            data,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _: (_ for _ in ()).throw(WorkSessionError("無效數值。")),
        )
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise WorkSessionError("研究工作階段損毀，已拒絕讀取。") from exc


class WorkSessionStore:
    """Append-only, self-contained sessions; never writes the legacy library."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def _path(self, key: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise WorkSessionError("無效工作階段識別碼。")
        if any(
            p.is_symlink()
            or (
                p.exists()
                and getattr(p.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            )
            for p in (self.directory, *self.directory.parents)
        ):
            raise WorkSessionError("工作階段目錄不能是連結。")
        path = self.directory / (key + ".json")
        if path.is_symlink():
            raise WorkSessionError("工作階段不能是連結。")
        return path

    def save(self, session: ResearchWorkSession) -> str:
        session = ResearchWorkSession.from_dict(session.to_dict())
        data = canonical(session.to_dict()).encode("utf-8")
        if len(data) > MAX_BYTES:
            raise WorkSessionError("完整證據超過保存上限；未裁短保存。")
        key = session.fingerprint
        path = self._path(key)
        self.directory.mkdir(parents=True, exist_ok=True)
        if path.exists():
            self.load(key)
            return key
        # Exclusive creation prevents replacing any existing research version.
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
        return key

    def load(self, key: str) -> ResearchWorkSession:
        path = self._path(key)
        if path.stat().st_size > MAX_BYTES:
            raise WorkSessionError("工作階段檔案過大。")
        payload = _decode(path.read_bytes())
        session = ResearchWorkSession.from_dict(payload)
        if session.fingerprint != key:
            raise WorkSessionError("工作階段雜湊不符，已拒絕讀取。")
        return session

    def keys(self) -> tuple[str, ...]:
        self._path("0" * 64)
        return tuple(sorted(path.stem for path in self.directory.glob("*.json")))

    def backup_bytes(self) -> bytes:
        sessions = {key: self.load(key).to_dict() for key in self.keys()}
        payload = {"format": "stocktool.work-session-backup", "version": 1, "sessions": sessions}
        data = canonical({"payload": payload, "fingerprint": digest(payload)}).encode("utf-8")
        if len(data) > MAX_BYTES:
            raise WorkSessionError("完整備份超過上限，未產生不完整備份。")
        return data

    def restore_bytes(self, data: bytes, *, append_only: bool = False) -> None:
        """Validate every dependency first; optional import never replaces versions."""
        envelope = _decode(data)
        _keys(envelope, {"payload", "fingerprint"})
        payload = envelope["payload"]
        _keys(payload, {"format", "version", "sessions"})
        if (
            payload["format"] != "stocktool.work-session-backup"
            or type(payload["version"]) is not int
            or payload["version"] != 1
        ):
            raise WorkSessionError("不支援的備份版本。")
        if digest(payload) != envelope["fingerprint"] or not isinstance(payload["sessions"], dict):
            raise WorkSessionError("備份完整性不符。")
        sessions = []
        for key, value in payload["sessions"].items():
            self._path(key)
            session = ResearchWorkSession.from_dict(value)
            if session.fingerprint != key:
                raise WorkSessionError("備份工作階段損毀。")
            sessions.append(session)
        if self.directory.exists() and not append_only:
            raise WorkSessionError("還原只允許全新目錄，不能覆寫既有研究。")
        # Check every collision before writing any additional version.
        for session in sessions:
            if self._path(session.fingerprint).exists():
                self.load(session.fingerprint)
        self.directory.mkdir(parents=True, exist_ok=append_only)
        for session in sessions:
            self.save(session)
