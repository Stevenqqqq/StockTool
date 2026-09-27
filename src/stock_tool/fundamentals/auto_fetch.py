"""Best-effort automatic fundamental data fetchers."""

from __future__ import annotations

from stock_tool.yfinance_runtime import configure_yfinance_cache

from dataclasses import dataclass
from datetime import date
from time import monotonic
from typing import Any, Iterable, cast

import pandas as pd
import yfinance as yf

from stock_tool.data.auto_fetch import Market, normalize_market, yfinance_symbol_candidates
from stock_tool.fundamentals.loader import FUNDAMENTAL_COLUMNS, FUNDAMENTAL_METRIC_COLUMNS
from stock_tool.network_deadline import RemoteCallTimeout, call_with_timeout


class FundamentalFetchError(ValueError):
    """Raised when automatic fundamental data cannot produce usable fields."""


@dataclass(frozen=True)
class FundamentalFetchResult:
    """Result returned by automatic fundamental data fetchers."""

    data: pd.DataFrame
    source: str
    symbol: str
    provider_symbol: str
    warnings: tuple[str, ...] = ()


def fetch_yfinance_fundamentals(
    symbol: str,
    *,
    market: Market = "TWSE",
    timeout_seconds: float = 8.0,
) -> FundamentalFetchResult:
    """Fetch best-effort fundamental metrics from yfinance.

    yfinance does not guarantee a complete or point-in-time fundamental
    dataset, especially for non-US stocks. This function only fills fields that
    are present or can be derived from returned statements; missing fields stay
    missing so the scoring layer can mark them as unknown.
    """

    user_symbol = str(symbol).strip()
    if not user_symbol:
        raise FundamentalFetchError("自動抓基本面資料需要股票代號。")

    market_key = cast(Market, normalize_market(market))
    query_symbols = yfinance_symbol_candidates(user_symbol, market=market_key)
    failures: list[str] = []
    deadline = monotonic() + max(0.0, timeout_seconds)

    for query_symbol in query_symbols:
        remaining = deadline - monotonic()
        if remaining <= 0:
            failures.append("Fundamental provider timed out; online fetch was skipped.")
            break
        ticker = _ticker_for_symbol(query_symbol)
        try:
            info, financials, balance_sheet, cashflow = call_with_timeout(
                lambda: _fetch_ticker_payload(ticker), timeout_seconds=remaining
            )
        except RemoteCallTimeout:
            failures.append(
                f"{query_symbol}: Fundamental provider timed out; online fetch was skipped."
            )
            break
        except Exception as exc:
            failures.append(f"{query_symbol}: {exc}")
            continue

        row, warnings = _build_fundamental_row(
            user_symbol=user_symbol,
            provider_symbol=query_symbol,
            market=market_key,
            info=info,
            financials=financials,
            balance_sheet=balance_sheet,
            cashflow=cashflow,
        )
        metric_count = sum(
            not _is_missing(row.get(column)) for column in FUNDAMENTAL_METRIC_COLUMNS
        )
        if metric_count == 0:
            failures.append(f"{query_symbol}：沒有可用的基本面指標")
            continue

        if query_symbol != query_symbols[0]:
            warnings.append("原本選擇的台股市場後綴沒有可用基本面資料；" f"已改用 {query_symbol}。")

        frame = pd.DataFrame([row])
        return FundamentalFetchResult(
            data=frame,
            source="yfinance",
            symbol=user_symbol,
            provider_symbol=query_symbol,
            warnings=tuple(warnings),
        )

    details = "；".join(failures) if failures else "沒有可嘗試的 yfinance 查詢代號"
    raise FundamentalFetchError(f"yfinance 沒有回傳可用基本面指標。{details}")


