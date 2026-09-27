import json
from threading import Event

import pytest

from stock_tool.research.public_request import PublicResponse
from stock_tool.research.request_controller import ResearchRequestController
from stock_tool.research.work_session import WorkSessionError, combine_snapshots
from test_public_research_request import prepared, finish
from test_research_work_session import snapshots


def test_duplicate_send_and_switch_away_never_reuse_late_answer():
    snapshot, request = prepared()
    release = Event()
    calls = []

    def slow(payload):
        calls.append(payload)
        release.wait(3)
        return PublicResponse("late", "stop")

    controller = ResearchRequestController()
    controller.start(snapshot, request, slow, provider="fixture", model="fake")
    try:
        assert controller.poll(snapshot) == "pending"
        with pytest.raises(WorkSessionError):
            controller.start(snapshot, request, slow, provider="fixture", model="fake")
        controller.synchronize(combine_snapshots(*snapshots("JPM", "US")))
        assert controller.poll(snapshot) == "idle"
        assert controller.attempt_json == "null"
    finally:
        release.set()
    assert len(calls) == 1


def test_completed_invalid_response_records_exact_request_once():
    snapshot, request = prepared()
    controller = ResearchRequestController()
    controller.start(
        snapshot,
        request,
        lambda _: PublicResponse("bad json", "stop"),
        provider="fixture",
        model="fake",
    )
    finish(controller.job, snapshot.fingerprint)
    controller.poll(snapshot)
    record = json.loads(controller.attempt_json)
    assert record["status"] == "invalid"
    assert record["payload"] == json.loads(request.payload_json)
    saved = controller.attempt_json
    controller.poll(snapshot)
    assert controller.attempt_json == saved
    controller.discard()
    assert controller.attempt_json == "null"


@pytest.mark.parametrize(
    "response",
    [
        pytest.param(
            PublicResponse("bad json", "stop", "not-an-iso-date"),
            id="malformed-generated-at",
        ),
        pytest.param(
            PublicResponse("bad json", "stop", None, "not-json"),
            id="malformed-review-json",
        ),
    ],
)
def test_malformed_response_metadata_is_saved_as_invalid_without_raw_output(response):
    snapshot, request = prepared()
    controller = ResearchRequestController()
    controller.start(
        snapshot,
        request,
        lambda _: response,
        provider="fixture",
        model="fake",
    )
    finish(controller.job, snapshot.fingerprint)

    assert controller.poll(snapshot) == "invalid"
    record = json.loads(controller.attempt_json)
    assert record["status"] == "invalid"
    assert record["raw_response"] is None
    assert record["payload"] == json.loads(request.payload_json)
    assert "bad json" not in controller.attempt_json
    assert "not-an-iso-date" not in controller.attempt_json
    assert "not-json" not in controller.attempt_json
    assert controller.poll(snapshot) == "invalid"
