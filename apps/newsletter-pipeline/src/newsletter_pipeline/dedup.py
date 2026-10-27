"""Dédoublonnage : URL canonique (sans paramètres de suivi) et empreinte de titre normalisé."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Paramètres de suivi retirés des URL : par préfixe (utm_, mtm_, at_… ) ou par nom exact.
TRACKING_PREFIXES = ("utm_", "mtm_", "pk_", "piwik_", "matomo_", "at_", "hsa_", "vero_", "oly_", "mc_", "_hs", "wt.")
TRACKING_PARAMS = frozenset({
    "fbclid", "gclid", "dclid", "gbraid", "wbraid", "msclkid", "igshid", "igsh", "yclid", "twclid", "ttclid",
    "mkt_tok", "ref_src", "ref_url", "s_kwcid", "xtor", "_ga", "_gl", "srsltid", "cmpid", "ncid", "smid",
    "sr_share", "ocid", "trk", "trkcampaign", "spm",
})
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")
_SUFFIX_SEP = re.compile(r"\s+[|–—-]\s+")


def _is_tracking(key: str) -> bool:
    k = key.lower()
    return k in TRACKING_PARAMS or k.startswith(TRACKING_PREFIXES)


def canonical_url(url: str) -> str:
    """Retourne une URL comparable : schéma et hôte en minuscules, sans fragment, sans utm/fbclid/xtor…,
    paramètres restants triés, barre oblique finale retirée (sauf racine).

    Retourne "" pour une URL inexploitable : relative (pas d'hôte), schéma autre que http(s), port invalide."""
    url = (url or "").strip()
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:  # port non numérique, crochets IPv6 mal formés…
        return ""
    scheme = (parts.scheme or "https").lower()
    host = (parts.hostname or "").lower().rstrip(".")
    if scheme not in ("http", "https") or not host:
        return ""
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking(k)]
    query = urlencode(sorted(kept), doseq=True)
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"
    return urlunsplit((scheme, host, path, query, ""))


def url_variants(url: str) -> set[str]:
    """Les quatre écritures équivalentes d'une URL canonique (http/https × avec/sans www), pour
    reconnaître le même article syndiqué sous deux adresses."""
    canon = canonical_url(url)
    if not canon:
        return set()
    parts = urlsplit(canon)
    bare = parts.netloc[4:] if parts.netloc.startswith("www.") else parts.netloc
    return {
        urlunsplit((scheme, host, parts.path, parts.query, ""))
        for scheme in ("http", "https") for host in (bare, "www." + bare)
    }


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
