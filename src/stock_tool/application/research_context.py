"""UI-independent handoffs into the market-qualified research workflow.

The Dashboard has several places from which a user can open research (for
example Explore, the home screen, and a saved continuation).  This module is
the deliberately small contract between those callers and the research
workspace.  It contains no Streamlit state and performs no data fetching.

``ResearchContext`` is immutable and normalises its security identity through
the shared :class:`~stock_tool.domain.models.Symbol` and
:class:`~stock_tool.domain.models.Market` models.  ``ResearchContextQueue`` is
an in-memory, one-shot handoff queue: a context can be observed with
``peek()`` and is removed exactly once by ``consume()``/``consume_once()``.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
import json
from threading import RLock
from typing import Any, Final

from stock_tool.domain.models import Market, Symbol


class ResearchContextValidationError(ValueError):
    """Raised when a research handoff is malformed or outside the contract."""


# A handoff may originate in the home screen or any native workspace.  The
# explicit ``research`` key is included even though the current navigation
# shell enters the research view from ``home``; it is a stable application
# boundary and must not depend on a UI route label.
ALLOWED_WORKSPACES: Final[frozenset[str]] = frozenset(
    {"home", "explore", "research", "strategy", "holdings", "library", "settings"}
)

# Keep action names semantic and independent of button labels or legacy page
# names.  These are the only actions that may cross the handoff boundary.
ALLOWED_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "research_current_data",
        "open_strategy",
        "open_holdings",
        "open_library",
        "return_to_research",
        "explore_to_research",
    }
)

# Only explicit, supported markets are safe for a research handoff.  AUTO and
# CUSTOM are intentionally excluded: accepting either would make the context
# ambiguous at the point where a downstream workspace consumes it.
ALLOWED_MARKETS: Final[frozenset[Market]] = frozenset({Market.TWSE, Market.TPEX, Market.US})


class ResearchWorkspace(StrEnum):
    """Stable application workspace identifiers used by a handoff."""

    HOME = "home"
    EXPLORE = "explore"
    RESEARCH = "research"
    STRATEGY = "strategy"
    HOLDINGS = "holdings"
    LIBRARY = "library"
    SETTINGS = "settings"


class ResearchHandoffAction(StrEnum):
    """Allowed semantic destinations/actions for research handoffs."""

    RESEARCH_CURRENT_DATA = "research_current_data"
    OPEN_STRATEGY = "open_strategy"
    OPEN_HOLDINGS = "open_holdings"
    OPEN_LIBRARY = "open_library"
    RETURN_TO_RESEARCH = "return_to_research"
    EXPLORE_TO_RESEARCH = "explore_to_research"


# Short aliases make the contract convenient for callers without creating a
# second set of values or validation rules.
Workspace = ResearchWorkspace
HandoffAction = ResearchHandoffAction
ResearchAction = ResearchHandoffAction
ResearchContextAction = ResearchHandoffAction
ResearchWorkspaceKey = ResearchWorkspace
ValidationError = ResearchContextValidationError
VALID_WORKSPACES = ALLOWED_WORKSPACES
VALID_ACTIONS = ALLOWED_ACTIONS


@dataclass(frozen=True, slots=True)
class ResearchContext:
    """One immutable, market-qualified request handed to a research workspace.

    ``symbol`` and ``market`` accept the ordinary string values used by UI
    adapters, or canonical ``Symbol``/``Market`` values from the domain layer.
    They are stored as canonical domain objects after validation.  A context
    never infers a market and never accepts ``AUTO``/``CUSTOM``.
    """

    symbol: Symbol
    market: Market
    origin_workspace: ResearchWorkspace
    destination_workspace: ResearchWorkspace
    action: ResearchHandoffAction
    data_as_of: str | None = None
    snapshot_fingerprint: str | None = None

    def __post_init__(self) -> None:
        """Canonicalise all values and reject malformed handoffs fail-closed."""

        identity = _canonical_identity(self.symbol, self.market)
        origin = _workspace(self.origin_workspace, field="origin_workspace")
        destination = _workspace(
            self.destination_workspace,
            field="destination_workspace",
        )
        action = _action(self.action)
        _validate_route(origin, destination, action)
        data_as_of = _optional_iso_date(self.data_as_of)
        snapshot_fingerprint = _optional_fingerprint(self.snapshot_fingerprint)

        object.__setattr__(self, "symbol", identity)
        object.__setattr__(self, "market", identity.market)
        object.__setattr__(self, "origin_workspace", origin)
        object.__setattr__(self, "destination_workspace", destination)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "data_as_of", data_as_of)
        object.__setattr__(self, "snapshot_fingerprint", snapshot_fingerprint)

    @property
    def symbol_code(self) -> str:
        """Return the provider-neutral code used in serialized handoffs."""

        return self.symbol.code

    @property
    def canonical_symbol(self) -> str:
        """Return the stable ``MARKET:CODE`` identity."""

        return self.symbol.canonical

    @property
    def identity(self) -> str:
        """Compatibility alias for :attr:`canonical_symbol`."""

        return self.canonical_symbol

    def to_dict(self) -> dict[str, object]:
        """Serialize only the contract's non-sensitive, immutable values."""

        return {
            "symbol": self.symbol.code,
            "market": self.market.value,
            "origin_workspace": self.origin_workspace.value,
            "destination_workspace": self.destination_workspace.value,
            "action": self.action.value,
            "data_as_of": self.data_as_of,
            "snapshot_fingerprint": self.snapshot_fingerprint,
        }

    # Common serialization spelling used by application result objects.
    as_dict = to_dict

    def to_json(self) -> str:
        """Return deterministic JSON suitable for a short-lived handoff."""

        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ResearchContext":
        """Parse a serialized context without accepting unknown fields.

        Parsing is intentionally strict so a malformed or stale UI payload is
        discarded instead of being partially interpreted.  ``schema_version``
        is accepted for forward-compatible callers, but is not emitted by the
        compact contract serializer.
        """

        if not isinstance(payload, Mapping):
            raise ResearchContextValidationError("ResearchContext payload must be a mapping.")

        expected = {
            "symbol",
            "market",
            "origin_workspace",
            "destination_workspace",
            "action",
            "data_as_of",
            "snapshot_fingerprint",
        }
        keys = set(payload)
        if any(not isinstance(key, str) for key in keys):
            raise ResearchContextValidationError("ResearchContext payload keys must be strings.")
        if "schema_version" in keys:
            version = payload.get("schema_version")
            if version != 1:
                raise ResearchContextValidationError(
                    "ResearchContext payload has an unsupported schema version."
                )
            keys.remove("schema_version")
        if keys != expected:
            missing = sorted(expected - keys)
            unknown = sorted(keys - expected)
            detail: list[str] = []
            if missing:
                detail.append("missing " + ", ".join(missing))
            if unknown:
                detail.append("unknown " + ", ".join(unknown))
            raise ResearchContextValidationError(
                "ResearchContext payload has an invalid schema"
                + (": " + "; ".join(detail) if detail else ".")
            )

        return cls(
            symbol=payload["symbol"],
            market=payload["market"],
            origin_workspace=payload["origin_workspace"],
            destination_workspace=payload["destination_workspace"],
            action=payload["action"],
            data_as_of=payload["data_as_of"],
            snapshot_fingerprint=payload["snapshot_fingerprint"],
        )

    @classmethod
    def from_json(cls, payload: str) -> "ResearchContext":
        """Parse one JSON object through :meth:`from_dict`."""

        if not isinstance(payload, str) or not payload.strip():
            raise ResearchContextValidationError("ResearchContext JSON must be a non-empty string.")
        try:
            value = json.loads(payload)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ResearchContextValidationError("ResearchContext JSON is invalid.") from exc
        return cls.from_dict(value)


