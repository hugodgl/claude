"""Profils de ton : 3 presets et génération de 3 exemples de réponses par LLM."""
from __future__ import annotations

import logging
from typing import Any

from core.llm import LLM, LLMError, complete_json

log = logging.getLogger(__name__)

PRESETS: dict[str, dict[str, Any]] = {
    "chaleureux": {
        "label": "Chaleureux",
        "description": "Proche, humain, on remercie avec le sourire.",
        "do": ["remercier chaleureusement et nommément", "reprendre un détail concret de l'avis",
               "inviter à revenir"],
        "dont": ["pas de formule commerciale", "pas d'émoji", "pas de phrase de plus de 20 mots"],
    },
    "sobre": {
        "label": "Sobre",
        "description": "Court, professionnel, sans effusion.",
        "do": ["remercier simplement", "rester factuel et courtois", "vouvoyer"],
        "dont": ["pas de points d'exclamation à répétition", "pas d'émoji", "pas de familiarité"],
    },
    "dynamique": {
        "label": "Dynamique",
        "description": "Enjoué, énergique, phrases courtes.",
        "do": ["ton enjoué", "phrases courtes et rythmées", "un point d'exclamation bienvenu"],
        "dont": ["pas d'émoji", "pas d'argot", "pas de promesse (remise, cadeau)"],
    },
}

FALLBACK_EXAMPLES: dict[str, list[str]] = {
    "chaleureux": [
        "Merci infiniment {prenom} pour ce retour qui nous touche ! Toute l'équipe est ravie que votre visite "
        "vous ait plu. Au plaisir de vous accueillir à nouveau très bientôt. {signature}",
        "Merci {prenom} pour votre avis et vos remarques, que nous prenons à cœur. Nous espérons vous "
        "revoir bientôt pour vous offrir une expérience encore meilleure. {signature}",
        "Bonjour {prenom}, nous sommes sincèrement désolés que votre expérience n'ait pas été à la hauteur. "
        "Nous aimerions en parler avec vous : n'hésitez pas à nous contacter directement. {signature}",
    ],
    "sobre": [
        "Merci {prenom} pour votre avis. Nous sommes heureux que votre visite vous ait donné satisfaction. "
        "À bientôt. {signature}",
        "Merci {prenom} pour ce retour. Nous prenons note de votre remarque afin de nous améliorer. "
        "{signature}",
        "Bonjour {prenom}, nous regrettons que votre expérience ne vous ait pas satisfait. Nous vous "
        "invitons à nous contacter directement afin d'en discuter. {signature}",
    ],
    "dynamique": [
        "Un grand merci {prenom} ! Votre avis fait plaisir à toute l'équipe. À très vite ! {signature}",
        "Merci {prenom} pour votre retour ! On garde votre remarque en tête pour faire encore mieux la "
        "prochaine fois. À bientôt ! {signature}",
        "Bonjour {prenom}, désolés que ce passage ne vous ait pas convaincu. On aimerait comprendre ce qui "
        "a coincé : contactez-nous directement, on s'en occupe. {signature}",
    ],
}

SAMPLE_REVIEWS = [
    ("5", "Accueil au top, produits excellents, on reviendra !"),
    ("4", "Très bien dans l'ensemble, juste un peu d'attente à la caisse."),
    ("2", "Déçu : commande incomplète et personne pour s'en occuper."),
]

SYSTEM_EXAMPLES = (
    "Tu aides un commerce de proximité à répondre publiquement à ses avis clients. "
    "Tu écris en français, à la première personne du pluriel, sans émoji, sans promesse commerciale "
    "(pas de remise, cadeau ni remboursement), sans donnée personnelle (ni téléphone, ni email, ni adresse), "
    "60 mots maximum par réponse. Réponds uniquement en JSON."
)


def default_profile(style: str, establishment_name: str, signature: str | None = None) -> dict[str, Any]:
    preset = PRESETS.get(style) or PRESETS["chaleureux"]
    return {
        "style": style if style in PRESETS else "chaleureux",
        "signature": (signature or "").strip() or f"L'équipe de {establishment_name}",
        "do": list(preset["do"]),
        "dont": list(preset["dont"]),
        "exemples": [],
    }


def fallback_examples(profile: dict[str, Any]) -> list[str]:
    style = profile.get("style", "chaleureux")
    sig = profile.get("signature", "")
    return [e.format(prenom="Camille", signature=sig).strip() for e in FALLBACK_EXAMPLES[style]]


def generate_examples(llm: LLM, establishment_name: str, profile: dict[str, Any]) -> tuple[list[str], bool]:
    """Retourne (3 exemples, généré_par_llm). Bascule sur des exemples par défaut si le modèle échoue."""
    reviews_block = "\n".join(f"- Avis {i + 1} ({note} étoiles) : « {texte} »"
                              for i, (note, texte) in enumerate(SAMPLE_REVIEWS))
    prompt = (
        f"Établissement : {establishment_name}\n"
        f"Style demandé : {profile.get('style')}\n"
        f"À faire : {'; '.join(profile.get('do', []))}\n"
        f"À éviter : {'; '.join(profile.get('dont', []))}\n"
        f"Signature à placer en fin de réponse : {profile.get('signature')}\n\n"
        "Rédige une réponse pour chacun de ces trois avis fictifs, qui serviront d'exemples de ton :\n"
        f"{reviews_block}\n\n"
        'Réponds avec un objet JSON de la forme {"exemples": ["réponse 1", "réponse 2", "réponse 3"]}.'
    )
    try:
        data = complete_json(llm, prompt, system=SYSTEM_EXAMPLES, max_tokens=800)
    except LLMError as e:
        log.warning("génération des exemples de ton impossible : %s", e)
        return fallback_examples(profile), False
    examples = data.get("exemples") if isinstance(data, dict) else None
    if not isinstance(examples, list) or len([e for e in examples if isinstance(e, str) and e.strip()]) < 3:
        return fallback_examples(profile), False
    return [e.strip() for e in examples if isinstance(e, str) and e.strip()][:3], True
