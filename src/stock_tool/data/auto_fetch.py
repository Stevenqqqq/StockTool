"""Automatic price download providers with explicit fallback and cache metadata."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Callable, Literal

import pandas as pd
import yfinance as yf

from stock_tool.config import DEFAULT_FEATURE_FLAGS
from stock_tool.data.cache import (
    CacheState,
    DEFAULT_CACHE_DIR,
    inspect_cached_prices,
    save_cached_prices,
)
from stock_tool.data.cleaner import DataValidationError, clean_price_data
from stock_tool.data.contracts import (
    ProviderResult,
    adapt_legacy_fetch_result,
    sanitize_provider_text,
)
from stock_tool.data.loader import REQUIRED_COLUMNS, STANDARD_COLUMNS
from stock_tool.data.policies import (
    DEFAULT_RETRY_POLICY,
    ProviderErrorCategory,
    ProviderExecutionError,
    ProviderHealthTracker,
    RetryPolicy,
    execute_with_retry,
)
from stock_tool.data.registry import (
    DEFAULT_PROVIDER_REGISTRY,
    ProviderRegistry,
    ProviderRegistryError,
)

Market = Literal["TWSE", "TPEX", "US", "TW", "TPEx", "AUTO", "CUSTOM"]
ProviderChoice = Literal["auto", "yfinance", "finmind", "cache"]

YFINANCE_PROVIDER = "yfinance"
FINMIND_PROVIDER = "finmind"
STOOQ_PROVIDER = "stooq"
FINMIND_DOWNLOAD_URL = "https://api.finmindtrade.com/api/v4/data"


class DataFetchError(ValueError):
    """Raised when price data cannot be downloaded or loaded from cache."""


class ProviderContractDisabledError(RuntimeError):
    """Raised when the Sprint 2 adapter is called before explicit enablement."""


@dataclass(frozen=True)
class ProviderAttempt:
    """One provider attempt and the result shown to users."""

    provider: str
    success: bool
    reason: str


@dataclass(frozen=True)
class FetchResult:
    """Result returned by automatic price downloads."""

    data: pd.DataFrame
    source: str
    symbol: str
    provider_symbol: str
    from_cache: bool
    cache_file: Path | None
    market: str
    start_date: str
    end_date: str
    source_type: str
    warnings: tuple[str, ...] = ()
    attempts: tuple[ProviderAttempt, ...] = ()
    fetched_at: str | None = None
    last_data_date: str | None = None
    cache_state: str | None = None
    cache_age_seconds: float | None = None


def fetch_prices(
    symbol: str,
    *,
    market: Market = "TWSE",
    start: str | date | None = None,
    end: str | date | None = None,
    interval: str = "1d",
    provider: ProviderChoice = "auto",
    use_cache: bool = True,
    force_refresh: bool = False,
    cache_dir: str | Path | None = DEFAULT_CACHE_DIR,
    timeout_seconds: int = 20,
    log_dir: str | Path = Path("logs"),
    registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY,
    retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    sleeper: Callable[[float], None] | None = None,
    clock: Callable[[], float] | None = None,
    health_tracker: ProviderHealthTracker | None = None,
    now: Callable[[], datetime] | None = None,
) -> FetchResult:
    """Fetch OHLCV data through online providers with cache fallback.

    The default path is conservative and explicit:

    1. Try yfinance.
    2. Try FinMind only when ``FINMIND_TOKEN`` exists and the market is Taiwan.
    3. Try existing ``data/cache`` files.
    4. Raise a user-readable error that recommends CSV upload as the final
       manual fallback.
    """

    user_symbol = str(symbol).strip()
    if not user_symbol:
        raise DataFetchError("自動抓資料需要股票代號。")

    start_text, end_text = default_date_range(start, end)
    market_key = normalize_market(market)
    provider_key = str(provider).strip().lower()
    query_symbols = yfinance_symbol_candidates(user_symbol, market=market_key)
    query_symbol = query_symbols[0]
    attempts: list[ProviderAttempt] = []

    try:
        remote_providers = (
            ()
            if provider_key == "cache"
            else registry.ordered(provider_id=provider_key, market=market_key)
        )
    except ProviderRegistryError as exc:
        raise DataFetchError(str(exc)) from None
    provider_order = [definition.provider_id for definition in remote_providers]
    if use_cache:
        provider_order.append("cache")
    if provider_key == "cache" and force_refresh:
        # Refresh explicitly asks for an online attempt before stale-if-error cache.
        provider_order = [
            definition.provider_id
            for definition in registry.ordered(provider_id="auto", market=market_key)
        ]
        if use_cache:
            provider_order.append("cache")

    sleep = sleeper if sleeper is not None else __import__("time").sleep
    monotonic = clock if clock is not None else __import__("time").monotonic
    timestamp = now if now is not None else lambda: datetime.now(UTC)
    for provider_name in provider_order:
        if provider_name == "cache":
            if not use_cache:
                attempts.append(ProviderAttempt("cache", False, "使用者已停用快取。"))
                continue
            cached_result = _try_cache(
                user_symbol=user_symbol,
                query_symbols=query_symbols,
                market=market_key,
                start=start_text,
                end=end_text,
                interval=interval,
                cache_dir=cache_dir,
                attempts=attempts,
                allow_stale=retry_policy.allow_stale_if_error,
            )
            if cached_result is not None:
                return cached_result
            continue

        if provider_name == YFINANCE_PROVIDER:
            for candidate_symbol in query_symbols:
                try:
                    attempt_started = monotonic()
                    data, retry_attempts = execute_with_retry(
                        lambda: _fetch_yfinance(
                            user_symbol=user_symbol,
                            query_symbol=candidate_symbol,
                            market=market_key,
                            start=start_text,
                            end=end_text,
                            interval=interval,
                            timeout_seconds=timeout_seconds,
                        ),
                        provider=f"{YFINANCE_PROVIDER}:{candidate_symbol}",
                        policy=retry_policy,
                        sleeper=sleep,
                        clock=monotonic,
                    )
                    attempts.extend(_legacy_attempts(retry_attempts))
                    _record_health(
                        health_tracker,
                        provider=YFINANCE_PROVIDER,
                        market=market_key,
                        success=True,
                        latency_ms=(monotonic() - attempt_started) * 1_000,
                        source_type="online",
                    )
                    saved_path = None
                    if use_cache:
                        saved_path = save_cached_prices(
                            data,
                            source=YFINANCE_PROVIDER,
                            symbol=candidate_symbol,
                            start=start_text,
                            end=end_text,
                            interval=interval,
                            cache_dir=cache_dir,
                            market=market_key,
                            fetched_at=timestamp(),
                        )
                    warnings = _cross_market_warnings(
                        primary_symbol=query_symbol,
                        matched_symbol=candidate_symbol,
                        market=market_key,
                    )
                    return FetchResult(
                        data=data,
                        source=YFINANCE_PROVIDER,
                        symbol=user_symbol,
                        provider_symbol=candidate_symbol,
                        from_cache=False,
                        cache_file=saved_path,
                        market=market_key,
                        start_date=start_text,
                        end_date=end_text,
                        source_type="online",
                        warnings=warnings,
                        attempts=tuple(attempts),
                        fetched_at=timestamp().isoformat(),
                        last_data_date=_last_data_date(data),
                        cache_state=CacheState.FRESH.value if saved_path else None,
                    )
                except ProviderExecutionError as exc:
                    attempts.extend(_legacy_attempts(exc.attempts))
                    _record_health(
                        health_tracker,
                        provider=YFINANCE_PROVIDER,
                        market=market_key,
                        success=False,
                        latency_ms=None,
                        category=exc.category,
                    )
                    continue

        if provider_name == FINMIND_PROVIDER:
            try:
                attempt_started = monotonic()
                data, retry_attempts = execute_with_retry(
                    lambda: _fetch_finmind(
                        user_symbol=user_symbol,
                        query_symbol=query_symbol,
                        market=market_key,
                        start=start_text,
                        end=end_text,
                        timeout_seconds=timeout_seconds,
                    ),
                    provider=FINMIND_PROVIDER,
                    policy=retry_policy,
                    sleeper=sleep,
                    clock=monotonic,
                )
                attempts.extend(_legacy_attempts(retry_attempts))
                _record_health(
                    health_tracker,
                    provider=FINMIND_PROVIDER,
                    market=market_key,
                    success=True,
                    latency_ms=(monotonic() - attempt_started) * 1_000,
                    source_type="online",
                )
                finmind_symbol = _finmind_symbol(query_symbol)
                saved_path = None
                if use_cache:
                    saved_path = save_cached_prices(
                        data,
                        source=FINMIND_PROVIDER,
                        symbol=finmind_symbol,
                        start=start_text,
                        end=end_text,
                        interval=interval,
                        cache_dir=cache_dir,
                        market=market_key,
                        fetched_at=timestamp(),
                    )
                return FetchResult(
                    data=data,
                    source=FINMIND_PROVIDER,
                    symbol=user_symbol,
                    provider_symbol=finmind_symbol,
                    from_cache=False,
                    cache_file=saved_path,
                    market=market_key,
                    start_date=start_text,
                    end_date=end_text,
                    source_type="online",
                    attempts=tuple(attempts),
                    fetched_at=timestamp().isoformat(),
                    last_data_date=_last_data_date(data),
                    cache_state=CacheState.FRESH.value if saved_path else None,
                )
            except ProviderExecutionError as exc:
                attempts.extend(_legacy_attempts(exc.attempts))
                _record_health(
                    health_tracker,
                    provider=FINMIND_PROVIDER,
                    market=market_key,
                    success=False,
                    latency_ms=None,
                    category=exc.category,
                )
                continue

    message = _failure_message(
        user_symbol=user_symbol,
        query_symbol=", ".join(query_symbols),
        market=market_key,
        start=start_text,
        end=end_text,
        attempts=attempts,
    )
    _log_fetch_error(message, log_dir=log_dir)
    raise DataFetchError(message)


def fetch_prices_result(
    symbol: str,
    *,
    market: Market = "TWSE",
    start: str | date | None = None,
    end: str | date | None = None,
    interval: str = "1d",
    provider: ProviderChoice = "auto",
    use_cache: bool = True,
    force_refresh: bool = False,
    cache_dir: str | Path | None = DEFAULT_CACHE_DIR,
    timeout_seconds: int = 20,
    log_dir: str | Path = Path("logs"),
    registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY,
    retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    sleeper: Callable[[float], None] | None = None,
    clock: Callable[[], float] | None = None,
    health_tracker: ProviderHealthTracker | None = None,
    now: Callable[[], datetime] | None = None,
    contracts_enabled: bool | None = None,
) -> ProviderResult[pd.DataFrame]:
    """Return the new contract around the unchanged legacy fetch workflow.

    The adapter is default-off during Sprint 2. Existing dashboard and CLI
    callers continue using ``fetch_prices`` until a later application-service
    migration explicitly enables this path.
    """

    enabled = (
        DEFAULT_FEATURE_FLAGS.provider_contracts_enabled
        if contracts_enabled is None
        else bool(contracts_enabled)
    )
    if not enabled:
        raise ProviderContractDisabledError(
            "Sprint 2 provider contract 尚未啟用；既有 fetch_prices 流程維持不變。"
        )

    legacy_result = fetch_prices(
        symbol,
        market=market,
        start=start,
        end=end,
        interval=interval,
        provider=provider,
        use_cache=use_cache,
        force_refresh=force_refresh,
        cache_dir=cache_dir,
        timeout_seconds=timeout_seconds,
        log_dir=log_dir,
        registry=registry,
        retry_policy=retry_policy,
        sleeper=sleeper,
        clock=clock,
        health_tracker=health_tracker,
        now=now,
    )
    return adapt_legacy_fetch_result(legacy_result, interval=interval)


def normalize_yfinance_symbol(symbol: str, *, market: Market | str = "TWSE") -> str:
    """Convert a user symbol to the query symbol expected by yfinance."""

    value = str(symbol).strip().upper()
    if not value:
        raise DataFetchError("請輸入股票代號。")
    # Market indexes are already provider-qualified symbols.  In particular
    # ``^TWII``, ``^TWO`` and ``^GSPC`` must never be treated as numeric
    # Taiwan equities and receive a ``.TW``/``.TWO`` suffix.
    if value in {"^TWII", "^TWO", "^GSPC"}:
        return value
    if value.endswith((".TW", ".TWO")):
        return value

    market_key = normalize_market(market)
    if market_key == "TWSE":
        return f"{value}.TW" if "." not in value else value
    if market_key == "TPEX":
        return f"{value}.TWO" if "." not in value else value
    if market_key == "US":
        return value
    if market_key == "AUTO":
        return f"{value}.TW" if value.isdigit() else value
    return value


def yfinance_symbol_candidates(symbol: str, *, market: Market | str = "TWSE") -> tuple[str, ...]:
    """Return yfinance query symbols to try, preserving the selected market first.

    Taiwan tickers can trade on TWSE (``.TW``) or TPEx/OTC (``.TWO``). Users
    often know the numeric code but not the exchange suffix, so Taiwan numeric
    symbols are retried against both suffixes before failing.
    """

    value = str(symbol).strip().upper()
    if not value:
        raise DataFetchError("請輸入股票代號。")

    market_key = normalize_market(market)
    primary = normalize_yfinance_symbol(value, market=market_key)
    candidates = [primary]

    base = value
    if value.endswith(".TW"):
        base = value.removesuffix(".TW")
        if market_key in {"TWSE", "TPEX", "AUTO"}:
            candidates.append(f"{base}.TWO")
    elif value.endswith(".TWO"):
        base = value.removesuffix(".TWO")
        if market_key in {"TWSE", "TPEX", "AUTO"}:
            candidates.append(f"{base}.TW")
    elif value.isdigit():
        if market_key == "TWSE":
            candidates.append(f"{value}.TWO")
        elif market_key == "TPEX":
            candidates.append(f"{value}.TW")
        elif market_key == "AUTO":
            candidates.extend([f"{value}.TWO"])

    unique: list[str] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return tuple(unique)


def normalize_stooq_symbol(symbol: str, *, market: Market | str = "TWSE") -> str:
    """Backward-compatible Stooq symbol conversion for old cache names."""

    value = str(symbol).strip()
    if not value:
        raise DataFetchError("請輸入股票代號。")
    if "." in value:
        return value.lower()
    market_key = normalize_market(market)
    if market_key in {"TWSE", "TPEX", "TW"}:
        return f"{value}.tw".lower()
    if market_key == "US":
        return f"{value}.us".lower()
    return value.lower()


def normalize_market(market: Market | str) -> str:
    """Normalize dashboard market labels to internal market codes."""

    value = str(market).strip().upper()
    aliases = {
        "TW": "TWSE",
        "TSE": "TWSE",
        "TWSE": "TWSE",
        "台股上市 TWSE": "TWSE",
        "TPEX": "TPEX",
        "TWO": "TPEX",
        "OTC": "TPEX",
        "台股上櫃 TPEX": "TPEX",
        "US": "US",
        "美股 US": "US",
        "AUTO": "AUTO",
        "CUSTOM": "CUSTOM",
    }
    return aliases.get(value, value)


def default_date_range(
    start: str | date | None,
    end: str | date | None,
    *,
    today: date | None = None,
) -> tuple[str, str]:
    """Return non-empty start/end dates, defaulting to the last two years."""

    end_date = _parse_date(end) if end not in (None, "") else (today or date.today())
    start_date = _parse_date(start) if start not in (None, "") else _two_years_before(end_date)
    if start_date > end_date:
        raise DataFetchError(
            f"日期區間不合理：起始日 {start_date.isoformat()} 晚於 "
            f"結束日 {end_date.isoformat()}。"
        )
    return start_date.isoformat(), end_date.isoformat()


def _fetch_yfinance(
    *,
    user_symbol: str,
    query_symbol: str,
    market: str,
    start: str,
    end: str,
    interval: str,
    timeout_seconds: int,
) -> pd.DataFrame:
    raw = _download_yfinance_history(
        query_symbol=query_symbol,
        start=start,
        end=_exclusive_end_date(end),
        interval=interval,
        timeout_seconds=timeout_seconds,
    )
    return standardize_yfinance_frame(
        raw,
        user_symbol=user_symbol,
        query_symbol=query_symbol,
        market=market,
        start=start,
        end=end,
    )


def _download_yfinance_history(
    *,
    query_symbol: str,
    start: str,
    end: str,
    interval: str,
    timeout_seconds: int,
) -> pd.DataFrame:
    return yf.download(
        query_symbol,
        start=start,
        end=end,
        interval=interval,
        progress=False,
        auto_adjust=False,
        actions=False,
        threads=False,
        timeout=timeout_seconds,
    )


def standardize_yfinance_frame(
    raw: pd.DataFrame,
    *,
    user_symbol: str,
    query_symbol: str,
    market: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    """Convert yfinance data to the project's standard OHLCV schema."""

    columns = _returned_columns(raw)
    row_count = 0 if raw is None else len(raw)
    if raw is None or raw.empty:
        raise DataFetchError(
            _provider_data_error(
                provider=YFINANCE_PROVIDER,
                user_symbol=user_symbol,
                query_symbol=query_symbol,
                market=market,
                start=start,
                end=end,
                columns=columns,
                row_count=row_count,
                reason="資料來源回傳空資料。",
            )
        )

    frame = _flatten_columns(raw)
    frame = frame.reset_index()
    rename_map: dict[str, str] = {}
    for column in frame.columns:
        normalized = _normalize_column_name(column)
        if normalized in {"date", "datetime"}:
            rename_map[column] = "date"
        elif normalized == "open":
            rename_map[column] = "open"
        elif normalized == "high":
            rename_map[column] = "high"
        elif normalized == "low":
            rename_map[column] = "low"
        elif normalized == "close":
            rename_map[column] = "close"
        elif normalized in {"adj_close", "adjusted_close"}:
            rename_map[column] = "adjusted_close"
        elif normalized == "volume":
            rename_map[column] = "volume"

    standardized = frame.rename(columns=rename_map).copy(deep=True)
    missing = [
        column
        for column in REQUIRED_COLUMNS
        if column not in standardized.columns and column != "symbol"
    ]
    if "date" not in standardized.columns or missing:
        raise DataFetchError(
            _provider_data_error(
                provider=YFINANCE_PROVIDER,
                user_symbol=user_symbol,
                query_symbol=query_symbol,
                market=market,
                start=start,
                end=end,
                columns=columns,
                row_count=row_count,
                reason=f"Missing required columns after conversion: {', '.join(['date', *missing])}",
            )
        )

    standardized["symbol"] = str(user_symbol)
    if "adjusted_close" not in standardized.columns:
        standardized["adjusted_close"] = standardized["close"]

    standardized = standardized.loc[:, list(STANDARD_COLUMNS)].copy(deep=True)
    standardized = standardized.dropna(subset=["open", "high", "low", "close", "volume"])

    if standardized.empty:
        raise DataFetchError(
            _provider_data_error(
                provider=YFINANCE_PROVIDER,
                user_symbol=user_symbol,
                query_symbol=query_symbol,
                market=market,
                start=start,
                end=end,
                columns=columns,
                row_count=row_count,
                reason="All rows were removed because OHLCV values were missing.",
            )
        )

    try:
        cleaned = clean_price_data(standardized.to_dict("records"))
    except DataValidationError as exc:
        raise DataFetchError(
            _provider_data_error(
                provider=YFINANCE_PROVIDER,
                user_symbol=user_symbol,
                query_symbol=query_symbol,
                market=market,
                start=start,
                end=end,
                columns=columns,
                row_count=row_count,
                reason=str(exc),
            )
        ) from exc

    if not cleaned.records:
        raise DataFetchError(
            _provider_data_error(
                provider=YFINANCE_PROVIDER,
                user_symbol=user_symbol,
                query_symbol=query_symbol,
                market=market,
                start=start,
                end=end,
                columns=columns,
                row_count=row_count,
                reason="No rows remained after data cleaning.",
            )
        )
    return pd.DataFrame(cleaned.records)


