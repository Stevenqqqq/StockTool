"""Bounded provider retry policy and in-memory health evidence."""

from __future__ import annotations

import socket
import time
import urllib.error
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TypeVar

from stock_tool.data.contracts import ProviderAttemptRecord, sanitize_provider_text

T = TypeVar("T")


class ProviderErrorCategory(StrEnum):
    """Stable failure categories for retry decisions and user evidence."""

    TIMEOUT = "timeout"
    CONNECTION = "connection"
    RATE_LIMIT = "rate_limit"
    TRANSIENT_HTTP = "transient_http"
    PERMANENT_HTTP = "permanent_http"
    CREDENTIAL = "credential"
    SCHEMA = "schema"
    INVALID_SYMBOL = "invalid_symbol"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded exponential retry policy with an optional retry-after cap."""

    max_attempts: int = 2
    initial_backoff_seconds: float = 0.25
    max_backoff_seconds: float = 2.0
    max_total_wait_seconds: float = 5.0
    allow_stale_if_error: bool = True

    def __post_init__(self) -> None:
        """Reject unsafe or unbounded retry configuration."""

        if self.max_attempts < 1:
            raise ValueError("max_attempts 至少為 1。")
        if (
            min(
                self.initial_backoff_seconds,
                self.max_backoff_seconds,
                self.max_total_wait_seconds,
            )
            < 0
        ):
            raise ValueError("retry 等待時間不可為負數。")

    def backoff_seconds(self, *, failure_index: int, retry_after: float | None = None) -> float:
        """Return a capped delay for a failed attempt, including Retry-After."""

        exponential = min(
            self.max_backoff_seconds,
            self.initial_backoff_seconds * (2 ** max(failure_index - 1, 0)),
        )
        requested = max(exponential, retry_after or 0.0)
        return min(requested, self.max_total_wait_seconds)


DEFAULT_RETRY_POLICY = RetryPolicy()


class ProviderExecutionError(RuntimeError):
    """Safe failed execution with normalized attempts for a caller to retain."""

    def __init__(
        self,
        *,
        category: ProviderErrorCategory,
        attempts: tuple[ProviderAttemptRecord, ...],
        message: str,
    ) -> None:
        super().__init__(sanitize_provider_text(message))
        self.category = category
        self.attempts = attempts


def classify_provider_error(error: BaseException) -> ProviderErrorCategory:
    """Classify known provider failures without exposing their raw text."""

    if isinstance(error, TimeoutError):
        return ProviderErrorCategory.TIMEOUT
    if isinstance(error, urllib.error.HTTPError):
        return _http_category(error.code)
    if isinstance(error, (ConnectionError, socket.gaierror, urllib.error.URLError)):
        return ProviderErrorCategory.CONNECTION
    status_code = getattr(getattr(error, "response", None), "status_code", None)
    if isinstance(status_code, int):
        return _http_category(status_code)

    text = sanitize_provider_text(error).lower()
    if any(marker in text for marker in ("token", "api key", "api_key", "credential")):
        return ProviderErrorCategory.CREDENTIAL
    if any(marker in text for marker in ("missing required columns", "schema", "欄位")):
        return ProviderErrorCategory.SCHEMA
    if any(marker in text for marker in ("invalid symbol", "not found", "查無", "代號")):
        return ProviderErrorCategory.INVALID_SYMBOL
    if any(marker in text for marker in ("不支援", "unsupported", "only supports")):
        return ProviderErrorCategory.UNSUPPORTED
    return ProviderErrorCategory.UNKNOWN


def is_retryable(category: ProviderErrorCategory) -> bool:
    """Return whether a category can receive a bounded retry."""

    return category in {
        ProviderErrorCategory.TIMEOUT,
        ProviderErrorCategory.CONNECTION,
        ProviderErrorCategory.RATE_LIMIT,
        ProviderErrorCategory.TRANSIENT_HTTP,
    }


def execute_with_retry(
    operation: Callable[[], T],
    *,
    provider: str,
    policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[T, tuple[ProviderAttemptRecord, ...]]:
    """Run one operation under a finite, test-injectable retry boundary."""

    attempts: list[ProviderAttemptRecord] = []
    total_wait = 0.0
    started = clock()
    for number in range(1, policy.max_attempts + 1):
        try:
            value = operation()
        except Exception as error:  # Provider exceptions are untrusted at this boundary.
            category = classify_provider_error(error)
            message = _safe_failure_message(category, error)
            attempts.append(
                ProviderAttemptRecord(
                    provider=provider,
                    success=False,
                    reason=f"第 {number} 次失敗（{category.value}）：{message}",
                )
            )
            can_retry = number < policy.max_attempts and is_retryable(category)
            if not can_retry:
                raise ProviderExecutionError(
                    category=category,
                    attempts=tuple(attempts),
                    message=message,
                ) from None
            delay = policy.backoff_seconds(
                failure_index=number, retry_after=_retry_after_seconds(error)
            )
            if total_wait + delay > policy.max_total_wait_seconds or clock() - started + delay > (
                policy.max_total_wait_seconds
            ):
                raise ProviderExecutionError(
                    category=category,
                    attempts=tuple(attempts),
                    message=message,
                ) from None
            sleeper(delay)
            total_wait += delay
        else:
            attempts.append(
                ProviderAttemptRecord(
                    provider=provider,
                    success=True,
                    reason=f"第 {number} 次完成。",
                )
            )
            return value, tuple(attempts)
    raise AssertionError("retry loop must return or raise")


@dataclass(frozen=True, slots=True)
class ProviderHealthSnapshot:
    """Runtime-only, non-sensitive provider health record."""

    provider: str
    enabled: bool
    capabilities: tuple[str, ...]
    last_success_at: str | None = None
    last_failure_at: str | None = None
    last_latency_ms: float | None = None
    consecutive_failures: int = 0
    last_error_category: str | None = None
    rate_limit_state: str | None = None
    recent_source_type: str | None = None
    recent_cache_state: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Serialize health evidence without exceptions or credential text."""

        return {
            "provider": self.provider,
            "enabled": self.enabled,
            "capabilities": list(self.capabilities),
            "last_success_at": self.last_success_at,
            "last_failure_at": self.last_failure_at,
            "last_latency_ms": self.last_latency_ms,
            "consecutive_failures": self.consecutive_failures,
            "last_error_category": self.last_error_category,
            "rate_limit_state": self.rate_limit_state,
            "recent_source_type": self.recent_source_type,
            "recent_cache_state": self.recent_cache_state,
        }


