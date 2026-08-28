"""Fundamental growth screening strategy."""

from __future__ import annotations

import pandas as pd

from stock_tool.fundamentals.models import (
    FundamentalPointInTimeMode,
    prepare_fundamental_strategy_frame,
)

from stock_tool.strategies.base import (
    StrategyBase,
    StrategyParameterError,
    finalize_signals,
    prepare_price_frame,
    previous_by_symbol,
)


class FundamentalGrowthStrategy(StrategyBase):
    """Buy when growth, profitability, and balance-sheet thresholds are met."""

    name = "fundamental_growth"
    description = "依 EPS 成長、營收成長、ROE 與負債比門檻產生基本面篩選研究訊號。"
    risk_notes = (
        "基本面資料必須使用實際可取得日期，避免前視偏誤。",
        "Accounting revisions and reporting lags can materially change historical screening results.",
    )
    default_parameters = {
        **StrategyBase.default_parameters,
        "eps_growth_min": 0.10,
        "revenue_growth_min": 0.10,
        "roe_min": 0.12,
        "debt_ratio_max": 0.50,
        "date_col": "date",
        "eps_growth_col": "eps_growth",
        "revenue_growth_col": "revenue_growth",
        "roe_col": "roe",
        "debt_ratio_col": "debt_ratio",
        "point_in_time_mode": FundamentalPointInTimeMode.LEGACY.value,
    }

    def validate_parameters(self) -> None:
        self._validate_sizing_parameters()
        if float(self.parameters["roe_min"]) < 0:
            raise StrategyParameterError("roe_min 不可為負數。")
        if float(self.parameters["debt_ratio_max"]) < 0:
            raise StrategyParameterError("debt_ratio_max 不可為負數。")

    def generate_signals(
        self,
        price_data: pd.DataFrame,
        fundamentals: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Generate signals from point-in-time fundamental data.

        The fundamental ``date`` column is interpreted as the data availability
        date. Values are merged backward with price dates, so future reports are
        not used for earlier price rows.
        """

        if fundamentals is None:
            raise ValueError("基本面成長策略需要 fundamentals 基本面資料。")

        frame = prepare_price_frame(price_data, ())
        available = prepare_fundamental_strategy_frame(
            fundamentals,
            mode=str(self.parameters["point_in_time_mode"]),
        )
        features = self._merge_fundamentals(frame, available.data)
        eps_col = str(self.parameters["eps_growth_col"])
        revenue_col = str(self.parameters["revenue_growth_col"])
        roe_col = str(self.parameters["roe_col"])
        debt_col = str(self.parameters["debt_ratio_col"])
        pass_screen = (
            (features[eps_col] >= float(self.parameters["eps_growth_min"]))
            & (features[revenue_col] >= float(self.parameters["revenue_growth_min"]))
            & (features[roe_col] >= float(self.parameters["roe_min"]))
            & (features[debt_col] <= float(self.parameters["debt_ratio_max"]))
        )
        previous_pass = previous_by_symbol(
            features.assign(pass_screen=pass_screen), "pass_screen"
        ).eq(True)
        buy = pass_screen & previous_pass.eq(False)
        sell = pass_screen.eq(False) & previous_pass
        signal = pd.Series(0, index=features.index)
        signal.loc[buy] = 1
        signal.loc[sell] = -1
        return finalize_signals(features, signal, strategy=self)

    def _merge_fundamentals(
        self,
        price_frame: pd.DataFrame,
        fundamentals: pd.DataFrame,
    ) -> pd.DataFrame:
        date_col = str(self.parameters["date_col"])
        required = {
            date_col,
            "symbol",
            str(self.parameters["eps_growth_col"]),
            str(self.parameters["revenue_growth_col"]),
            str(self.parameters["roe_col"]),
            str(self.parameters["debt_ratio_col"]),
        }
        missing = sorted(required - set(fundamentals.columns))
        if missing:
            raise ValueError(f"fundamentals missing required columns: {', '.join(missing)}")

        fund = fundamentals.copy(deep=True)
        fund = fund.rename(columns={date_col: "fundamental_date"})
        fund["fundamental_date"] = pd.to_datetime(fund["fundamental_date"]).astype("datetime64[ns]")
        fund["symbol"] = fund["symbol"].astype(str)
        price = price_frame.copy(deep=True)
        price["_price_date"] = pd.to_datetime(price["date"]).astype("datetime64[ns]")

        merged_parts: list[pd.DataFrame] = []
        for symbol, price_group in price.groupby("symbol", sort=False):
            fund_group = fund.loc[fund["symbol"] == symbol].sort_values("fundamental_date")
            price_group = price_group.sort_values("_price_date")
            if fund_group.empty:
                merged = price_group.copy()
                for column in required - {date_col, "symbol"}:
                    merged[column] = pd.NA
            else:
                merged = pd.merge_asof(
                    price_group,
                    fund_group,
                    left_on="_price_date",
                    right_on="fundamental_date",
                    by="symbol",
                    direction="backward",
                )
            merged_parts.append(merged)

        result = pd.concat(merged_parts, ignore_index=True)
        result = result.drop(columns=["_price_date", "fundamental_date"], errors="ignore")
        return result.sort_values(["symbol", "date"], kind="mergesort").reset_index(drop=True)
