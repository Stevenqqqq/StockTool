"""Offline review of the real Research Workspace, synthetic inputs only."""

from dataclasses import replace
import os
from pathlib import Path
import tempfile
from stock_tool.company_dossier import CompanyDossier
from stock_tool.company_research import CompanyResearchProfile
from stock_tool.application.research_snapshot import ScenarioReferenceRange
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

profile = CompanyResearchProfile(
    symbol=symbol,
    provider_symbol=symbol,
    company_name="合成驗證公司 " + symbol,
    sector="合成科技",
    industry="合成產業",
    website="https://example.com",
    main_business=("合成公司業務，只用於測試。",),
    technical_features=(),
    linked_industries=(),
    current_applications=(),
    future_applications=(),
    bottlenecks=(),
    additional_checks=(),
    data_sources=("synthetic",),
    limitations=("合成資料不能作為真實研究。",),
    fact_fields=(),
    dossier=CompanyDossier(
        symbol=symbol,
        market="TWSE",
        website="https://example.com",
        industry_lens="合成",
        facts=(),
        questions=("尚待查核營收。",),
        gaps=("合成公司資料缺口，沒有官方文件。",),
        documents=(),
        checked_at="2026-01-01T00:00:00Z",
        state="stale",
    ),
)
date_mode = st.selectbox("情境日期測試", ("同日", "未知", "未來", "歷史"))
reference_date = snapshot.price.last_data_date if snapshot.price else None
if date_mode == "未知":
    reference_date = None
elif date_mode == "未來":
    reference_date = "2099-01-01"
elif date_mode == "歷史":
    reference_date = "2020-01-01"
scenario = ScenarioReferenceRange(
    title="合成區間",
    method="合成既有參考",
    as_of_date=reference_date,
    latest_close=None,
    range_low=base,
    range_high=base + 20,
    breakout_observation=base + 30,
    risk_reference=base - 10,
    assumptions=("合成假設",),
    limitations=("不代表真實研究資格",),
    available=True,
)
snapshot = replace(snapshot, company_profile=profile, scenario_reference=scenario)
render_research_workspace(st, snapshot)
