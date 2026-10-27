"""Extraction robuste de JSON depuis une sortie de modèle de langage."""
from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_think(text: str) -> str:
    """Retire les blocs <think>…</think> que certains modèles locaux (Qwen3) insèrent."""
    return _THINK.sub("", text).strip()


def extract_json(text: str) -> Any:
    """Retourne le premier objet ou tableau JSON trouvé dans `text`.

    Tolère : texte autour, blocs ```json, blocs <think>, virgules finales simples.
    Lève ValueError si rien d'exploitable.
    """
    if text is None:
        raise ValueError("texte vide")
    cleaned = strip_think(text)
    candidates = [cleaned]
    candidates += [m.group(1) for m in _FENCE.finditer(cleaned)]
    decoder = json.JSONDecoder()
    for cand in candidates:
        cand = cand.strip()
        if not cand:
            continue
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            pass
        for i, ch in enumerate(cand):
            if ch in "{[":
                try:
                    obj, _ = decoder.raw_decode(cand[i:])
                    return obj
                except json.JSONDecodeError:
                    # tentative : retirer les virgules finales
                    fixed = re.sub(r",\s*([}\]])", r"\1", cand[i:])
                    try:
                        obj, _ = decoder.raw_decode(fixed)
                        return obj
                    except json.JSONDecodeError:
                        continue
    raise ValueError("aucun JSON exploitable dans la réponse")
