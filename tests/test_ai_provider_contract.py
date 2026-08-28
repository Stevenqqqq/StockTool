from __future__ import annotations

import io
import json
from urllib.error import HTTPError, URLError

import pytest

from stock_tool.research.assistant import (
    AIProviderConfig,
    AIProviderFailure,
    ClaimKind,
    EvidenceBundle,
    EvidenceRecord,
    OpenAICompatibleProvider,
)


def _bundle() -> EvidenceBundle:
    return EvidenceBundle(
        symbol="MU",
        market="US",
        snapshot_fingerprint="provider-fixture",
        evidence=(
            EvidenceRecord(
                evidence_id="price-close",
                kind=ClaimKind.FACT,
                label="Latest close",
                text="Latest close is 100.",
                source="fixture-provider",
                provider="fixture-provider",
                symbol="MU",
                market="US",
                field="close",
                available_at="2026-07-27",
                fetched_at="2026-07-27T08:00:00+00:00",
            ),
        ),
    )


class _Response:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _size: int) -> bytes:
        return self.body


def test_openai_compatible_provider_uses_bounded_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _urlopen(request, timeout: float):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["authorization"] = request.get_header("Authorization")
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _Response(
            json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "claims": [
                                            {
                                                "kind": "fact",
                                                "section": "facts",
                                                "text": "Latest close is 100.",
                                                "citation_ids": ["price-close"],
                                            }
                                        ]
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    provider = OpenAICompatibleProvider(
        AIProviderConfig("https://example.test/v1", "test-key", "fixture-model")
    )

    response = provider.generate(_bundle())

    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["timeout"] == 12.0
    assert captured["authorization"] == "Bearer test-key"
    assert captured["payload"]["model"] == "fixture-model"
    assert response["claims"][0]["citation_ids"] == ["price-close"]


@pytest.mark.parametrize(
    "base_url",
    [
        "http://example.test/v1",
        "https://user:password@example.test/v1",
        "https://example.test/v1?token=value",
        "https://example.test/v1#fragment",
    ],
)
def test_remote_or_credentialed_base_urls_are_rejected(base_url: str) -> None:
    with pytest.raises(ValueError):
        AIProviderConfig(base_url, "key", "fixture-model")


@pytest.mark.parametrize("base_url", ["http://localhost:8080/v1", "http://127.0.0.1:8080/v1"])
def test_local_http_compatible_endpoints_remain_supported(base_url: str) -> None:
    config = AIProviderConfig(base_url, "key", "fixture-model")

    assert config.base_url == base_url


@pytest.mark.parametrize(
    "failure",
    [
        URLError("offline"),
        TimeoutError("timeout"),
        HTTPError("https://example.test/v1", 429, "rate limit", {}, io.BytesIO(b"failure")),
        HTTPError("https://example.test/v1", 500, "failure", {}, io.BytesIO(b"failure")),
    ],
)
def test_provider_errors_are_safe_and_do_not_echo_authorization(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    def _urlopen(*_args: object, **_kwargs: object):
        raise failure

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    provider = OpenAICompatibleProvider(
        AIProviderConfig("https://example.test/v1", "super-secret-key", "fixture-model")
    )

    with pytest.raises(AIProviderFailure) as error:
        provider.generate(_bundle())

    assert "super-secret-key" not in str(error.value)
    assert "authorization" not in str(error.value).lower()


@pytest.mark.parametrize(
    "body",
    [b"not-json", b'{"choices": []}', b'{"choices":[{"message":{}}]}'],
)
def test_invalid_or_incomplete_provider_envelope_is_rejected(
    monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: _Response(body))
    provider = OpenAICompatibleProvider(
        AIProviderConfig("https://example.test/v1", "key", "fixture-model")
    )

    with pytest.raises(AIProviderFailure):
        provider.generate(_bundle())


def test_oversized_provider_response_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *_args, **_kwargs: _Response(b"x" * 12_001)
    )
    provider = OpenAICompatibleProvider(
        AIProviderConfig("https://example.test/v1", "key", "fixture-model")
    )

    with pytest.raises(AIProviderFailure):
        provider.generate(_bundle())
