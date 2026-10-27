"""Accès au LLM via le socle commun (`core.llm.get_llm`), avec un simulateur réaliste en mode `mock`.

En mode `mock`, `MockLLM` répond `{}` par défaut : inutilisable pour une démo. On lui branche un
répondeur déterministe qui produit des idées et des scripts plausibles, ce qui permet de dérouler
toute la chaîne (sujet → script → validation → rendu → dry-run) sans Ollama ni réseau.
"""
from __future__ import annotations

import json
import re

from core.llm import LLM, MockLLM, get_llm

from .settings import Settings

_QUESTION_RE = re.compile(r"Question du prospect : « (.+?) »")
_FORMAT_RE = re.compile(r"Format : (short|long|linkedin|pin)\b")
_PRODUCT_RE = re.compile(r"Produit : (\w+)")
_VARIANT_RE = re.compile(r"Variante (\d)")
_COUNT_RE = re.compile(r"Propose (\d+) questions")
_EXISTING_RE = re.compile(r"^- (.+)$", re.MULTILINE)


class FakeResponder:
    """Réponses JSON plausibles et déterministes pour `MockLLM` (tests, démo sans modèle)."""

    def __init__(self) -> None:
        self.calls = 0
        self.ideas_counter = 0

    def __call__(self, prompt: str, system: str | None) -> str:
        self.calls += 1
        if '"questions"' in prompt:
            return self._ideas(prompt)
        return self._script(prompt)

    def _ideas(self, prompt: str) -> str:
        count = int(_COUNT_RE.search(prompt).group(1)) if _COUNT_RE.search(prompt) else 5
        product = _PRODUCT_RE.search(prompt).group(1) if _PRODUCT_RE.search(prompt) else "avis"
        existing = _EXISTING_RE.findall(prompt)
        angles = ["pas-a-pas", "mythe", "checklist", "erreur-frequente", "outil", "cas-concret"]
        questions = []
        if existing:  # un doublon volontaire : le dédoublonnage doit l'écarter
            questions.append({"question": existing[0], "angle": "mythe"})
        for _ in range(count):
            self.ideas_counter += 1
            n = self.ideas_counter
            questions.append(
                {
                    "question": f"Question simulée numéro {n} sur le thème {product} : par où commencer ?",
                    "angle": angles[n % len(angles)],
                }
            )
        return json.dumps({"questions": questions}, ensure_ascii=False)

    def _script(self, prompt: str) -> str:
        q = _QUESTION_RE.search(prompt).group(1) if _QUESTION_RE.search(prompt) else "la question"
        fmt = _FORMAT_RE.search(prompt).group(1) if _FORMAT_RE.search(prompt) else "short"
        variant = int(_VARIANT_RE.search(prompt).group(1)) if _VARIANT_RE.search(prompt) else 1
        base = q.rstrip(" ?.!")
        prefixes = {1: "", 2: "L'erreur à éviter : ", 3: "Cas concret : "}
        title = (prefixes[variant] + base)[:70]
        hashtags = ["conseil", "methode", "independant"]
        if fmt == "short":
            payload = {
                "hook": f"{base} ? La réponse tient en trente secondes.",
                "body": [
                    "D'abord, on pose le problème en une phrase, sans jargon.",
                    "Ensuite, on regarde ce qui existe déjà avant d'acheter quoi que ce soit.",
                    "Puis on teste sur un seul cas, pendant une semaine.",
                    "On note ce qui a marché, et ce qui a coincé.",
                    "Et seulement après, on généralise.",
                ],
                "cta": "Le guide complet est en lien dans la bio.",
                "title": title,
                "description": f"{base} : la méthode simple, sans jargon, pour s'y mettre dès cette semaine.",
                "hashtags": hashtags,
                "duration_s": 32,
            }
        elif fmt == "long":
            payload = {
                "hook": f"{base} ? Voici le plan complet, étape par étape.",
                "body": [
                    "Partie 1 — Le problème : pourquoi cette question revient tout le temps, et ce qu'elle cache vraiment.",
                    "Partie 2 — Les idées reçues : ce que l'on croit, et pourquoi c'est souvent faux.",
                    "Partie 3 — La méthode : les étapes dans l'ordre, avec ce qu'il faut préparer avant.",
                    "Partie 4 — Le cas concret : une entreprise imaginaire déroule la méthode, avec ses erreurs.",
                    "Partie 5 — Le plan d'action : quoi faire cette semaine, et comment mesurer le résultat.",
                ],
                "cta": "Le modèle de document est en description, et dites-moi en commentaire ce qui bloque chez vous.",
                "title": title,
                "description": f"{base} : une méthode complète en cinq parties, avec un cas concret et un plan d'action.",
                "hashtags": hashtags,
                "duration_s": 480,
            }
        elif fmt == "linkedin":
            payload = {
                "hook": f"{base} ? La vraie réponse est moins compliquée qu'on ne le pense.",
                "body": [
                    "Dans la plupart des entreprises que je rencontre, la même scène se répète : "
                    "cette question arrive en fin de réunion, quand tout le monde est déjà fatigué, "
                    "et elle reste sans réponse claire pendant des mois.",
                    "Pourtant la réponse tient en trois idées simples. D'abord, poser le problème par "
                    "écrit en une phrase, sans jargon. Ensuite, regarder ce qui existe déjà dans "
                    "l'entreprise avant d'acheter quoi que ce soit. Enfin, tester sur un seul cas "
                    "pendant une semaine, et mesurer avec honnêteté ce que cela change.",
                    "Ce qui bloque n'est presque jamais la technique. C'est l'absence de temps dédié "
                    "et la peur de mal faire. Un créneau court, bloqué dans l'agenda chaque semaine, "
                    "suffit pour avancer sans mettre l'activité en danger.",
                    "La semaine prochaine, je partage le détail de la méthode, étape par étape, "
                    "avec les pièges à éviter et un exemple complet.",
                ],
                "cta": "Si le sujet vous parle, dites-le en commentaire : je vous envoie la fiche complète.",
                "title": title,
                "description": f"Post LinkedIn : {base}.",
                "hashtags": hashtags,
                "duration_s": 60,
            }
        else:  # pin
            payload = {
                "hook": base[:60],
                "body": [
                    "Poser le problème en une phrase",
                    "Vérifier ce qui existe déjà",
                    "Tester sur un seul cas",
                    "Mesurer, puis généraliser",
                ],
                "cta": "Le guide complet est sur la page liée.",
                "title": f"{base} : la méthode simple en quatre étapes"[:100],
                "description": (
                    f"{base} : une méthode claire, sans jargon, pour s'y mettre cette semaine. "
                    "Guide complet et modèle à télécharger sur la page liée."
                )[:500],
                "hashtags": hashtags,
                "duration_s": 15,
            }
        return json.dumps(payload, ensure_ascii=False)


def get_engine_llm(settings: Settings) -> LLM:
    """LLM de l'app : toujours via `core.llm.get_llm` ; en mode mock, répondeur réaliste."""
    llm = get_llm(settings)
    if isinstance(llm, MockLLM):
        return MockLLM(responses=FakeResponder())
    return llm