def _fetch_ticker_payload(
    ticker: Any,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read all optional yfinance fields inside one bounded call."""

    return (
        _ticker_info(ticker),
        _statement_frame(getattr(ticker, "financials", pd.DataFrame())),
        _statement_frame(getattr(ticker, "balance_sheet", pd.DataFrame())),
        _statement_frame(getattr(ticker, "cashflow", pd.DataFrame())),
    )


def _build_fundamental_row(
    *,
    user_symbol: str,
    provider_symbol: str,
    market: str,
    info: dict[str, Any],
    financials: pd.DataFrame,
    balance_sheet: pd.DataFrame,
    cashflow: pd.DataFrame,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = [
        "Automatic fundamentals do not provide a verified historical available_date and are excluded by strict point-in-time strategies.",
        "基本面資料來自 yfinance 盡力補齊，可能不完整或不是最新資料。",
        "缺漏欄位會保持空白，不會為了評分而編造資料。",
    ]
    revenue = _first_number(
        info.get("totalRevenue"),
        _latest_statement_value(financials, ("Total Revenue", "Revenue")),
    )
    previous_revenue = _previous_statement_value(financials, ("Total Revenue", "Revenue"))
    revenue_growth = _first_number(info.get("revenueGrowth"), _growth(revenue, previous_revenue))

    gross_profit = _latest_statement_value(financials, ("Gross Profit",))
    operating_income = _latest_statement_value(
        financials,
        ("Operating Income", "Operating Income or Loss"),
    )
    net_income = _latest_statement_value(
        financials,
        (
            "Net Income",
            "Net Income Common Stockholders",
            "Net Income From Continuing Operation Net Minority Interest",
        ),
    )
    gross_margin = _first_number(info.get("grossMargins"), _ratio(gross_profit, revenue))
    operating_margin = _first_number(
        info.get("operatingMargins"), _ratio(operating_income, revenue)
    )
    net_margin = _first_number(info.get("profitMargins"), _ratio(net_income, revenue))

    total_assets = _latest_statement_value(balance_sheet, ("Total Assets",))
    equity = _latest_statement_value(
        balance_sheet,
        ("Stockholders Equity", "Total Equity Gross Minority Interest", "Common Stock Equity"),
    )
    total_debt = _first_number(
        info.get("totalDebt"),
        _latest_statement_value(balance_sheet, ("Total Debt", "Net Debt")),
    )
    debt_to_equity = _number(info.get("debtToEquity"))
    debt_ratio = _ratio(total_debt, total_assets)
    if debt_ratio is None and debt_to_equity is not None:
        debt_equity_ratio = debt_to_equity / 100.0 if abs(debt_to_equity) > 5 else debt_to_equity
        if debt_equity_ratio >= 0:
            debt_ratio = debt_equity_ratio / (1.0 + debt_equity_ratio)
            warnings.append("負債比是由 yfinance 的 debtToEquity 欄位近似換算，請視為估算值。")

    roe = _first_number(info.get("returnOnEquity"), _ratio(net_income, equity))
    roa = _first_number(info.get("returnOnAssets"), _ratio(net_income, total_assets))

    operating_cash_flow = _first_number(
        info.get("operatingCashflow"),
        _latest_statement_value(
            cashflow, ("Operating Cash Flow", "Total Cash From Operating Activities")
        ),
    )
    free_cash_flow = _first_number(
        info.get("freeCashflow"),
        _latest_statement_value(cashflow, ("Free Cash Flow",)),
    )

    row = {
        "symbol": user_symbol,
        "market": market,
        "fiscal_period": _fiscal_period(financials),
        "period_type": "mixed",
        "as_of_date": date.today().isoformat(),
        "filing_date": pd.NA,
        "available_date": pd.NA,
        "revenue": revenue,
        "revenue_growth_yoy": revenue_growth,
        "eps": _first_number(info.get("trailingEps"), info.get("epsTrailingTwelveMonths")),
        "eps_growth_yoy": _first_number(
            info.get("earningsGrowth"), info.get("earningsQuarterlyGrowth")
        ),
        "gross_margin": gross_margin,
        "operating_margin": operating_margin,
        "net_margin": net_margin,
        "roe": roe,
        "roa": roa,
        "debt_ratio": debt_ratio,
        "operating_cash_flow": operating_cash_flow,
        "free_cash_flow": free_cash_flow,
        "pe_ratio": _first_number(info.get("trailingPE"), info.get("forwardPE")),
        "pb_ratio": _number(info.get("priceToBook")),
        "dividend_yield": _number(info.get("dividendYield")),
        "source": "yfinance",
        "provider_symbol": provider_symbol,
    }
    return {
        column: row.get(column, pd.NA)
        for column in (*FUNDAMENTAL_COLUMNS, "source", "provider_symbol")
    }, warnings


def _ticker_for_symbol(query_symbol: str) -> Any:
    configure_yfinance_cache()
    return yf.Ticker(query_symbol)


def _ticker_info(ticker: Any) -> dict[str, Any]:
    if hasattr(ticker, "get_info"):
        info = ticker.get_info()
    else:
        info = getattr(ticker, "info", {})
    return dict(info or {})


def _statement_frame(value: Any) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value.copy(deep=True)
    return pd.DataFrame()


def _latest_statement_value(frame: pd.DataFrame, row_names: Iterable[str]) -> float | None:
    values = _statement_values(frame, row_names)
    return values[0] if values else None


def _previous_statement_value(frame: pd.DataFrame, row_names: Iterable[str]) -> float | None:
    values = _statement_values(frame, row_names)
    return values[1] if len(values) > 1 else None


def _statement_values(frame: pd.DataFrame, row_names: Iterable[str]) -> list[float]:
    if frame.empty:
        return []
    normalized_index = {_normalize_name(index): index for index in frame.index}
    selected_index = None
    for name in row_names:
        selected_index = normalized_index.get(_normalize_name(name))
        if selected_index is not None:
            break
    if selected_index is None:
        return []
    values: list[float] = []
    for value in frame.loc[selected_index].tolist():
        number = _number(value)
        if number is not None:
            values.append(number)
    return values


def _fiscal_period(financials: pd.DataFrame) -> str:
    if not financials.empty and len(financials.columns) > 0:
        first_column = financials.columns[0]
        if isinstance(first_column, pd.Timestamp):
            return first_column.date().isoformat()
        return str(first_column)
    return f"latest_{date.today().isoformat()}"


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _number(value)
        if number is not None:
            return number
    return None


def _number(value: Any) -> float | None:
    if _is_missing(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ratio(numerator: Any, denominator: Any) -> float | None:
    top = _number(numerator)
    bottom = _number(denominator)
    if top is None or bottom is None or bottom == 0.0:
        return None
    return top / bottom


def _growth(current: Any, previous: Any) -> float | None:
    current_value = _number(current)
    previous_value = _number(previous)
    if current_value is None or previous_value is None or previous_value == 0.0:
        return None
    return (current_value - previous_value) / abs(previous_value)


def _is_missing(value: Any) -> bool:
    return value is None or pd.isna(value)


def _normalize_name(value: Any) -> str:
    return str(value).strip().lower().replace("_", " ")
