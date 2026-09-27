from streamlit.testing.v1 import AppTest


def test_explicit_public_send_and_invalid_result_do_not_break_local_ui():
    app = AppTest.from_string("""
import streamlit as st
from test_research_work_session import snapshots
from stock_tool.dashboard.components.work_session import render_work_session
from stock_tool.research.public_request import PublicResponse
h, c = snapshots()
render_work_session(st, h, c,
    transport=lambda _: PublicResponse('invalid response', 'stop'),
    provider='isolated fixture', model='not a real model')
""").run(timeout=20)
    assert not app.exception
    next(b for b in app.button if b.key.startswith("work_send_")).click().run(
        timeout=20
    )
    app.run(timeout=20)
    assert not app.exception
    assert any("回應失效" in item.value for item in app.warning)
    assert app.session_state["work_ai_controller"].attempt_json != "null"
    assert any(b.key.startswith("work_save_") for b in app.button)


def test_unconfigured_ui_has_no_send_and_etf_never_enters_company_model():
    for symbol, kind in (("3006", "股票"), ("00935", "ETF")):
        app = AppTest.from_string(f"""
import streamlit as st
from test_research_work_session import snapshots
from stock_tool.dashboard.components.work_session import render_work_session
h, c = snapshots({symbol!r}, 'TWSE', {kind!r})
render_work_session(st, h, c)
""").run(timeout=20)
        assert not app.exception
        assert not any(b.key.startswith("work_send_") for b in app.button)
        assert any("尚未啟用" in item.value for item in app.caption)


def test_local_groq_requires_explicit_enable_and_does_not_read_key_on_render(monkeypatch):
    # The key loader is deliberately not invoked until a worker sends a request.
    import stock_tool.research.groq_transport as provider

    calls = []

    def never_send(self, payload):
        calls.append(payload)
        raise AssertionError("must not send on render")

    monkeypatch.setattr(provider.LocalGroqTransport, "__call__", never_send)
    app = AppTest.from_string("""
import streamlit as st
from test_research_work_session import snapshots
from stock_tool.dashboard.components.work_session import render_work_session
h, c = snapshots()
render_work_session(st, h, c, allow_local_groq=True)
""").run(timeout=20)
    assert not app.exception
    assert not any(b.key.startswith("work_send_") for b in app.button)
    app.checkbox[0].check().run(timeout=20)
    assert not app.exception
    assert any(b.key.startswith("work_send_") for b in app.button)
    assert calls == []