class ResearchContextQueue:
    """Thread-safe FIFO queue whose contexts are each consumed at most once."""

    def __init__(self) -> None:
        self._items: deque[ResearchContext] = deque()
        self._lock = RLock()

    def enqueue(self, context: ResearchContext) -> ResearchContext:
        """Queue a validated context and return the queued value.

        Enqueuing the same immutable context while it is already pending is
        idempotent.  This prevents Streamlit reruns from creating duplicate
        handoffs while still allowing a context to be queued again after it
        has been consumed.
        """

        if not isinstance(context, ResearchContext):
            raise ResearchContextValidationError(
                "ResearchContextQueue accepts only ResearchContext values."
            )
        with self._lock:
            if context not in self._items:
                self._items.append(context)
        return context

    def enqueue_many(self, contexts: Any) -> tuple[ResearchContext, ...]:
        """Queue a finite iterable of contexts in order."""

        try:
            values = tuple(contexts)
        except TypeError as exc:
            raise ResearchContextValidationError("contexts must be iterable.") from exc
        for context in values:
            self.enqueue(context)
        return values

    @property
    def pending(self) -> bool:
        """Whether at least one context awaits one-shot consumption."""

        with self._lock:
            return bool(self._items)

    @property
    def has_pending(self) -> bool:
        """Compatibility alias for :attr:`pending`."""

        return self.pending

    @property
    def pending_context(self) -> ResearchContext | None:
        """Return the next context without consuming it."""

        return self.peek()

    def peek(self) -> ResearchContext | None:
        """Return the oldest pending context without removing it."""

        with self._lock:
            return self._items[0] if self._items else None

    def consume(self) -> ResearchContext | None:
        """Atomically remove and return the oldest context, once only."""

        with self._lock:
            return self._items.popleft() if self._items else None

    def consume_for_destination(self, destination: object) -> ResearchContext | None:
        """Atomically consume the oldest pending context for one destination.

        A different destination at the head must not block a later context that
        belongs to the current workspace.  Non-matching items remain in their
        original order, and malformed destinations fail closed without touching
        the queue.
        """

        try:
            target = _workspace(destination, field="destination_workspace")
        except ResearchContextValidationError:
            return None
        with self._lock:
            for index, context in enumerate(self._items):
                if context.destination_workspace is target:
                    self._items.rotate(-index)
                    selected = self._items.popleft()
                    self._items.rotate(index)
                    return selected
        return None

    def consume_once(self, expected: ResearchContext | None = None) -> ResearchContext | None:
        """Consume one context, optionally only when it matches ``expected``.

        A mismatching expected value leaves the queue untouched and returns
        ``None``.  This gives rerun callers a safe compare-and-consume helper.
        """

        if expected is not None and not isinstance(expected, ResearchContext):
            raise ResearchContextValidationError(
                "expected must be a ResearchContext when provided."
            )
        with self._lock:
            if not self._items:
                return None
            if expected is not None:
                if self._items[0] != expected:
                    return None
            return self._items.popleft()

    def clear(self) -> None:
        """Discard all pending handoffs."""

        with self._lock:
            self._items.clear()

    def snapshot(self) -> tuple[ResearchContext, ...]:
        """Return an immutable view of pending contexts without consuming."""

        with self._lock:
            return tuple(self._items)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def __bool__(self) -> bool:
        return self.pending


