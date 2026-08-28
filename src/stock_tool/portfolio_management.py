"""Manual portfolio tracking helpers.

This module is deliberately limited to position bookkeeping and unrealized P/L
analysis. It does not place orders and does not connect to any broker.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import pandas as pd

from stock_tool.domain.models import Market, MissingData, MissingDataState
from stock_tool.runtime_paths import default_runtime_paths

DEFAULT_PORTFOLIO_PATH = default_runtime_paths().portfolio_file
PORTFOLIO_COLUMNS = ("symbol", "quantity", "average_cost", "market", "currency", "note")


@dataclass(frozen=True, slots=True)
class PortfolioLoadResult:
    """Normalized legacy-compatible portfolio data and explicit migration warnings."""

    frame: pd.DataFrame
    warnings: tuple[str, ...] = ()
    missing_data: tuple[MissingData, ...] = ()


def load_portfolio(path: str | Path | None = None) -> pd.DataFrame:
    """Load a local manual portfolio CSV, returning an empty schema if absent."""

    return load_portfolio_result(path).frame


def load_portfolio_result(path: str | Path | None = None) -> PortfolioLoadResult:
    """Load a portfolio with explicit warnings for ambiguous legacy records."""

    file_path = _resolve_portfolio_path(path)
    if not file_path.exists():
        return PortfolioLoadResult(frame=_empty_portfolio())
    try:
        frame = pd.read_csv(
            file_path, dtype={"symbol": str, "market": str, "currency": str, "note": str}
        )
    except (OSError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        return PortfolioLoadResult(
            frame=_empty_portfolio(),
            warnings=(f"Portfolio file could not be read: {exc}",),
            missing_data=(
                MissingData(
                    field="portfolio",
                    state=MissingDataState.UNKNOWN,
                    reason="The local portfolio CSV could not be parsed.",
                ),
            ),
        )
    warnings, missing_data = _legacy_portfolio_warnings(frame)
    return PortfolioLoadResult(
        frame=normalize_portfolio(frame), warnings=tuple(warnings), missing_data=tuple(missing_data)
    )


def save_portfolio(
    frame: pd.DataFrame,
    path: str | Path | None = None,
) -> Path:
    """Save a normalized manual portfolio CSV and return the path."""

    output = normalize_portfolio(frame)
    file_path = _resolve_portfolio_path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(file_path, index=False, encoding="utf-8-sig")
    return file_path


def add_portfolio_position(
    frame: pd.DataFrame,
    *,
    symbol: str,
    quantity: float,
    average_cost: float,
    market: str = "TWSE",
    currency: str | None = None,
    note: str = "",
) -> pd.DataFrame:
    """Return a new portfolio with one position added or updated."""

    canonical_market = _canonical_market(market)
    normalized_currency = _normalized_currency(currency, canonical_market)
    item = pd.DataFrame(
        [
            {
                "symbol": str(symbol).strip(),
                "quantity": quantity,
                "average_cost": average_cost,
                "market": canonical_market,
                "currency": normalized_currency,
                "note": note,
            }
        ]
    )
    combined = pd.concat([normalize_portfolio(frame), item], ignore_index=True)
    return normalize_portfolio(combined)


def remove_portfolio_position(
    frame: pd.DataFrame,
    *,
    symbol: str,
    market: str | None = None,
) -> pd.DataFrame:
    """Return a new portfolio with one market-qualified position removed.

    ``market=None`` remains a temporary compatibility path only when the symbol
    occurs once. Ambiguous requests are rejected rather than removing multiple
    market identities.
    """

    output = normalize_portfolio(frame)
    symbol_key = str(symbol).strip()
    matches = output.loc[output["symbol"].astype(str) == symbol_key]
    if market is None:
        if len(matches) != 1:
            raise ValueError("Removing a portfolio position requires a market-qualified identity.")
        market_key = str(matches.iloc[0]["market"])
    else:
        market_key = _canonical_market(market)
    mask = ~(
        (output["symbol"].astype(str) == symbol_key)
        & (output["market"].astype(str).str.upper() == market_key)
    )
    return output.loc[mask, list(PORTFOLIO_COLUMNS)].reset_index(drop=True)


def normalize_portfolio(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize manual portfolio columns without mutating input data."""

    output = frame.copy(deep=True)
    for column in PORTFOLIO_COLUMNS:
        if column not in output.columns:
            output[column] = ""
    output = output.loc[:, list(PORTFOLIO_COLUMNS)].copy(deep=True)
    output["symbol"] = output["symbol"].fillna("").astype(str).str.strip().str.upper()
    output["market"] = output["market"].fillna("").astype(str).str.strip().str.upper()
    output["market"] = output["market"].map(_canonical_market_or_unknown)
    output["currency"] = [
        _currency_or_unknown(currency, market)
        for currency, market in zip(output["currency"], output["market"], strict=True)
    ]
    output["note"] = output["note"].fillna("").astype(str)
    output["quantity"] = pd.to_numeric(output["quantity"], errors="coerce").fillna(0.0)
    output["average_cost"] = pd.to_numeric(output["average_cost"], errors="coerce").fillna(0.0)
    output = output.loc[(output["symbol"] != "") & (output["quantity"] > 0)]
    output = output.drop_duplicates(subset=["symbol", "market"], keep="last")
    return output.sort_values(["market", "symbol"]).reset_index(drop=True)