def _fetch_finmind(
    *,
    user_symbol: str,
    query_symbol: str,
    market: str,
    start: str,
    end: str,
    timeout_seconds: int,
) -> pd.DataFrame:
    if market not in {"TWSE", "TPEX"}:
        raise DataFetchError("FinMind 備援目前只支援台股。")
    token = os.getenv("FINMIND_TOKEN", "").strip()
    if not token:
        raise DataFetchError("未設定 FINMIND_TOKEN，因此略過 FinMind 備援。")

    data_id = _finmind_symbol(query_symbol)
    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": data_id,
        "start_date": start,
        "end_date": end,
        "token": token,
    }
    url = f"{FINMIND_DOWNLOAD_URL}?{urllib.parse.urlencode(params)}"
    payload = json.loads(_download_text(url, timeout_seconds=timeout_seconds))
    if payload.get("status") not in {200, "200"}:
        raise DataFetchError(f"FinMind 回傳狀態={payload.get('status')}：{payload.get('msg')}")

    raw = pd.DataFrame(payload.get("data") or [])
    if raw.empty:
        raise DataFetchError(
            _provider_data_error(
                provider=FINMIND_PROVIDER,
                user_symbol=user_symbol,
                query_symbol=data_id,
                market=market,
                start=start,
                end=end,
                columns=(),
                row_count=0,
                reason="資料來源回傳空資料。",
            )
        )

    renamed = raw.rename(
        columns={
            "Trading_Volume": "volume",
            "open": "open",
            "max": "high",
            "min": "low",
            "close": "close",
        }
    ).copy(deep=True)
    renamed["symbol"] = str(user_symbol)
    renamed["adjusted_close"] = renamed["close"]
    try:
        cleaned = clean_price_data(renamed.loc[:, list(STANDARD_COLUMNS)].to_dict("records"))
    except DataValidationError as exc:
        raise DataFetchError(str(exc)) from exc
    if not cleaned.records:
        raise DataFetchError("FinMind 資料清洗後沒有可用資料列。")
    return pd.DataFrame(cleaned.records)