# Name used by callers that do not need the more specific class spelling.
HandoffQueue = ResearchContextQueue
OneShotQueue = ResearchContextQueue


def _canonical_identity(symbol: object, market: object) -> Symbol:
    if isinstance(symbol, Symbol):
        identity = symbol
        try:
            selected_market = Market.parse(market)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ResearchContextValidationError("ResearchContext.market is invalid.") from exc
        if selected_market is not identity.market:
            raise ResearchContextValidationError(
                "ResearchContext symbol and market must identify the same security."
            )
    else:
        if not isinstance(symbol, str):
            raise ResearchContextValidationError(
                "ResearchContext.symbol must be a symbol or string."
            )
        try:
            selected_market = Market.parse(market)  # type: ignore[arg-type]
            if selected_market not in ALLOWED_MARKETS:
                raise ResearchContextValidationError(
                    "ResearchContext requires an explicit TWSE, TPEX, or US market."
                )
            identity = Symbol.parse(symbol, market=selected_market)
        except (TypeError, ValueError) as exc:
            raise ResearchContextValidationError(
                "ResearchContext symbol or market is invalid."
            ) from exc
    if identity.market not in ALLOWED_MARKETS:
        raise ResearchContextValidationError(
            "ResearchContext requires an explicit TWSE, TPEX, or US market."
        )
    return identity


