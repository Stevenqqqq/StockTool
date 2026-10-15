"""Frozen EXE review of synthetic restart, cached prices and FX boundaries."""

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

import pandas as pd
import streamlit as st

from stock_tool.application import holding_analysis
from stock_tool.application.holding_identity import save_identity_state
from stock_tool.application.portfolio_workspace import PortfolioWorkspaceApplicationService
from stock_tool.dashboard import app
from stock_tool.dashboard.pages import portfolio_workspace
from stock_tool.fundamentals.auto_fetch import FundamentalFetchResult
from stock_tool.portfolio_fx import FxResolution
from stock_tool.portfolio_valuation import FxQuote
from stock_tool.runtime_paths import RuntimePaths

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)
FETCHED = "2026-10-16T22:30:00Z"
paths = RuntimePaths.from_environment()
if not paths.root.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()):
    raise RuntimeError("An isolated temporary runtime is required")
if not paths.root.name.startswith("stocktool-cache-review-"):
    raise RuntimeError("A dedicated stocktool-cache-review-* runtime is required")
if not getattr(sys, "frozen", False):
    raise RuntimeError("Review must use the frozen candidate EXE")


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


holding_analysis.datetime = Clock
portfolio_workspace.datetime = Clock
app.AUTO_FUNDAMENTAL_FILE = paths.processed_dir / "fundamentals_auto.csv"
app.SAMPLE_FUNDAMENTAL_FILE = paths.root / "absent-sample.csv"
app.DEFAULT_DATABASE = paths.data_dir / "stock_data.sqlite"
paths.data_dir.mkdir(parents=True, exist_ok=True)
service = PortfolioWorkspaceApplicationService(
    portfolio_path=paths.portfolio_file,
    ledger_path=paths.data_dir / "absent-ledger.sqlite",
    now=lambda: NOW,
)
if not paths.portfolio_file.exists():
    service.save_positions(
        pd.DataFrame(
            [
                dict(
                    symbol=symbol,
                    market=market,
                    currency=currency,
                    quantity=2,
                    average_cost=80,
                    note="synthetic review only",
                )
                for symbol, market, currency in (("3006", "TWSE", "TWD"), ("MU", "US", "USD"))
            ]
        )
    )
if not app.DEFAULT_DATABASE.exists():
    rows = []
    for symbol, market, provider_symbol in (("3006", "TWSE", "3006.TW"), ("MU", "US", "MU")):
        for day in pd.bdate_range(end="2026-10-16", periods=80):
            rows.append(
                dict(
                    symbol=symbol,
                    market=market,
                    date=day.date().isoformat(),
                    open=100,
                    high=102,
                    low=99,
                    close=100,
                    volume=1000,
                    adjusted_close=100,
                    provider="synthetic",
                    provider_symbol=provider_symbol,
                    source_type="cache",
                    last_data_date="2026-10-16",
                    fetched_at=FETCHED,
                    checked_at=FETCHED,
                )
            )
    app._persist_price_data(pd.DataFrame(rows), app.DEFAULT_DATABASE)
    save_identity_state(
        paths.data_dir / "holding_identity.json",
        {
            "profiles": {
                f"{symbol}|{market}": dict(
                    symbol=symbol,
                    market=market,
                    currency=currency,
                    instrument_type="股票",
                    name="合成驗證 " + symbol,
                    source="synthetic",
                    fetched_at=FETCHED,
                )
                for symbol, market, currency in (("3006", "TWSE", "TWD"), ("MU", "US", "USD"))
            },
            "overrides": {},
        },
    )
app._init_state(st)
if not app.AUTO_FUNDAMENTAL_FILE.exists():
    app.fetch_yfinance_fundamentals = lambda symbol, **_k: FundamentalFetchResult(
        pd.DataFrame([dict(symbol=symbol, fiscal_period="2026-06-30", pe_ratio=12)]),
        "synthetic",
        symbol,
        symbol,
    )
    for symbol, market in (("3006", "TWSE"), ("MU", "US")):
        app._ensure_symbol_data(st, symbol=symbol, market=market)

st.set_page_config(layout="wide")
st.caption("隔離合成驗證：時鐘固定為2026-10-18週日，沒有真實持股、行情或外部AI。")
st.write("重啟後的基本面市場身分")
st.dataframe(st.session_state.fundamentals[["symbol", "market", "fiscal_period"]])
mode = st.selectbox("驗證情境", ["完整參考估值", "FX更新過期", "MU價格衝突", "MU缺價格"])
base = app._load_default_database_prices(app.DEFAULT_DATABASE)
assert base is not None
original = base.copy(deep=True)
view = base.copy(deep=True)
if mode == "MU價格衝突":
    conflict = view.loc[(view.symbol == "MU") & (view.date == view.date.max())].copy()
    conflict["close"] = 150
    view = pd.concat([view, conflict], ignore_index=True)
elif mode == "MU缺價格":
    view = view.loc[view.symbol != "MU"].copy()
st.session_state.price_data = view
stamp = FETCHED if mode == "FX更新過期" else "2026-10-18T10:00:00Z"
st.session_state.portfolio_fx_resolution = FxResolution(
    quote=FxQuote.manual("USD", "TWD", 32, stamp), status="synthetic"
)
if st.session_state.get("review_mode") != mode:
    st.session_state["review_mode"] = mode
    st.session_state.pop("portfolio_workspace_analysis", None)
    st.session_state.pop("holding_refresh_key", None)


def offline():
    raise OSError("Synthetic offline provider; cached originals retained")


portfolio_workspace.render_portfolio_workspace(st, service=service, refresh_callback=offline)
analysis = st.session_state.get("portfolio_workspace_analysis")
assert analysis is not None
pd.testing.assert_frame_equal(base, original)
fundamental_identities = sorted(
    [
        list(v)
        for v in st.session_state.fundamentals[["symbol", "market"]].itertuples(
            index=False, name=None
        )
    ]
)
assert fundamental_identities == [["3006", "TWSE"], ["MU", "US"]]
result = {
    "executable": sys.executable,
    "app_module": app.__file__,
    "holding_module": holding_analysis.__file__,
    "pid": os.getpid(),
    "mode": mode,
    "clock": NOW.isoformat(),
    "fundamental_identities": fundamental_identities,
    "fundamental_csv_sha256": hashlib.sha256(app.AUTO_FUNDAMENTAL_FILE.read_bytes()).hexdigest(),
    "base_market_value": analysis.valuation.base_market_value,
    "weights_available": analysis.valuation.positions.weight.notna().tolist(),
    "prices_original_unchanged": True,
    "acquisition_times": sorted(set(base.checked_at.astype(str))),
    "native_values": [
        None if pd.isna(v) else float(v) for v in analysis.valuation.positions.native_market_value
    ],
}
(paths.root / "exe-review-binding.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
)
