"""Provider-independent identity and missing-data domain models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class Market(str, Enum):
    """Canonical markets supported by the current product boundary."""

    TWSE = "TWSE"
    TPEX = "TPEX"
    US = "US"
    AUTO = "AUTO"
    CUSTOM = "CUSTOM"

    @classmethod
    def parse(cls, value: Market | str) -> Market:
        """Normalize a market enum, code, or current dashboard label."""

        if isinstance(value, cls):
            return value
        normalized = str(value).strip().upper()
        aliases = {
            "TW": cls.TWSE,
            "TSE": cls.TWSE,
            "TWSE": cls.TWSE,
            "台股上市 TWSE": cls.TWSE,
            "TPEX": cls.TPEX,
            "TWO": cls.TPEX,
            "OTC": cls.TPEX,
            "台股上櫃 TPEX": cls.TPEX,
            "US": cls.US,
            "美股 US": cls.US,
            "AUTO": cls.AUTO,
            "CUSTOM": cls.CUSTOM,
        }
        try:
            return aliases[normalized]
        except KeyError as exc:
            raise ValueError(f"不支援的市場：{value!r}") from exc


@dataclass(frozen=True, slots=True)
class Symbol:
    """Canonical provider-independent security identity."""

    code: str
    market: Market

    def __post_init__(self) -> None:
        normalized_code = str(self.code).strip().upper()
        if not normalized_code:
            raise ValueError("股票代號不可為空。")
        normalized_market = Market.parse(self.market)
        if normalized_code.endswith((".TW", ".TWO")):
            raise ValueError("Canonical Symbol.code 不可包含 provider 市場後綴。")
        object.__setattr__(self, "code", normalized_code)
        object.__setattr__(self, "market", normalized_market)

    @classmethod
    def parse(cls, value: str, *, market: Market | str) -> Symbol:
        """Create a canonical symbol and validate known Taiwan suffixes."""

        raw_code = str(value).strip().upper()
        if not raw_code:
            raise ValueError("股票代號不可為空。")

        selected_market = Market.parse(market)
        suffix_market: Market | None = None
        if raw_code.endswith(".TWO"):
            raw_code = raw_code.removesuffix(".TWO")
            suffix_market = Market.TPEX
        elif raw_code.endswith(".TW"):
            raw_code = raw_code.removesuffix(".TW")
            suffix_market = Market.TWSE

        if suffix_market is not None:
            if selected_market is Market.AUTO:
                selected_market = suffix_market
            elif selected_market is not suffix_market:
                raise ValueError(
                    "市場與代號後綴不一致：" f"market={selected_market.value}, symbol={value!r}。"
                )

        return cls(code=raw_code, market=selected_market)

    @property
    def canonical(self) -> str:
        """Return a stable market-qualified identity string."""

        return f"{self.market.value}:{self.code}"

    def to_dict(self) -> dict[str, str]:
        """Serialize the symbol without provider-specific suffixes."""

        return {"code": self.code, "market": self.market.value}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Symbol:
        """Deserialize a symbol from its stable dictionary form."""

        return cls(code=str(payload["code"]), market=Market.parse(payload["market"]))


class MissingDataState(str, Enum):
    """Explicit states used instead of ambiguous null-like values."""

    MISSING = "missing"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"
    STALE = "stale"

    @classmethod
    def parse(cls, value: MissingDataState | str) -> MissingDataState:
        """Parse a serialized missing-data state."""

        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            raise ValueError(f"不支援的 missing-data state：{value!r}") from exc


@dataclass(frozen=True, slots=True)
class MissingData:
    """Serializable explanation for one unavailable or unreliable field."""

    field: str
    state: MissingDataState
    reason: str

    def __post_init__(self) -> None:
        field = str(self.field).strip()
        reason = str(self.reason).strip()
        if not field:
            raise ValueError("MissingData.field 不可為空。")
        if not reason:
            raise ValueError("MissingData.reason 不可為空。")
        object.__setattr__(self, "field", field)
        object.__setattr__(self, "state", MissingDataState.parse(self.state))
        object.__setattr__(self, "reason", reason)

    def to_dict(self) -> dict[str, str]:
        """Serialize the missing-data state for reports or persistence."""

        return {
            "field": self.field,
            "state": self.state.value,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> MissingData:
        """Deserialize an explicit missing-data value."""

        return cls(
            field=str(payload["field"]),
            state=MissingDataState.parse(payload["state"]),
            reason=str(payload["reason"]),
        )
