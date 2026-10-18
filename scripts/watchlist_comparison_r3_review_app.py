"""Isolated EXE: real watchlist, hydration, shell routing and research, fake providers only."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile

import pandas as pd
import streamlit as st

from stock_tool.application.instrument_names import InstrumentName, NameDirectory
from stock_tool.company_research import build_company_research_profile as profile_builder
from stock_tool.dashboard import app, instrument_names
from stock_tool.dashboard.state import navigate_to_workspace
from stock_tool.data.auto_fetch import FetchResult
from stock_tool.data.contracts import (
    DataSourceMetadata,
    DataSourceType,
    ProviderResult,
    ProviderStatus,
    QualityReport,
    QualityStatus,
)
from stock_tool.domain.models import Symbol
from stock_tool.runtime_paths import RuntimePaths
from stock_tool.watchlist import save_watchlist

paths = RuntimePaths.from_environment()
if not paths.root.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()):
    raise RuntimeError("Temporary runtime required")
if not paths.root.name.startswith("stocktool-watchlist-review-"):
    raise RuntimeError("Dedicated stocktool-watchlist-review-* runtime required")
if not getattr(sys, "frozen", False) and not Path(app.__file__).resolve().is_relative_to(
    Path(__file__).resolve().parents[1] / "src"
):
    raise RuntimeError("Source validation must import this isolated checkout")
paths.root.mkdir(parents=True, exist_ok=True)
app.DEFAULT_DATABASE = paths.data_dir / "stock_data.sqlite"
app.SAMPLE_FUNDAMENTAL_FILE = paths.root / "no-sample.csv"
app.AUTO_FUNDAMENTAL_FILE = paths.processed_dir / "fundamentals_auto.csv"


def bind_fixture_names(st, paths):
    directory = NameDirectory(paths.cache_dir / "fixture-names-only.json")
    directory.records["TWSE:companies"] = {
        code: InstrumentName(
            "TWSE",
            code,
            name,
            name,
            "synthetic-name-fixture",
            "2026-10-13",
            "2026-10-13T12:00:00+00:00",
        )
        for code, name in {"3006": "晶豪科", "6669": "緯穎", "6933": "AMAX-KY"}.items()
    }
    instrument_names.current_names.set(directory)
    return lambda: None


instrument_names.bind_names = bind_fixture_names
st.set_page_config(layout="wide")
st.sidebar.caption("合成隔離驗證；不連網、不代表真實行情")
mode = st.sidebar.selectbox("驗證情境", ["正常", "日期不同", "缺資料", "離線"])


def fixture(code):
    count = 10 if mode == "缺資料" and code == "6933" else 65
    end = "2026-10-12" if mode == "日期不同" and code == "6933" else "2026-10-13"
    frame = pd.DataFrame({"date": pd.bdate_range(end=end, periods=count)})
    frame["date"] = frame.date.dt.date.map(str)
    offset = {"3006": 100, "6669": 200, "6933": 300}[code]
    slope = {"3006": 1.0, "6669": 2.5, "6933": -0.6}[code]
    frame["close"] = [offset + slope * i for i in range(count)]
    frame["symbol"] = code
    frame["market"] = "TWSE"
    frame["open"] = frame.close - 1
    frame["high"] = frame.close + 2
    frame["low"] = frame.close - 2
    frame["adjusted_close"] = frame.close
    frame["volume"] = 1000.0
    frame.loc[count - 1, "volume"] = {"3006": 1300.0, "6669": 1800.0, "6933": 700.0}[code]
    frame["provider"] = "synthetic"
    frame["fetched_at"] = "2026-10-13T12:00:00Z"
    frame["checked_at"] = frame.fetched_at
    return frame.iloc[:0] if mode == "缺資料" and code == "6669" else frame


def fetch(code, **kwargs):
    if mode == "離線":
        raise RuntimeError("synthetic offline")
    frame = fixture(code)
    return FetchResult(
        data=frame,
        source="synthetic",
        symbol=code,
        provider_symbol=code + ".TW",
        from_cache=False,
        cache_file=None,
        market="TWSE",
        start_date="2026-07-01",
        end_date="2026-10-13",
        source_type="local_file",
        fetched_at="2026-10-13T12:00:00Z",
        last_data_date="2026-10-13",
    )


def fetch_contract(code, **kwargs):
    result = fetch(code, **kwargs)
    identity = Symbol.parse(code, market="TWSE")
    return ProviderResult(
        status=ProviderStatus.SUCCESS,
        data=result.data,
        metadata=DataSourceMetadata(
            provider="synthetic",
            source_type=DataSourceType.LOCAL_FILE,
            requested_symbol=identity,
            resolved_symbol=identity,
            provider_symbol=code + ".TW",
            request_start=kwargs.get("start"),
            request_end=kwargs.get("end"),
            interval=kwargs.get("interval"),
            fetched_at=result.fetched_at,
            last_data_date=result.last_data_date,
        ),
        quality=QualityReport(QualityStatus.VALID, len(result.data), len(result.data)),
    )


def no_fundamentals(*args, **kwargs):
    raise app.FundamentalFetchError("合成基本面缺漏")


def profile(code, **kwargs):
    return profile_builder(
        code,
        market="TWSE",
        info={"longName": {"3006": "晶豪科", "6669": "緯穎", "6933": "AMAX-KY"}[code]},
        allow_remote_fetch=False,
        include_details=False,
    )


app.fetch_prices = fetch
app.fetch_prices_result = fetch_contract
app.fetch_yfinance_fundamentals = no_fundamentals
app.build_company_research_profile = profile
if not paths.watchlist_file.exists():
    save_watchlist(
        pd.DataFrame(
            [dict(symbol=s, market="TWSE", note="synthetic") for s in ("6669", "6933", "3006")]
        ),
        paths.watchlist_file,
    )
app._init_state(st)
if st.session_state.get("fixture_mode") != mode and mode != "離線":
    frames = pd.concat([fixture(s) for s in ("6669", "6933", "3006")], ignore_index=True)
    # Each mode has its own in-memory input; do not merge old complete fixtures into missing ones.
    st.session_state.price_data = frames
    app._portfolio_price_context = lambda st: st.session_state.price_data.copy(deep=True)
st.session_state["fixture_mode"] = mode
app._portfolio_price_context = lambda st: st.session_state.price_data.copy(deep=True)
if "review_started" not in st.session_state:
    st.session_state["review_started"] = True
    navigate_to_workspace(st.session_state, workspace="explore", legacy_page="自選股清單")
if st.sidebar.button("回到自選股比較"):
    navigate_to_workspace(st.session_state, workspace="explore", legacy_page="自選股清單")
    st.rerun()
app.main()
(paths.root / "exe-binding.json").write_text(
    json.dumps(
        {
            "executable": sys.executable,
            "module": app.__file__,
            "mode": mode,
            "watchlist_sha256": hashlib.sha256(paths.watchlist_file.read_bytes()).hexdigest(),
            "active_symbol": st.session_state.get("active_symbol"),
        },
        indent=2,
    ),
    encoding="utf-8",
)
