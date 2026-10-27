"""Correspondance NUTS 3 (nomenclature 2021) → code département français. Utilisée pour TED."""
from __future__ import annotations

NUTS3_TO_DEPT: dict[str, str] = {
    # Île-de-France
    "FR101": "75", "FR102": "77", "FR103": "78", "FR104": "91", "FR105": "92", "FR106": "93",
    "FR107": "94", "FR108": "95",
    # Centre-Val de Loire
    "FRB01": "18", "FRB02": "28", "FRB03": "36", "FRB04": "37", "FRB05": "41", "FRB06": "45",
    # Bourgogne-Franche-Comté
    "FRC11": "21", "FRC12": "58", "FRC13": "71", "FRC14": "89", "FRC21": "25", "FRC22": "39",
    "FRC23": "70", "FRC24": "90",
    # Normandie
    "FRD11": "14", "FRD12": "50", "FRD13": "61", "FRD21": "27", "FRD22": "76",
    # Hauts-de-France
    "FRE11": "59", "FRE12": "62", "FRE21": "02", "FRE22": "60", "FRE23": "80",
    # Grand Est
    "FRF11": "67", "FRF12": "68", "FRF21": "08", "FRF22": "10", "FRF23": "51", "FRF24": "52",
    "FRF31": "54", "FRF32": "55", "FRF33": "57", "FRF34": "88",
    # Pays de la Loire
    "FRG01": "44", "FRG02": "49", "FRG03": "53", "FRG04": "72", "FRG05": "85",
    # Bretagne
    "FRH01": "22", "FRH02": "29", "FRH03": "35", "FRH04": "56",
    # Nouvelle-Aquitaine
    "FRI11": "24", "FRI12": "33", "FRI13": "40", "FRI14": "47", "FRI15": "64", "FRI21": "19",
    "FRI22": "23", "FRI23": "87", "FRI31": "16", "FRI32": "17", "FRI33": "79", "FRI34": "86",
    # Occitanie
    "FRJ11": "11", "FRJ12": "30", "FRJ13": "34", "FRJ14": "48", "FRJ15": "66", "FRJ21": "09",
    "FRJ22": "12", "FRJ23": "31", "FRJ24": "32", "FRJ25": "46", "FRJ26": "65", "FRJ27": "81",
    "FRJ28": "82",
    # Auvergne-Rhône-Alpes
    "FRK11": "03", "FRK12": "15", "FRK13": "43", "FRK14": "63", "FRK21": "01", "FRK22": "07",
    "FRK23": "26", "FRK24": "38", "FRK25": "42", "FRK26": "69", "FRK27": "73", "FRK28": "74",
    # Provence-Alpes-Côte d'Azur
    "FRL01": "04", "FRL02": "05", "FRL03": "06", "FRL04": "13", "FRL05": "83", "FRL06": "84",
    # Corse
    "FRM01": "2A", "FRM02": "2B",
    # Outre-mer
    "FRY10": "971", "FRY20": "972", "FRY30": "973", "FRY40": "974", "FRY50": "976",
}


def dept_from_nuts(code: str | None) -> str | None:
    """`FRK26` → `69`. Un code plus large (`FRK2`, `FR`, `FRA`) ou étranger donne None."""
    if not code:
        return None
    return NUTS3_TO_DEPT.get(str(code).strip().upper())


def is_french_nuts(code: str | None) -> bool:
    return bool(code) and str(code).strip().upper().startswith("FR")
