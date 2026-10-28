"""Extraction robuste de JSON depuis une sortie de modèle de langage."""
from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```[A-Za-z0-9_+-]*[ \t]*\n?(.*?)```", re.DOTALL)
# Bloc <think> fermé, ou ouvert jusqu'à la fin (réponse coupée pendant la réflexion).
_THINK = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL)
_START = re.compile(r"[{\[]")
_TRAILING_COMMA = re.compile(r",\s*([}\]])")
# NaN / Infinity ne sont pas du JSON : convertis en null plutôt que de propager un float nan.
_DECODER = json.JSONDecoder(parse_constant=lambda _name: None)


def strip_think(text: str) -> str:
    """Retire les blocs <think>…</think> que certains modèles locaux (Qwen3) insèrent.

    Un bloc ouvert et jamais refermé (réponse tronquée pendant la réflexion) est retiré jusqu'à la fin :
    ce qu'il contient n'est pas une réponse.
    """
    return _THINK.sub("", text).strip()


def extract_json(text: str) -> Any:
    """Retourne le premier objet (dict) ou tableau (list) JSON trouvé dans `text`.

    Tolère : texte autour, blocs ``` (avec ou sans langage, essayés en premier), blocs <think>,
    virgules finales, accolades dans les chaînes, `NaN`/`Infinity` (convertis en None). Les scalaires
    isolés (`42`, `null`, `"abc"`) ne sont pas des réponses exploitables. Lève ValueError sinon.
    """
    if not text:
        raise ValueError("texte vide")
    cleaned = strip_think(text)
    candidates = [m.group(1) for m in _FENCE.finditer(cleaned)] + [cleaned]
    for cand in candidates:
        cand = cand.strip()
        if not cand:
            continue
        for variant in (cand, _TRAILING_COMMA.sub(r"\1", cand)):
            for m in _START.finditer(variant):
                try:
                    obj, _ = _DECODER.raw_decode(variant, m.start())
                except json.JSONDecodeError:
                    continue
                return obj
    raise ValueError("aucun JSON exploitable dans la réponse")
