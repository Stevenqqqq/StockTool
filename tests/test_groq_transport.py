from io import BytesIO
import json

import pytest

from stock_tool.research.groq_transport import ENDPOINT, GroqTransport, _NoRedirect
from stock_tool.research.work_session import WorkSessionError
from test_public_research_request import prepared


def test_exact_public_body_and_no_private_context(monkeypatch):
    _, request = prepared()
    captured = []

    class Opener:
        def open(self, req, timeout):
            captured.append(req)
            assert timeout == 10
            return BytesIO(
                json.dumps(
                    {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
                ).encode()
            )

    monkeypatch.setattr("urllib.request.build_opener", lambda *_: Opener())
    transport = GroqTransport("TEST_KEY", "test-model", True)
    assert "TEST_KEY" not in repr(transport)
    assert transport(request.payload_json.encode()).finish_reason == "stop"
    assert len(captured) == 1
    assert captured[0].full_url == ENDPOINT
    body = json.loads(captured[0].data)
    assert json.loads(body["messages"][1]["content"]) == json.loads(request.payload_json)
    assert "CANARY" not in captured[0].data.decode()
    assert "tools" not in body


def test_unconfirmed_free_account_and_redirect_rejected():
    with pytest.raises(WorkSessionError):
        GroqTransport("TEST_KEY", "test-model")
    with pytest.raises(WorkSessionError):
        _NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example")


def test_error_is_sanitized_without_retry(monkeypatch):
    _, request = prepared()
    calls = []

    class Opener:
        def open(self, req, timeout):
            calls.append(req)
            raise OSError("CANARY_SECRET")

    monkeypatch.setattr("urllib.request.build_opener", lambda *_: Opener())
    with pytest.raises(WorkSessionError) as error:
        GroqTransport("TEST_KEY", "test-model", True)(request.payload_json.encode())
    assert "CANARY" not in str(error.value)
    assert len(calls) == 1


def test_generation_and_review_http_bodies_keep_private_canary_local(monkeypatch):
    from stock_tool.research.groq_transport import LocalGroqTransport
    from stock_tool.research.work_session import canonical
    from test_semantic_review import reviewed_example

    snapshot, request, answer, review, _ = reviewed_example()
    from stock_tool.research.work_session import ResearchWorkSession

    local_session = ResearchWorkSession(snapshot, "CANARY_PRIVATE_QUESTION", snapshot.created_at)
    assert "CANARY" in canonical(local_session.to_dict())
    captured = []
    responses = iter((answer, canonical(review)))

    class Opener:
        def open(self, req, timeout):
            captured.append(json.loads(req.data))
            return BytesIO(
                json.dumps(
                    {
                        "choices": [
                            {"message": {"content": next(responses)}, "finish_reason": "stop"}
                        ]
                    }
                ).encode()
            )

    monkeypatch.setattr("urllib.request.build_opener", lambda *_: Opener())
    monkeypatch.setattr("stock_tool.research.local_credentials.load_groq_key", lambda: "TEST_KEY")
    result = LocalGroqTransport(True)(request.payload_json.encode())
    assert result.review_json is not None
    assert len(captured) == 2
    assert "reasoning_effort" not in captured[0]
    assert captured[1]["reasoning_effort"] == "high"
    assert captured[0]["max_completion_tokens"] == 4096
    assert captured[1]["max_completion_tokens"] == 8192
    public = json.loads(request.payload_json)
    assert json.loads(captured[0]["messages"][1]["content"]) == public
    from stock_tool.research.semantic_review import review_input

    assert captured[1]["messages"][1]["content"] == review_input(public, answer)
    for body in captured:
        assert "CANARY" not in canonical(body)
        assert "TEST_KEY" not in canonical(body)


def test_review_rejects_extra_private_fields_before_network(monkeypatch):
    from test_semantic_review import reviewed_example

    _, request, answer, _, _ = reviewed_example()
    public = json.loads(request.payload_json)
    public["holdings"] = "CANARY_PRIVATE"
    monkeypatch.setattr("urllib.request.build_opener", lambda *_: pytest.fail("network forbidden"))
    with pytest.raises(WorkSessionError):
        GroqTransport("TEST_KEY", "test-model", True).review(json.dumps(public).encode(), answer)