def _try_cache(
    *,
    user_symbol: str,
    query_symbols: tuple[str, ...],
    market: str,
    start: str,
    end: str,
    interval: str,
    cache_dir: str | Path | None,
    attempts: list[ProviderAttempt],
    allow_stale: bool,
) -> FetchResult | None:
    for source, symbol in _cache_candidates(user_symbol, query_symbols, market):
        inspected = inspect_cached_prices(
            source=source,
            symbol=symbol,
            start=start,
            end=end,
            interval=interval,
            cache_dir=cache_dir,
        )
        cache_file = inspected.path
        if inspected.state is CacheState.MISSING:
            continue
        if inspected.state is CacheState.CORRUPT:
            attempts.append(
                ProviderAttempt(
                    f"cache:{source}",
                    False,
                    inspected.warning or "快取檔案損毀，未作為備援。",
                )
            )
            continue
        if inspected.state is CacheState.EXPIRED:
            attempts.append(ProviderAttempt(f"cache:{source}", False, "快取已過期，未作為備援。"))
            continue
        if inspected.state is CacheState.STALE and not allow_stale:
            attempts.append(
                ProviderAttempt(f"cache:{source}", False, "快取已過期且備援政策不允許使用。")
            )
            continue
        if inspected.data is None:
            continue
        try:
            validated = _validate_cached_frame(inspected.data, cache_file=cache_file)
        except DataFetchError as exc:
            attempts.append(ProviderAttempt(f"cache:{source}", False, sanitize_provider_text(exc)))
            continue
        attempts.append(
            ProviderAttempt(f"cache:{source}", True, f"已載入 {len(validated)} 筆資料。")
        )
        return FetchResult(
            data=validated,
            source=source,
            symbol=user_symbol,
            provider_symbol=symbol,
            from_cache=True,
            cache_file=cache_file,
            market=market,
            start_date=start,
            end_date=end,
            source_type="cache",
            warnings=(
                "線上資料來源失敗或使用者選擇快取；已載入本機快取資料。",
                *(
                    ("快取資料已過期，僅作為備援研究參考。",)
                    if inspected.state is CacheState.STALE
                    else ()
                ),
            ),
            attempts=tuple(attempts),
            fetched_at=inspected.metadata.fetched_at if inspected.metadata else None,
            last_data_date=(
                inspected.metadata.last_data_date
                if inspected.metadata
                else _last_data_date(validated)
            ),
            cache_state=inspected.state.value,
            cache_age_seconds=inspected.age_seconds,
        )

    attempts.append(ProviderAttempt("cache", False, "找不到符合條件且有效的快取檔案。"))
    return None


