from __future__ import annotations

import urllib.error
from email.message import Message

import pytest

from stock_tool.data.policies import (
    ProviderErrorCategory,
    ProviderExecutionError,
    RetryPolicy,
    classify_provider_error,
    execute_with_retry,
)
from stock_tool.data.registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistryError


def test_registry_orders_only_compatible_enabled_providers() -> None:
    assert [
        item.provider_id
        for item in DEFAULT_PROVIDER_REGISTRY.ordered(provider_id="auto", market="US")
    ] == ["yfinance"]
    assert [
        item.provider_id
        for item in DEFAULT_PROVIDER_REGISTRY.ordered(provider_id="auto", market="TWSE")
    ] == [
        "yfinance",
        "finmind",
    ]


def test_registry_rejects_explicit_incompatible_provider() -> None:
    with pytest.raises(ProviderRegistryError, match="不支援市場"):
        DEFAULT_PROVIDER_REGISTRY.ordered(provider_id="finmind", market="US")


def test_retry_retries_transient_http_without_real_sleep() -> None:
    calls = 0
    waits: list[float] = []

    def operation() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError("https://example.test", 503, "down", Message(), None)
        return "ok"

    value, attempts = execute_with_retry(
        operation,
        provider="yfinance",
        policy=RetryPolicy(max_attempts=2, initial_backoff_seconds=0.5),
        sleeper=waits.append,
        clock=lambda: 0.0,
    )

    assert value == "ok"
    assert len(attempts) == 2
    assert waits == [0.5]


def test_retry_respects_retry_after_and_never_retries_permanent_http() -> None:
    headers = Message()
    headers["Retry-After"] = "1"
    error = urllib.error.HTTPError("https://example.test", 429, "slow", headers, None)
    assert classify_provider_error(error) is ProviderErrorCategory.RATE_LIMIT
    waits: list[float] = []
    calls = 0

    def rate_limited() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise error
        return "ok"

    assert (
        execute_with_retry(
            rate_limited,
            provider="yfinance",
            policy=RetryPolicy(max_attempts=2),
            sleeper=waits.append,
            clock=lambda: 0.0,
        )[0]
        == "ok"
    )
    assert waits == [1.0]

    with pytest.raises(ProviderExecutionError) as raised:
        execute_with_retry(
            lambda: (_ for _ in ()).throw(
                urllib.error.HTTPError("https://example.test", 404, "missing", Message(), None)
            ),
            provider="yfinance",
            policy=RetryPolicy(max_attempts=3),
            sleeper=waits.append,
            clock=lambda: 0.0,
        )
    assert raised.value.category is ProviderErrorCategory.PERMANENT_HTTP
    assert len(raised.value.attempts) == 1


def test_retry_redacts_credential_text_but_keeps_non_sensitive_diagnostics() -> None:
    with pytest.raises(ProviderExecutionError) as raised:
        execute_with_retry(
            lambda: (_ for _ in ()).throw(ValueError("API key: secret-value; HTTP 401")),
            provider="finmind",
            policy=RetryPolicy(max_attempts=2),
            sleeper=lambda _: None,
            clock=lambda: 0.0,
        )
    assert "secret-value" not in str(raised.value)
    assert "[REDACTED]" in str(raised.value)
    assert "HTTP 401" in str(raised.value)
