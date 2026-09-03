from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re
import ssl
from urllib.request import Request, urlopen
from xml.etree import ElementTree

import certifi
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ictlab.categories import classify_article
from ictlab.models import NewsArticle


CONTENT_NAMESPACE = "http://purl.org/rss/1.0/modules/content/"
DC_NAMESPACE = "http://purl.org/dc/elements/1.1/"
ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"
MAX_FEED_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class FeedSource:
    name: str
    url: str
    content_limit: int | None = None


@dataclass(frozen=True)
class FeedItem:
    title: str
    original_url: str
    published_at: datetime | None
    content: str | None


@dataclass(frozen=True)
class CollectionResult:
    inserted: int
    duplicates: int


RSS_SOURCES = (
    FeedSource(name="TechCrunch", url="https://techcrunch.com/feed/"),
    FeedSource(
        name="전자신문",
        url="https://rss.etnews.com/03.xml",
        content_limit=1000,
    ),
    FeedSource(
        name="보안뉴스",
        url="https://www.boannews.com/media/news_rss.xml",
        content_limit=1000,
    ),
)


def fetch_feed(url: str) -> bytes:
    request = Request(
        url,
        headers={"User-Agent": "ICTLab/1.0 (+https://ict.metol.cloud)"},
    )
    tls_context = ssl.create_default_context(cafile=certifi.where())
    with urlopen(request, timeout=20, context=tls_context) as response:
        payload = response.read(MAX_FEED_BYTES + 1)
    if len(payload) > MAX_FEED_BYTES:
        raise ValueError("RSS feed exceeds the maximum allowed size")
    return payload


def parse_feed(payload: bytes) -> list[FeedItem]:
    root = ElementTree.fromstring(_normalize_xml_encoding(payload))
    if root.tag == f"{{{ATOM_NAMESPACE}}}feed":
        return _parse_atom(root)
    return _parse_rss(root)


def collect_rss(
    session: Session,
    sources: Iterable[FeedSource] = RSS_SOURCES,
    fetcher: Callable[[str], bytes] = fetch_feed,
) -> CollectionResult:
    inserted = 0
    duplicates = 0

    for source in sources:
        try:
            items = parse_feed(fetcher(source.url))
        except Exception as exc:
            print(f"RSS 수집 실패 [{source.name}]: {exc}")
            continue
        for item in items:
            article = NewsArticle(
                title=item.title,
                original_url=item.original_url,
                source_name=source.name,
                published_at=item.published_at,
                content=_limit_content(item.content, source.content_limit),
            )
            article.category = classify_article(
                article.title,
                article.content,
                article.source_name,
            )
            try:
                with session.begin_nested():
                    session.add(article)
                    session.flush()
            except IntegrityError:
                duplicates += 1
            else:
                inserted += 1

    session.commit()
    return CollectionResult(inserted=inserted, duplicates=duplicates)


def _parse_rss(root: ElementTree.Element) -> list[FeedItem]:
    items = []
    for element in root.findall("./channel/item"):
        title = _text(element.find("title"))
        link = _text(element.find("link"))
        if not title or not link:
            continue
        content = _text(element.find(f"{{{CONTENT_NAMESPACE}}}encoded"))
        if content is None:
            content = _text(element.find("description"))
        published = _text(element.find("pubDate"))
        if published is None:
            published = _text(element.find(f"{{{DC_NAMESPACE}}}date"))
        items.append(
            FeedItem(
                title=title,
                original_url=link,
                published_at=_parse_datetime(published),
                content=content,
            )
        )
    return items


def _parse_atom(root: ElementTree.Element) -> list[FeedItem]:
    namespace = f"{{{ATOM_NAMESPACE}}}"
    items = []
    for element in root.findall(f"{namespace}entry"):
        title = _text(element.find(f"{namespace}title"))
        link_element = element.find(f"{namespace}link[@rel='alternate']")
        if link_element is None:
            link_element = element.find(f"{namespace}link")
        link = link_element.get("href", "").strip() if link_element is not None else ""
        if not title or not link:
            continue
        content = _text(element.find(f"{namespace}content"))
        if content is None:
            content = _text(element.find(f"{namespace}summary"))
        published = _text(element.find(f"{namespace}published"))
        if published is None:
            published = _text(element.find(f"{namespace}updated"))
        items.append(
            FeedItem(
                title=title,
                original_url=link,
                published_at=_parse_datetime(published),
                content=content,
            )
        )
    return items


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _text(element: ElementTree.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _normalize_xml_encoding(payload: bytes) -> bytes:
    declaration = payload[:200]
    match = re.search(br"encoding=[\"']([^\"']+)[\"']", declaration, re.IGNORECASE)
    if match is None:
        return payload
    encoding = match.group(1).decode("ascii")
    if encoding.lower().replace("_", "-") in {"utf-8", "utf8"}:
        return payload
    decoded = payload.decode(encoding)
    decoded = re.sub(
        r"encoding=[\"'][^\"']+[\"']",
        'encoding="utf-8"',
        decoded,
        count=1,
        flags=re.IGNORECASE,
    )
    return decoded.encode("utf-8")


def _limit_content(content: str | None, limit: int | None) -> str | None:
    if content is None or limit is None or len(content) <= limit:
        return content
    return content[:limit].rstrip()
