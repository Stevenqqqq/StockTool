"""Persistent watchlist helpers for local research workflows."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from stock_tool.domain.models import Market, Symbol
from stock_tool.portfolio_management import normalize_portfolio
from stock_tool.runtime_paths import default_runtime_paths

DEFAULT_WATCHLIST_PATH = default_runtime_paths().watchlist_file
WATCHLIST_COLUMNS = ("symbol", "market", "note")
EFFECTIVE_WATCHLIST_COLUMNS = (*WATCHLIST_COLUMNS, "tracking_source")
_TRACKABLE_MARKETS = frozenset({Market.TWSE, Market.TPEX, Market.US})


def load_watchlist(path: str | Path | None = None) -> pd.DataFrame:
    """Load a local watchlist CSV, returning an empty schema when absent."""

    file_path = default_runtime_paths().watchlist_file if path is None else Path(path)
    if not file_path.exists():
        return pd.DataFrame(columns=list(WATCHLIST_COLUMNS))
    frame = pd.read_csv(file_path, dtype={"symbol": str, "market": str, "note": str})
    return normalize_watchlist(frame)


def save_watchlist(
    frame: pd.DataFrame,
    path: str | Path | None = None,
) -> Path:
    """Save a normalized watchlist CSV and return the written path."""

    output = normalize_watchlist(frame)
    file_path = default_runtime_paths().watchlist_file if path is None else Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(file_path, index=False, encoding="utf-8-sig")
    return file_path


def add_watchlist_symbol(
    frame: pd.DataFrame,
    *,
    symbol: str,
    market: str = "TW",
    note: str = "",
) -> pd.DataFrame:
    """Return a new watchlist with one symbol added or updated."""

    item = pd.DataFrame(
        [{"symbol": str(symbol).strip(), "market": str(market).strip().upper(), "note": note}]
    )
    combined = pd.concat([normalize_watchlist(frame), item], ignore_index=True)
    return normalize_watchlist(combined)


def remove_watchlist_symbol(
    frame: pd.DataFrame,
    *,
    symbol: str,
    market: str | None = None,
) -> pd.DataFrame:
    """Return a new watchlist with matching symbols removed."""

    output = normalize_watchlist(frame)
    symbol_key = str(symbol).strip()
    if market is None:
        mask = output["symbol"].astype(str) != symbol_key
    else:
        market_key = str(market).strip().upper()
        mask = ~(
            (output["symbol"].astype(str) == symbol_key)
            & (output["market"].astype(str).str.upper() == market_key)
        )
    return output.loc[mask, list(WATCHLIST_COLUMNS)].reset_index(drop=True)


def normalize_watchlist(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize watchlist columns without mutating the caller's DataFrame."""

    output = frame.copy(deep=True)
    for column in WATCHLIST_COLUMNS:
        if column not in output.columns:
            output[column] = ""
    output = output.loc[:, list(WATCHLIST_COLUMNS)].copy(deep=True)
    output["symbol"] = output["symbol"].fillna("").astype(str).str.strip()
    output["market"] = output["market"].fillna("TW").astype(str).str.strip().str.upper()
    output["market"] = output["market"].replace("", "TW")
    output["note"] = output["note"].fillna("").astype(str)
    output = output.loc[output["symbol"] != ""]
    output = output.drop_duplicates(subset=["symbol", "market"], keep="last")
    return output.sort_values(["market", "symbol"]).reset_index(drop=True)


def build_effective_watchlist(manual: pd.DataFrame, portfolio: pd.DataFrame) -> pd.DataFrame:
    """Return manual tracking plus in-memory, market-qualified holdings tracking.

    Persisted watchlist rows remain the only editable source.  Holdings add an
    in-memory tracking row only when their market is explicitly resolvable as
    TWSE, TPEX, or US; ambiguous markets are never guessed or auto-written.
    """

    rows: dict[tuple[str, str], dict[str, str]] = {}
    for row in normalize_watchlist(manual).itertuples(index=False):
        identity = _trackable_identity(row.symbol, row.market)
        if identity is None:
            key = (str(row.market).strip().upper(), str(row.symbol).strip().upper())
            rows[key] = {
                "symbol": str(row.symbol).strip().upper(),
                "market": str(row.market).strip().upper(),
                "note": str(row.note),
                "tracking_source": "手動自選",
            }
            continue
        rows[identity] = {
            "symbol": identity[1],
            "market": identity[0],
            "note": str(row.note),
            "tracking_source": "手動自選",
        }

    normalized_portfolio = normalize_portfolio(portfolio)
    for row in normalized_portfolio.itertuples(index=False):
        identity = _trackable_identity(row.symbol, row.market)
        if identity is None:
            continue
        existing = rows.get(identity)
        if existing is None:
            rows[identity] = {
                "symbol": identity[1],
                "market": identity[0],
                "note": "",
                "tracking_source": "持股自動追蹤",
            }
        elif existing["tracking_source"] == "手動自選":
            existing["tracking_source"] = "手動自選＋持股"

    return (
        pd.DataFrame(rows.values(), columns=list(EFFECTIVE_WATCHLIST_COLUMNS))
        .sort_values(["market", "symbol"], kind="stable")
        .reset_index(drop=True)
    )


def _trackable_identity(symbol: object, market: object) -> tuple[str, str] | None:
    """Return an explicit canonical identity without inferring ambiguous markets."""

    try:
        parsed = Symbol.parse(str(symbol), market=str(market))
    except ValueError:
        return None
    if parsed.market not in _TRACKABLE_MARKETS:
        return None
    return parsed.market.value, parsed.code
