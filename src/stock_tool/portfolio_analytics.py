"""Pure portfolio analytics input preparation.

The dashboard is intentionally kept as a renderer. This module prepares the
canonical, market-qualified inputs consumed by portfolio health analysis.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from stock_tool.domain.models import MissingData, MissingDataState

CANONICAL_MARKETS = frozenset({"TWSE", "TPEX", "US"})
IDENTITY_COLUMN = "\u8b58\u5225"
PORTFOLIO_WIDE_LABEL = "\u6574\u9ad4\u6295\u8cc7\u7d44\u5408"
UNKNOWN_IDENTITY_LABEL = "\u7121\u6cd5\u5224\u5b9a"


@dataclass(frozen=True, slots=True)
class PortfolioIdentity:
    """A normalized, market-qualified portfolio identity."""

    symbol: str
    market: str

    def __post_init__(self) -> None:
        symbol = str(self.symbol).strip().upper()
        market = str(self.market).strip().upper()
        if not symbol or market not in CANONICAL_MARKETS:
            raise ValueError("PortfolioIdentity requires a canonical symbol and market.")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "market", market)

    @property
    def label(self) -> str:
        """Return the user-facing symbol/market label."""

        return f"{self.symbol}/{self.market}"


@dataclass(frozen=True, slots=True)
class PortfolioDataGap:
    """Structured missing-data metadata for one UI-visible data gap."""

    missing_data: MissingData
    affected_identities: tuple[PortfolioIdentity, ...] = ()


@dataclass(frozen=True, slots=True)
class PortfolioRiskInputResult:
    """One immutable snapshot of per-position risk inputs and data gaps."""

    frame: pd.DataFrame
    missing_data: tuple[MissingData, ...]
    warnings: tuple[str, ...] = ()
    data_gaps: tuple[PortfolioDataGap, ...] = ()


def build_portfolio_risk_inputs(
    prices: pd.DataFrame | None,
    positions: pd.DataFrame,
    *,
    volatility_window: int = 20,
) -> PortfolioRiskInputResult:
    """Build one volatility/drawdown row per ``symbol + market`` position.

    Volatility uses only trailing close-to-close returns in the supplied
    history. Drawdown is the minimum close-to-running-peak ratio over that
    same loaded history. Unknown markets and insufficient histories remain
    missing; no value is filled with zero.
    """

    if volatility_window <= 0:
        raise ValueError("volatility_window must be positive")
    identities = _position_identities(positions)
    columns = [
        "symbol",
        "market",
        "volatility_20",
        "max_drawdown",
        "observation_count",
        "source",
    ]
    if identities.empty:
        return PortfolioRiskInputResult(pd.DataFrame(columns=columns), ())

    work = _prepare_prices(prices)
    rows: list[dict[str, object]] = []
    missing: list[MissingData] = []
    data_gaps: list[PortfolioDataGap] = []
    for identity_row in identities.itertuples(index=False):
        identity = PortfolioIdentity(identity_row.symbol, identity_row.market)
        history = work.loc[
            (work["symbol"] == identity.symbol) & (work["market"] == identity.market)
        ].copy()
        observations = len(history)
        volatility: float | None = None
        drawdown: float | None = None
        if observations >= 2:
            closes = history["close"].astype(float)
            peak = closes.cummax()
            drawdown = float((closes / peak - 1.0).min())
        if observations >= volatility_window + 1:
            returns = history["close"].pct_change().dropna()
            if len(returns) >= volatility_window:
                volatility = float(returns.tail(volatility_window).std(ddof=0))
        if volatility is None:
            item = MissingData(
                field="technical_indicators",
                state=MissingDataState.MISSING,
                reason=(
                    f"{identity.label} lacks {volatility_window + 1} valid closes required for "
                    f"volatility_{volatility_window}."
                ),
            )
            missing.append(item)
            data_gaps.append(PortfolioDataGap(item, (identity,)))
        if drawdown is None:
            item = MissingData(
                field="portfolio_prices",
                state=MissingDataState.MISSING,
                reason=f"{identity.label} lacks at least two valid closes for loaded-period drawdown.",
            )
            missing.append(item)
            data_gaps.append(PortfolioDataGap(item, (identity,)))
        rows.append(
            {
                "symbol": identity.symbol,
                "market": identity.market,
                "volatility_20": volatility,
                "max_drawdown": drawdown,
                "observation_count": observations,
                "source": "loaded_close_history",
            }
        )

    return PortfolioRiskInputResult(
        frame=pd.DataFrame(rows, columns=columns),
        missing_data=_unique_missing(missing),
        data_gaps=_unique_data_gaps(data_gaps),
    )


def build_portfolio_data_gaps(
    *,
    positions: pd.DataFrame,
    missing_data: tuple[MissingData, ...],
    structured_gaps: tuple[PortfolioDataGap, ...] = (),
) -> pd.DataFrame:
    """Create a user-facing gap table from structured missing-data metadata.

    ``positions`` is retained for API compatibility but is never used to infer
    an affected identity. A gap without structured identity metadata is shown
    as unknown. This deliberately avoids parsing the free-text reason field.
    """

    del positions
    identities_by_gap = _gap_identity_index(structured_gaps)
    rows = [
        {
            "\u529f\u80fd": item.field,
            "\u7f3a\u5c11\u8cc7\u6599": item.state.value,
            IDENTITY_COLUMN: _affected_identity_label(item, identities_by_gap),
            "\u539f\u56e0": item.reason,
            "\u4fee\u5fa9\u65b9\u5f0f": _repair_action(item.field, item.state),
            "\u53ef\u81ea\u52d5\u88dc\u9f4a": (
                "\u53ef\u5617\u8a66\u5f9e\u5df2\u8f09\u5165\u50f9\u683c\u6216\u8cc7\u6599\u4f86\u6e90\u88dc\u9f4a"
                if item.field != "portfolio_fx"
                else "\u5426\uff0c\u9700\u8f38\u5165\u624b\u52d5 USD/TWD \u532f\u7387"
            ),
        }
        for item in _unique_missing(list(missing_data))
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "\u529f\u80fd",
            "\u7f3a\u5c11\u8cc7\u6599",
            IDENTITY_COLUMN,
            "\u539f\u56e0",
            "\u4fee\u5fa9\u65b9\u5f0f",
            "\u53ef\u81ea\u52d5\u88dc\u9f4a",
        ],
    )


def _prepare_prices(prices: pd.DataFrame | None) -> pd.DataFrame:
    required = {"symbol", "market", "date", "close"}
    if prices is None or prices.empty or not required.issubset(prices.columns):
        return pd.DataFrame(columns=sorted(required))
    output = prices.loc[:, ["symbol", "market", "date", "close"]].copy(deep=True)
    output["symbol"] = output["symbol"].fillna("").astype(str).str.strip().str.upper()
    output["market"] = output["market"].fillna("").astype(str).str.strip().str.upper()
    output["date"] = pd.to_datetime(output["date"], errors="coerce")
    output["close"] = pd.to_numeric(output["close"], errors="coerce")
    output = output.loc[
        output["symbol"].ne("")
        & output["market"].isin(CANONICAL_MARKETS)
        & output["date"].notna()
        & output["close"].gt(0)
    ].copy()
    return (
        output.sort_values(["symbol", "market", "date"], kind="stable")
        .drop_duplicates(["symbol", "market", "date"], keep="last")
        .reset_index(drop=True)
    )


def _position_identities(positions: pd.DataFrame | None) -> pd.DataFrame:
    if positions is None or positions.empty or not {"symbol", "market"}.issubset(positions.columns):
        return pd.DataFrame(columns=["symbol", "market"])
    output = positions.loc[:, ["symbol", "market"]].copy(deep=True)
    output["symbol"] = output["symbol"].fillna("").astype(str).str.strip().str.upper()
    output["market"] = output["market"].fillna("").astype(str).str.strip().str.upper()
    return (
        output.loc[output["symbol"].ne("") & output["market"].isin(CANONICAL_MARKETS)]
        .drop_duplicates(["symbol", "market"], keep="first")
        .sort_values(["symbol", "market"], kind="stable")
        .reset_index(drop=True)
    )


def _gap_identity_index(
    structured_gaps: tuple[PortfolioDataGap, ...],
) -> dict[MissingData, tuple[PortfolioIdentity, ...]]:
    output: dict[MissingData, list[PortfolioIdentity]] = {}
    for gap in structured_gaps:
        output.setdefault(gap.missing_data, []).extend(gap.affected_identities)
    return {item: tuple(dict.fromkeys(identities)) for item, identities in output.items()}


def _affected_identity_label(
    item: MissingData,
    identities_by_gap: dict[MissingData, tuple[PortfolioIdentity, ...]],
) -> str:
    if item.field == "portfolio_fx":
        return PORTFOLIO_WIDE_LABEL
    identities = identities_by_gap.get(item, ())
    return ", ".join(identity.label for identity in identities) or UNKNOWN_IDENTITY_LABEL


def _repair_action(field: str, state: MissingDataState) -> str:
    if state is MissingDataState.STALE:
        return "\u91cd\u65b0\u6574\u7406\u8cc7\u6599\u4f86\u6e90\u6216\u66f4\u65b0\u5feb\u53d6"
    if field == "portfolio_fx":
        return "\u8f38\u5165\u6709\u6548 USD/TWD \u532f\u7387\u4e26\u6309\u5957\u7528"
    if field in {"technical_indicators", "portfolio_prices"}:
        return "\u66f4\u65b0\u8a72\u6301\u80a1\u7684\u50f9\u683c\u6b77\u53f2\uff0c\u81f3\u5c11\u63d0\u4f9b\u8db3\u5920\u65e5\u7dda\u8cc7\u6599"
    if field == "composite_score":
        return "\u88dc\u9f4a\u8a72 symbol + market \u7684\u5b8c\u6574\u7d9c\u5408\u8a55\u5206\u8f38\u5165"
    return "\u88dc\u9f4a\u5c0d\u61c9\u8cc7\u6599\u5f8c\u91cd\u65b0\u6574\u7406"


def _unique_missing(items: list[MissingData]) -> tuple[MissingData, ...]:
    seen: set[tuple[str, MissingDataState, str]] = set()
    output: list[MissingData] = []
    for item in items:
        key = (item.field, item.state, item.reason)
        if key not in seen:
            seen.add(key)
            output.append(item)
    return tuple(output)


def _unique_data_gaps(items: list[PortfolioDataGap]) -> tuple[PortfolioDataGap, ...]:
    seen: set[tuple[MissingData, tuple[PortfolioIdentity, ...]]] = set()
    output: list[PortfolioDataGap] = []
    for item in items:
        key = (item.missing_data, item.affected_identities)
        if key not in seen:
            seen.add(key)
            output.append(item)
    return tuple(output)
