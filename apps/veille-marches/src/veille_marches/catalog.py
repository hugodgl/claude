"""Référentiels du site : formules et prix, métiers → préfixes CPV, départements, calendrier des envois."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
DIGEST_HOUR = 7          # heure (Paris) du digest quotidien, alignée sur le plist launchd
DIGEST_CUTOFF_HOUR = 6   # inscrit avant 6 h → premier digest le jour même


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    monthly_price: int          # € HT par mois
    yearly_price: int           # € HT par an (10 mois payés)
    max_departments: int
    features: tuple[str, ...]
    highlight: bool = False

    @property
    def yearly_monthly_equivalent(self) -> str:
        return f"{self.yearly_price / 12:.2f}".replace(".", ",").rstrip("0").rstrip(",")

    def price(self, period: str) -> int:
        return self.yearly_price if period == "yearly" else self.monthly_price


PLANS: dict[str, Plan] = {
    "essentiel": Plan(
        code="essentiel", name="Essentiel", monthly_price=29, yearly_price=290, max_departments=2,
        features=(
            "Alertes quotidiennes à 7 h, seulement s'il y a du nouveau",
            "1 métier (codes CPV), 2 départements",
            "Résumé en langage clair et score de 0 à 100 pour chaque marché",
            "Lien vers l'avis original à chaque fois",
            "Réglages modifiables à tout moment, sans engagement",
        ),
    ),
    "pro": Plan(
        code="pro", name="Pro", monthly_price=49, yearly_price=490, max_departments=6, highlight=True,
        features=(
            "Tout Essentiel",
            "Jusqu'à 6 départements",
            "Brief hebdomadaire d'attribution : qui a remporté quoi, à quel prix, quels acheteurs publient",
            "Acheteurs actifs et concurrents récurrents sur 12 mois",
            "Support prioritaire par email",
        ),
    ),
}
PERIODS = {"monthly": "Mensuel", "yearly": "Annuel (10 mois payés, 2 offerts)"}


def plan_or_default(code: str | None) -> Plan:
    return PLANS.get((code or "").strip().lower(), PLANS["essentiel"])


@dataclass(frozen=True)
class Trade:
    code: str
    label: str
    cpv_prefixes: tuple[str, ...]
    hint: str = ""


TRADES: dict[str, Trade] = {
    "espaces_verts": Trade("espaces_verts", "Espaces verts, paysage, élagage", ("773",),
                           "CPV 773xxxxx : plantation, entretien, élagage, arrosage"),
    "nettoyage": Trade("nettoyage", "Nettoyage de locaux", ("9091",), "CPV 9091xxxx : nettoyage de bâtiments"),
    "peinture": Trade("peinture", "Peinture, revêtements, finitions", ("4544", "4543"),
                      "CPV 4544xxxx peinture et vitrerie, 4543xxxx revêtements de sols et murs"),
    "electricite": Trade("electricite", "Électricité (installation)", ("4531",), "CPV 4531xxxx"),
    "plomberie": Trade("plomberie", "Plomberie, chauffage, climatisation", ("4533",), "CPV 4533xxxx"),
    "menuiserie": Trade("menuiserie", "Menuiserie, bois, agencement", ("4542",), "CPV 4542xxxx"),
    "voirie": Trade("voirie", "Voirie, travaux routiers", ("45233",), "CPV 45233xxx"),
    "signaletique": Trade("signaletique", "Signalétique, enseignes", ("34992", "45233290"),
                          "CPV 34992xxx panneaux et enseignes, 45233290 pose de signalisation"),
    "autre": Trade("autre", "Autre métier (indiquez vos préfixes CPV)", (), "ex. 45261 pour la couverture"),
}


def trade_or_default(code: str | None) -> Trade:
    return TRADES.get((code or "").strip().lower(), TRADES["autre"])


def trade_for_prefixes(prefixes: list[str]) -> Trade | None:
    """Retrouve le métier dont les préfixes CPV sont tous présents (pour pré-remplir l'espace abonné)."""
    for trade in TRADES.values():
        if trade.cpv_prefixes and all(p in prefixes for p in trade.cpv_prefixes):
            return trade
    return None


DEPARTMENTS: dict[str, str] = {
    "01": "Ain", "02": "Aisne", "03": "Allier", "04": "Alpes-de-Haute-Provence", "05": "Hautes-Alpes",
    "06": "Alpes-Maritimes", "07": "Ardèche", "08": "Ardennes", "09": "Ariège", "10": "Aube", "11": "Aude",
    "12": "Aveyron", "13": "Bouches-du-Rhône", "14": "Calvados", "15": "Cantal", "16": "Charente",
    "17": "Charente-Maritime", "18": "Cher", "19": "Corrèze", "2A": "Corse-du-Sud", "2B": "Haute-Corse",
    "21": "Côte-d'Or", "22": "Côtes-d'Armor", "23": "Creuse", "24": "Dordogne", "25": "Doubs", "26": "Drôme",
    "27": "Eure", "28": "Eure-et-Loir", "29": "Finistère", "30": "Gard", "31": "Haute-Garonne", "32": "Gers",
    "33": "Gironde", "34": "Hérault", "35": "Ille-et-Vilaine", "36": "Indre", "37": "Indre-et-Loire", "38": "Isère",
    "39": "Jura", "40": "Landes", "41": "Loir-et-Cher", "42": "Loire", "43": "Haute-Loire",
    "44": "Loire-Atlantique", "45": "Loiret", "46": "Lot", "47": "Lot-et-Garonne", "48": "Lozère",
    "49": "Maine-et-Loire", "50": "Manche", "51": "Marne", "52": "Haute-Marne", "53": "Mayenne",
    "54": "Meurthe-et-Moselle", "55": "Meuse", "56": "Morbihan", "57": "Moselle", "58": "Nièvre", "59": "Nord",
    "60": "Oise", "61": "Orne", "62": "Pas-de-Calais", "63": "Puy-de-Dôme", "64": "Pyrénées-Atlantiques",
    "65": "Hautes-Pyrénées", "66": "Pyrénées-Orientales", "67": "Bas-Rhin", "68": "Haut-Rhin", "69": "Rhône",
    "70": "Haute-Saône", "71": "Saône-et-Loire", "72": "Sarthe", "73": "Savoie", "74": "Haute-Savoie",
    "75": "Paris", "76": "Seine-Maritime", "77": "Seine-et-Marne", "78": "Yvelines", "79": "Deux-Sèvres",
    "80": "Somme", "81": "Tarn", "82": "Tarn-et-Garonne", "83": "Var", "84": "Vaucluse", "85": "Vendée",
    "86": "Vienne", "87": "Haute-Vienne", "88": "Vosges", "89": "Yonne", "90": "Territoire de Belfort",
    "91": "Essonne", "92": "Hauts-de-Seine", "93": "Seine-Saint-Denis", "94": "Val-de-Marne", "95": "Val-d'Oise",
    "971": "Guadeloupe", "972": "Martinique", "973": "Guyane", "974": "La Réunion", "976": "Mayotte",
}


def department_label(code: str) -> str:
    name = DEPARTMENTS.get(code)
    return f"{code} – {name}" if name else code


def next_digest_at(now: datetime) -> datetime:
    """Prochain digest (7 h, heure de Paris) : le jour même si l'inscription a lieu avant 6 h, sinon le lendemain."""
    local = now.astimezone(PARIS)
    day = local.date() if local.hour < DIGEST_CUTOFF_HOUR else local.date() + timedelta(days=1)
    return datetime.combine(day, time(DIGEST_HOUR, 0), tzinfo=PARIS)


def next_weekly_brief_at(now: datetime) -> datetime:
    """Prochain brief hebdo : dimanche 18 h (Paris)."""
    local = now.astimezone(PARIS)
    days_ahead = (6 - local.weekday()) % 7
    candidate = datetime.combine(local.date() + timedelta(days=days_ahead), time(18, 0), tzinfo=PARIS)
    if candidate <= local:
        candidate += timedelta(days=7)
    return candidate


@dataclass
class SampleAlert:
    """Exemple d'alerte affiché sur la page d'accueil (construit depuis une fixture, voir `sample.py`)."""

    subject: str
    items: list = field(default_factory=list)
