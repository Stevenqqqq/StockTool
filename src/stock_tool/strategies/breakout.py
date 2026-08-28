"""Price breakout strategy."""

from __future__ import annotations

import pandas as pd

from stock_tool.strategies.base import (
    StrategyBase,
    StrategyParameterError,
    finalize_signals,
    prepare_price_frame,
    rolling_by_symbol,
)


class BreakoutStrategy(StrategyBase):
    """Buy when close breaks the prior N-day high; sell on prior N-day low break."""

    name = "breakout"
    description = "收盤價突破前 N 日高點產生買入研究訊號；跌破前 N 日低點產生賣出研究訊號。"
    risk_notes = (
        "價格短暫突破區間後可能快速失敗，突破訊號需要搭配風控。",
        "Execution price, slippage, and liquidity matter for breakout studies.",
    )
    default_parameters = {
        **StrategyBase.default_parameters,
        "lookback": 20,
        "price_col": "close",
        "high_col": "high",
        "low_col": "low",
    }

    def validate_parameters(self) -> None:
        self._validate_sizing_parameters()
        if int(self.parameters["lookback"]) <= 0:
            raise StrategyParameterError("回看天數必須大於 0。")

    def generate_signals(
        self,
        price_data: pd.DataFrame,
        fundamentals: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Generate breakout signals using prior ranges shifted by one bar."""

        del fundamentals
        lookback = int(self.parameters["lookback"])
        price_col = str(self.parameters["price_col"])
        high_col = str(self.parameters["high_col"])
        low_col = str(self.parameters["low_col"])
        frame = prepare_price_frame(price_data, (price_col, high_col, low_col))
        prior_high = rolling_by_symbol(
            frame,
            high_col,
            window=lookback,
            statistic="max",
            shift=1,
        )
        prior_low = rolling_by_symbol(
            frame,
            low_col,
            window=lookback,
            statistic="min",
            shift=1,
        )
        buy = frame[price_col] > prior_high
        sell = frame[price_col] < prior_low
        signal = pd.Series(0, index=frame.index)
        signal.loc[buy] = 1
        signal.loc[sell] = -1
        return finalize_signals(frame, signal, strategy=self)
