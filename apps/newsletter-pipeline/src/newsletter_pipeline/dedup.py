"""Dédoublonnage : URL canonique (sans paramètres de suivi) et empreinte de titre normalisé."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Paramètres de suivi retirés des URL (en plus de tout paramètre commençant par `utm_`).
TRACKING_PARAMS = frozenset({
    "fbclid", "gclid", "dclid", "gbraid", "wbraid", "msclkid", "igshid", "yclid", "twclid",
    "mc_cid", "mc_eid", "_hsenc", "_hsmi", "mkt_tok", "ref_src", "oly_enc_id", "oly_anon_id",
    "vero_id", "s_kwcid", "pk_campaign", "pk_kwd", "piwik_campaign", "matomo_campaign",
})
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")
_SUFFIX_SEP = re.compile(r"\s+[|–—-]\s+")


def canonical_url(url: str) -> str:
    """Retourne une URL comparable : schéma et hôte en minuscules, sans fragment, sans utm/fbclid…,
    paramètres restants triés, barre oblique finale retirée (sauf racine)."""
    url = (url or "").strip()
    if not url:
        return ""
    parts = urlsplit(url)
    scheme = (parts.scheme or "https").lower()
    host = parts.hostname.lower() if parts.hostname else ""
    port = parts.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    kept = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    ]
    query = urlencode(sorted(kept), doseq=True)
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"
    return urlunsplit((scheme, host, path, query, ""))


def normalize_title(title: str, source_name: str | None = None) -> str:
    """Minuscules, sans accents ni ponctuation, espaces réduits ; retire un suffixe « - Nom de la
    source » ou « | Nom de la source » quand il est présent."""
    t = unicodedata.normalize("NFKD", title or "")
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = t.strip()
    if source_name:
        src = unicodedata.normalize("NFKD", source_name)
        src = "".join(ch for ch in src if not unicodedata.combining(ch)).strip().lower()
        pieces = _SUFFIX_SEP.split(t)
        if len(pieces) > 1 and pieces[-1].strip().lower() == src:
            t = " ".join(pieces[:-1])
    t = t.lower()
    t = _PUNCT.sub(" ", t)
    t = _SPACES.sub(" ", t).strip()
    return t


def title_hash(title: str, source_name: str | None = None) -> str:
    return hashlib.sha1(normalize_title(title, source_name).encode("utf-8")).hexdigest()


def content_hash(text: str | None) -> str | None:
    if not text:
        return None
    normalized = _SPACES.sub(" ", text).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
