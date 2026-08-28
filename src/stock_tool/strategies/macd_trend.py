"""MACD trend-following strategy."""

from __future__ import annotations

import pandas as pd

from stock_tool.indicators import add_macd
from stock_tool.strategies.base import (
    StrategyBase,
    StrategyParameterError,
    finalize_signals,
    prepare_price_frame,
    previous_by_symbol,
)


class MACDTrendStrategy(StrategyBase):
    """Buy on DIF crossing above DEA; sell on DIF crossing below DEA."""

    name = "macd_trend"
    description = "MACD DIF 上穿 DEA 產生買入研究訊號；下穿 DEA 產生賣出研究訊號。"
    risk_notes = (
        "MACD 屬於趨勢跟隨指標，可能落後轉折點。",
        "Short-term noise can create false crosses.",
    )
    default_parameters = {
        **StrategyBase.default_parameters,
        "fast_period": 12,
        "slow_period": 26,
        "signal_period": 9,
        "price_col": "close",
    }

    def validate_parameters(self) -> None:
        self._validate_sizing_parameters()
        fast_period = int(self.parameters["fast_period"])
        slow_period = int(self.parameters["slow_period"])
        signal_period = int(self.parameters["signal_period"])
        if min(fast_period, slow_period, signal_period) <= 0:
            raise StrategyParameterError("MACD 期間必須大於 0。")
        if fast_period >= slow_period:
            raise StrategyParameterError("快線期間必須小於慢線期間。")

    def generate_signals(
        self,
        price_data: pd.DataFrame,
        fundamentals: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Generate MACD cross signals using backward-looking EMA values."""

        del fundamentals
        frame = prepare_price_frame(price_data, (str(self.parameters["price_col"]),))
        frame = add_macd(
            frame,
            fast_period=int(self.parameters["fast_period"]),
            slow_period=int(self.parameters["slow_period"]),
            signal_period=int(self.parameters["signal_period"]),
            price_col=str(self.parameters["price_col"]),
        )
        prev_dif = previous_by_symbol(frame, "macd_dif")
        prev_dea = previous_by_symbol(frame, "macd_dea")
        buy = (frame["macd_dif"] > frame["macd_dea"]) & (prev_dif <= prev_dea)
        sell = (frame["macd_dif"] < frame["macd_dea"]) & (prev_dif >= prev_dea)
        signal = pd.Series(0, index=frame.index)
        signal.loc[buy] = 1
        signal.loc[sell] = -1
        return finalize_signals(frame, signal, strategy=self)
