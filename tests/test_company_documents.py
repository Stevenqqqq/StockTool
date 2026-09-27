from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

import stock_tool.company_documents as reader


@pytest.fixture
def transport(monkeypatch):
    requests = []
    closed = []
    responses = []
    monkeypatch.setattr(
        reader.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))]
    )
    raw = SimpleNamespace(close=lambda: closed.append("raw"), settimeout=lambda value: None)
    monkeypatch.setattr(reader.socket, "create_connection", lambda address, **k: raw)
    monkeypatch.setattr(
        reader.ssl,
        "create_default_context",
        lambda **k: SimpleNamespace(wrap_socket=lambda sock, **k: sock),
    )

    class Connection:
        sock = None

        def __init__(self, host, **kwargs):
            self.host = host

        def request(self, method, path, headers):
            requests.append((self.host, method, path, headers))

        def getresponse(self):
            return responses.pop(0)

        def close(self):
            closed.append("connection")

    monkeypatch.setattr(reader.http.client, "HTTPSConnection", Connection)
    return requests, responses, closed


def response(body=b"<main><p>We provide DDR4 memory products.</p></main>", status=200, **headers):
    headers = {"Content-Type": "text/html; charset=utf-8", **headers}
    return SimpleNamespace(
        status=status, getheader=lambda name: headers.get(name), read=io.BytesIO(body).read
    )


def test_public_reader_pins_dns_preserves_tls_name_and_closes_connection(transport):
    requests, responses, closed = transport
    responses.append(response())
    doc = reader.fetch_company_document(
        "https://example.com/products", origin="https://example.com"
    )
    assert "DDR4" in doc.text and doc.fetched_at
    assert requests[0][:3] == ("example.com", "GET", "/products")
    assert set(closed) == {"connection", "raw"}


def test_redirect_is_revalidated_before_second_connection(transport):
    requests, responses, closed = transport
    responses.append(response(status=302, Location="http://127.0.0.1/private"))
    with pytest.raises(ValueError):
        reader.fetch_company_document("https://example.com", origin="https://example.com")
    assert len(requests) == 1 and closed


def test_same_domain_redirect_reads_final_document(transport):
    requests, responses, _ = transport
    responses.extend((response(status=302, Location="/products"), response()))
    doc = reader.fetch_company_document("https://example.com", origin="https://example.com")
    assert len(requests) == 2 and doc.url == "https://example.com/products"


@pytest.mark.parametrize(
    "bad",
    [
        response(status=403),
        response(**{"Content-Type": "application/pdf"}),
        response(**{"Content-Encoding": "gzip"}),
        response(body=b"x" * 2_000_001),
    ],
)
def test_unreadable_or_oversized_content_cannot_become_evidence(transport, bad):
    _, responses, closed = transport
    responses.append(bad)
    with pytest.raises(ValueError):
        reader.fetch_company_document("https://example.com", origin="https://example.com")
    assert closed


def test_private_dns_is_rejected_before_socket_connection(monkeypatch):
    monkeypatch.setattr(
        reader.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))]
    )
    monkeypatch.setattr(
        reader.socket,
        "create_connection",
        lambda *a, **k: pytest.fail("private connection attempted"),
    )
    with pytest.raises(ValueError):
        reader.fetch_company_document("https://example.com", origin="https://example.com")


@pytest.mark.parametrize(
    "url", ["https://8.8.8.8", "https://[2606:4700:4700::1111]", "https://localhost"]
)
def test_ip_literal_cannot_define_company_identity(url):
    with pytest.raises(ValueError):
        reader.public_url(url, url)