def _validate_cached_frame(frame: pd.DataFrame, *, cache_file: Path) -> pd.DataFrame:
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise DataFetchError(f"快取檔案 {cache_file} 缺少必要欄位：{', '.join(missing)}")
    try:
        cleaned = clean_price_data(frame.loc[:, list(STANDARD_COLUMNS)].to_dict("records"))
    except DataValidationError as exc:
        raise DataFetchError(f"快取檔案 {cache_file} 驗證失敗：{exc}") from exc
    if not cleaned.records:
        raise DataFetchError(f"快取檔案 {cache_file} 沒有可用資料列。")
    return pd.DataFrame(cleaned.records)


def _cache_candidates(
    user_symbol: str,
    query_symbols: tuple[str, ...],
    market: str,
) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    for query_symbol in query_symbols:
        candidates.extend(
            [
                (YFINANCE_PROVIDER, query_symbol),
                (FINMIND_PROVIDER, _finmind_symbol(query_symbol)),
            ]
        )
    candidates.extend(
        [
            (STOOQ_PROVIDER, normalize_stooq_symbol(user_symbol, market=market)),
        ]
    )
    unique: list[tuple[str, str]] = []
    for item in candidates:
        if item not in unique:
            unique.append(item)
    return unique


def _cross_market_warnings(
    *,
    primary_symbol: str,
    matched_symbol: str,
    market: str,
) -> tuple[str, ...]:
    """Explain automatic Taiwan TW/TWO fallback when a non-primary suffix works."""

    if primary_symbol == matched_symbol:
        return ()
    if market in {"TWSE", "TPEX", "AUTO"} and {
        primary_symbol.rsplit(".", 1)[-1],
        matched_symbol.rsplit(".", 1)[-1],
    } <= {"TW", "TWO"}:
        return (
            "原本選擇的台股市場後綴查不到資料，系統已自動改用 "
            f"{matched_symbol}。請再確認該股票實際屬於上市或上櫃市場。",
        )
    return ()