def _workspace(value: object, *, field: str) -> ResearchWorkspace:
    if isinstance(value, ResearchWorkspace):
        return value
    if not isinstance(value, str):
        raise ResearchContextValidationError(f"ResearchContext.{field} is invalid.")
    normalized = value.strip().lower()
    try:
        return ResearchWorkspace(normalized)
    except ValueError as exc:
        raise ResearchContextValidationError(
            f"ResearchContext.{field} must be one of {sorted(ALLOWED_WORKSPACES)}."
        ) from exc


def _action(value: object) -> ResearchHandoffAction:
    if isinstance(value, ResearchHandoffAction):
        return value
    if not isinstance(value, str):
        raise ResearchContextValidationError("ResearchContext.action is invalid.")
    normalized = value.strip().lower()
    try:
        return ResearchHandoffAction(normalized)
    except ValueError as exc:
        raise ResearchContextValidationError(
            f"ResearchContext.action must be one of {sorted(ALLOWED_ACTIONS)}."
        ) from exc


def _validate_route(
    origin: ResearchWorkspace,
    destination: ResearchWorkspace,
    action: ResearchHandoffAction,
) -> None:
    """Reject a valid-looking payload whose action and route disagree."""

    expected: dict[ResearchHandoffAction, tuple[ResearchWorkspace, ResearchWorkspace]] = {
        ResearchHandoffAction.EXPLORE_TO_RESEARCH: (
            ResearchWorkspace.EXPLORE,
            ResearchWorkspace.RESEARCH,
        ),
        ResearchHandoffAction.RESEARCH_CURRENT_DATA: (
            ResearchWorkspace.LIBRARY,
            ResearchWorkspace.RESEARCH,
        ),
        ResearchHandoffAction.RETURN_TO_RESEARCH: (
            ResearchWorkspace.STRATEGY,
            ResearchWorkspace.RESEARCH,
        ),
        ResearchHandoffAction.OPEN_STRATEGY: (
            ResearchWorkspace.RESEARCH,
            ResearchWorkspace.STRATEGY,
        ),
        ResearchHandoffAction.OPEN_HOLDINGS: (
            ResearchWorkspace.RESEARCH,
            ResearchWorkspace.HOLDINGS,
        ),
        ResearchHandoffAction.OPEN_LIBRARY: (
            ResearchWorkspace.RESEARCH,
            ResearchWorkspace.LIBRARY,
        ),
    }
    expected_origin, expected_destination = expected[action]
    if origin is not expected_origin or destination is not expected_destination:
        # RETURN_TO_RESEARCH is intentionally also valid from Holdings.
        if not (
            action is ResearchHandoffAction.RETURN_TO_RESEARCH
            and origin is ResearchWorkspace.HOLDINGS
            and destination is ResearchWorkspace.RESEARCH
        ):
            raise ResearchContextValidationError(
                "ResearchContext action does not match its origin and destination."
            )


def _optional_iso_date(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        raise ResearchContextValidationError("ResearchContext.data_as_of must be an ISO date.")
    text = value.strip()
    if not text:
        return None
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ResearchContextValidationError(
            "ResearchContext.data_as_of must be an ISO date (YYYY-MM-DD)."
        ) from exc
    return parsed.isoformat()


def _optional_fingerprint(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ResearchContextValidationError(
            "ResearchContext.snapshot_fingerprint must be a string."
        )
    text = value.strip()
    if not text:
        return None
    if len(text) > 256 or any(character.isspace() for character in text):
        raise ResearchContextValidationError("ResearchContext.snapshot_fingerprint is invalid.")
    return text


__all__ = [
    "ALLOWED_ACTIONS",
    "ALLOWED_MARKETS",
    "ALLOWED_WORKSPACES",
    "HandoffAction",
    "HandoffQueue",
    "OneShotQueue",
    "ResearchAction",
    "ResearchContext",
    "ResearchContextAction",
    "ResearchContextQueue",
    "ResearchContextValidationError",
    "ResearchHandoffAction",
    "ResearchWorkspace",
    "ResearchWorkspaceKey",
    "VALID_ACTIONS",
    "VALID_WORKSPACES",
    "ValidationError",
    "Workspace",
]
