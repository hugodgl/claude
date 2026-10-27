"""Prompts (français) : garde-fous éditoriaux, idées de sujets, scripts par format."""

from __future__ import annotations

from .products import ANGLES, Product

SYSTEM_PROMPT = (
    "Tu écris des contenus courts et utiles, en français, pour des indépendants et de petites "
    "entreprises. Règles absolues :\n"
    "1. Français uniquement ; pas un mot d'anglais sauf le nom propre d'un outil.\n"
    "2. Aucun chiffre, pourcentage, montant ou statistique que tu ne peux pas sourcer. Si tu "
    "utilises un chiffre, il vient d'une source publique nommée (organisme, étude, texte "
    "officiel) et tu l'écris dans le champ « description » sous la forme « Source : … ». "
    "Dans le doute, formule sans chiffre.\n"
    "3. Pas de nom de personne réelle ni d'entreprise réelle, pas de promesse de résultat, pas de "
    "conseil juridique ou fiscal personnalisé : tu expliques une méthode.\n"
    "4. Chaque contenu répond précisément à la question posée, avec le vocabulaire du métier ; "
    "zéro généralité sur « l'IA qui change tout » ou « le digital ».\n"
    "5. Phrases courtes, orales, une idée par phrase. Le ton suit la consigne (tutoiement ou "
    "vouvoiement) et reste le même du début à la fin.\n"
    "6. Tu réponds uniquement avec un objet JSON valide, sans texte autour, sans commentaire."
)

FORMAT_INSTRUCTIONS = {
    "short": (
        "vidéo verticale de 45 secondes maximum (environ 80 à 110 mots au total). "
        "hook = première phrase, dite en moins de trois secondes ; body = 4 à 8 phrases, une "
        "par entrée, chacune dicible en une respiration ; cta = dernière phrase ; "
        "duration_s = durée estimée à voix haute, 45 au plus."
    ),
    "long": (
        "vidéo YouTube de 6 à 10 minutes présentée sous forme de plan. body contient exactement "
        "5 entrées, une par partie, chacune commençant par « Partie N — titre : » suivie de 2 à 4 "
        "phrases qui résument ce que la partie dit ; hook = accroche des 15 premières secondes ; "
        "cta = fin de vidéo ; duration_s entre 360 et 600."
    ),
    "linkedin": (
        "post LinkedIn de 150 à 220 mots au total (hook + body + cta). hook = première ligne, "
        "celle qu'on voit avant « voir plus » ; body = 3 à 5 paragraphes courts, un par entrée ; "
        "cta = dernière ligne, une question ou une invitation ; pas de liste d'émojis ; "
        "duration_s = temps de lecture, environ 60."
    ),
    "pin": (
        "épingle Pinterest. title = titre SEO de 60 à 100 caractères contenant le mot-clé "
        "principal ; description = 2 à 3 phrases SEO (500 caractères au plus) avec les mots-clés "
        "placés naturellement ; hook = texte court affiché sur l'image (60 caractères au plus) ; "
        "body = 3 à 5 points très courts affichés sur l'image ; cta = une phrase ; duration_s = 15."
    ),
}

APPROACHES = {
    1: "réponse directe et pratique : la méthode, étape par étape",
    2: "l'erreur fréquente d'abord, puis la correction",
    3: (
        "un mini-cas concret anonymisé (personne ou entreprise imaginaire, sans nom réel), "
        "puis la leçon à retenir"
    ),
}

JSON_SHAPE = (
    '{"hook": str, "body": [str, ...], "cta": str, "title": str, "description": str, '
    '"hashtags": [str, ...], "duration_s": int}'
)


def _tone(product: Product) -> str:
    return "tutoiement" if product.tone == "tu" else "vouvoiement"


def ideas_prompt(product: Product, count: int, existing: list[str]) -> str:
    angles = "\n".join(f"  - {slug} : {desc}" for slug, desc in ANGLES.items())
    listed = "\n".join(f"- {q}" for q in existing[:80]) or "- (aucune)"
    return (
        f"Produit : {product.slug} — {product.label}.\n"
        f"Promesse : {product.promise}. Public : {product.audience}.\n\n"
        f"Propose {count} questions nouvelles que ce public tape réellement dans un moteur de "
        "recherche, pose dans un groupe professionnel ou à un confrère. Questions concrètes, "
        "formulées avec leurs mots, une seule idée par question, 60 à 120 caractères. "
        "Aucune question déjà présente ou quasi identique à la liste ci-dessous.\n\n"
        f"Angles possibles (un par question, varie-les) :\n{angles}\n\n"
        f"Questions déjà en banque :\n{listed}\n\n"
        'Réponds avec exactement : {"questions": [{"question": str, "angle": str}, ...]}'
    )


def script_prompt(
    product: Product, question: str, angle: str | None, fmt: str, variant: int
) -> str:
    angle_desc = ANGLES.get(angle or "", "libre")
    cta_target = f"{product.cta_hint} (lien en description ou en bio)"
    return (
        f"Produit : {product.slug} — {product.label}.\n"
        f"Promesse : {product.promise}. Public : {product.audience}. Ton : {_tone(product)}.\n"
        f"Question du prospect : « {question} »\n"
        f"Angle : {angle or 'libre'} — {angle_desc}.\n"
        f"Format : {fmt} — {FORMAT_INSTRUCTIONS[fmt]}\n"
        f"Variante {variant} — approche : {APPROACHES[variant]}.\n\n"
        f"Réponds avec exactement cet objet JSON : {JSON_SHAPE}\n"
        "- title : moins de 70 caractères, précis, sans promesse mensongère.\n"
        "- description : 2 à 4 phrases pour la description de la plateforme ; si un chiffre est "
        "utilisé quelque part, ajoute « Source : … » ici.\n"
        f"- cta : renvoie vers {cta_target}.\n"
        "- hashtags : 3 à 6 mots-clés, en minuscules, sans espace ni signe #.\n"
        "- body : une phrase (ou un paragraphe pour LinkedIn, une partie pour long) par entrée."
    )
