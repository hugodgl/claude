"""Collecte des sources : flux RSS/Atom via feedparser, pages via httpx + trafilatura.

Règles :
- un délai de politesse entre deux requêtes HTTP (`request_delay_s`) ;
- chaque source est traitée dans son propre try/except : une erreur n'arrête pas le lot, elle est
  consignée dans `sources.last_error` ;
- dédoublonnage avant insertion : URL canonique (sans utm/fbclid…) et empreinte de titre normalisé.
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
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import feedparser
import httpx
import trafilatura

from . import db
from .dedup import canonical_url, content_hash, title_hash
from .settings import Settings
from .sources import load_sources, sync_sources

log = logging.getLogger(__name__)

MIN_ARTICLE_CHARS = 300
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
    """Convertit un fragment HTML (résumé RSS) en texte brut compact."""
    if not html:
        return ""
    parser = _TextExtractor()
    parser.feed(html)
    text = unescape("".join(parser.parts))
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


def _registrable(host: str) -> str:
    host = (host or "").lower()
    return host[4:] if host.startswith("www.") else host


def discover_links(html: str, base_url: str, include_patterns: list[str] | None = None,
                   max_links: int = 8) -> list[str]:
    """Trouve, dans une page de liste, les liens qui ressemblent à des articles du même site."""
    parser = _LinkCollector()
    parser.feed(html)
    base_host = _registrable(urlsplit(base_url).hostname or "")
    base_canon = canonical_url(base_url)
    patterns = [re.compile(p) for p in (include_patterns or [])]
    found: list[str] = []
    seen: set[str] = set()
    for href in parser.links:
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
        if canon == base_canon or canon in seen:
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


def extract_article(html: str, url: str) -> dict[str, Any]:
    """Texte principal + métadonnées d'une page d'article (trafilatura, mode précision)."""
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
        parser = _LinkCollector()
        parser.feed(html)
        result["title"] = (parser.title or "").strip() or None
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


# ------------------------------------------------------------------ collecteur
@dataclass
class SourceReport:
    name: str
    kind: str
    seen: int = 0
    inserted: int = 0
    duplicates: int = 0
    skipped: int = 0
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
        if self._requests and self.settings.request_delay_s > 0:
            self.sleep(self.settings.request_delay_s)
        self._requests += 1
        response = self.client.get(url)
        response.raise_for_status()
        return response

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
                items = self._fetch_rss(source)
            else:
                items = self._fetch_page_source(source)
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
    def _fetch_rss(self, source: sqlite3.Row) -> list[FetchedItem]:
        url = source["url"]
        if url.startswith(("http://", "https://")):
            response = self._get(url)
            parsed = feedparser.parse(
                response.content, response_headers={"content-type": response.headers.get("content-type", "")}
            )
        else:
            if not Path(url).exists():
                raise FileNotFoundError(f"fichier de flux introuvable : {url}")
            parsed = feedparser.parse(url)  # chemin local (tests, fixtures, exports)
        if parsed.get("bozo") and not parsed.entries:
            raise ValueError(f"flux illisible : {parsed.get('bozo_exception')}")
        items: list[FetchedItem] = []
        for entry in parsed.entries:
            link = entry.get("link") or next(
                (lk.get("href") for lk in entry.get("links", []) if lk.get("rel", "alternate") == "alternate"),
                None,
            )
            title = html_to_text(entry.get("title", "")).strip()
            if not link or not title:
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
                    article = extract_article(page.text, link)
                    if len(article["text"]) > len(item.content_text or ""):
                        item.content_text = article["text"]
                    item.author = item.author or article["author"]
                    item.published_at = item.published_at or article["published_at"]
                except Exception as exc:  # noqa: BLE001
                    log.info("page de l'entrée %s non récupérée : %s", link, exc)
            items.append(item)
        return items

    # -- pages -------------------------------------------------------------------------------
    def _fetch_page_source(self, source: sqlite3.Row) -> list[FetchedItem]:
        listing = self._get(source["url"])
        patterns = json.loads(source["include_patterns"] or "[]")
        links = discover_links(listing.text, str(listing.url), patterns, self.settings.max_links_per_page)
        items: list[FetchedItem] = []
        for link in links:
            if self.conn.execute("SELECT 1 FROM items WHERE url = ?", (link,)).fetchone():
                continue  # déjà en base : on évite la requête
            try:
                page = self._get(link)
            except httpx.HTTPError as exc:
                log.info("lien ignoré %s : %s", link, exc)
                continue
            article = extract_article(page.text, link)
            if not article["title"] or len(article["text"]) < MIN_ARTICLE_CHARS:
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
        for item in items:
            url = canonical_url(item.url)
            thash = title_hash(item.title, source["name"])
            if not url or thash in batch_hashes or db.item_exists(self.conn, url, thash):
                sr.duplicates += 1
                continue
            batch_hashes.add(thash)
            text = (item.content_text or "")[: self.settings.max_content_chars] or None
            record = {
                "url": url, "title": item.title[:300], "title_hash": thash,
                "published_at": item.published_at, "author": item.author, "summary": item.summary,
                "content_text": text, "content_hash": content_hash(text or item.summary),
            }
            sr.titles.append(item.title)
            if dry_run:
                sr.inserted += 1
                continue
            db.insert_item(self.conn, source["id"], record)
            sr.inserted += 1