class ProviderHealthTracker:
    """Per-runtime in-memory health tracker; restart deliberately resets it."""

    def __init__(self) -> None:
        self._records: dict[str, ProviderHealthSnapshot] = {}

    def record(
        self,
        *,
        provider: str,
        enabled: bool,
        capabilities: tuple[str, ...],
        success: bool,
        latency_ms: float | None,
        category: ProviderErrorCategory | None = None,
        source_type: str | None = None,
        cache_state: str | None = None,
        now: datetime | None = None,
    ) -> None:
        """Record one completed attempt without retaining raw failure details."""

        key = str(provider).strip().lower()
        previous = self._records.get(key)
        timestamp = (now or datetime.now(UTC)).isoformat()
        failures = 0 if success else (previous.consecutive_failures if previous else 0) + 1
        self._records[key] = ProviderHealthSnapshot(
            provider=key,
            enabled=enabled,
            capabilities=capabilities,
            last_success_at=(
                timestamp if success else (previous.last_success_at if previous else None)
            ),
            last_failure_at=(
                timestamp if not success else (previous.last_failure_at if previous else None)
            ),
            last_latency_ms=latency_ms,
            consecutive_failures=failures,
            last_error_category=None if success else (category.value if category else "unknown"),
            rate_limit_state=(
                "rate_limited" if category is ProviderErrorCategory.RATE_LIMIT else None
            ),
            recent_source_type=source_type,
            recent_cache_state=cache_state,
        )

    def snapshots(self) -> tuple[ProviderHealthSnapshot, ...]:
        """Return stable provider snapshots for UI evidence rendering."""

        return tuple(self._records[key] for key in sorted(self._records))


def _http_category(status_code: int) -> ProviderErrorCategory:
    if status_code == 429:
        return ProviderErrorCategory.RATE_LIMIT
    if status_code == 408 or status_code >= 500:
        return ProviderErrorCategory.TRANSIENT_HTTP
    return ProviderErrorCategory.PERMANENT_HTTP


def _retry_after_seconds(error: BaseException) -> float | None:
    headers = getattr(error, "headers", None) or getattr(
        getattr(error, "response", None), "headers", None
    )
    if headers is None:
        return None
    try:
        value = headers.get("Retry-After")
        return max(float(value), 0.0) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_failure_message(category: ProviderErrorCategory, error: BaseException) -> str:
    detail = sanitize_provider_text(error)
    if category in {ProviderErrorCategory.CREDENTIAL, ProviderErrorCategory.INVALID_SYMBOL}:
        return detail
    if category is ProviderErrorCategory.RATE_LIMIT:
        return "資料來源暫時限制請求，將依備援政策處理。"
    if category is ProviderErrorCategory.TIMEOUT:
        return "資料來源逾時。"
    if category is ProviderErrorCategory.CONNECTION:
        return "無法連線至資料來源。"
    return detail or "資料來源發生未預期錯誤。"
