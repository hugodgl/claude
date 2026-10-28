"""Ligne éditoriale par produit (plan 4, section 4.2) et angles de traitement."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    bg0: str
    bg1: str
    accent: str
    text: str = "#FFFFFF"
    accent_text: str = "#1A1A1A"


@dataclass(frozen=True)
class Product:
    slug: str
    label: str
    promise: str
    audience: str
    tone: str  # "tu" ou "vous"
    cta_hint: str
    hashtags: tuple[str, ...]
    palette: Palette
    # plateformes préférées, dans l'ordre, pour la rotation du calendrier
    platforms: tuple[str, ...] = ("youtube", "tiktok", "pinterest", "linkedin")


PRODUCTS: dict[str, Product] = {
    "avis": Product(
        slug="avis",
        label="Plus d'avis Google pour les commerces de proximité",
        promise="plus de clients pour ton commerce",
        audience="restaurateurs, coiffeurs, garagistes, artisans et commerçants indépendants",
        tone="tu",
        cta_hint=(
            "le kit gratuit « demander un avis » (affiche QR + trois messages prêts à envoyer)"
        ),
        hashtags=("avisgoogle", "commerce", "commercant", "fichegoogle"),
        palette=Palette(bg0="#2B1B12", bg1="#8A4B10", accent="#FFD166"),
        platforms=("youtube", "tiktok", "pinterest"),
    ),
    "marches": Product(
        slug="marches",
        label=(
            "Les marchés publics sans jargon pour les entreprises d'espaces verts et les artisans"
        ),
        promise="des marchés publics gagnables, expliqués simplement",
        audience=(
            "dirigeants d'entreprises d'espaces verts, paysagistes et artisans du bâtiment "
            "qui n'ont jamais répondu à un appel d'offres"
        ),
        tone="vous",
        cta_hint="la veille gratuite des marchés d'espaces verts de votre département",
        hashtags=("marchespublics", "espacesverts", "paysagiste", "artisan", "appeldoffres"),
        palette=Palette(bg0="#0B2E20", bg1="#1F7A4D", accent="#C6F91F"),
        platforms=("linkedin", "youtube", "tiktok", "pinterest"),
    ),
    "cabinets": Product(
        slug="cabinets",
        label="L'IA concrète en cabinet d'expertise comptable",
        promise="l'IA en cabinet, concrètement, un cas d'usage à la fois",
        audience=(
            "experts-comptables, chefs de mission et collaborateurs de cabinets de 5 à 50 personnes"
        ),
        tone="vous",
        cta_hint="la newsletter hebdo « l'IA en cabinet » (un cas d'usage testé par semaine)",
        hashtags=("expertcomptable", "cabinetcomptable", "ia", "comptabilite"),
        palette=Palette(bg0="#0D1B2A", bg1="#1B5C8A", accent="#5FC9F8"),
        platforms=("linkedin", "youtube", "pinterest"),
    ),
}

ANGLES: dict[str, str] = {
    "script-pret-a-dire": "les phrases exactes à dire ou à écrire, réutilisables telles quelles",
    "erreur-frequente": "l'erreur que presque tout le monde fait, puis comment la corriger",
    "pas-a-pas": "une procédure concrète en étapes numérotées",
    "mythe": "une idée reçue démontée avec un raisonnement simple",
    "checklist": "une liste de vérification courte à cocher",
    "avant-apres": "la situation avant, la situation après, ce qui a changé",
    "cas-concret": "un exemple anonymisé et réaliste, sans nom réel",
    "comparatif": "option A contre option B, et quand choisir l'une ou l'autre",
    "outil": "un outil ou un support concret et la façon de s'en servir",
    "question-piege": "la question que personne n'ose poser, avec une réponse honnête",
}

def get_product(slug: str) -> Product:
    try:
        return PRODUCTS[slug]
    except KeyError:
        raise ValueError(f"produit inconnu : {slug!r} (choix : {', '.join(PRODUCTS)})") from None


def product_rotation(platform: str) -> list[str]:
    """Produits à servir sur une plateforme, dans l'ordre de rotation."""
    return [p.slug for p in PRODUCTS.values() if platform in p.platforms] or list(PRODUCTS)
