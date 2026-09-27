"""Company-specific product and business evidence, independent of ticker-specific rules."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from time import monotonic
from typing import Callable
from urllib.parse import unquote, urljoin

from stock_tool.company_documents import CompanyDocument, fetch_company_document, public_url
from stock_tool.network_deadline import call_with_timeout


@dataclass(frozen=True)
class CompanyFact:
    section: str
    subject: str
    statement: str
    stage: str
    excerpt: str
    url: str
    title: str
    published_at: str
    fetched_at: str


@dataclass(frozen=True)
class CompanyDossier:
    symbol: str
    market: str
    website: str
    industry_lens: str
    facts: tuple[CompanyFact, ...]
    questions: tuple[str, ...]
    gaps: tuple[str, ...]
    documents: tuple[CompanyDocument, ...]
    checked_at: str
    state: str = "fresh"

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(asdict(self), ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()


SECTIONS = ("公司角色", "產品與技術", "應用與客戶", "營運與收入", "進度與變化", "公司揭露的風險")

# These are research questions, never assertions about a company or its customers.
LENSES = (
    (
        "記憶體",
        r"\b(?:dram|nand|nor flash|memory)\b|記憶體",
        (
            "產品世代：DDR／LPDDR／Flash 分別有哪些規格？產品列示、送樣與量產要分開。",
            "收入結構：各種記憶體的營收占比、價格與出貨量如何變化？產品存在不代表收入重要。",
            "風險驗證：庫存、委外產能與產品世代轉換是否影響毛利？沒有直接證據，不把 DDR 當作 HBM／AI 受惠。",
        ),
    ),
    (
        "晶圓代工與半導體",
        r"foundry|semiconductor|半導體|晶圓",
        (
            "技術位置：公司是設計、製造、封測或設備材料供應者？製程／封裝規格與量產日期各是什麼？",
            "收入結構：各技術節點、產品及終端市場的營收比重，與產能利用率如何變化？",
            "風險驗證：資本支出、良率、客戶集中與出口管制是否已有公司層級證據？",
        ),
    ),
    (
        "金融與租賃",
        r"bank|financial|insurance|leasing|金融|銀行|租賃|保險",
        (
            "業務結構：放款、租賃、保險、手續費或投資收入各占多少？不要套用硬體製程指標。",
            "營運品質：淨利差、資金成本、逾放／信用成本、資本適足與地區曝險如何變化？",
            "風險驗證：資產品質、利率與監管變動對哪個業務產生影響？",
        ),
    ),
    (
        "軟體與服務",
        r"software|cloud|saas|軟體|雲端",
        (
            "產品結構：實際產品／服務、目標客戶與訂閱、授權或用量計費方式。",
            "營運品質：經常性收入、續約、客戶留存與雲端成本；只採用公司有公布的指標。",
            "風險驗證：產品競爭、客戶集中、資料安全與基礎設施支出。",
        ),
    ),
    (
        "醫療與生技",
        r"biotech|pharma|health|medical|生技|醫療|藥",
        (
            "產品階段：已核准銷售、臨床各期與研發中產品分開，並核對適應症及法規地區。",
            "營運品質：已上市產品收入、授權金、研發支出與現金可支應期間。",
            "風險驗證：臨床終點、核准條件、專利期限與商業化進度。",
        ),
    ),
    (
        "運輸與航運",
        r"shipping|marine|transport|logistics|航運|海運|物流",
        (
            "服務結構：貨櫃、散裝、物流或客運，航線／船型與服務市場如何分布？",
            "營運品質：運量、運價、裝載率、長約占比與船隊成本；區分公司資料和市場指數。",
            "風險驗證：燃油、運力供需、航線中斷、租船與資本支出。",
        ),
    ),
    (
        "工業與消費",
        r"industrial|consumer|retail|manufactur|工業|消費|零售|製造",
        (
            "產品結構：具體產品線、規格、品牌／代工角色、客戶及銷售通路。",
            "營運品質：產品／地區收入占比、訂單、毛利與庫存；沒有公布就保持缺口。",
            "風險驗證：原料成本、需求、產能、客戶集中及替代品競爭。",
        ),
    ),
)

_PRODUCT = re.compile(
    r"(?<![A-Za-z])(?:LPDDR\s*[1-6](?:X)?|DDR\s*[1-6](?:L)?|DDR\s+I(?:/II(?:/III)?)?|HBM\s*[1-4](?:E)?|"
    r"SDRAM|PSRAM|DRAM|LPDRAM|NOR\s*Flash|NAND\s*Flash|eMMC|MCP|KGD|CoWoS|SoIC|"
    r"\d+(?:\.\d+)?\s*(?:nm|奈米)|PCIe\s*[3-7](?:\.\d)?|"
    r"Wi-Fi\s*[5-8]|Ethernet|Azure|Microsoft\s*365|Dynamics\s*365|Copilot|Surface|"
    r"consumer\s*(?:&|and)\s*community banking|commercial\s*(?:&|and)\s*investment bank(?:ing)?|asset\s*(?:&|and)\s*wealth management|"
    r"\d+\s*(?:Gb|GB|Mbps|MT/s|Gbps))(?![A-Za-z0-9])",
    re.I,
)


def _stage(text: str) -> str:
    # A plan, negation or expectation must never turn into completed production.
    if re.search(
        r"尚未|未量產|未上市|預計|計[劃畫]|規劃|將於|有望|目標|expected|expect|plan|scheduled|will |target|not yet|not in",
        text,
        re.I,
    ):
        return "規劃／預期（非已實現）"
    if re.search(r"送樣|樣品|sampling|samples?\b", text, re.I):
        return "送樣／樣品"
    if re.search(r"研發|開發中|under development|developing|clinical|臨床", text, re.I):
        return "研發／驗證"
    if re.search(
        r"已.{0,12}量產|進入量產|mass production|volume production|commercially available|已上市|獲准",
        text,
        re.I,
    ):
        return "來源提及量產／商用（須看日期及原文）"
    return "官網列示／提及（量產狀態未確認）"


def _lens(text: str) -> tuple[str, tuple[str, ...]]:
    for name, pattern, questions in LENSES:
        if re.search(pattern, text, re.I):
            return name, questions
    return "一般公司", (
        "這家公司具體賣哪些產品或服務？規格、客戶與商業模式各是什麼？",
        "主要收入來源、營收占比與最近營運變化是否有期間明確的公司資料？",
        "關鍵競爭能力、成本與風險的公司證據是什麼？缺少證據不套用其他產業結論。",
    )


def build_dossier(
    symbol: str,
    market: str,
    website: str,
    documents: tuple[CompanyDocument, ...],
    *,
    industry: str = "",
    checked_at: str = "",
    failures: tuple[str, ...] = (),
) -> CompanyDossier:
    facts: list[CompanyFact] = []
    seen: set[tuple[str, str]] = set()
    counters = {section: 0 for section in SECTIONS}
    product_subjects: set[str] = set()
    date_failures: list[str] = []
    for doc in documents:
        if doc.published_at:
            try:
                published = datetime.fromisoformat(doc.published_at.replace("Z", "+00:00"))
                published = published.replace(tzinfo=UTC) if published.tzinfo is None else published
                if published > datetime.now(UTC):
                    raise ValueError("future date")
            except ValueError:
                date_failures.append("有頁面的發布日期無法確認或在未來，該頁未納入分析。")
                continue
        reporting_page = bool(
            re.search(
                r"annual.report|quarterly|earnings|financial.results|/ir/|/investor/|年報|財務報告|營收報告",
                doc.url + " " + doc.title,
                re.I,
            )
        )
        # Prose is preserved, not rewritten into unsupported facts by a model.
        sentences = [
            s.strip()
            for s in re.split(r"\n|(?<=[。！？])\s*|(?<=[.!?])\s+(?=[A-Z])", doc.text)
            if 10 <= len(s.strip()) <= 1400
        ]
        for sentence in sentences:
            if re.search(
                r"olympic|奧運|worldwide partner|in our (?:strongly held )?opinion|legislators wrote|CCAR|stress test, as currently constructed",
                sentence,
                re.I,
            ):
                continue
            if re.search(
                r"cookie|privacy policy|all rights reserved|隱私權|登入|註冊|javascript|copyright|工作環境|福利制度|校園|職涯|apprenticeship|contact sales|sales partner|sales specialist|secondary nav|chart title|yearnet income",
                sentence,
                re.I,
            ):
                continue
            products = tuple(
                dict.fromkeys(re.sub(r"\s+", "", m.group(0)) for m in _PRODUCT.finditer(sentence))
            )
            roles = len(sentence) >= 30 and re.search(
                r"fabless (?:company|semiconductor)|semiconductor foundry|financial services firm|leader in investment banking|IC設計|IC 設計|晶圓代工|專業.{0,8}設計|(?:本公司|我們).{0,8}提供.{0,30}服務|we (?:design|manufacture|develop)|we provide.{0,80}(?:products|services|solutions)",
                sentence,
                re.I,
            )
            categories: list[tuple[str, str]] = []
            if products:
                categories.append(("產品與技術", "、".join(products[:12])))
            elif re.search(
                r"product|solution|service|產品|服務|業務", doc.title, re.I
            ) and re.search(r"提供|推出|包括|涵蓋|offer|provide|include|solution", sentence, re.I):
                categories.append(("產品與技術", "產品／服務內容"))
            if roles:
                categories.append(("公司角色", "供應鏈／商業角色"))
            if len(sentence) >= 35 and re.search(
                r"應用(?!程式)|客戶|車用|工控|伺服器|customers?|automotive|industrial|data center",
                sentence,
                re.I,
            ):
                categories.append(("應用與客戶", "應用／客戶描述"))
            financial_claim = re.search(
                r"本(?:公司|行|集團).{0,30}(?:營收|收入)|(?:營收|營業利益|毛利|利差|逾放|運量).{0,30}\d|"
                r"revenue (?:grew|increased|decreased|was|of)|net interest income|net income",
                sentence,
                re.I,
            )
            if financial_claim or (
                reporting_page
                and re.search(r"\d", sentence)
                and re.search(
                    r"營收|營業利益|毛利|revenue|net interest|net income|margin", sentence, re.I
                )
            ):
                categories.append(("營運與收入", "營運／收入描述"))
            if len(sentence) >= 25 and re.search(
                r"量產|送樣|已上市|年增|mass production|volume production|sampling|grew \d|launched",
                sentence,
                re.I,
            ):
                categories.append(("進度與變化", "公司進度描述"))
            if (
                not re.search(
                    r"(?:AI|artificial intelligence).{0,180}(?:jobs?|employment|labor market|workforce)|"
                    r"(?:jobs?|employment|labor market).{0,180}(?:AI|artificial intelligence)|人工智慧.{0,80}(?:就業|失業|工作機會)",
                    sentence,
                    re.I,
                )
                and (
                    reporting_page
                    or re.search(
                        r"本(?:公司|行|集團).{0,30}(?:風險|下滑)|we face|our (?:business|results).{0,50}(?:risk|adverse)",
                        sentence,
                        re.I,
                    )
                )
                and re.search(
                    r"信用|利率|流動性|匯率|庫存|產能|需求|供應|監管|資本|競爭|地緣|通膨|衰退|"
                    r"credit|interest rate|liquidity|currency|inventory|capacity|demand|supply|regulat|capital|competit|geopolit|inflation|recession|volatil",
                    sentence,
                    re.I,
                )
                and re.search(
                    r"風險|不確定|衰退|下滑|uncertain|headwind|credit loss|adverse|recession|risk (?:of|from)|face.{0,60}risk",
                    sentence,
                    re.I,
                )
            ):
                categories.append(("公司揭露的風險", "公司風險描述"))
            for section, subject in categories:
                if section == "產品與技術" and subject in product_subjects:
                    continue
                if counters[section] >= (24 if section == "產品與技術" else 4):
                    continue
                key = (section, sentence)
                if key in seen:
                    continue
                seen.add(key)
                if section == "產品與技術":
                    product_subjects.add(subject)
                counters[section] += 1
                stage = _stage(sentence)
                statement = f"官網資料提及：{subject}" if section == "產品與技術" else subject
                facts.append(
                    CompanyFact(
                        section,
                        subject,
                        statement,
                        stage,
                        sentence[:1000],
                        doc.url,
                        doc.title,
                        doc.published_at,
                        doc.fetched_at,
                    )
                )
    # Favor distinct specifications instead of repeated descriptions of one family.
    selected: list[CompanyFact] = []
    products_seen: set[str] = set()
    for fact in facts:
        if fact.section == "產品與技術":
            if fact.subject in products_seen:
                continue
            products_seen.add(fact.subject)
        selected.append(fact)
    limits = {
        "公司角色": 2,
        "產品與技術": 12,
        "應用與客戶": 3,
        "營運與收入": 3,
        "進度與變化": 2,
        "公司揭露的風險": 2,
    }
    facts = []
    for section in SECTIONS:
        candidates = [fact for fact in selected if fact.section == section]
        if section == "產品與技術":
            candidates.sort(
                key=lambda fact: (
                    bool(
                        re.search(r"(?:DDR|HBM)\s*[1-6]|\d+\s*(?:Gb|Mbps|nm)", fact.excerpt, re.I)
                    ),
                    len(fact.excerpt) >= 40,
                    len(tuple(_PRODUCT.finditer(fact.excerpt))),
                ),
                reverse=True,
            )
        facts.extend(candidates[: limits[section]])
    lens, questions = _lens(
        industry + " " + " ".join(f.subject for f in facts if f.section == "產品與技術")
    )
    gaps = [
        f"尚未取得足夠的{section}公司證據。" for section, count in counters.items() if not count
    ]
    gaps.extend(
        (
            "產品列示不代表已量產、仍在供貨或已貢獻主要營收；未列出也不代表公司沒有該產品。",
            "尚未逐一核對最新財報分部占比及完整年報；不能據產品目錄推算收入或投資價值。",
        )
    )
    if any(not d.published_at for d in documents):
        gaps.append("部分頁面未提供發布／生效日期；取得日期只能證明本次讀到，不代表內容最新。")
    gaps.extend(failures[:4])
    gaps.extend(dict.fromkeys(date_failures))
    if len(selected) > len(facts):
        gaps.append("畫面與 AI 共用精選的公司證據；完整頁面仍可由來源連結核對。")
    return CompanyDossier(
        symbol,
        market,
        website,
        lens,
        tuple(facts),
        questions,
        tuple(gaps),
        documents,
        checked_at or datetime.now(UTC).isoformat(),
    )


def _link_score(url: str, label: str, lens: str) -> int:
    text = unquote(url + " " + label).lower()
    if re.search(
        r"login|logout|register|career|privacy|cookie|contact|esg|sustainab|/legal/|/impact|/policy|governance|business-principles|/patents|招聘|招募|永續|聯絡|隱私",
        text,
    ):
        return -100
    if re.search(r"\.(?:pdf|zip|xlsx?|png|jpg|svg|mp4)(?:\?|$)", text):
        return -100
    score = 0
    for pattern, points in (
        (r"product|產品|solution|service|服務|technology|技術", 9),
        (r"about|introduction|overview|簡介", 8),
        (r"application|應用", 7),
        (r"investor|financial|營收|財務|法人|annual|業務", 6),
        (r"news|press|新聞", 4),
        (r"/tw/|/zh|chinese|繁體", 6),
    ):
        if re.search(pattern, text):
            score += points
    if lens == "記憶體" and re.search(r"ddr|dram|flash|memory|記憶體", text):
        score += 12
    if re.search(r"ddr[1-6]|hbm|\d+nm|量產", text):
        score += 8
    if re.search(r"introduction|簡介|about us|our businesses|what we do", text):
        score += 24
    if re.search(r"annual.report|quarterly.earnings|financial|財務|營收|earnings.release", text):
        score += 22
    if re.search(r"/ir(?:/|$)|investor relations", text):
        score += 10
    if "?" in url:
        score -= 5
    return score


def _topic(url: str) -> str:
    for topic, pattern in (
        ("finance", r"investor|financial|annual|revenue|/ir(?:/|$)"),
        ("about", r"about|introduction|overview"),
        ("application", r"application|solution"),
        ("news", r"news|press"),
        ("product", r"product|technology|service"),
    ):
        if re.search(pattern, url, re.I):
            return topic
    return "other"


def collect_dossier(
    symbol: str,
    market: str,
    website: str,
    *,
    industry: str,
    cache_dir: Path,
    force: bool = False,
    max_pages: int = 14,
    budget_seconds: float = 90.0,
    loader: Callable[..., CompanyDocument] = fetch_company_document,
) -> CompanyDossier:
    """Read a bounded set of linked company pages; partial failure stays explicit."""
    if market not in {"TWSE", "TPEX", "US"} or not re.fullmatch(r"[A-Z0-9.^_-]{1,24}", symbol):
        return build_dossier(
            symbol, market, website, (), failures=("標的市場或身份未確認，未讀取公司官網。",)
        )
    try:
        origin = public_url(website.replace("http://", "https://", 1), website)
    except (ValueError, TypeError):
        return build_dossier(
            symbol, market, website, (), failures=("沒有可確認的公司 HTTPS 官網，未猜測來源。",)
        )
    key = hashlib.sha256(f"{symbol}|{market}|{origin}".encode()).hexdigest()
    path = cache_dir / f"{key}.json"
    previous: tuple[CompanyDocument, ...] = ()
    now = datetime.now(UTC)
    try:
        if path.stat().st_size > 2_000_000:
            raise ValueError("cache too large")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload["identity"] != [symbol, market, origin] or payload["schema"] != 1:
            raise ValueError("cache identity")
        stamp = datetime.fromisoformat(payload["checked_at"])
        age = (now - stamp).total_seconds()
        docs = payload["documents"]
        if not isinstance(docs, list) or len(docs) > 16 or age < 0:
            raise ValueError("cache contract")
        for doc in docs:
            public_url(doc["url"], origin)
            if not all(
                isinstance(doc[field], str)
                for field in ("title", "text", "published_at", "fetched_at")
            ):
                raise ValueError("cache content")
            obtained = datetime.fromisoformat(doc["fetched_at"])
            if obtained.tzinfo is None or obtained > now or len(doc["text"]) > 120_000:
                raise ValueError("cache timestamp or length")
        previous = tuple(CompanyDocument(**{**doc, "links": ()}) for doc in docs)
        if not force and age < 86400:
            return replace(
                build_dossier(
                    symbol,
                    market,
                    origin,
                    previous,
                    industry=industry,
                    checked_at=payload["checked_at"],
                    failures=tuple(payload.get("failures", ())),
                ),
                state="cached",
            )
    except (OSError, ValueError, KeyError, TypeError):
        previous = ()
    documents: list[CompanyDocument] = []
    failures: list[str] = []
    frontier = [(100, origin)]
    seen: set[str] = set()
    lens, _ = _lens(industry)
    topic_counts: dict[str, int] = {}
    deadline = monotonic() + budget_seconds
    while frontier and len(seen) < max_pages and monotonic() < deadline:

        def priority(item: tuple[int, str]) -> int:
            topic = _topic(item[1])
            return item[0] - 25 * topic_counts.get(topic, 0)

        frontier.sort(key=priority, reverse=True)
        _, url = frontier.pop(0)
        if url in seen:
            continue
        seen.add(url)
        topic = _topic(url)
        topic_counts[topic] = topic_counts.get(topic, 0) + 1
        try:
            remaining = min(18.0, deadline - monotonic())
            if remaining <= 0:
                break
            doc = call_with_timeout(
                lambda: loader(url, origin=origin, timeout=remaining), timeout_seconds=remaining
            )
            public_url(doc.url, origin)
            if len(doc.text.strip()) < 15:
                raise ValueError("頁面沒有可讀正文，可能需要 JavaScript 或登入。")
            documents.append(doc)
            if lens == "一般公司":
                lens, _ = _lens(doc.text[:12000])
            for href, label in doc.links:
                try:
                    link = public_url(urljoin(doc.url, href), origin)
                    score = _link_score(link, label, lens)
                    if score > 0 and link not in seen and all(item[1] != link for item in frontier):
                        frontier.append((score, link))
                except ValueError:
                    continue
            frontier = sorted(frontier, reverse=True)[:150]
        except Exception as exc:
            reason = (
                str(exc)[:140]
                if isinstance(exc, (ValueError, TimeoutError))
                else type(exc).__name__
            )
            failures.append(f"官網部分頁面未完成：{reason}；不以猜測補足。")
    if not documents and previous:
        return replace(
            build_dossier(
                symbol,
                market,
                origin,
                previous,
                industry=industry,
                failures=("本次更新失敗，以下保留前次資料；請核對各頁取得日期。",),
            ),
            state="stale",
        )
    if frontier:
        failures.append("本次已達頁數或時間上限，並未讀完全部官網及文件。")
    result = build_dossier(
        symbol, market, origin, tuple(documents), industry=industry, failures=tuple(failures)
    )
    if documents:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "schema": 1,
                "identity": [symbol, market, origin],
                "checked_at": result.checked_at,
                "documents": [{**asdict(d), "links": []} for d in documents],
                "failures": failures[:4],
            }
            fd, temp = tempfile.mkstemp(dir=cache_dir, suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(payload, stream, ensure_ascii=False)
                os.replace(temp, path)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
        except OSError:
            result = replace(
                result, gaps=(*result.gaps, "本次資料未能保存；重新開啟可能需要再讀取。")
            )
    return result
