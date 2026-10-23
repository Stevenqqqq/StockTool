"""Offline review of the real Research Workspace, synthetic inputs only."""

import os
from pathlib import Path
import tempfile
import pandas as pd
import streamlit as st
from stock_tool.application.research_snapshot import (
    ResearchWorkspaceService,
    ResearchSourceMetadata,
)
from stock_tool.dashboard.pages.research import render_research_workspace
from stock_tool.domain.models import Symbol, Market

runtime = Path(os.environ["STOCK_TOOL_USER_DATA_DIR"]).resolve()
if not runtime.is_relative_to(Path(tempfile.gettempdir()).resolve()) or not runtime.name.startswith(
    "stocktool-chart-"
):
    raise RuntimeError("Isolated stocktool-chart-* temp runtime required")
st.set_page_config(layout="wide")
st.caption("圖表隔離驗證：全部為合成資料，不是實際行情或公司研究")
symbol = st.selectbox("驗證股票", ["3006", "2330"])
mode = st.selectbox("驗證資料狀態", ["完整OHLCV", "只有收盤價", "無成交量", "全部不足"])
frame = pd.DataFrame({"date": pd.bdate_range("2024-01-01", periods=650)})
base = 100 if symbol == "3006" else 1000
frame["close"] = [base + i * 0.1 + 5 * ((i % 20) / 20) for i in range(len(frame))]
frame["open"] = frame.close + [(-1 if i % 2 else 1) for i in range(len(frame))]
frame["high"] = frame[["open", "close"]].max(axis=1) + 2
frame["low"] = frame[["open", "close"]].min(axis=1) - 2
frame["volume"] = [1000 + (i % 17) * 100 for i in range(len(frame))]
frame["symbol"] = symbol
indicators = frame[["date"]].copy()
indicators["sma_20"] = frame.close.rolling(20).mean()
indicators["sma_60"] = frame.close.rolling(60).mean()
if mode == "只有收盤價":
    frame = frame[["date", "symbol", "close"]]
elif mode == "無成交量":
    frame = frame.drop(columns="volume")
elif mode == "全部不足":
    frame = frame.iloc[:0]
snapshot = ResearchWorkspaceService().build(
    symbol=Symbol(symbol, Market.TWSE),
    price_data=frame,
    indicators=indicators,
    fundamental_results=None,
    stock_score=None,
    company_profile=None,
    scenario_reference=None,
    source_metadata=ResearchSourceMetadata(
        provider="synthetic",
        query_symbol=symbol,
        market="TWSE",
        source_type="local_file",
        fetched_at=None,
        last_data_date=None,
        row_count=len(frame),
    ),
)
render_research_workspace(st, snapshot)