def portfolio_summary(
    positions: pd.DataFrame,
    latest_prices: pd.DataFrame | None,
) -> pd.DataFrame:
    """Calculate market value and unrealized P/L from manual positions."""

    normalized = normalize_portfolio(positions)
    if normalized.empty:
        return pd.DataFrame(
            columns=[
                "symbol",
                "market",
                "quantity",
                "average_cost",
                "latest_price",
                "cost_basis",
                "market_value",
                "unrealized_pnl",
                "unrealized_pnl_pct",
                "weight",
                "note",
            ]
        )

    price_lookup = _latest_price_lookup(latest_prices)
    output = normalized.copy(deep=True)
    output["latest_price"] = [
        price_lookup.get((str(row.symbol).upper(), str(row.market).upper()))
        for row in output[["symbol", "market"]].itertuples(index=False)
    ]
    output["cost_basis"] = output["quantity"] * output["average_cost"]
    output["market_value"] = output["quantity"] * pd.to_numeric(
        output["latest_price"],
        errors="coerce",
    )
    output["unrealized_pnl"] = output["market_value"] - output["cost_basis"]
    output["unrealized_pnl_pct"] = output["unrealized_pnl"] / output["cost_basis"].where(
        output["cost_basis"] != 0
    )
    total_market_value = output["market_value"].sum(skipna=True)
    same_currency = output["currency"].nunique(dropna=False) == 1 and str(
        output["currency"].iloc[0]
    ).upper() in {"TWD", "USD"}
    complete_prices = output["market_value"].notna().all()
    if same_currency and complete_prices and total_market_value and total_market_value > 0:
        output["weight"] = output["market_value"] / total_market_value
    else:
        output["weight"] = pd.NA
    return output[
        [
            "symbol",
            "market",
            "quantity",
            "average_cost",
            "latest_price",
            "cost_basis",
            "market_value",
            "unrealized_pnl",
            "unrealized_pnl_pct",
            "weight",
            "note",
        ]
    ]


def _latest_price_lookup(latest_prices: pd.DataFrame | None) -> dict[tuple[str, str], float]:
    if latest_prices is None or latest_prices.empty:
        return {}
    if not {"symbol", "market", "close"}.issubset(latest_prices.columns):
        return {}

    output = latest_prices.copy(deep=True)
    output["market"] = output["market"].map(_price_market_or_empty)
    output = output.loc[output["market"] != ""].copy(deep=True)
    if "date" in output.columns:
        output = output.sort_values(["symbol", "market", "date"])
    latest = output.groupby(["symbol", "market"], as_index=False, sort=False).tail(1)
    return {
        (str(row["symbol"]).upper(), _canonical_market(str(row["market"]))): float(row["close"])
        for _, row in latest.iterrows()
        if pd.notna(row.get("close"))
    }


def _resolve_portfolio_path(path: str | Path | None) -> Path:
    return default_runtime_paths().portfolio_file if path is None else Path(path)


def _empty_portfolio() -> pd.DataFrame:
    return pd.DataFrame(columns=list(PORTFOLIO_COLUMNS))


def _canonical_market(value: str) -> str:
    market = Market.parse(value)
    if market in {Market.AUTO, Market.CUSTOM}:
        return market.value
    return market.value


def _canonical_market_or_unknown(value: str) -> str:
    if not value:
        return "UNKNOWN"
    try:
        return _canonical_market(value)
    except ValueError:
        return "UNKNOWN"


def _normalized_currency(value: str | None, market: str) -> str:
    raw = str(value or "").strip().upper()
    if raw:
        if raw not in {"TWD", "USD"}:
            raise ValueError("Unsupported portfolio currency. Use TWD or USD.")
        return raw
    defaults = {"TWSE": "TWD", "TPEX": "TWD", "US": "USD"}
    if market in defaults:
        return defaults[market]
    raise ValueError(f"Market {market} requires an explicit currency.")


def _currency_or_unknown(value: str | None, market: str) -> str:
    try:
        return _normalized_currency(value, market)
    except ValueError:
        return "UNKNOWN"


def _legacy_portfolio_warnings(frame: pd.DataFrame) -> tuple[list[str], list[MissingData]]:
    warnings: list[str] = []
    missing_data: list[MissingData] = []
    missing_columns = sorted(set(PORTFOLIO_COLUMNS).difference(frame.columns))
    if missing_columns:
        warnings.append(f"Portfolio CSV is missing columns: {', '.join(missing_columns)}.")
    if (
        "market" not in frame.columns
        or frame.get("market", pd.Series(dtype=str)).fillna("").eq("").any()
    ):
        missing_data.append(
            MissingData(
                field="portfolio.market",
                state=MissingDataState.UNKNOWN,
                reason="Legacy portfolio rows without a market are retained as UNKNOWN and are not inferred.",
            )
        )
    if "currency" not in frame.columns:
        warnings.append(
            "Legacy portfolio has no currency column; standard markets receive documented defaults."
        )
    return warnings, missing_data


def _price_market_or_empty(value: object) -> str:
    try:
        market = _canonical_market(str(value))
        return market if market in {"TWSE", "TPEX", "US"} else ""
    except ValueError:
        return ""
