"""Moving-average crossover strategy."""

from __future__ import annotations

import pandas as pd

from stock_tool.indicators import add_sma
from stock_tool.strategies.base import (
    StrategyBase,
    StrategyParameterError,
    finalize_signals,
    prepare_price_frame,
    previous_by_symbol,
)


class MACrossStrategy(StrategyBase):
    """Buy on short SMA crossing above long SMA; sell on the opposite cross."""

    name = "ma_cross"
    description = "20 日均線上穿 60 日均線產生買入研究訊號；反向交叉產生賣出研究訊號。"
    risk_notes = (
        "Moving-average strategies can lag in fast reversals.",
        "盤整市場可能產生反覆假突破與來回停損。",
    )
    default_parameters = {
        **StrategyBase.default_parameters,
        "short_window": 20,
        "long_window": 60,
        "price_col": "close",
    }

    def validate_parameters(self) -> None:
        self._validate_sizing_parameters()
        short_window = int(self.parameters["short_window"])
        long_window = int(self.parameters["long_window"])
        if short_window <= 0 or long_window <= 0:
            raise StrategyParameterError("均線天數必須大於 0。")
        if short_window >= long_window:
            raise StrategyParameterError("短均線天數必須小於長均線天數。")

    def generate_signals(
        self,
        price_data: pd.DataFrame,
        fundamentals: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Generate MA cross signals using only current and historical prices."""

        del fundamentals
        short_window = int(self.parameters["short_window"])
        long_window = int(self.parameters["long_window"])
        price_col = str(self.parameters["price_col"])
        frame = prepare_price_frame(price_data, (price_col,))
        frame = add_sma(
            frame,
            periods=(short_window, long_window),
            price_col=price_col,
        )

        short = frame[f"sma_{short_window}"]
        long = frame[f"sma_{long_window}"]
        prev_short = previous_by_symbol(frame, f"sma_{short_window}")
        prev_long = previous_by_symbol(frame, f"sma_{long_window}")
        buy = (short > long) & (prev_short <= prev_long)
        sell = (short < long) & (prev_short >= prev_long)
        signal = pd.Series(0, index=frame.index)
        signal.loc[buy] = 1
        signal.loc[sell] = -1
        return finalize_signals(frame, signal, strategy=self)
