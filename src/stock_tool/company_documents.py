"""Bounded public-company website reader; never follows instructions in documents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
import http.client
import ipaddress
import re
import socket
import ssl
from time import monotonic
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

import certifi


@dataclass(frozen=True)
class CompanyDocument:
    url: str
    title: str
    text: str
    published_at: str
    fetched_at: str
    links: tuple[tuple[str, str], ...] = ()


def public_url(url: str, origin: str) -> str:
    """Allow only HTTPS within the provider-identified company's domain."""
    parsed, root = urlsplit(url), urlsplit(origin)
    host = (parsed.hostname or "").lower().rstrip(".")
    domain = (root.hostname or "").lower().removeprefix("www.").rstrip(".")
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
        or not domain
        or not (host == domain or host.endswith("." + domain))
    ):
        raise ValueError("僅讀取已確認公司網域的 HTTPS 公開資料。")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("公司來源必須是公開網域。")
    if host == "localhost" or "." not in host:
        raise ValueError("不允許本機來源。")
    return urlunsplit(
        ("https", parsed.netloc, quote(unquote(parsed.path), safe="/:%@-._~"), parsed.query, "")
    )


class _CompanyHTML(HTMLParser):
    """Extract prose separately from navigation, but keep links for discovery."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.title_depth = 0
        self.title_parts: list[str] = []
        self.parts: list[str] = []
        self.blocks: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.anchor = ""
        self.anchor_text: list[str] = []
        self.published_at = ""
        self.hidden: list[str] = []
        self.in_main = False
        self.main_blocks: list[str] = []

    def flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self.parts)).strip()
        if text and text not in self.blocks:
            self.blocks.append(text)
        if text and self.in_main and text not in self.main_blocks:
            self.main_blocks.append(text)
        self.parts = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "main":
            self.flush()
            self.in_main = True
        if tag == "a":
            self.anchor, self.anchor_text = values.get("href") or "", []
        if tag == "meta" and (values.get("property") or values.get("name")) in {
            "article:published_time",
            "datePublished",
            "date",
            "pubdate",
        }:
            self.published_at = (values.get("content") or "")[:32]
        if tag in {"script", "style", "nav", "header", "footer", "form", "noscript", "svg"}:
            self.hidden.append(tag)
        if tag == "title":
            self.title_depth += 1
        if tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "section"}:
            self.flush()

    def handle_endtag(self, tag: str) -> None:
        if tag == "main":
            self.flush()
            self.in_main = False
        if tag == "a" and self.anchor:
            self.links.append((self.anchor, " ".join(self.anchor_text).strip()))
            self.anchor = ""
        if tag in self.hidden:
            self.hidden.remove(tag)
        if tag == "title":
            self.title_depth = max(0, self.title_depth - 1)
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "section"}:
            self.flush()

    def handle_data(self, data: str) -> None:
        if self.anchor:
            self.anchor_text.append(data)
        if self.title_depth:
            self.title_parts.append(data)
        if not self.hidden and not self.title_depth:
            self.parts.append(data)


def parse_company_html(url: str, html: str, fetched_at: str) -> CompanyDocument:
    parser = _CompanyHTML()
    parser.feed(html)
    parser.flush()
    return CompanyDocument(
        url,
        " ".join(parser.title_parts).strip()[:180],
        "\n".join(parser.main_blocks or parser.blocks)[:120_000],
        parser.published_at,
        fetched_at,
        tuple(parser.links[:2500]),
    )


def fetch_company_document(url: str, *, origin: str, timeout: float = 6.0) -> CompanyDocument:
    """Pin a public DNS result for TLS; validate every redirect before connecting."""
    deadline = monotonic() + timeout
    for _ in range(4):
        url = public_url(url, origin)
        parsed = urlsplit(url)
        host = str(parsed.hostname)
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(
            not ipaddress.ip_address(item[4][0]).is_global for item in addresses
        ):
            raise ValueError("公司網域解析到非公開位址，已停止讀取。")
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("官網讀取逾時。")
        # Connect to the validated IP while retaining the original TLS server name.
        raw = socket.create_connection((str(addresses[0][4][0]), 443), timeout=remaining)
        connection = http.client.HTTPSConnection(host, timeout=remaining)
        try:
            context = ssl.create_default_context(cafile=certifi.where())
            connection.sock = context.wrap_socket(raw, server_hostname=host)
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            connection.request(
                "GET",
                path,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; StockTool/1.4; public company research)",
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
                    "Accept-Encoding": "identity",
                },
            )
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                url = urljoin(url, response.getheader("Location") or "")
                continue
            if response.status != 200:
                raise ValueError(f"官網回應 HTTP {response.status}。")
            content_type = response.getheader("Content-Type") or ""
            if (response.getheader("Content-Encoding") or "identity").lower() != "identity":
                raise ValueError("官網使用未支援的壓縮回應，本次未納入分析。")
            if not any(
                value in content_type.lower() for value in ("text/html", "application/xhtml")
            ):
                raise ValueError("本次自動讀取僅支援公開 HTML；文件下載需另行核對。")
            chunks: list[bytes] = []
            length = 0
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError("官網讀取逾時。")
                if connection.sock:
                    connection.sock.settimeout(remaining)
                chunk = response.read(32_768)
                if not chunk:
                    break
                length += len(chunk)
                if length > 2_000_000:
                    raise ValueError("官網頁面過大，已停止讀取。")
                chunks.append(chunk)
            raw_html = b"".join(chunks)
            match = re.search(r"charset=[\"']?([\w-]+)", content_type, re.I)
            encoding = match.group(1) if match else "utf-8"
            try:
                html = raw_html.decode(encoding, errors="replace")
            except LookupError:
                html = raw_html.decode("utf-8", errors="replace")
            return parse_company_html(url, html, datetime.now(UTC).isoformat())
        finally:
            connection.close()
            raw.close()
    raise ValueError("官網重新導向次數過多。")
