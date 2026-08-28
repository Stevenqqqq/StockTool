"""Immutable, Decimal-based portfolio ledger and deterministic replay engine.

This module is intentionally independent of the legacy portfolio CSV, dashboard,
and market-price SQLite store. It records native-currency facts only; a caller
may later attach explicit market prices without inventing FX or missing prices.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Iterable, Mapping

import pandas as pd

from stock_tool.domain.models import Market, MissingData, MissingDataState, Symbol

SUPPORTED_CURRENCIES = frozenset({"TWD", "USD"})
CANONICAL_POSITION_MARKETS = frozenset({Market.TWSE, Market.TPEX, Market.US})
ZERO = Decimal("0")


class LedgerReplayError(ValueError):
    """Raised when an immutable ledger cannot be safely replayed."""


class LedgerEntryType(str, Enum):
    """Supported native-currency ledger event classes."""

    OPENING_POSITION = "opening_position"
    BUY = "buy"
    SELL = "sell"
    CASH_DEPOSIT = "cash_deposit"
    CASH_WITHDRAWAL = "cash_withdrawal"
    DIVIDEND = "dividend"
    FEE = "fee"
    TAX = "tax"
    FX_CONVERSION = "fx_conversion"

    @classmethod
    def parse(cls, value: LedgerEntryType | str) -> LedgerEntryType:
        """Parse a supported entry type without silently accepting unknown events."""

        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            raise ValueError(f"unsupported ledger entry type: {value!r}") from exc


@dataclass(frozen=True, slots=True)
class _EntryFieldPolicy:
    """Define which accounting fields are meaningful for one ledger event."""

    allows_symbol: bool = False
    allows_quantity: bool = False
    allows_unit_price: bool = False
    allows_native_cash_delta: bool = False
    allows_fee: bool = False
    allows_tax: bool = False
    allows_target_currency: bool = False
    allows_target_cash_delta: bool = False
    allows_fx_rate: bool = False


_ENTRY_FIELD_POLICIES: Mapping[LedgerEntryType, _EntryFieldPolicy] = {
    LedgerEntryType.OPENING_POSITION: _EntryFieldPolicy(
        allows_symbol=True,
        allows_quantity=True,
        allows_unit_price=True,
    ),
    LedgerEntryType.BUY: _EntryFieldPolicy(
        allows_symbol=True,
        allows_quantity=True,
        allows_unit_price=True,
        allows_native_cash_delta=True,
        allows_fee=True,
        allows_tax=True,
    ),
    LedgerEntryType.SELL: _EntryFieldPolicy(
        allows_symbol=True,
        allows_quantity=True,
        allows_unit_price=True,
        allows_native_cash_delta=True,
        allows_fee=True,
        allows_tax=True,
    ),
    LedgerEntryType.CASH_DEPOSIT: _EntryFieldPolicy(allows_native_cash_delta=True),
    LedgerEntryType.CASH_WITHDRAWAL: _EntryFieldPolicy(allows_native_cash_delta=True),
    LedgerEntryType.DIVIDEND: _EntryFieldPolicy(
        allows_symbol=True,
        allows_native_cash_delta=True,
        allows_tax=True,
    ),
    LedgerEntryType.FEE: _EntryFieldPolicy(
        allows_native_cash_delta=True,
        allows_fee=True,
    ),
    LedgerEntryType.TAX: _EntryFieldPolicy(
        allows_native_cash_delta=True,
        allows_tax=True,
    ),
    LedgerEntryType.FX_CONVERSION: _EntryFieldPolicy(
        allows_native_cash_delta=True,
        allows_fee=True,
        allows_target_currency=True,
        allows_target_cash_delta=True,
        allows_fx_rate=True,
    ),
}


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One immutable native-currency accounting fact.

    ``native_cash_delta`` is explicit for cash flows, dividends, and FX source
    legs. Buy and sell entries derive their cash delta from quantity, price,
    fee, and tax, preventing contradictory cash accounting.
    """

    entry_id: str
    entry_type: LedgerEntryType
    effective_at: datetime
    sequence: int
    symbol: Symbol | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    currency: str = ""
    native_cash_delta: Decimal | None = None
    fee: Decimal = ZERO
    tax: Decimal = ZERO
    target_currency: str | None = None
    target_cash_delta: Decimal | None = None
    fx_rate: Decimal | None = None
    source: str = "manual"
    note: str = ""
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        entry_id = str(self.entry_id).strip()
        if not entry_id:
            raise ValueError("ledger entry_id is required")
        if int(self.sequence) < 0:
            raise ValueError("ledger sequence must be non-negative")
        if not isinstance(self.effective_at, datetime):
            raise TypeError("ledger effective_at must be a datetime")
        timestamp = self.effective_at
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        else:
            timestamp = timestamp.astimezone(UTC)
        entry_type = LedgerEntryType.parse(self.entry_type)
        symbol = self.symbol
        if symbol is not None and symbol.market not in CANONICAL_POSITION_MARKETS:
            raise ValueError("ledger positions require a canonical market-qualified symbol")
        quantity = _decimal_or_none(self.quantity, "quantity")
        unit_price = _decimal_or_none(self.unit_price, "unit_price")
        cash_delta = _decimal_or_none(self.native_cash_delta, "native_cash_delta")
        fee = _decimal(self.fee, "fee")
        tax = _decimal(self.tax, "tax")
        target_delta = _decimal_or_none(self.target_cash_delta, "target_cash_delta")
        fx_rate = _decimal_or_none(self.fx_rate, "fx_rate")
        if fee < ZERO or tax < ZERO:
            raise ValueError("ledger fee and tax must be non-negative")
        if quantity is not None and quantity <= ZERO:
            raise ValueError("ledger quantity must be positive")
        if unit_price is not None and unit_price < ZERO:
            raise ValueError("ledger unit_price must be non-negative")
        if fx_rate is not None and fx_rate <= ZERO:
            raise ValueError("ledger fx_rate must be positive")
        target_currency = _optional_text(self.target_currency)
        _validate_entry_field_policy(
            entry_type=entry_type,
            symbol=symbol,
            quantity=quantity,
            unit_price=unit_price,
            native_cash_delta=cash_delta,
            fee=fee,
            tax=tax,
            target_currency=target_currency,
            target_cash_delta=target_delta,
            fx_rate=fx_rate,
        )
        if entry_type in {
            LedgerEntryType.OPENING_POSITION,
            LedgerEntryType.BUY,
            LedgerEntryType.SELL,
        }:
            if symbol is None or quantity is None:
                raise ValueError(f"{entry_type.value} requires symbol and quantity")
        if entry_type in {LedgerEntryType.BUY, LedgerEntryType.SELL} and unit_price is None:
            raise ValueError(f"{entry_type.value} requires unit_price")
        if entry_type is LedgerEntryType.BUY and cash_delta is not None:
            assert quantity is not None and unit_price is not None
            expected_cash_delta = -(quantity * unit_price + fee + tax)
            if cash_delta != expected_cash_delta:
                raise ValueError("buy native_cash_delta must match quantity, price, fee, and tax")
        if entry_type is LedgerEntryType.SELL and cash_delta is not None:
            assert quantity is not None and unit_price is not None
            expected_cash_delta = quantity * unit_price - fee - tax
            if cash_delta != expected_cash_delta:
                raise ValueError("sell native_cash_delta must match quantity, price, fee, and tax")
        if entry_type is LedgerEntryType.FX_CONVERSION:
            if target_currency is None:
                raise ValueError("FX conversion requires a valid target_currency")
            if cash_delta is None or cash_delta >= ZERO or target_delta is None:
                raise ValueError(
                    "FX conversion requires negative source and positive target cash legs"
                )
            if target_delta <= ZERO or fx_rate is None:
                raise ValueError("FX conversion requires a positive target amount and fx_rate")
            source_principal = -cash_delta - fee
            if source_principal <= ZERO or source_principal * fx_rate != target_delta:
                raise ValueError(
                    "fx_conversion native_cash_delta must match source principal, fee, and rate"
                )
        if entry_type is LedgerEntryType.CASH_DEPOSIT and (
            cash_delta is None or cash_delta <= ZERO
        ):
            raise ValueError("cash_deposit requires a positive native_cash_delta")
        if entry_type is LedgerEntryType.CASH_WITHDRAWAL and (
            cash_delta is None or cash_delta >= ZERO
        ):
            raise ValueError("cash_withdrawal requires a negative native_cash_delta")
        if entry_type is LedgerEntryType.DIVIDEND and (cash_delta is None or cash_delta < ZERO):
            raise ValueError("dividend requires a non-negative native_cash_delta")
        if entry_type is LedgerEntryType.FEE:
            _validate_explicit_debit("fee", fee, cash_delta)
        if entry_type is LedgerEntryType.TAX:
            _validate_explicit_debit("tax", tax, cash_delta)
        currency = _currency_or_empty(self.currency)
        target_currency = _currency_or_empty(target_currency) if target_currency else None
        source = str(self.source).strip() or "unknown"
        metadata = tuple(sorted((str(key), str(value)) for key, value in self.metadata))
        object.__setattr__(self, "entry_id", entry_id)
        object.__setattr__(self, "entry_type", entry_type)
        object.__setattr__(self, "effective_at", timestamp)
        object.__setattr__(self, "sequence", int(self.sequence))
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "unit_price", unit_price)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "native_cash_delta", cash_delta)
        object.__setattr__(self, "fee", fee)
        object.__setattr__(self, "tax", tax)
        object.__setattr__(self, "target_currency", target_currency)
        object.__setattr__(self, "target_cash_delta", target_delta)
        object.__setattr__(self, "fx_rate", fx_rate)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "note", str(self.note))
        object.__setattr__(self, "metadata", metadata)

    def to_dict(self) -> dict[str, Any]:
        """Serialize Decimal values as exact strings for deterministic replay."""

        return {
            "entry_id": self.entry_id,
            "entry_type": self.entry_type.value,
            "effective_at": self.effective_at.isoformat(),
            "sequence": self.sequence,
            "symbol": self.symbol.to_dict() if self.symbol is not None else None,
            "quantity": _decimal_text(self.quantity),
            "unit_price": _decimal_text(self.unit_price),
            "currency": self.currency,
            "native_cash_delta": _decimal_text(self.native_cash_delta),
            "fee": _decimal_text(self.fee),
            "tax": _decimal_text(self.tax),
            "target_currency": self.target_currency,
            "target_cash_delta": _decimal_text(self.target_cash_delta),
            "fx_rate": _decimal_text(self.fx_rate),
            "source": self.source,
            "note": self.note,
            "metadata": list(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> LedgerEntry:
        """Deserialize one exact ledger event from its public representation."""

        raw_symbol = payload.get("symbol")
        return cls(
            entry_id=str(payload["entry_id"]),
            entry_type=LedgerEntryType.parse(str(payload["entry_type"])),
            effective_at=_parse_datetime(payload["effective_at"]),
            sequence=int(payload["sequence"]),
            symbol=Symbol.from_dict(raw_symbol) if isinstance(raw_symbol, Mapping) else None,
            quantity=_decimal_or_none(payload.get("quantity"), "quantity"),
            unit_price=_decimal_or_none(payload.get("unit_price"), "unit_price"),
            currency=str(payload.get("currency", "")),
            native_cash_delta=_decimal_or_none(
                payload.get("native_cash_delta"), "native_cash_delta"
            ),
            fee=_decimal(payload.get("fee", "0"), "fee"),
            tax=_decimal(payload.get("tax", "0"), "tax"),
            target_currency=_optional_text(payload.get("target_currency")),
            target_cash_delta=_decimal_or_none(
                payload.get("target_cash_delta"), "target_cash_delta"
            ),
            fx_rate=_decimal_or_none(payload.get("fx_rate"), "fx_rate"),
            source=str(payload.get("source", "unknown")),
            note=str(payload.get("note", "")),
            metadata=tuple(tuple(item) for item in payload.get("metadata", ())),
        )


@dataclass(frozen=True, slots=True)
class CurrencyAmount:
    """One exact amount in a native currency."""

    currency: str
    amount: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "currency", _currency_or_empty(self.currency))
        object.__setattr__(self, "amount", _decimal(self.amount, "amount"))


@dataclass(frozen=True, slots=True)
class LedgerPosition:
    """A replayed average-cost position with optional native price evidence."""

    symbol: Symbol
    currency: str
    quantity: Decimal
    average_cost: Decimal
    cost_basis: Decimal
    market_price: Decimal | None = None
    market_value: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    weight: Decimal | None = None

    def __post_init__(self) -> None:
        if self.quantity <= ZERO:
            raise ValueError("ledger position quantity must be positive")
        object.__setattr__(self, "currency", _currency_or_empty(self.currency))
        object.__setattr__(self, "quantity", _decimal(self.quantity, "quantity"))
        object.__setattr__(self, "average_cost", _decimal(self.average_cost, "average_cost"))
        object.__setattr__(self, "cost_basis", _decimal(self.cost_basis, "cost_basis"))


@dataclass(frozen=True, slots=True)
class LedgerSnapshot:
    """Immutable result of replaying an ordered portfolio ledger."""

    positions: tuple[LedgerPosition, ...]
    cash_balances: tuple[CurrencyAmount, ...]
    realized_pnl_by_currency: tuple[CurrencyAmount, ...]
    dividend_income_by_currency: tuple[CurrencyAmount, ...]
    fees_paid_by_currency: tuple[CurrencyAmount, ...]
    taxes_paid_by_currency: tuple[CurrencyAmount, ...]
    unavailable_realized_currencies: tuple[str, ...] = ()
    missing_data: tuple[MissingData, ...] = ()
    applied_entry_ids: tuple[str, ...] = ()

    @property
    def position_count(self) -> int:
        """Return the count of positive, market-qualified replayed positions."""

        return len(self.positions)

    def position(self, symbol: Symbol) -> LedgerPosition | None:
        """Return one position only by its full market-qualified identity."""

        return next((item for item in self.positions if item.symbol == symbol), None)

    def cash_balance(self, currency: str) -> Decimal:
        """Return native cash, or zero when no event has touched that currency."""

        return _amount_lookup(self.cash_balances).get(_currency_or_empty(currency), ZERO)

    def realized_pnl(self, currency: str) -> Decimal | None:
        """Return realized P/L, or unavailable after a legacy opening import."""

        normalized = _currency_or_empty(currency)
        if normalized in self.unavailable_realized_currencies:
            return None
        return _amount_lookup(self.realized_pnl_by_currency).get(normalized, ZERO)

    def dividend_income(self, currency: str) -> Decimal:
        """Return gross dividend income before the separately recorded tax."""

        return _amount_lookup(self.dividend_income_by_currency).get(
            _currency_or_empty(currency), ZERO
        )

    def fees_paid(self, currency: str) -> Decimal:
        """Return cumulative transaction and explicit fee entries."""

        return _amount_lookup(self.fees_paid_by_currency).get(_currency_or_empty(currency), ZERO)

    def taxes_paid(self, currency: str) -> Decimal:
        """Return cumulative transaction, dividend, and explicit tax entries."""

        return _amount_lookup(self.taxes_paid_by_currency).get(_currency_or_empty(currency), ZERO)

    def with_market_prices(self, prices: Mapping[Symbol, Decimal]) -> LedgerSnapshot:
        """Attach explicit native prices without inventing missing valuations or FX."""

        normalized = {symbol: _decimal(price, "market price") for symbol, price in prices.items()}
        positions: list[LedgerPosition] = []
        missing = list(self.missing_data)
        for position in self.positions:
            price = normalized.get(position.symbol)
            if price is None or price <= ZERO:
                reason = (
                    f"No explicit native market price is available for {position.symbol.canonical}."
                    if price is None
                    else f"Non-positive native market price is unavailable for {position.symbol.canonical}."
                )
                missing.append(
                    MissingData(
                        field="latest_price",
                        state=MissingDataState.MISSING,
                        reason=reason,
                    )
                )
                positions.append(
                    replace(
                        position,
                        market_price=None,
                        market_value=None,
                        unrealized_pnl=None,
                        weight=None,
                    )
                )
                continue
            value = position.quantity * price
            positions.append(
                replace(
                    position,
                    market_price=price,
                    market_value=value,
                    unrealized_pnl=value - position.cost_basis,
                    weight=None,
                )
            )
        currencies = {position.currency for position in positions}
        complete = bool(positions) and all(
            position.market_value is not None for position in positions
        )
        if complete and len(currencies) == 1:
            total = sum((position.market_value or ZERO for position in positions), ZERO)
            if total > ZERO:
                positions = [
                    replace(position, weight=(position.market_value or ZERO) / total)
                    for position in positions
                ]
        elif complete and len(currencies) > 1:
            missing.append(
                MissingData(
                    field="fx_rate",
                    state=MissingDataState.MISSING,
                    reason=(
                        "Cross-currency conversion evidence is missing; consolidated weights are "
                        "unavailable."
                    ),
                )
            )
        return replace(self, positions=tuple(positions), missing_data=_unique_missing(missing))

    def to_dict(self) -> dict[str, Any]:
        """Serialize the replay result with exact Decimal strings."""

        return {
            "positions": [_position_to_dict(item) for item in self.positions],
            "cash_balances": _amounts_to_dict(self.cash_balances),
            "realized_pnl_by_currency": _amounts_to_dict(self.realized_pnl_by_currency),
            "dividend_income_by_currency": _amounts_to_dict(self.dividend_income_by_currency),
            "fees_paid_by_currency": _amounts_to_dict(self.fees_paid_by_currency),
            "taxes_paid_by_currency": _amounts_to_dict(self.taxes_paid_by_currency),
            "unavailable_realized_currencies": list(self.unavailable_realized_currencies),
            "missing_data": [item.to_dict() for item in self.missing_data],
            "applied_entry_ids": list(self.applied_entry_ids),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> LedgerSnapshot:
        """Deserialize an exact replay snapshot without recomputing accounting."""

        return cls(
            positions=tuple(_position_from_dict(item) for item in payload.get("positions", ())),
            cash_balances=_amounts_from_dict(payload.get("cash_balances", {})),
            realized_pnl_by_currency=_amounts_from_dict(
                payload.get("realized_pnl_by_currency", {})
            ),
            dividend_income_by_currency=_amounts_from_dict(
                payload.get("dividend_income_by_currency", {})
            ),
            fees_paid_by_currency=_amounts_from_dict(payload.get("fees_paid_by_currency", {})),
            taxes_paid_by_currency=_amounts_from_dict(payload.get("taxes_paid_by_currency", {})),
            unavailable_realized_currencies=tuple(
                sorted(str(item) for item in payload.get("unavailable_realized_currencies", ()))
            ),
            missing_data=tuple(
                MissingData.from_dict(item) for item in payload.get("missing_data", ())
            ),
            applied_entry_ids=tuple(str(item) for item in payload.get("applied_entry_ids", ())),
        )


@dataclass(frozen=True, slots=True)
class LedgerImportResult:
    """Read-only legacy CSV conversion into explicit opening positions."""

    entries: tuple[LedgerEntry, ...]
    warnings: tuple[str, ...] = ()
    missing_data: tuple[MissingData, ...] = ()


def replay_ledger(entries: Iterable[LedgerEntry]) -> LedgerSnapshot:
    """Replay immutable events in timestamp, sequence, then entry-ID order."""

    ordered = sorted(
        tuple(entries), key=lambda item: (item.effective_at, item.sequence, item.entry_id)
    )
    seen: set[str] = set()
    state = _ReplayState()
    for entry in ordered:
        if entry.entry_id in seen:
            raise LedgerReplayError(f"duplicate entry_id: {entry.entry_id}")
        seen.add(entry.entry_id)
        state.apply(entry)
    return state.snapshot(tuple(item.entry_id for item in ordered))


def import_legacy_opening_positions(frame: pd.DataFrame) -> LedgerImportResult:
    """Convert a legacy aggregate portfolio frame to deterministic opening events.

    The input is never changed. Missing identity, currency, quantity, or cost
    evidence produces structured MissingData rather than inferred history.
    """

    if frame is None or frame.empty:
        return LedgerImportResult(())
    work = frame.copy(deep=True)
    entries: list[LedgerEntry] = []
    missing: list[MissingData] = []
    warnings: list[str] = []
    rows = work.to_dict("records")
    for index, row in enumerate(rows):
        symbol_raw = str(row.get("symbol", "")).strip()
        market_raw = str(row.get("market", "")).strip()
        currency_raw = str(row.get("currency", "")).strip()
        quantity = _try_decimal(row.get("quantity"))
        average_cost = _try_decimal(row.get("average_cost"))
        try:
            market = Market.parse(market_raw)
            symbol = Symbol.parse(symbol_raw, market=market)
            if market not in CANONICAL_POSITION_MARKETS:
                raise ValueError("unresolved market")
        except ValueError:
            missing.append(
                MissingData(
                    field="portfolio.market",
                    state=MissingDataState.UNKNOWN,
                    reason=f"Legacy row {index} has no canonical market-qualified symbol.",
                )
            )
            continue
        if not currency_raw:
            missing.append(
                MissingData(
                    field="portfolio.currency",
                    state=MissingDataState.MISSING,
                    reason=f"Legacy row {index} has no native currency evidence.",
                )
            )
            continue
        try:
            currency = _currency_or_empty(currency_raw)
        except ValueError:
            missing.append(
                MissingData(
                    field="portfolio.currency",
                    state=MissingDataState.UNKNOWN,
                    reason=f"Legacy row {index} has unsupported currency evidence.",
                )
            )
            continue
        if quantity is None or quantity <= ZERO:
            missing.append(
                MissingData(
                    field="portfolio.quantity",
                    state=MissingDataState.MISSING,
                    reason=f"Legacy row {index} has no positive quantity.",
                )
            )
            continue
        if average_cost is None or average_cost < ZERO:
            missing.append(
                MissingData(
                    field="portfolio.average_cost",
                    state=MissingDataState.MISSING,
                    reason=f"Legacy row {index} has no non-negative average cost.",
                )
            )
            continue
        entries.append(
            LedgerEntry(
                entry_id=f"legacy-opening:{symbol.market.value}:{symbol.code}",
                entry_type=LedgerEntryType.OPENING_POSITION,
                effective_at=datetime(1970, 1, 1, tzinfo=UTC),
                sequence=index,
                symbol=symbol,
                quantity=quantity,
                unit_price=average_cost,
                currency=currency,
                source="legacy_portfolio_csv",
                note=str(row.get("note", "")),
            )
        )
    entries.sort(
        key=lambda item: (
            item.symbol.market.value if item.symbol else "",
            item.symbol.code if item.symbol else "",
        )
    )
    if missing:
        warnings.append(
            "Some legacy rows could not become opening positions because source evidence is incomplete."
        )
    return LedgerImportResult(tuple(entries), tuple(warnings), _unique_missing(missing))


class _ReplayState:
    """Mutable internal state that is discarded after one deterministic replay."""

    def __init__(self) -> None:
        self.positions: dict[Symbol, LedgerPosition] = {}
        self.cash: dict[str, Decimal] = {}
        self.realized: dict[str, Decimal] = {}
        self.dividends: dict[str, Decimal] = {}
        self.fees: dict[str, Decimal] = {}
        self.taxes: dict[str, Decimal] = {}
        self.unavailable_realized: set[str] = set()
        self.missing: list[MissingData] = []

    def apply(self, entry: LedgerEntry) -> None:
        """Apply one already-validated event or fail without emitting a snapshot."""

        if entry.entry_type is LedgerEntryType.OPENING_POSITION:
            self._opening(entry)
        elif entry.entry_type is LedgerEntryType.BUY:
            self._buy(entry)
        elif entry.entry_type is LedgerEntryType.SELL:
            self._sell(entry)
        elif entry.entry_type is LedgerEntryType.DIVIDEND:
            self._dividend(entry)
        elif entry.entry_type is LedgerEntryType.CASH_DEPOSIT:
            self._cash_flow(entry, require_nonnegative=True)
        elif entry.entry_type is LedgerEntryType.CASH_WITHDRAWAL:
            self._cash_flow(entry, require_nonnegative=False)
        elif entry.entry_type is LedgerEntryType.FEE:
            self._fee(entry)
        elif entry.entry_type is LedgerEntryType.TAX:
            self._tax(entry)
        elif entry.entry_type is LedgerEntryType.FX_CONVERSION:
            self._fx(entry)
        else:  # Defensive branch for future enum extensions.
            raise LedgerReplayError(f"unsupported ledger entry type: {entry.entry_type.value}")

    def _opening(self, entry: LedgerEntry) -> None:
        if not entry.currency:
            self._missing("ledger.currency", "Opening position has no native currency.")
            return
        if entry.unit_price is None:
            self._missing("ledger.unit_price", "Opening position has no cost evidence.")
            return
        assert entry.symbol is not None and entry.quantity is not None
        self.unavailable_realized.add(entry.currency)
        self._add_position(entry.symbol, entry.currency, entry.quantity, entry.unit_price)

    def _buy(self, entry: LedgerEntry) -> None:
        currency = self._required_currency(entry)
        assert (
            entry.symbol is not None and entry.quantity is not None and entry.unit_price is not None
        )
        cost = entry.quantity * entry.unit_price + entry.fee + entry.tax
        self._change_cash(currency, -cost, require_nonnegative=True)
        self._add_position(entry.symbol, currency, entry.quantity, cost / entry.quantity)
        self.fees[currency] = self.fees.get(currency, ZERO) + entry.fee
        self.taxes[currency] = self.taxes.get(currency, ZERO) + entry.tax

    def _sell(self, entry: LedgerEntry) -> None:
        currency = self._required_currency(entry)
        assert (
            entry.symbol is not None and entry.quantity is not None and entry.unit_price is not None
        )
        position = self.positions.get(entry.symbol)
        if position is None or position.quantity < entry.quantity:
            raise LedgerReplayError(f"insufficient position for sell: {entry.symbol.canonical}")
        if position.currency != currency:
            raise LedgerReplayError("sell currency differs from the existing position currency")
        removed_cost = position.average_cost * entry.quantity
        net_proceeds = entry.quantity * entry.unit_price - entry.fee - entry.tax
        self._change_cash(currency, net_proceeds, require_nonnegative=False)
        self.realized[currency] = self.realized.get(currency, ZERO) + net_proceeds - removed_cost
        self.fees[currency] = self.fees.get(currency, ZERO) + entry.fee
        self.taxes[currency] = self.taxes.get(currency, ZERO) + entry.tax
        remainder = position.quantity - entry.quantity
        if remainder == ZERO:
            del self.positions[entry.symbol]
        else:
            self.positions[entry.symbol] = replace(
                position,
                quantity=remainder,
                cost_basis=position.average_cost * remainder,
                market_price=None,
                market_value=None,
                unrealized_pnl=None,
                weight=None,
            )

    def _dividend(self, entry: LedgerEntry) -> None:
        currency = self._required_currency(entry)
        assert entry.native_cash_delta is not None
        self._change_cash(currency, entry.native_cash_delta, require_nonnegative=False)
        self.dividends[currency] = (
            self.dividends.get(currency, ZERO) + entry.native_cash_delta + entry.tax
        )
        self.taxes[currency] = self.taxes.get(currency, ZERO) + entry.tax

    def _cash_flow(self, entry: LedgerEntry, *, require_nonnegative: bool) -> None:
        currency = self._required_currency(entry)
        assert entry.native_cash_delta is not None
        self._change_cash(
            currency, entry.native_cash_delta, require_nonnegative=not require_nonnegative
        )

    def _fee(self, entry: LedgerEntry) -> None:
        currency = self._required_currency(entry)
        amount = entry.native_cash_delta if entry.native_cash_delta is not None else -entry.fee
        if amount >= ZERO:
            raise LedgerReplayError("fee entry must reduce cash")
        self._change_cash(currency, amount, require_nonnegative=True)
        self.fees[currency] = self.fees.get(currency, ZERO) + (-amount)

    def _tax(self, entry: LedgerEntry) -> None:
        currency = self._required_currency(entry)
        amount = entry.native_cash_delta if entry.native_cash_delta is not None else -entry.tax
        if amount >= ZERO:
            raise LedgerReplayError("tax entry must reduce cash")
        self._change_cash(currency, amount, require_nonnegative=True)
        self.taxes[currency] = self.taxes.get(currency, ZERO) + (-amount)

    def _fx(self, entry: LedgerEntry) -> None:
        source = self._required_currency(entry)
        assert entry.native_cash_delta is not None
        assert (
            entry.target_currency is not None
            and entry.target_cash_delta is not None
            and entry.fx_rate is not None
        )
        if entry.target_currency == source:
            raise LedgerReplayError("FX conversion requires distinct currencies")
        source_principal = -entry.native_cash_delta - entry.fee
        expected = source_principal * entry.fx_rate
        if source_principal <= ZERO or expected != entry.target_cash_delta:
            raise LedgerReplayError(
                "FX conversion source principal, fee, and target cash do not match its explicit rate"
            )
        self._change_cash(source, entry.native_cash_delta, require_nonnegative=True)
        self._change_cash(entry.target_currency, entry.target_cash_delta, require_nonnegative=False)
        self.fees[source] = self.fees.get(source, ZERO) + entry.fee

    def _add_position(
        self, symbol: Symbol, currency: str, quantity: Decimal, per_share_cost: Decimal
    ) -> None:
        current = self.positions.get(symbol)
        if current is None:
            self.positions[symbol] = LedgerPosition(
                symbol=symbol,
                currency=currency,
                quantity=quantity,
                average_cost=per_share_cost,
                cost_basis=quantity * per_share_cost,
            )
            return
        if current.currency != currency:
            raise LedgerReplayError(
                "position currency changed without an explicit conversion policy"
            )
        total_quantity = current.quantity + quantity
        total_cost = current.cost_basis + quantity * per_share_cost
        self.positions[symbol] = LedgerPosition(
            symbol=symbol,
            currency=currency,
            quantity=total_quantity,
            average_cost=total_cost / total_quantity,
            cost_basis=total_cost,
        )

    def _change_cash(self, currency: str, delta: Decimal, *, require_nonnegative: bool) -> None:
        updated = self.cash.get(currency, ZERO) + delta
        if require_nonnegative and updated < ZERO:
            raise LedgerReplayError(f"insufficient cash in {currency}")
        self.cash[currency] = updated

    def _required_currency(self, entry: LedgerEntry) -> str:
        if not entry.currency:
            raise LedgerReplayError(f"{entry.entry_type.value} requires native currency")
        return entry.currency

    def _missing(self, field: str, reason: str) -> None:
        self.missing.append(MissingData(field=field, state=MissingDataState.MISSING, reason=reason))

    def snapshot(self, entry_ids: tuple[str, ...]) -> LedgerSnapshot:
        """Freeze internal balances into a stable public replay result."""

        return LedgerSnapshot(
            positions=tuple(
                sorted(self.positions.values(), key=lambda item: item.symbol.canonical)
            ),
            cash_balances=_amounts(self.cash),
            realized_pnl_by_currency=_amounts(self.realized),
            dividend_income_by_currency=_amounts(self.dividends),
            fees_paid_by_currency=_amounts(self.fees),
            taxes_paid_by_currency=_amounts(self.taxes),
            unavailable_realized_currencies=tuple(sorted(self.unavailable_realized)),
            missing_data=_unique_missing(self.missing),
            applied_entry_ids=entry_ids,
        )


def _validate_entry_field_policy(
    *,
    entry_type: LedgerEntryType,
    symbol: Symbol | None,
    quantity: Decimal | None,
    unit_price: Decimal | None,
    native_cash_delta: Decimal | None,
    fee: Decimal,
    tax: Decimal,
    target_currency: str | None,
    target_cash_delta: Decimal | None,
    fx_rate: Decimal | None,
) -> None:
    """Reject non-applicable accounting fields before replay can ignore them."""

    policy = _ENTRY_FIELD_POLICIES[entry_type]
    _reject_disallowed(entry_type, "symbol", symbol, policy.allows_symbol)
    _reject_disallowed(entry_type, "quantity", quantity, policy.allows_quantity)
    _reject_disallowed(entry_type, "unit_price", unit_price, policy.allows_unit_price)
    _reject_disallowed(
        entry_type,
        "native_cash_delta",
        native_cash_delta,
        policy.allows_native_cash_delta,
    )
    _reject_disallowed(entry_type, "fee", fee, policy.allows_fee, zero_is_empty=True)
    _reject_disallowed(entry_type, "tax", tax, policy.allows_tax, zero_is_empty=True)
    _reject_disallowed(
        entry_type,
        "target_currency",
        target_currency,
        policy.allows_target_currency,
    )
    _reject_disallowed(
        entry_type,
        "target_cash_delta",
        target_cash_delta,
        policy.allows_target_cash_delta,
    )
    _reject_disallowed(entry_type, "fx_rate", fx_rate, policy.allows_fx_rate)


def _reject_disallowed(
    entry_type: LedgerEntryType,
    field: str,
    value: object,
    allowed: bool,
    *,
    zero_is_empty: bool = False,
) -> None:
    """Raise a stable validation error only for a meaningful disallowed value."""

    if allowed or value is None:
        return
    if zero_is_empty and value == ZERO:
        return
    label = "FX conversion" if entry_type is LedgerEntryType.FX_CONVERSION else entry_type.value
    raise ValueError(f"{label} does not allow {field}")


def _validate_explicit_debit(
    entry_name: str, declared_amount: Decimal, cash_delta: Decimal | None
) -> None:
    """Validate a standalone fee or tax cash reduction without inference."""

    if declared_amount == ZERO and cash_delta is None:
        raise ValueError(
            f"{entry_name} requires a negative native_cash_delta or non-zero {entry_name}"
        )
    if cash_delta is not None:
        if cash_delta >= ZERO:
            raise ValueError(f"{entry_name} native_cash_delta must reduce cash")
        if declared_amount != ZERO and cash_delta != -declared_amount:
            raise ValueError(f"{entry_name} must match native_cash_delta")


def _decimal(value: object, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"ledger {field} must be decimal-compatible") from exc
    if not result.is_finite():
        raise ValueError(f"ledger {field} must be finite")
    return result


def _decimal_or_none(value: object, field: str) -> Decimal | None:
    return None if value is None or str(value).strip() == "" else _decimal(value, field)


def _try_decimal(value: object) -> Decimal | None:
    try:
        return _decimal_or_none(value, "legacy value")
    except ValueError:
        return None


def _currency_or_empty(value: object) -> str:
    currency = str(value or "").strip().upper()
    if not currency:
        return ""
    if currency not in SUPPORTED_CURRENCIES:
        raise ValueError(f"unsupported native currency: {currency}")
    return currency


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _parse_datetime(value: object) -> datetime:
    timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return timestamp.replace(tzinfo=UTC) if timestamp.tzinfo is None else timestamp.astimezone(UTC)


def _amounts(values: Mapping[str, Decimal]) -> tuple[CurrencyAmount, ...]:
    return tuple(CurrencyAmount(currency, amount) for currency, amount in sorted(values.items()))


def _amount_lookup(values: tuple[CurrencyAmount, ...]) -> dict[str, Decimal]:
    return {item.currency: item.amount for item in values}


def _amounts_to_dict(values: tuple[CurrencyAmount, ...]) -> dict[str, str]:
    return {item.currency: format(item.amount, "f") for item in values}


def _amounts_from_dict(payload: object) -> tuple[CurrencyAmount, ...]:
    if not isinstance(payload, Mapping):
        raise ValueError("ledger currency amounts must be a mapping")
    return tuple(
        CurrencyAmount(str(currency), _decimal(amount, "amount"))
        for currency, amount in sorted(payload.items())
    )


def _position_to_dict(position: LedgerPosition) -> dict[str, Any]:
    return {
        "symbol": position.symbol.to_dict(),
        "currency": position.currency,
        "quantity": _decimal_text(position.quantity),
        "average_cost": _decimal_text(position.average_cost),
        "cost_basis": _decimal_text(position.cost_basis),
        "market_price": _decimal_text(position.market_price),
        "market_value": _decimal_text(position.market_value),
        "unrealized_pnl": _decimal_text(position.unrealized_pnl),
        "weight": _decimal_text(position.weight),
    }


def _position_from_dict(payload: Mapping[str, Any]) -> LedgerPosition:
    return LedgerPosition(
        symbol=Symbol.from_dict(payload["symbol"]),
        currency=str(payload["currency"]),
        quantity=_decimal(payload["quantity"], "quantity"),
        average_cost=_decimal(payload["average_cost"], "average_cost"),
        cost_basis=_decimal(payload["cost_basis"], "cost_basis"),
        market_price=_decimal_or_none(payload.get("market_price"), "market_price"),
        market_value=_decimal_or_none(payload.get("market_value"), "market_value"),
        unrealized_pnl=_decimal_or_none(payload.get("unrealized_pnl"), "unrealized_pnl"),
        weight=_decimal_or_none(payload.get("weight"), "weight"),
    )


def _decimal_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _unique_missing(items: list[MissingData]) -> tuple[MissingData, ...]:
    seen: set[tuple[str, MissingDataState, str]] = set()
    output: list[MissingData] = []
    for item in items:
        key = (item.field, item.state, item.reason)
        if key not in seen:
            seen.add(key)
            output.append(item)
    return tuple(output)
