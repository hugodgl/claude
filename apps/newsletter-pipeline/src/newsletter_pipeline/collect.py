"""Collecte des sources : flux RSS/Atom via feedparser, pages via httpx + trafilatura.

Règles :
- un délai de politesse entre deux requêtes HTTP (`request_delay_s`) ;
- chaque source est traitée dans son propre try/except : une erreur n'arrête pas le lot, elle est
  consignée dans `sources.last_error` ; pour une source `page`, un article illisible n'arrête pas la source ;
- toute réponse HTTP est lue en flux et plafonnée à `max_page_bytes` ;
- dédoublonnage avant insertion : URL canonique (sans utm/fbclid/xtor…, http/https et www confondus) et
  empreinte de titre normalisé.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from calendar import timegm
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import feedparser
import httpx
import trafilatura

from . import db
from .dedup import canonical_url, content_hash, title_hash, url_variants
from .settings import Settings
from .sources import load_sources, sync_sources

log = logging.getLogger(__name__)

MIN_ARTICLE_CHARS = 300
MAX_DISCOVERED_LINKS = 100  # liens candidats lus sur une page de liste (avant filtrage des connus)
HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")
EXCLUDED_PATH_PARTS = (
    "/tag/", "/tags/", "/category/", "/categorie/", "/categories/", "/author/", "/auteur/", "/page/",
    "/login", "/connexion", "/contact", "/mentions-legales", "/cgu", "/cgv", "/politique", "/privacy",
    "/cookies", "/newsletter", "/feed", "/rss", "/search", "/recherche", "/wp-json", "/wp-admin",
)
EXCLUDED_SUFFIXES = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".zip", ".xml", ".mp3", ".mp4")


# ------------------------------------------------------------------ utilitaires HTML
class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str | None) -> str:
    """Convertit un fragment HTML (résumé RSS) en texte brut compact. Les entités sont décodées une
    seule fois, par le parseur (`&amp;lt;` reste `&lt;`)."""
    if not html:
        return ""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()  # sans close(), un « & » dans les derniers caractères retient la fin du texte
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.title: str | None = None
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        elif tag == "title" and self.title is None:
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title = (self.title or "") + data


def _links_and_title(html: str) -> tuple[list[str], str | None]:
    parser = _LinkCollector()
    parser.feed(html)
    parser.close()
    return parser.links, parser.title


def _registrable(host: str) -> str:
    host = (host or "").lower()
    return host[4:] if host.startswith("www.") else host


def discover_links(html: str, base_url: str, include_patterns: list[str] | None = None,
                   max_links: int = 8) -> list[str]:
    """Trouve, dans une page de liste, les liens qui ressemblent à des articles du même site."""
    links, _ = _links_and_title(html)
    base_host = _registrable(urlsplit(base_url).hostname or "")
    base_canon = canonical_url(base_url)
    patterns = [re.compile(p) for p in (include_patterns or [])]
    found: list[str] = []
    seen: set[str] = set()
    for href in links:
        href = href.strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base_url, href)
        parts = urlsplit(absolute)
        if parts.scheme not in ("http", "https"):
            continue
        if _registrable(parts.hostname or "") != base_host:
            continue
        canon = canonical_url(absolute)
        if not canon or canon == base_canon or canon in seen:
            continue
        path = parts.path.lower()
        if any(part in path + "/" for part in EXCLUDED_PATH_PARTS) or path.endswith(EXCLUDED_SUFFIXES):
            continue
        if patterns:
            if not any(p.search(absolute) for p in patterns):
                continue
        else:
            segments = [s for s in path.split("/") if s]
            slug = segments[-1] if segments else ""
            if not (len(segments) >= 2 or slug.count("-") >= 3):
                continue
        seen.add(canon)
        found.append(canon)
        if len(found) >= max_links:
            break
    return found


def extract_article(html: str | bytes, url: str) -> dict[str, Any]:
    """Texte principal + métadonnées d'une page d'article (trafilatura, mode précision). Accepte les
    octets bruts : trafilatura détecte alors lui-même l'encodage (utile sans charset dans l'en-tête)."""
    doc = trafilatura.bare_extraction(
        html, url=url, with_metadata=True, include_comments=False, favor_precision=True
    )
    result: dict[str, Any] = {"title": None, "author": None, "published_at": None, "text": "",
                              "description": None}
    if doc is not None:
        result["title"] = (doc.title or "").strip() or None
        result["author"] = (doc.author or "").strip() or None
        result["published_at"] = doc.date or None
        result["text"] = (doc.text or "").strip()
        result["description"] = (doc.description or "").strip() or None
    if not result["title"]:
        text_html = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
        _, title = _links_and_title(text_html)
        result["title"] = (title or "").strip() or None
    return result


def parse_feed_date(entry: Any) -> str | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            try:
                return datetime.fromtimestamp(timegm(value), tz=UTC).replace(microsecond=0).isoformat()
            except (OverflowError, ValueError, TypeError):
                continue
    return None


def sane_date(value: str | None, today: date | None = None) -> str | None:
    """Garde une date ISO plausible (AAAA-MM-JJ ou datetime) ; None si illisible ou dans le futur
    (au-delà de demain : fuseaux obligent)."""
    if not value:
        return None
    try:
        d = date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
    if d > (today or datetime.now(UTC).date()) + timedelta(days=1):
        return None
    return str(value)


def _content_type(response: httpx.Response) -> str:
    return (response.headers.get("content-type") or "").split(";")[0].strip().lower()


def _looks_like_html(response: httpx.Response) -> bool:
    ct = _content_type(response)
    return not ct or ct in HTML_CONTENT_TYPES


# ------------------------------------------------------------------ collecteur
@dataclass
class SourceReport:
    name: str
    kind: str
    seen: int = 0
    inserted: int = 0
    duplicates: int = 0
    skipped: int = 0  # entrées sans lien/titre exploitable, pages non HTML, articles trop courts ou illisibles
    error: str | None = None
    titles: list[str] = field(default_factory=list)


@dataclass
class CollectReport:
    sources: list[SourceReport] = field(default_factory=list)
    dry_run: bool = False

    @property
    def inserted(self) -> int:
        return sum(s.inserted for s in self.sources)

    @property
    def errors(self) -> list[SourceReport]:
        return [s for s in self.sources if s.error]


@dataclass
class FetchedItem:
    url: str
    title: str
    published_at: str | None = None
    author: str | None = None
    summary: str | None = None
    content_text: str | None = None


class Collector:
    def __init__(self, conn: sqlite3.Connection, settings: Settings, *,
                 client: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep):
        self.conn = conn
        self.settings = settings
        self.sleep = sleep
        self._client = client
        self._requests = 0

    # -- HTTP -------------------------------------------------------------------------------
    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self.settings.http_timeout_s,
                headers={"User-Agent": self.settings.user_agent,
                         "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.6"},
                follow_redirects=True,
            )
        return self._client

    def _get(self, url: str) -> httpx.Response:
        """GET avec délai de politesse, lu en flux et plafonné à `max_page_bytes`. Retourne une réponse
        en mémoire (content, text, url, en-tête content-type)."""
        if self._requests and self.settings.request_delay_s > 0:
            self.sleep(self.settings.request_delay_s)
        self._requests += 1
        limit = max(1, int(self.settings.max_page_bytes))
        with self.client.stream("GET", url) as response:
            response.raise_for_status()
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > limit:
                raise ValueError(f"réponse trop volumineuse ({declared} octets, max {limit}) : {url}")
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > limit:
                    raise ValueError(f"réponse trop volumineuse (> {limit} octets) : {url}")
                chunks.append(chunk)
            return httpx.Response(
                response.status_code,
                headers={"content-type": response.headers.get("content-type", "")},
                content=b"".join(chunks),
                request=response.request,
            )

    # -- lot ---------------------------------------------------------------------------------
    def sync_from_yaml(self) -> dict[str, int]:
        return sync_sources(self.conn, load_sources(self.settings.sources_file))

    def run(self, source_name: str | None = None, *, dry_run: bool = False) -> CollectReport:
        report = CollectReport(dry_run=dry_run)
        if source_name:
            source = db.get_source(self.conn, source_name)
            if source is None:
                raise LookupError(f"source inconnue : {source_name!r} (voir `np sources`)")
            sources = [source]
        else:
            sources = db.list_sources(self.conn, active_only=True)
        for source in sources:
            report.sources.append(self.collect_source(source, dry_run=dry_run))
        return report

    def collect_source(self, source: sqlite3.Row, *, dry_run: bool = False) -> SourceReport:
        sr = SourceReport(name=source["name"], kind=source["kind"])
        try:
            if source["kind"] == "rss":
                items = self._fetch_rss(source, sr)
            else:
                items = self._fetch_page_source(source, sr)
            sr.seen = len(items)
            self._store(source, items, sr, dry_run=dry_run)
            if not dry_run:
                db.mark_source_fetched(self.conn, source["id"], None)
        except Exception as exc:  # noqa: BLE001 - une source en erreur n'arrête pas le lot
            sr.error = f"{type(exc).__name__}: {exc}"
            log.warning("source %s en erreur : %s", source["name"], sr.error)
            if not dry_run:
                db.mark_source_fetched(self.conn, source["id"], sr.error)
        return sr

    # -- RSS / Atom --------------------------------------------------------------------------
    def _fetch_rss(self, source: sqlite3.Row, sr: SourceReport) -> list[FetchedItem]:
        url = source["url"]
        if url.startswith(("http://", "https://")):
            response = self._get(url)
            parsed = feedparser.parse(
                response.content, response_headers={"content-type": response.headers.get("content-type", "")}
            )
            base_url = str(response.url)
        else:
            if not Path(url).exists():
                raise FileNotFoundError(f"fichier de flux introuvable : {url}")
            parsed = feedparser.parse(url)  # chemin local (tests, fixtures, exports)
            base_url = str(parsed.feed.get("link") or "")
        if parsed.get("bozo") and not parsed.entries:
            raise ValueError(f"flux illisible : {parsed.get('bozo_exception')}")
        items: list[FetchedItem] = []
        for entry in parsed.entries:
            link = entry.get("link") or next(
                (lk.get("href") for lk in entry.get("links", []) if lk.get("rel", "alternate") == "alternate"),
                None,
            )
            link = urljoin(base_url, str(link).strip()) if link else ""
            title = html_to_text(entry.get("title", "")).strip()
            if not title or not link.lower().startswith(("http://", "https://")):
                sr.skipped += 1
                continue
            summary = html_to_text(entry.get("summary", ""))
            contents = entry.get("content") or []
            content = html_to_text(contents[0].get("value", "")) if contents else ""
            if len(content) < len(summary):
                content = summary
            author = (entry.get("author") or "").strip() or None
            item = FetchedItem(url=link, title=title, published_at=parse_feed_date(entry), author=author,
                               summary=summary[:1000] or None, content_text=content or None)
            if self.settings.rss_fetch_pages:
                try:
                    page = self._get(link)
                    if not _looks_like_html(page):
                        raise ValueError(f"contenu non HTML ({_content_type(page)})")
                    article = extract_article(page.text if page.charset_encoding else page.content, link)
                    if len(article["text"]) > len(item.content_text or ""):
                        item.content_text = article["text"]
                    item.author = item.author or article["author"]
                    item.published_at = item.published_at or article["published_at"]
                except Exception as exc:  # noqa: BLE001 - la page est un bonus, le flux suffit
                    log.info("page de l'entrée %s non récupérée : %s", link, exc)
            items.append(item)
        return items

    # -- pages -------------------------------------------------------------------------------
    def _fetch_page_source(self, source: sqlite3.Row, sr: SourceReport) -> list[FetchedItem]:
        listing = self._get(source["url"])
        if not _looks_like_html(listing):
            raise ValueError(f"page de liste non HTML ({_content_type(listing)}) : {source['url']}")
        patterns = json.loads(source["include_patterns"] or "[]")
        links = discover_links(listing.text, str(listing.url), patterns, MAX_DISCOVERED_LINKS)
        items: list[FetchedItem] = []
        fetched = 0
        for link in links:
            if fetched >= self.settings.max_links_per_page:
                break
            if db.item_exists(self.conn, link):
                continue  # déjà en base : on évite la requête, et on regarde le lien suivant
            fetched += 1
            try:
                page = self._get(link)
                if not _looks_like_html(page):
                    log.info("lien ignoré %s : contenu %s", link, _content_type(page) or "inconnu")
                    sr.skipped += 1
                    continue
                article = extract_article(page.text if page.charset_encoding else page.content, link)
            except Exception as exc:  # noqa: BLE001 - un article illisible n'arrête pas la source
                log.info("lien ignoré %s : %s", link, exc)
                sr.skipped += 1
                continue
            if not article["title"] or len(article["text"]) < MIN_ARTICLE_CHARS:
                sr.skipped += 1
                continue
            items.append(FetchedItem(
                url=link, title=article["title"], published_at=article["published_at"],
                author=article["author"], summary=(article["description"] or article["text"][:400]),
                content_text=article["text"],
            ))
        return items

    # -- stockage ----------------------------------------------------------------------------
    def _store(self, source: sqlite3.Row, items: list[FetchedItem], sr: SourceReport, *, dry_run: bool) -> None:
        batch_hashes: set[str] = set()
        batch_urls: set[str] = set()
        for item in items:
            url = canonical_url(item.url)
            if not url:
                log.info("URL inexploitable ignorée (%s) : %r", source["name"], item.url)
                sr.skipped += 1
                continue
            thash = title_hash(item.title, source["name"])
            variants = url_variants(url)
            if thash in batch_hashes or variants & batch_urls or db.item_exists(self.conn, url, thash):
                sr.duplicates += 1
                continue
            batch_hashes.add(thash)
            batch_urls |= variants
            text = (item.content_text or "")[: self.settings.max_content_chars] or None
            record = {
                "url": url, "title": item.title[:300], "title_hash": thash,
                "published_at": sane_date(item.published_at), "author": item.author, "summary": item.summary,
                "content_text": text, "content_hash": content_hash(text or item.summary),
            }
            sr.titles.append(item.title)
            if dry_run:
                sr.inserted += 1
                continue
            try:
                db.insert_item(self.conn, source["id"], record)
            except sqlite3.IntegrityError:  # URL déjà prise sous une écriture non couverte par les variantes
                sr.duplicates += 1
                continue
            sr.inserted += 1
