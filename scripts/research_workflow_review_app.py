"""Offline UI review harness. Requires an explicitly isolated temporary runtime."""

from datetime import UTC, datetime
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from test_research_work_session import snapshots  # noqa: E402
from stock_tool.application.portfolio_workspace import (  # noqa: E402
    PortfolioWorkspaceApplicationService,
)
from stock_tool.dashboard.pages.portfolio_workspace import render_portfolio_workspace  # noqa: E402
from stock_tool.dashboard.pages.research import render_research_workspace  # noqa: E402
from stock_tool.dashboard.pages.library import render_library_workspace  # noqa: E402
from stock_tool.research.library import ResearchLibrary  # noqa: E402
from stock_tool.runtime_paths import RuntimePaths  # noqa: E402
from stock_tool.portfolio_valuation import FxQuote  # noqa: E402

runtime = Path(os.environ.get("STOCK_TOOL_USER_DATA_DIR", "")).resolve()
if not runtime.is_relative_to(Path(tempfile.gettempdir()).resolve()) or not runtime.name.startswith(
    "stocktool-workflow-"
):
    raise RuntimeError("Review harness only runs in an explicitly named temporary runtime")
if os.environ.get("STOCK_TOOL_AI_API_KEY"):
    raise RuntimeError("Offline review must not have an AI key")
paths = RuntimePaths.from_environment()
paths.data_dir.mkdir(parents=True, exist_ok=True)
st.title("研究工作階段隔離驗證 · 合成資料")
service = PortfolioWorkspaceApplicationService()
stamp = st.session_state.setdefault("fixture_timestamp", datetime.now(UTC).isoformat())
identities = [
    ("3006", "TWSE", "股票"),
    ("JPM", "US", "股票"),
    ("MU", "US", "股票"),
    ("00935", "TWSE", "ETF"),
]
companies = {}
for symbol, market, kind in identities:
    _, company = snapshots(symbol, market, kind)
    companies[company.symbol.canonical] = company
    st.session_state.setdefault("holding_profiles", {})[f"{symbol}|{market}"] = {
        "symbol": symbol,
        "market": market,
        "instrument_type": kind,
        "source": "隔離合成資料",
        "name": symbol,
        "currency": "TWD" if market != "US" else "USD",
        "fetched_at": stamp,
    }
st.session_state["dashboard_research_snapshots"] = companies
portfolio_file = paths.data_dir / "portfolio.csv"
if not portfolio_file.exists():
    pd.DataFrame(
        [
            dict(
                symbol=symbol,
                market=market,
                currency="USD" if market == "US" else "TWD",
                quantity=2,
                average_cost=30,
                note="CANARY_LOCAL_ONLY",
            )
            for symbol, market, _ in identities
        ]
    ).to_csv(portfolio_file, index=False)
st.session_state["price_data"] = pd.DataFrame(
    [
        dict(
            symbol=symbol,
            market=market,
            close=35,
            date=stamp[:10],
            fetched_at=stamp,
            provider="fixture",
        )
        for symbol, market, _ in identities
    ]
)
positions = service.load_positions()
quote = FxQuote.manual("USD", "TWD", 32, stamp)
st.session_state["portfolio_fx_resolution"] = SimpleNamespace(quote=quote)
st.session_state["portfolio_workspace_analysis"] = service.analyze(
    positions=positions, prices=st.session_state["price_data"], fx_quote=quote
)


def open_research(symbol, market):
    st.session_state["review_page"] = "公司研究"
    st.session_state["review_company"] = (symbol, market)
    st.rerun()


def handoff(destination, current):
    if destination == "holdings":
        st.session_state["portfolio_workspace_focus"] = {
            "symbol": current.symbol.code,
            "market": current.symbol.market.value,
        }
        st.session_state["review_page"] = "持股"
        st.rerun()


left, right = st.columns(2)
if left.button("前往持股"):
    st.session_state["review_page"] = "持股"
if right.button("前往研究庫"):
    st.session_state["review_page"] = "研究庫"
page = st.session_state.get("review_page", "持股")
if page == "研究庫":
    render_library_workspace(st, source=None, library=ResearchLibrary(paths.research_library_dir))
elif page == "公司研究":
    symbol, market = st.session_state["review_company"]
    company = next(
        c for c in companies.values() if c.symbol.code == symbol and c.symbol.market.value == market
    )
    preparation = render_research_workspace(st, company, on_handoff=handoff)
    if preparation and preparation.request:
        request = preparation.request
        if (request.symbol, request.market) in [(s, m) for s, m, _ in identities]:
            open_research(request.symbol, request.market)
else:
    render_portfolio_workspace(st, service=service, on_research=open_research)