def _provider_order(provider: str) -> tuple[str, ...]:
    """Return the legacy explicit order for callers outside registry orchestration."""
    if provider == "auto":
        return (YFINANCE_PROVIDER, FINMIND_PROVIDER, "cache")
    if provider == YFINANCE_PROVIDER:
        return (YFINANCE_PROVIDER, "cache")
    if provider == FINMIND_PROVIDER:
        return (FINMIND_PROVIDER, "cache")
    if provider == "cache":
        return ("cache",)
    raise DataFetchError(f"不支援的資料來源：{provider}")


def _legacy_attempts(records: tuple[object, ...]) -> list[ProviderAttempt]:
    """Project normalized retry records onto the legacy FetchResult attempt API."""

    return [
        ProviderAttempt(
            provider=str(getattr(record, "provider", "provider")),
            success=bool(getattr(record, "success", False)),
            reason=sanitize_provider_text(getattr(record, "reason", "資料來源未回傳原因。")),
        )
        for record in records
    ]


def _record_health(
    tracker: ProviderHealthTracker | None,
    *,
    provider: str,
    market: str,
    success: bool,
    latency_ms: float | None,
    category: ProviderErrorCategory | None = None,
    source_type: str | None = None,
) -> None:
    """Best-effort runtime health recording that cannot alter fetch outcomes."""

    if tracker is None:
        return
    tracker.record(
        provider=provider,
        enabled=True,
        capabilities=(market,),
        success=success,
        latency_ms=latency_ms,
        category=category,
        source_type=source_type,
    )


