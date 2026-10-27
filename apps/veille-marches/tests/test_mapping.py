"""Mapping des enregistrements sources vers les modèles normalisés."""
from datetime import UTC

from conftest import load_fixture

from veille_marches.collectors.boamp import is_excluded_nature, map_boamp_record
from veille_marches.collectors.decp import department_from_place, map_decp_record
from veille_marches.collectors.ted import build_query, is_opportunity, map_ted_notice
from veille_marches.dates import parse_dt
from veille_marches.mapping import (
    all_values,
    decode_json_strings,
    first_value,
    get_path,
    parse_amount,
    pick_text,
    scan_cpv_codes,
)
from veille_marches.models import Notice, Subscriber, normalize_cpv, normalize_department
from veille_marches.nuts import dept_from_nuts


# ---------------------------------------------------------------- outils génériques
def test_get_path_flattens_lists():
    obj = {"a": {"lots": [{"cpv": {"code": "1"}}, {"cpv": {"code": "2"}}, {"cpv": {"code": ["3", "4"]}}]}}
    assert get_path(obj, "a.lots.cpv.code") == ["1", "2", "3", "4"]
    assert get_path(obj, "a.missing.code") == []
    assert first_value(obj, ["a.missing", "a.lots.cpv.code"]) == "1"
    assert all_values(obj, ["a.lots.cpv.code", "a.lots.cpv.code"]) == ["1", "2", "3", "4"]


def test_decode_json_strings_only_when_json():
    rec = {"donnees": '{"OBJET": {"CPV": {"PRINCIPAL": {"CODE": "77310000"}}}}', "gestion": "pas du json", "x": 1}
    out = decode_json_strings(rec, ["donnees", "gestion"])
    assert out["donnees"]["OBJET"]["CPV"]["PRINCIPAL"]["CODE"] == "77310000"
    assert out["gestion"] == "pas du json" and rec["donnees"].startswith("{")


def test_scan_cpv_codes_finds_codes_under_cpv_keys_only():
    obj = {"OBJET": {"CPV": {"PRINCIPAL": {"CODE": "77310000-6"}, "SUPPLEMENTAIRE": [{"CODE": "77340000"}]},
                     "REFERENCE": {"CODE": "12345678"}}, "CodesCPV": "45112700-2 ; 45233140-2"}
    assert scan_cpv_codes(obj) == ["77310000", "77340000", "45112700", "45233140"]


def test_parse_amount_formats():
    assert parse_amount("1 200 000") == 1_200_000
    assert parse_amount("125 000,50 EUR") == 125000.5
    assert parse_amount("1.250.000,00") == 1_250_000
    assert parse_amount(950000) == 950000.0
    assert parse_amount({"ESTIMEE": "180000"}) == 180000.0
    assert parse_amount(["", "300000"]) == 300000.0
    assert parse_amount("non précisé") is None
    assert parse_amount(None) is None and parse_amount(True) is None


def test_pick_text_multilingual():
    langs = ["fra", "eng"]
    assert pick_text({"eng": "Green", "fra": "Vert"}, langs) == "Vert"
    assert pick_text({"eng": ["Green spaces"]}, langs) == "Green spaces"
    assert pick_text(["", "x"], langs) == "x"
    assert pick_text(None, langs) is None


def test_parse_dt_formats():
    assert parse_dt("2026-10-24+02:00").date().isoformat() == "2026-10-24"
    assert parse_dt("20261026").isoformat() == "2026-10-26T00:00:00+00:00"
    assert parse_dt("2026-11-28T12:00:00+01:00").astimezone(UTC).hour == 11
    assert parse_dt("2026-11-20T17:00:00").tzinfo is not None
    assert parse_dt("") is None and parse_dt("n/a") is None


def test_normalizers():
    assert normalize_cpv("77310000-6") == "77310000" and normalize_cpv("30") is None and normalize_cpv(None) is None
    assert normalize_department("1") == "01" and normalize_department("2a") == "2A"
    assert normalize_department("971") == "971" and normalize_department("69M") == "69"
    assert normalize_department("69259") == "69" and normalize_department("20167") == "2A"
    assert normalize_department("20200") == "2B" and normalize_department("97400") == "974"
    assert normalize_department("FRK26") is None and normalize_department("") is None
    assert dept_from_nuts("FRK26") == "69" and dept_from_nuts("frm01") == "2A" and dept_from_nuts("FRK2") is None


def test_notice_model_cleans_cpv_and_departments():
    n = Notice(source="boamp", source_id="x", title="t", cpv_codes=["77310000-6", "30", "77310000"],
               departments=["69", "1", "69", "bad"])
    assert n.cpv_codes == ["77310000"] and n.departments == ["69", "01"]
    s = Subscriber(email="a@b.fr", cpv_prefixes=["773", "77310000-6", "x", "773"], departments=["69", "1"])
    assert s.cpv_prefixes == ["773", "77310000"] and s.departments == ["69", "01"]


