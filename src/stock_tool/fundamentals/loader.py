"""CSV loader for fundamental financial data."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pandas as pd

from stock_tool.domain.models import Market

FUNDAMENTAL_IDENTITY_COLUMNS = (
    "symbol",
    "market",
    "fiscal_period",
)

FUNDAMENTAL_METADATA_COLUMNS = (
    "period_type",
    "as_of_date",
    "filing_date",
    "available_date",
    "source",
)

FUNDAMENTAL_METRIC_COLUMNS = (
    "revenue",
    "revenue_growth_yoy",
    "eps",
    "eps_growth_yoy",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "roe",
    "roa",
    "debt_ratio",
    "operating_cash_flow",
    "free_cash_flow",
    "pe_ratio",
    "pb_ratio",
    "dividend_yield",
)

FUNDAMENTAL_COLUMNS = (
    *FUNDAMENTAL_IDENTITY_COLUMNS,
    *FUNDAMENTAL_METADATA_COLUMNS,
    *FUNDAMENTAL_METRIC_COLUMNS,
)

REQUIRED_COLUMNS = ("symbol", "fiscal_period")

NUMERIC_COLUMNS = FUNDAMENTAL_METRIC_COLUMNS

COLUMN_ALIASES = {
    "symbol": "symbol",
    "ticker": "symbol",
    "code": "symbol",
    "stock_id": "symbol",
    "股票代號": "symbol",
    "fiscal_period": "fiscal_period",
    "period": "fiscal_period",
    "quarter": "fiscal_period",
    "market": "market",
    "exchange": "market",
    "period_type": "period_type",
    "basis": "period_type",
    "as_of_date": "as_of_date",
    "as_of": "as_of_date",
    "filing_date": "filing_date",
    "filed_date": "filing_date",
    "available_date": "available_date",
    "availability_date": "available_date",
    "source": "source",
    "財報期間": "fiscal_period",
    "revenue": "revenue",
    "營收": "revenue",
    "revenue_growth_yoy": "revenue_growth_yoy",
    "revenue_yoy": "revenue_growth_yoy",
    "營收年增率": "revenue_growth_yoy",
    "eps": "eps",
    "每股盈餘": "eps",
    "eps_growth_yoy": "eps_growth_yoy",
    "eps_yoy": "eps_growth_yoy",
    "eps年增率": "eps_growth_yoy",
    "gross_margin": "gross_margin",
    "毛利率": "gross_margin",
    "operating_margin": "operating_margin",
    "營業利益率": "operating_margin",
    "net_margin": "net_margin",
    "淨利率": "net_margin",
    "roe": "roe",
    "roa": "roa",
    "debt_ratio": "debt_ratio",
    "負債比": "debt_ratio",
    "operating_cash_flow": "operating_cash_flow",
    "ocf": "operating_cash_flow",
    "營業現金流": "operating_cash_flow",
    "free_cash_flow": "free_cash_flow",
    "fcf": "free_cash_flow",
    "自由現金流": "free_cash_flow",
    "pe_ratio": "pe_ratio",
    "pe": "pe_ratio",
    "本益比": "pe_ratio",
    "pb_ratio": "pb_ratio",
    "pb": "pb_ratio",
    "股價淨值比": "pb_ratio",
    "dividend_yield": "dividend_yield",
    "殖利率": "dividend_yield",
}


class FundamentalDataError(ValueError):
    """Raised when fundamental input data cannot be loaded safely."""


def load_fundamentals_csv(
    file_path: str | Path,
    *,
    encoding: str = "utf-8-sig",
    column_mapping: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    """Load and standardize a fundamental CSV file.

    ``symbol`` and ``fiscal_period`` are required. Financial fields that are
    absent from the CSV are added as missing values so the scoring layer can
    explicitly mark insufficient data as ``unknown``.
    """

    path = Path(file_path)
    frame = pd.read_csv(path, encoding=encoding, dtype={"symbol": str})
    if frame.empty:
        raise FundamentalDataError("Fundamental CSV is empty.")

    frame = _rename_columns(frame, column_mapping)
    missing_required = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing_required:
        raise FundamentalDataError(
            f"Fundamental CSV missing required columns: {', '.join(missing_required)}"
        )

    output = frame.copy(deep=True)
    output["symbol"] = output["symbol"].astype("string").str.strip()
    output["fiscal_period"] = output["fiscal_period"].astype("string").str.strip()
    if "market" not in output.columns:
        output["market"] = "UNKNOWN"
    output["market"] = output["market"].map(normalize_fundamental_market)
    if "period_type" not in output.columns:
        output["period_type"] = "unknown"
    output["period_type"] = output["period_type"].map(_normalize_period_type)
    if "as_of_date" not in output.columns:
        output["as_of_date"] = pd.NA
    output["as_of_date"] = _normalize_optional_date(output["as_of_date"])
    for column in ("filing_date", "available_date"):
        if column not in output.columns:
            output[column] = pd.NA
        output[column] = _normalize_optional_date(output[column])
    if "source" not in output.columns:
        output["source"] = "unknown"
    output["source"] = output["source"].astype("string").str.strip().replace("", "unknown")
    _validate_required_values(output)
    output["symbol"] = output["symbol"].astype(str).str.upper()
    output["fiscal_period"] = output["fiscal_period"].astype(str)

    for column in NUMERIC_COLUMNS:
        if column not in output.columns:
            output[column] = pd.NA
        output[column] = pd.to_numeric(output[column], errors="coerce")

    ordered_columns = list(FUNDAMENTAL_COLUMNS)
    extra_columns = [column for column in output.columns if column not in ordered_columns]
    return output.loc[:, ordered_columns + extra_columns]


def _validate_required_values(frame: pd.DataFrame) -> None:
    blank_symbol = frame["symbol"].isna() | frame["symbol"].astype(str).str.strip().eq("")
    blank_period = frame["fiscal_period"].isna() | frame["fiscal_period"].astype(
        str
    ).str.strip().eq("")
    if blank_symbol.any():
        rows = ", ".join(str(index + 2) for index in frame.index[blank_symbol].tolist())
        raise FundamentalDataError(f"Fundamental CSV contains blank symbol at row(s): {rows}.")
    if blank_period.any():
        rows = ", ".join(str(index + 2) for index in frame.index[blank_period].tolist())
        raise FundamentalDataError(
            f"Fundamental CSV contains blank fiscal_period at row(s): {rows}."
        )

    duplicate_columns = ["symbol", "market", "fiscal_period"]
    duplicate_mask = frame.duplicated(duplicate_columns, keep=False)
    if duplicate_mask.any():
        duplicate_keys = (
            frame.loc[duplicate_mask, duplicate_columns]
            .drop_duplicates()
            .astype(str)
            .agg("/".join, axis=1)
            .tolist()
        )
        raise FundamentalDataError(
            "Fundamental CSV contains duplicate symbol/fiscal_period rows within market: "
            + ", ".join(duplicate_keys)
        )


def _rename_columns(
    frame: pd.DataFrame,
    column_mapping: Mapping[str, str] | None,
) -> pd.DataFrame:
    explicit_mapping = {
        _normalize_name(source): target for source, target in (column_mapping or {}).items()
    }
    rename_map: dict[str, str] = {}
    for column in frame.columns:
        normalized = _normalize_name(str(column))
        mapped = explicit_mapping.get(normalized, COLUMN_ALIASES.get(normalized, normalized))
        rename_map[column] = mapped
    return frame.rename(columns=rename_map)


def _normalize_name(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def normalize_fundamental_market(value: object) -> str:
    """Return a canonical research market without guessing legacy identities."""

    if value is None or pd.isna(value):
        return "UNKNOWN"
    try:
        market = Market.parse(str(value))
    except ValueError:
        return "UNKNOWN"
    return market.value if market in {Market.TWSE, Market.TPEX, Market.US} else "UNKNOWN"


def _normalize_period_type(value: object) -> str:
    if value is None or pd.isna(value):
        return "unknown"
    normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "fy": "annual",
        "year": "annual",
        "yearly": "annual",
        "annual": "annual",
        "quarter": "quarterly",
        "quarterly": "quarterly",
        "ttm": "ttm",
        "trailing_twelve_months": "ttm",
        "mixed": "mixed",
        "unknown": "unknown",
        "": "unknown",
    }
    return aliases.get(normalized, "unknown")


def _normalize_optional_date(values: pd.Series) -> pd.Series:
    text = values.astype("string").str.strip().replace("", pd.NA)
    parsed = pd.to_datetime(text, errors="coerce")
    normalized = parsed.dt.strftime("%Y-%m-%d").astype("string")
    return normalized.where(parsed.notna(), pd.NA)