def _last_data_date(frame: pd.DataFrame) -> str | None:
    """Return the newest usable date for non-sensitive provenance metadata."""

    if frame.empty or "date" not in frame.columns:
        return None
    values = pd.to_datetime(frame["date"], errors="coerce").dropna()
    return values.max().date().isoformat() if not values.empty else None


def _flatten_columns(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy(deep=True)
    if not isinstance(output.columns, pd.MultiIndex):
        return output

    known = {"date", "datetime", "open", "high", "low", "close", "adj close", "volume"}
    flattened: list[str] = []
    for column in output.columns:
        parts = [str(part) for part in column if part not in (None, "")]
        selected = next((part for part in parts if part.strip().lower() in known), parts[0])
        flattened.append(selected)
    output.columns = flattened
    return output


def _normalize_column_name(column: object) -> str:
    return str(column).strip().lower().replace(" ", "_").replace("-", "_")


def _returned_columns(raw: pd.DataFrame | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw.columns, pd.MultiIndex):
        return tuple(
            "|".join(str(part) for part in column if part not in (None, ""))
            for column in raw.columns
        )
    return tuple(str(column) for column in raw.columns)


def _provider_data_error(
    *,
    provider: str,
    user_symbol: str,
    query_symbol: str,
    market: str,
    start: str,
    end: str,
    columns: tuple[str, ...],
    row_count: int,
    reason: str,
) -> str:
    column_text = ", ".join(columns) if columns else "(none)"
    return (
        f"{provider} 沒有回傳可用 OHLCV 股價資料。"
        f"原因：{reason} "
        f"使用者輸入代號={user_symbol}；實際查詢代號={query_symbol}；市場={market}；"
        f"日期區間={start} 到 {end}；回傳欄位={column_text}；回傳筆數={row_count}。"
    )


def _failure_message(
    *,
    user_symbol: str,
    query_symbol: str,
    market: str,
    start: str,
    end: str,
    attempts: list[ProviderAttempt],
) -> str:
    lines = [
        "自動抓資料失敗：所有資料來源都沒有取得可用股價資料。",
        f"使用者輸入代號：{user_symbol}",
        f"實際查詢代號：{query_symbol}",
        f"市場：{market}",
        f"日期區間：{start} 到 {end}",
        "已嘗試資料來源：",
    ]
    for attempt in attempts:
        status = "成功" if attempt.success else "失敗"
        lines.append(f"- {attempt.provider}: {status}，{attempt.reason}")
    lines.append("建議：確認代號、市場與日期區間，或改用「資料匯入」上傳 CSV。")
    return "\n".join(lines)


def _log_fetch_error(message: str, *, log_dir: str | Path) -> None:
    try:
        path = Path(log_dir) / "error.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().isoformat(timespec="seconds")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {message}\n\n")
    except OSError:
        return


def _download_text(url: str, *, timeout_seconds: int) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "stock-analysis-tool/0.1 research"},
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8-sig")


def _parse_date(value: str | date | None) -> date:
    if value is None:
        raise DataFetchError("日期不可為空白。")
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError as exc:
        raise DataFetchError(f"日期格式錯誤，應為 YYYY-MM-DD：{text}") from exc


def _two_years_before(value: date) -> date:
    try:
        return value.replace(year=value.year - 2)
    except ValueError:
        return value - timedelta(days=365 * 2)


def _exclusive_end_date(value: str) -> str:
    return (_parse_date(value) + timedelta(days=1)).isoformat()


def _finmind_symbol(query_symbol: str) -> str:
    return str(query_symbol).upper().replace(".TW", "").replace(".TWO", "")