# ---------------------------------------------------------------- BOAMP
def test_boamp_record_with_json_string_donnees():
    rec = load_fixture("boamp_records.json")["results"][0]
    n = map_boamp_record(rec)
    assert n.source == "boamp" and n.source_id == "26-145201"
    assert n.buyer_name == "Commune de Villeurbanne" and n.buyer_dept == "69" and n.departments == ["69"]
    assert n.cpv_codes == ["77310000", "77340000", "77312000"]
    assert n.estimated_amount == 180000.0
    assert n.published_at.date().isoformat() == "2026-10-26"
    assert n.deadline_at.isoformat() == "2026-11-28T11:00:00+00:00"
    assert n.procedure_type == "Procédure adaptée"
    assert "Accord-cadre" in n.description
    assert n.url == "https://www.boamp.fr/pages/avis/?q=idweb:%2226-145201%22"
    assert n.raw["idweb"] == "26-145201"


def test_boamp_record_with_lots_and_no_amount():
    rec = load_fixture("boamp_records.json")["results"][1]
    n = map_boamp_record(rec)
    assert n.cpv_codes == ["77311000", "77312000"] and n.departments == ["01"]
    assert n.estimated_amount is None and n.procedure_type == "Appel d'offres ouvert"


def test_boamp_award_notice_excluded():
    rec = load_fixture("boamp_records.json")["results"][2]
    assert is_excluded_nature(rec) and map_boamp_record(rec) is None


def test_boamp_direct_cpv_field_and_department_from_donnees():
    rec = load_fixture("boamp_records.json")["results"][4]
    n = map_boamp_record(rec)
    assert n.cpv_codes == ["77341000", "77211400"]          # descripteur_code "30" n'est pas un CPV
    assert n.departments == ["69"] and n.buyer_dept == "69"  # 69M → 69 via donnees.OBJET.LIEU_EXEC_LIVR.CODE
    assert n.estimated_amount == 1_200_000


def test_boamp_record_without_id_is_dropped():
    assert map_boamp_record({"objet": "x"}) is None


# ---------------------------------------------------------------- TED
def test_ted_contract_notice_mapping():
    raw = load_fixture("ted_search.json")["notices"][0]
    n = map_ted_notice(raw)
    assert n.source == "ted" and n.source_id == "650123-2026"
    assert n.title.startswith("Entretien des espaces verts") and n.buyer_name == "Métropole de Lyon"
    assert n.departments == ["69"] and n.buyer_dept == "69"
    assert n.cpv_codes == ["77310000", "77311000"]
    assert n.estimated_amount == 1_250_000
    assert n.deadline_at.date().isoformat() == "2026-11-30"   # la plus proche des dates de lots
    assert n.published_at.date().isoformat() == "2026-10-24"
    assert n.procedure_type == "Procédure ouverte"
    assert n.url == "https://ted.europa.eu/fr/notice/-/detail/650123-2026"


def test_ted_award_notice_excluded_and_region_only_notice_kept():
    notices = load_fixture("ted_search.json")["notices"]
    assert not is_opportunity(notices[1]) and map_ted_notice(notices[1]) is None
    n = map_ted_notice(notices[2])
    assert n is not None and n.departments == [] and n.buyer_dept is None
    assert n.title == "Landscaping maintenance for a university campus"
    assert n.estimated_amount == 300000 and n.deadline_at is None
    assert n.url.endswith("651402-2026/pdf")
    assert is_opportunity({"notice-type": "cn-standard"}) and not is_opportunity({"notice-type": "pin-only"})


def test_ted_query_and_non_euro_amount():
    from datetime import date
    q = build_query(["773", "452"], "FRA", date(2026, 10, 25))
    assert q == ("(classification-cpv=773* OR classification-cpv=452*) AND place-of-performance=FRA"
                 " AND publication-date>=20261025")
    n = map_ted_notice({"publication-number": "1-2026", "notice-title": {"fra": "t"}, "estimated-value-proc": "100",
                        "estimated-value-cur-proc": "CHF", "form-type": "competition"})
    assert n.estimated_amount is None and n.url == "https://ted.europa.eu/fr/notice/-/detail/1-2026"


# ---------------------------------------------------------------- DECP
def test_decp_flat_and_nested_records():
    rows = load_fixture("decp_records.json")["results"]
    a = map_decp_record(rows[0])
    assert a.buyer_name == "Commune de Vénissieux" and a.holder_name == "Parcs et Jardins du Rhône SARL"
    assert a.amount == 92000 and a.cpv_code == "77310000" and a.dept == "69" and a.duration_months == 36
    assert a.notified_at.date().isoformat() == "2026-10-22"
    b = map_decp_record(rows[2])   # style v3 : acheteur / titulaires / lieuExecution en JSON
    assert b.buyer_name == "Métropole de Lyon" and b.buyer_id == "20004697700019"
    assert b.holder_name == "Parcs et Jardins du Rhône SARL" and b.holder_id == "41234567800021"
    assert b.dept == "69" and b.cpv_code == "77313000" and b.notified_at.date().isoformat() == "2026-10-23"
    c = map_decp_record(rows[5])
    assert c.dept is None and c.amount is None and c.holder_label == "SIRET 41234567800021"


def test_department_from_place():
    assert department_from_place("69259", "Code commune") == "69"
    assert department_from_place("13008", "Code postal") == "13"
    assert department_from_place("01", "Code département") == "01"
    assert department_from_place("2A004", "Code commune") == "2A"
    assert department_from_place("84", "Code région") is None
    assert department_from_place("FR", "Code pays") is None
    assert department_from_place("97411", None) == "974"
    assert department_from_place(None, "Code commune") is None
