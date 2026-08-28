"""Volume-confirmed price breakout strategy."""

from __future__ import annotations

import pandas as pd

from stock_tool.strategies.base import (
    StrategyBase,
    StrategyParameterError,
    finalize_signals,
    prepare_price_frame,
    rolling_by_symbol,
)


class VolumePriceBreakoutStrategy(StrategyBase):
    """Buy on prior-range price breakout confirmed by elevated volume."""

    name = "volume_price_breakout"
    description = "價格突破前期區間且成交量高於均量倍數時產生買入研究訊號；跌破下方區間產生賣出研究訊號。"
    risk_notes = (
        "Volume spikes can occur for non-trend reasons such as index rebalancing or news gaps.",
        "Liquidity and slippage assumptions should be stress-tested.",
    )
    default_parameters = {
        **StrategyBase.default_parameters,
        "lookback": 20,
        "volume_window": 20,
        "volume_multiplier": 1.5,
        "price_col": "close",
        "high_col": "high",
        "low_col": "low",
        "volume_col": "volume",
    }

    def validate_parameters(self) -> None:
        self._validate_sizing_parameters()
        if int(self.parameters["lookback"]) <= 0:
            raise StrategyParameterError("回看天數必須大於 0。")
        if int(self.parameters["volume_window"]) <= 0:
            raise StrategyParameterError("成交量均線天數必須大於 0。")
        if float(self.parameters["volume_multiplier"]) <= 0:
            raise StrategyParameterError("成交量倍數必須大於 0。")

    def generate_signals(
        self,
        price_data: pd.DataFrame,
        fundamentals: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Generate volume-confirmed breakout signals using prior windows."""

        del fundamentals
        lookback = int(self.parameters["lookback"])
        volume_window = int(self.parameters["volume_window"])
        volume_multiplier = float(self.parameters["volume_multiplier"])
        price_col = str(self.parameters["price_col"])
        high_col = str(self.parameters["high_col"])
        low_col = str(self.parameters["low_col"])
        volume_col = str(self.parameters["volume_col"])
        frame = prepare_price_frame(price_data, (price_col, high_col, low_col, volume_col))

        prior_high = rolling_by_symbol(frame, high_col, window=lookback, statistic="max", shift=1)
        prior_low = rolling_by_symbol(frame, low_col, window=lookback, statistic="min", shift=1)
        prior_volume_ma = rolling_by_symbol(
            frame,
            volume_col,
            window=volume_window,
            statistic="mean",
            shift=1,
        )
        buy = (frame[price_col] > prior_high) & (
            frame[volume_col] > prior_volume_ma * volume_multiplier
        )
        sell = frame[price_col] < prior_low
        signal = pd.Series(0, index=frame.index)
        signal.loc[buy] = 1
        signal.loc[sell] = -1
        return finalize_signals(frame, signal, strategy=self)
