from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from stock_tool.application.research_context import (
    ALLOWED_ACTIONS,
    ALLOWED_WORKSPACES,
    HandoffQueue,
    ResearchContext,
    ResearchContextQueue,
    ResearchContextValidationError,
)
from stock_tool.domain.models import Market, Symbol


def _context(**overrides: object) -> ResearchContext:
    values: dict[str, object] = {
        "symbol": "2330.TW",
        "market": "TWSE",
        "origin_workspace": "explore",
        "destination_workspace": "research",
        "action": "explore_to_research",
        "data_as_of": "2026-08-03",
        "snapshot_fingerprint": "snapshot-1",
    }
    values.update(overrides)
    return ResearchContext(**values)


def test_context_canonicalises_identity_and_keeps_contract_immutable() -> None:
    context = _context()

    assert isinstance(context.symbol, Symbol)
    assert context.symbol.code == "2330"
    assert context.market is Market.TWSE
    assert context.symbol_code == "2330"
    assert context.canonical_symbol == "TWSE:2330"
    assert context.identity == "TWSE:2330"
    with pytest.raises(FrozenInstanceError):
        context.action = "open_library"  # type: ignore[misc]


def test_context_round_trips_through_dict_and_json() -> None:
    context = _context()

    payload = context.to_dict()
    assert payload == {
        "symbol": "2330",
        "market": "TWSE",
        "origin_workspace": "explore",
        "destination_workspace": "research",
        "action": "explore_to_research",
        "data_as_of": "2026-08-03",
        "snapshot_fingerprint": "snapshot-1",
    }
    assert ResearchContext.from_dict(payload) == context
    assert ResearchContext.from_json(context.to_json()) == context


@pytest.mark.parametrize("market", ["AUTO", "CUSTOM", "", "unknown"])
def test_context_rejects_ambiguous_or_unknown_markets(market: str) -> None:
    with pytest.raises(ResearchContextValidationError):
        _context(market=market)


def test_context_rejects_symbol_market_mismatch_and_unknown_route_values() -> None:
    with pytest.raises(ValueError):
        _context(symbol="2330.TW", market="TPEX")
    with pytest.raises(ValueError):
        _context(origin_workspace="unknown")
    with pytest.raises(ValueError):
        _context(destination_workspace="legacy")
    with pytest.raises(ValueError):
        _context(action="buy")
    with pytest.raises(ValueError):
        _context(action="open_strategy")
    with pytest.raises(ValueError):
        _context(origin_workspace="holdings", action="explore_to_research")


def test_context_rejects_malformed_optional_metadata_and_payload_schema() -> None:
    with pytest.raises(ValueError):
        _context(data_as_of="yesterday")
    with pytest.raises(ValueError):
        _context(snapshot_fingerprint="contains whitespace")
    with pytest.raises(ValueError):
        ResearchContext.from_dict({"symbol": "2330"})
    with pytest.raises(ValueError):
        ResearchContext.from_dict({**_context().to_dict(), "unexpected": 1})
    with pytest.raises(ValueError):
        ResearchContext.from_json("[]")


def test_allowed_contract_values_are_explicit_and_include_research() -> None:
    assert ALLOWED_WORKSPACES == {
        "home",
        "explore",
        "research",
        "strategy",
        "holdings",
        "library",
        "settings",
    }
    assert ALLOWED_ACTIONS == {
        "research_current_data",
        "open_strategy",
        "open_holdings",
        "open_library",
        "return_to_research",
        "explore_to_research",
    }


def test_queue_peek_and_consume_are_one_shot_and_fifo() -> None:
    first = _context()
    second = _context(
        symbol="AAPL",
        market="US",
        origin_workspace="research",
        destination_workspace="strategy",
        action="open_strategy",
    )
    queue = ResearchContextQueue()

    assert queue.pending is False
    assert queue.peek() is None
    queue.enqueue(first)
    queue.enqueue(first)  # Streamlit rerun duplicate is idempotently ignored.
    queue.enqueue(second)
    assert queue.pending is True
    assert len(queue) == 2
    assert queue.peek() is first
    assert queue.consume_once(expected=second) is None
    assert queue.peek() is first
    assert queue.consume_once(expected=first) is first
    assert queue.consume() is second
    assert queue.consume() is None
    assert queue.pending is False


def test_queue_rejects_unvalidated_values_and_alias_has_same_behavior() -> None:
    queue = HandoffQueue()
    with pytest.raises(ResearchContextValidationError):
        queue.enqueue({"symbol": "2330"})  # type: ignore[arg-type]
    with pytest.raises(ResearchContextValidationError):
        queue.consume_once(expected="not-a-context")  # type: ignore[arg-type]
    context = _context()
    assert queue.enqueue_many([context]) == (context,)
    assert queue.pending_context is context
    assert queue.snapshot() == (context,)
    queue.clear()
    assert not queue


def test_destination_consume_skips_head_for_matching_context_without_reordering() -> None:
    strategy = _context(
        symbol="AAPL",
        market="US",
        origin_workspace="research",
        destination_workspace="strategy",
        action="open_strategy",
    )
    research = _context()
    library = _context(
        symbol="6488.TWO",
        market="TPEX",
        origin_workspace="research",
        destination_workspace="library",
        action="open_library",
    )
    queue = ResearchContextQueue()
    queue.enqueue_many([strategy, research, library])

    assert queue.consume_for_destination("research") is research
    assert queue.snapshot() == (strategy, library)
    assert queue.consume_for_destination("research") is None
    assert queue.consume_for_destination("strategy") is strategy
    assert queue.consume_for_destination("strategy") is None
    assert queue.consume_for_destination("library") is library


def test_destination_consume_malformed_destination_fails_closed() -> None:
    queue = ResearchContextQueue()
    context = _context()
    queue.enqueue(context)
    assert queue.consume_for_destination("not-a-workspace") is None
    assert queue.snapshot() == (context,)
