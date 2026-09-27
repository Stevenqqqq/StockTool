from dataclasses import replace
import json
from threading import Event
from time import monotonic, sleep

import pytest

from stock_tool.research.public_request import (
    PreparedPublicRequest,
    PublicRequestJob,
    PublicResponse,
)
from stock_tool.research.public_selection import PUBLIC_QUESTIONS
from stock_tool.research.work_session import WorkSessionError, canonical, combine_snapshots
from test_research_work_session import snapshots


def prepared():
    snapshot = combine_snapshots(*snapshots())
    return snapshot, PreparedPublicRequest.prepare(snapshot, PUBLIC_QUESTIONS[0])


def finish(job, identity):
    deadline = monotonic() + 3
    while monotonic() < deadline:
        result = job.poll(identity)
        if result.status != "pending":
            return result
        sleep(0.001)
    pytest.fail("isolated transport did not finish")


def test_transport_receives_only_public_bytes_and_receipt_matches():
    snapshot, request = prepared()
    sent = []

    def transport(payload):
        sent.append(payload)
        return PublicResponse('{"claims":[]}', "stop")

    job = PublicRequestJob(snapshot, request, transport)
    outcome = finish(job, snapshot.fingerprint)
    assert outcome.status == "received_unverified"
    assert len(sent) == 1
    body = json.loads(sent[0])
    assert set(body) == {"identity", "question", "evidence"}
    assert all(
        set(row) == {"evidence_id", "text", "url", "content_date", "retrieved_at"}
        for row in body["evidence"]
    )
    assert b"CANARY" not in sent[0]
    for forbidden in ("quantity", "average_cost", "weight", "holdings", "snapshot_fingerprint"):
        assert forbidden not in body
    receipt = json.loads(job.local_receipt())
    assert receipt["payload"] == body
    assert receipt["request_fingerprint"] == receipt["selection"]["request_fingerprint"]
    assert "raw_response" not in receipt


@pytest.mark.parametrize("mutation", ["private_field", "question", "manifest", "identity"])
def test_forged_or_stale_previews_never_reach_transport(mutation):
    snapshot, request = prepared()
    payload = json.loads(request.payload_json)
    if mutation == "private_field":
        payload["note"] = "CANARY_DO_NOT_SEND"
    elif mutation == "question":
        payload["question"] = "我的帳號 CANARY_ACCOUNT"
    elif mutation == "identity":
        payload["identity"]["symbol"] = "JPM"
    else:
        request = replace(request, manifest_json="{}")
    request = replace(request, payload_json=canonical(payload))
    sent = []
    with pytest.raises(WorkSessionError):
        PublicRequestJob(snapshot, request, lambda body: sent.append(body))
    assert sent == []


def test_timeout_is_nonblocking_and_late_response_cannot_reappear():
    snapshot, request = prepared()
    entered, release = Event(), Event()
    time = [0.0]

    def transport(payload):
        entered.set()
        release.wait(3)
        return PublicResponse("late", "stop")

    job = PublicRequestJob(snapshot, request, transport, clock=lambda: time[0], timeout_seconds=1)
    try:
        assert entered.wait(1)
        assert job.poll(snapshot.fingerprint).status == "pending"
        # Local snapshot access and serialization remain possible during request.
        assert snapshot.to_dict()["identity"]["symbol"] == "3006"
        time[0] = 2
        assert job.poll(snapshot.fingerprint).status == "timed_out"
    finally:
        release.set()
    assert job.poll(snapshot.fingerprint).raw_response is None
    assert job.poll(snapshot.fingerprint).status == "timed_out"


def test_switching_identity_permanently_discards_old_response():
    snapshot, request = prepared()
    job = PublicRequestJob(snapshot, request, lambda _: PublicResponse("old", "stop"))
    assert job.poll("different fingerprint").status == "superseded"
    assert job.poll(snapshot.fingerprint).status == "superseded"
    assert job.poll(snapshot.fingerprint).raw_response is None


@pytest.mark.parametrize(
    "response",
    [
        PublicResponse("partial", "length"),
        PublicResponse("filtered", "content_filter"),
        PublicResponse("x" * 96_001, "stop"),
        None,
    ],
)
def test_truncated_or_invalid_outputs_never_become_conclusions(response):
    snapshot, request = prepared()
    job = PublicRequestJob(snapshot, request, lambda _: response)
    result = finish(job, snapshot.fingerprint)
    assert result.status == "invalid"
    assert result.raw_response is None


def test_provider_error_never_echoes_secrets_or_automatically_retries():
    snapshot, request = prepared()
    calls = []

    def transport(payload):
        calls.append(payload)
        raise OSError("CANARY_KEY and C:/private/account.txt")

    job = PublicRequestJob(snapshot, request, transport)
    result = finish(job, snapshot.fingerprint)
    assert result.status == "failed"
    assert "CANARY" not in repr(result)
    assert "private" not in job.local_receipt()
    assert len(calls) == 1
    # Explicit retry creates a new attempt with the same reviewed public bytes.
    retry = PublicRequestJob(snapshot, request, transport)
    assert finish(retry, snapshot.fingerprint).status == "failed"
    assert calls == [request.payload_json.encode(), request.payload_json.encode()]
