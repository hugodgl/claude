"""Correspondances de champs entre les API sources et les modèles normalisés.

Les API n'étaient pas joignables depuis l'environnement de développement : ces dictionnaires sont
écrits d'après la documentation officielle et doivent être vérifiés au premier appel réel
(voir README, section « champs à vérifier »). Chaque clé liste des *chemins candidats*, essayés
dans l'ordre : le premier qui donne une valeur gagne. Un chemin est une suite de clés séparées par
des points ; une liste rencontrée en route est parcourue élément par élément.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

# --------------------------------------------------------------------------------------------
# BOAMP (Opendatasoft, jeu « boamp »)
# --------------------------------------------------------------------------------------------
BOAMP_MAPPING: dict[str, Any] = {
    # champs dont la valeur est une chaîne JSON à décoder avant lecture
    "json_string_fields": ["donnees", "gestion"],
    "source_id": ["idweb", "id"],
    "title": ["objet", "titre", "donnees.OBJET.TITRE_MARCHE"],
    "buyer_name": ["nomacheteur", "acheteur", "donnees.IDENTITE.DENOMINATION"],
    "departments": ["code_departement", "code_departement_prestation", "donnees.OBJET.LIEU_EXEC_LIVR.CODE"],
    # le CPV n'est pas un champ de premier niveau dans toutes les versions du jeu :
    # on essaie des champs directs, puis le JSON `donnees`, puis un balayage de toutes les clés « cpv »
    "cpv_codes": [
        "cpv", "code_cpv", "codes_cpv", "descripteur_code",
        "donnees.OBJET.CPV.PRINCIPAL.CODE", "donnees.OBJET.CPV.SUPPLEMENTAIRE.CODE",
        "donnees.OBJET.LOTS.LOT.CPV.PRINCIPAL.CODE",
    ],
    "cpv_scan_fields": ["donnees"],
    "description": ["donnees.OBJET.OBJET_COMPLET", "donnees.OBJET.CARACTERISTIQUES.DESCRIPTION", "resume_objet",
                    "descripteur_libelle"],
    "estimated_amount": ["donnees.OBJET.VALEUR.ESTIMEE", "donnees.OBJET.VALEUR", "donnees.OBJET.CARACTERISTIQUES.VALEUR",
                         "montant"],
    "published_at": ["dateparution", "date_parution"],
    "deadline_at": ["datelimitereponse", "date_limite_reponse", "donnees.CONDITION_DELAI.RECEPT_OFFRES"],
    "procedure_type": ["procedure_categorise", "procedure_libelle", "type_procedure", "nature_categorise_libelle"],
    "nature": ["nature_categorise_libelle", "nature_libelle", "typeavis_lib", "type_avis", "nature"],
    "url": ["url_avis"],
    "url_template": "https://www.boamp.fr/pages/avis/?q=idweb:%22{source_id}%22",
    # un avis dont la nature contient un de ces mots n'est pas une opportunité (attribution, annulation…)
    "exclude_nature_keywords": ["attribution", "annulation", "résultat", "resultat"],
    # requête Opendatasoft
    "date_field": "dateparution",
    "order_by": "dateparution desc",
    "cpv_where_template": 'search(donnees, "{cpv}")',
    "page_size": 100,
}

# --------------------------------------------------------------------------------------------
# TED (API v3, recherche « expert »)
# --------------------------------------------------------------------------------------------
TED_MAPPING: dict[str, Any] = {
    "source_id": ["publication-number"],
    "title": ["notice-title", "title-proc", "title-lot"],
    "buyer_name": ["buyer-name", "organisation-name-buyer"],
    "nuts": ["place-of-performance", "place-of-performance-subdiv-lot", "place-of-performance-subdiv-proc",
             "buyer-nuts", "organisation-nuts-buyer"],
    "cpv_codes": ["classification-cpv", "main-classification-proc", "main-classification-lot",
                  "additional-classification-proc", "additional-classification-lot"],
    "description": ["description-proc", "description-lot"],
    "estimated_amount": ["estimated-value-proc", "estimated-value-glo-proc", "estimated-value-lot"],
    "amount_currency": ["estimated-value-cur-proc", "estimated-value-cur-glo-proc", "estimated-value-cur-lot"],
    "published_at": ["publication-date", "dispatch-date"],
    "deadline_at": ["deadline-receipt-tender-date-lot", "deadline-date-lot", "deadline-receipt-request-date-lot"],
    "procedure_type": ["procedure-type"],
    "form_type": ["form-type"],
    "notice_type": ["notice-type"],
    "keep_form_types": ["competition"],
    "exclude_notice_type_prefixes": ["can-", "pin-", "veat", "corr", "brin-", "bri-"],
    "url_paths": ["links.html.FRA", "links.html.ENG", "links.htmlDirect.FRA", "links.pdf.FRA", "links.pdf.ENG"],
    "url_template": "https://ted.europa.eu/fr/notice/-/detail/{source_id}",
    "preferred_langs": ["fra", "FRA", "eng", "ENG", "mul", "MUL"],
    # champs demandés dans la requête POST /v3/notices/search
    "search_fields": [
        "publication-number", "notice-title", "buyer-name", "classification-cpv", "publication-date",
        "deadline-receipt-tender-date-lot", "place-of-performance", "estimated-value-proc",
        "estimated-value-cur-proc", "estimated-value-lot", "estimated-value-cur-lot", "procedure-type",
        "notice-type", "form-type", "description-proc", "links",
    ],
    "query_template": "({cpv_clause}) AND place-of-performance={country} AND publication-date>={date}",
    "cpv_clause_template": "classification-cpv={prefix}*",
    "scope": "ACTIVE",
}

# --------------------------------------------------------------------------------------------
# DECP (Opendatasoft, data.economie.gouv.fr : decp-v3 ou decp_augmente)
# --------------------------------------------------------------------------------------------
DECP_MAPPING: dict[str, Any] = {
    "json_string_fields": ["titulaires", "acheteur", "lieuexecution", "lieuExecution"],
    "source_id": ["id", "uid", "identifiant"],
    "title": ["objet", "objet_marche"],
    "buyer_name": ["acheteur_nom", "acheteur.nom", "nomacheteur", "acheteur_name", "nom_acheteur"],
    "buyer_id": ["acheteur_id", "acheteur.id", "idacheteur", "id_acheteur"],
    "holder_name": ["titulaire_denominationsociale", "titulaires.denominationSociale", "titulaire_nom",
                    "titulaires.titulaire.denominationSociale", "titulaire_nom_1", "denominationsociale_titulaire"],
    "holder_id": ["titulaire_id", "titulaires.id", "titulaires.titulaire.id", "titulaire_id_1", "id_titulaire"],
    "amount": ["montant", "montantcalcule", "montant_calcule"],
    "cpv_code": ["codecpv", "codeCPV", "code_cpv", "cpv"],
    "place_code": ["lieuexecution_code", "lieuExecution.code", "lieuexecution.code", "lieu_execution_code"],
    "place_type": ["lieuexecution_typecode", "lieuExecution.typeCode", "lieuexecution.typeCode",
                   "lieu_execution_type_code"],
    "dept": ["departement", "code_departement", "lieuexecution_departement", "departement_execution",
             "codedepartementexecution"],
    "procedure_type": ["procedure"],
    "nature": ["nature"],
    "notified_at": ["datenotification", "dateNotification", "date_notification"],
    "data_published_at": ["datepublicationdonnees", "datePublicationDonnees", "date_publication_donnees"],
    "duration_months": ["dureemois", "dureeMois", "duree_mois"],
    "date_field": "datenotification",
    "cpv_field": "codecpv",
    "order_by": "datenotification desc",
    "page_size": 100,
}

MAPPINGS = {"boamp": BOAMP_MAPPING, "ted": TED_MAPPING, "decp": DECP_MAPPING}

_CPV_RE = re.compile(r"\b(\d{8})(?:-\d)?\b")


# --------------------------------------------------------------------------------------------
# Lecture générique
# --------------------------------------------------------------------------------------------
def decode_json_strings(record: dict[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    """Retourne une copie de l'enregistrement où les champs listés, s'ils sont des chaînes JSON, sont décodés."""
    out = dict(record)
    for f in fields:
        v = out.get(f)
        if isinstance(v, str):
            text = v.strip()
            if text[:1] in "{[":
                try:
                    out[f] = json.loads(text)
                except json.JSONDecodeError:
                    pass
    return out


def get_path(obj: Any, path: str) -> list[Any]:
    """Toutes les valeurs (aplaties) trouvées au bout du chemin ; listes parcourues élément par élément."""
    current: list[Any] = [obj]
    for key in path.split("."):
        nxt: list[Any] = []
        for item in current:
            if isinstance(item, list):
                items = item
            else:
                items = [item]
            for it in items:
                if isinstance(it, dict) and key in it:
                    val = it[key]
                    if isinstance(val, list):
                        nxt.extend(val)
                    else:
                        nxt.append(val)
        current = nxt
        if not current:
            return []
    flat: list[Any] = []
    for v in current:
        if isinstance(v, list):
            flat.extend(v)
        else:
            flat.append(v)
    return [v for v in flat if v is not None and v != ""]


def first_value(obj: Any, paths: Iterable[str]) -> Any:
    for p in paths:
        vals = get_path(obj, p)
        if vals:
            return vals[0]
    return None


def all_values(obj: Any, paths: Iterable[str]) -> list[Any]:
    """Union (dédoublonnée, ordre conservé) des valeurs de tous les chemins candidats."""
    out: list[Any] = []
    for p in paths:
        for v in get_path(obj, p):
            if v not in out:
                out.append(v)
    return out


def scan_cpv_codes(obj: Any) -> list[str]:
    """Balaye récursivement un objet et retourne les codes CPV trouvés sous des clés contenant « cpv »."""
    found: list[str] = []

    def visit(node: Any, under_cpv: bool) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                visit(v, under_cpv or "cpv" in str(k).lower())
        elif isinstance(node, list):
            for v in node:
                visit(v, under_cpv)
        elif under_cpv and isinstance(node, (str, int)):
            for m in _CPV_RE.finditer(str(node)):
                if m.group(1) not in found:
                    found.append(m.group(1))

    visit(obj, False)
    return found


def pick_text(value: Any, preferred_langs: Iterable[str]) -> str | None:
    """Un champ multilingue TED (`{"fra": "…", "eng": "…"}` ou `{"fra": ["…"]}`) → une chaîne."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        for v in value:
            t = pick_text(v, preferred_langs)
            if t:
                return t
        return None
    if isinstance(value, dict):
        for lang in preferred_langs:
            if lang in value:
                t = pick_text(value[lang], preferred_langs)
                if t:
                    return t
        for v in value.values():
            t = pick_text(v, preferred_langs)
            if t:
                return t
    return str(value).strip() or None


def parse_amount(value: Any) -> float | None:
    """`"125 000,50"`, `125000.5`, `{"valeur": 125000}` → 125000.5 ; None si illisible."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for k in ("ESTIMEE", "estimee", "valeur", "value", "amount", "montant"):
            if k in value:
                return parse_amount(value[k])
        return None
    if isinstance(value, list):
        for v in value:
            a = parse_amount(v)
            if a is not None:
                return a
        return None
    text = str(value).strip().replace(" ", "").replace("\xa0", "").replace(" ", "")
    text = re.sub(r"(?i)(eur|€|ht|ttc)", "", text)
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", text)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None
