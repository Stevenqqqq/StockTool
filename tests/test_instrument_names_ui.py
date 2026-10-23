"""Synthetic Streamlit interaction checks, not browser/screenshot acceptance."""

from streamlit.testing.v1 import AppTest


def test_3006_summary_names_switching_and_visible_gaps(tmp_path):
    script = """
from dataclasses import replace
from pathlib import Path
import streamlit as st
from test_instrument_names import fetch
from test_research_header_completeness import _snapshot, _profile
from stock_tool.application.instrument_names import NameDirectory
from stock_tool.dashboard.instrument_names import current_names
from stock_tool.dashboard.components.research_header import render_research_header
from stock_tool.company_documents import CompanyDocument
from stock_tool.company_dossier import build_dossier
from stock_tool.domain.models import Market, Symbol

directory = NameDirectory(Path(CACHE_PATH))
if not directory.records:
    directory.refresh(fetch)
current_names.set(directory)
selection = st.selectbox("合成標的", ["3006", "6488", "00935", "MU"])
market = "TPEX" if selection == "6488" else "US" if selection == "MU" else "TWSE"
failed = st.checkbox("模擬官方名稱斷線")
if failed:
    directory.refresh(lambda _: [], force=True)
st.session_state.setdefault("untouched_input", {"quantity": 2, "cost": 99})
doc = CompanyDocument("https://example.com/products", "合成產品頁", "本公司提供DDR4記憶體，容量4Gb及8Gb，最高3200Mbps。", "", "2026-10-03T01:00:00+00:00")
dossier = build_dossier(selection, market, "https://example.com", (doc,), industry="記憶體") if selection == "3006" else None
profile = replace(_profile(), symbol=selection, company_name="Synthetic English name", dossier=dossier)
snapshot = replace(_snapshot(profile=profile), symbol=Symbol(selection, Market(market)), company_name=profile.company_name)
render_research_header(st, snapshot)
""".replace("CACHE_PATH", repr(str(tmp_path / "names.json")))
    app = AppTest.from_string(script).run()
    assert not app.exception
    assert app.title[0].value == "晶豪科"
    visible = "\n".join(str(x.value) for x in [*app.warning, *app.markdown, *app.info])
    assert "DDR4" in visible
    assert "部分可用" in visible
    assert "缺" in visible
    assert "這家公司做什麼" in visible
    assert "接下來先確認" in visible
    for code, expected in [
        ("6488", "環球晶"),
        ("00935", "野村臺灣新科技50"),
        ("MU", "Synthetic English name"),
        ("3006", "晶豪科"),
    ]:
        app.selectbox[0].set_value(code).run()
        assert not app.exception
        assert app.title[0].value == expected
    app.checkbox[0].check().run()
    assert not app.exception
    assert app.title[0].value == "晶豪科"
    assert any("沿用前次" in item.value for item in app.info)
    assert app.session_state["untouched_input"] == {"quantity": 2, "cost": 99}
    restarted = AppTest.from_string(script).run()
    assert not restarted.exception
    assert restarted.title[0].value == "晶豪科"
