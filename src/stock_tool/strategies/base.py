"""Base classes and helpers for pluggable research strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, ClassVar

import pandas as pd


class StrategyParameterError(ValueError):
    """Raised when strategy parameters are invalid."""


class StrategyBase(ABC):
    """Abstract base class for all pluggable research strategies."""

    name: ClassVar[str] = "base"
    description: ClassVar[str] = "策略基礎介面。"
    risk_notes: ClassVar[tuple[str, ...]] = (
        "這是研究訊號，不是個人化投資建議。",
    )
    default_parameters: ClassVar[Mapping[str, Any]] = {
        "quantity": None,
        "cash_amount": None,
        "target_percent": 1.0,
    }

    def __init__(self, **parameters: Any) -> None:
        explicit = set(parameters)
        merged = dict(self.default_parameters)
        merged.update(parameters)
        if ("quantity" in explicit or "cash_amount" in explicit) and "target_percent" not in explicit:
            merged["target_percent"] = None
        self.parameters: dict[str, Any] = merged
        self.validate_parameters()

    @abstractmethod
    def validate_parameters(self) -> None:
        """Validate strategy parameters and raise on invalid values."""

    @abstractmethod
    def generate_signals(
        self,
        price_data: pd.DataFrame,
        fundamentals: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Generate a DataFrame containing ``date``, ``symbol``, and ``signal``.

        Signals must be numeric: ``1`` for buy, ``0`` for no action, and ``-1``
        for sell. They are designed for research backtests and are not order
        instructions to a real broker.
        """

    def _validate_sizing_parameters(self) -> None:
        quantity = self.parameters.get("quantity")
        cash_amount = self.parameters.get("cash_amount")
        target_percent = self.parameters.get("target_percent")
        provided = [value is not None for value in (quantity, cash_amount, target_percent)]
        if sum(provided) > 1:
            raise StrategyParameterError(
                "quantity、cash_amount、target_percent 只能擇一設定。"
            )
        if quantity is not None and int(quantity) <= 0:
            raise StrategyParameterError("quantity 若有設定，必須大於 0。")
        if cash_amount is not None and float(cash_amount) <= 0:
            raise StrategyParameterError("cash_amount 若有設定，必須大於 0。")
        if target_percent is not None and not 0 < float(target_percent) <= 1:
            raise StrategyParameterError("target_percent 必須介於 0 到 1 之間。")

    def _attach_sizing(self, signals: pd.DataFrame) -> pd.DataFrame:
        output = signals.copy(deep=True)
        output["quantity"] = self.parameters.get("quantity")
        output["cash_amount"] = self.parameters.get("cash_amount")
        output["target_percent"] = self.parameters.get("target_percent")
        return output


def prepare_price_frame(
    price_data: pd.DataFrame,
    required_columns: tuple[str, ...],
) -> pd.DataFrame:
    """Return a sorted copy of price data for strategy calculations."""

    required = {"date", "symbol", *required_columns}
    missing = sorted(required - set(price_data.columns))
    if missing:
        raise ValueError(f"price_data missing required columns: {', '.join(missing)}")

    frame = price_data.copy(deep=True)
    frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
    frame["symbol"] = frame["symbol"].astype(str)
    return frame.sort_values(["symbol", "date"], kind="mergesort").reset_index(drop=True)


def previous_by_symbol(frame: pd.DataFrame, column: str) -> pd.Series:
    """Return previous-row values within each symbol."""

    return frame.groupby("symbol", sort=False)[column].shift(1)


def rolling_by_symbol(
    frame: pd.DataFrame,
    column: str,
    *,
    window: int,
    statistic: str,
    shift: int = 0,
) -> pd.Series:
    """Calculate grouped rolling statistics without crossing symbol boundaries."""

    if statistic not in {"mean", "max", "min"}:
        raise ValueError(f"Unsupported rolling statistic: {statistic}")

    def calculate(series: pd.Series) -> pd.Series:
        rolling = series.rolling(window=window, min_periods=window)
        if statistic == "mean":
            values = rolling.mean()
        elif statistic == "max":
            values = rolling.max()
        else:
            values = rolling.min()
        return values.shift(shift) if shift else values

    return frame.groupby("symbol", sort=False)[column].transform(calculate)


def finalize_signals(
    frame: pd.DataFrame,
    signal: pd.Series,
    *,
    strategy: StrategyBase,
) -> pd.DataFrame:
    """Standardize a signal series into the strategy signal contract."""

    output = frame.loc[:, ["date", "symbol"]].copy()
    output["signal"] = signal.fillna(0).astype(int)
    invalid = sorted(set(output["signal"]) - {-1, 0, 1})
    if invalid:
        raise ValueError(f"策略訊號只能是 -1、0 或 1；收到：{invalid}")
    output["reason"] = strategy.name
    return strategy._attach_sizing(output)
