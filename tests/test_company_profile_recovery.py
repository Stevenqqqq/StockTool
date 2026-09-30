"""Company metadata failures must remain visible and explicitly recoverable."""

from types import SimpleNamespace

import pytest

import stock_tool.company_research as company
import stock_tool.dashboard.app as app
from stock_tool.application.research_snapshot import ResearchSourceMetadata, ResearchWorkspaceService
from stock_tool.dashboard.pages.research import _render_company_overview
from stock_tool.domain.models import Market, Symbol


class State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


@pytest.mark.parametrize("failure", ["公司基本資料查詢逾時", "沒有公司描述或產業欄位"])
def test_failed_lookup_reason_survives_snapshot(monkeypatch, failure):
    monkeypatch.setattr(company, "_fetch_company_info", lambda *a, **k: ({}, "MU", failure))
    profile = company.build_company_research_profile("MU", market="US", include_details=True)
    snapshot = ResearchWorkspaceService().build(
        symbol=Symbol("MU", Market.US), price_data=None, indicators=None,
        fundamental_results=None, stock_score=None, company_profile=profile,
        scenario_reference=None, source_metadata=ResearchSourceMetadata.empty(symbol="MU", market="US"),
    )
    assert snapshot.company_profile is None
    reason = next(item.reason for item in snapshot.missing_data if item.field == "company_profile")
    assert reason == profile.retrieval_issue
    assert "重新讀取" in reason
    assert ("逾時" in reason) == ("逾時" in failure)


def test_missing_profile_retry_recovers_without_changing_price_or_other_company(monkeypatch):
    results = iter([
        ({}, "MU", "公司基本資料查詢逾時"),
        ({"symbol": "MU", "longName": "Micron", "industry": "Semiconductors"}, "MU", None),
    ])
    monkeypatch.setattr(company, "_fetch_company_info", lambda *a, **k: next(results))
    monkeypatch.setattr(app, "_canonical_concept_relations", lambda *a: ())
    price_source = {"market": "US", "user_symbol": "MU", "provider": "sqlite"}
    other = object()
    state = State(company_research_cache={"JPM|US": other}, price_data_source=price_source)
    st = SimpleNamespace(session_state=state)
    first = app._get_company_research_profile(st, "MU")
    assert not first.fact_fields
    snapshot = ResearchWorkspaceService().build(
        symbol=Symbol("MU", Market.US), price_data=None, indicators=None,
        fundamental_results=None, stock_score=None, company_profile=first,
        scenario_reference=None, source_metadata=ResearchSourceMetadata.empty(symbol="MU", market="US"),
    )
    reruns = []
    st.subheader = lambda *a: None
    st.button = lambda label, **kw: label == "重新讀取公司資料"
    st.rerun = lambda: reruns.append(True)
    _render_company_overview(st, snapshot)
    assert state.company_details_force and reruns
    recovered = app._get_company_research_profile(st, "MU")
    assert recovered.company_name == "Micron"
    assert recovered.retrieval_issue is None
    assert state.price_data_source is price_source
    assert state.company_research_cache["JPM|US"] is other


def test_offline_skip_explains_missing_company_without_network(monkeypatch):
    monkeypatch.setattr(company, "_fetch_company_info", lambda *a, **k: pytest.fail("network"))
    profile = company.build_company_research_profile("MU", market="US", allow_remote_fetch=False)
    assert "離線備援" in profile.retrieval_issue
    assert not profile.fact_fields
