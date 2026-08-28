"""RSI reversal strategy."""

from __future__ import annotations

import pandas as pd

from stock_tool.indicators import add_rsi
from stock_tool.strategies.base import (
    StrategyBase,
    StrategyParameterError,
    finalize_signals,
    prepare_price_frame,
    previous_by_symbol,
)


class RSIReversalStrategy(StrategyBase):
    """Buy on rebound from oversold RSI; flag overbought RSI as sell signal."""

    name = "rsi_reversal"
    description = "RSI 自超賣區回升產生買入研究訊號；RSI 高於過熱門檻產生賣出研究訊號。"
    risk_notes = (
        "Oversold conditions can persist during strong downtrends.",
        "RSI 門檻會受市場狀態影響，應使用樣本外資料驗證。",
    )
    default_parameters = {
        **StrategyBase.default_parameters,
        "period": 14,
        "oversold": 30.0,
        "overbought": 70.0,
        "price_col": "close",
    }

    def validate_parameters(self) -> None:
        self._validate_sizing_parameters()
        period = int(self.parameters["period"])
        oversold = float(self.parameters["oversold"])
        overbought = float(self.parameters["overbought"])
        if period <= 0:
            raise StrategyParameterError("RSI 期間必須大於 0。")
        if not 0 <= oversold < overbought <= 100:
            raise StrategyParameterError("RSI 門檻必須符合 0 <= 超賣 < 過熱 <= 100。")

    def generate_signals(
        self,
        price_data: pd.DataFrame,
        fundamentals: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Generate RSI reversal signals without using future prices."""

        del fundamentals
        period = int(self.parameters["period"])
        oversold = float(self.parameters["oversold"])
        overbought = float(self.parameters["overbought"])
        price_col = str(self.parameters["price_col"])
        frame = prepare_price_frame(price_data, (price_col,))
        frame = add_rsi(frame, period=period, price_col=price_col)
        rsi_col = f"rsi_{period}"
        prev_rsi = previous_by_symbol(frame, rsi_col)
        buy = (prev_rsi <= oversold) & (frame[rsi_col] > oversold)
        sell = frame[rsi_col] >= overbought
        signal = pd.Series(0, index=frame.index)
        signal.loc[buy] = 1
        signal.loc[sell] = -1
        return finalize_signals(frame, signal, strategy=self)
