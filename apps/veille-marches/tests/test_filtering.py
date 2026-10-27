"""Filtrage par abonné : CPV (exact / préfixe), départements, montant (inconnu = gardé et marqué)."""
from veille_marches.filtering import cpv_match_level, match_notice, matching_subscribers
from veille_marches.models import Notice, Subscriber


def notice(**kw) -> Notice:
    base = dict(source="boamp", source_id="x", title="Entretien", cpv_codes=["77310000"], departments=["69"],
                estimated_amount=180000.0)
    base.update(kw)
    return Notice(**base)


def test_cpv_levels():
    assert cpv_match_level(["77310000"], ["77310000"]) == "exact"
    assert cpv_match_level(["77311000"], ["773"]) == "prefix"
    assert cpv_match_level(["45233140"], ["773"]) == "none"
    assert cpv_match_level([], ["773"]) == "none"
    assert cpv_match_level(["45233140"], []) == "unfiltered"
    assert cpv_match_level(["77311000", "77310000"], ["773", "77310000"]) == "exact"


def test_match_cpv_department_amount():
    sub = Subscriber(email="a@b.fr", cpv_prefixes=["773"], departments=["69", "01"], amount_min=50000,
                     amount_max=500000)
    m = match_notice(notice(), sub)
    assert m.matched and m.cpv_match == "prefix" and m.dept_match is True and m.amount_status == "in_range"
    assert not match_notice(notice(cpv_codes=["45233140"]), sub).matched
    assert not match_notice(notice(departments=["13"]), sub).matched
    assert not match_notice(notice(estimated_amount=20000), sub).matched
    assert match_notice(notice(estimated_amount=20000), sub).amount_status == "out_of_range"
    assert not match_notice(notice(estimated_amount=900000), sub).matched


def test_unknown_amount_is_kept_and_flagged():
    sub = Subscriber(email="a@b.fr", cpv_prefixes=["773"], departments=["69"], amount_min=50000)
    m = match_notice(notice(estimated_amount=None), sub)
    assert m.matched and m.amount_status == "unknown" and "montant non précisé" in m.flags
    sub2 = Subscriber(email="a@b.fr", cpv_prefixes=["773"], departments=["69"])
    m2 = match_notice(notice(estimated_amount=None), sub2)
    assert m2.matched and m2.amount_status == "unfiltered" and "montant non précisé" in m2.flags


def test_unknown_department_policy(settings):
    sub = Subscriber(email="a@b.fr", cpv_prefixes=["773"], departments=["69"])
    n = notice(departments=[], buyer_dept=None)
    assert not match_notice(n, sub, settings).matched
    permissive = settings.model_copy(update={"match_unknown_department": True})
    m = match_notice(n, sub, permissive)
    assert m.matched and m.dept_match is None and "zone non précisée" in m.flags
    # abonné « toute la France » : un avis sans département passe, avec la mention
    national = Subscriber(email="n@b.fr", cpv_prefixes=["773"])
    m = match_notice(n, national, settings)
    assert m.matched and m.dept_match is True and "zone non précisée" in m.flags


def test_buyer_dept_fallback_when_departments_empty():
    sub = Subscriber(email="a@b.fr", cpv_prefixes=["773"], departments=["01"])
    assert match_notice(notice(departments=[], buyer_dept="01"), sub).matched


def test_matching_subscribers():
    subs = [Subscriber(id=1, email="lyon@b.fr", cpv_prefixes=["773"], departments=["69"]),
            Subscriber(id=2, email="psl@b.fr", cpv_prefixes=["773"], departments=["13"]),
            Subscriber(id=3, email="fr@b.fr", cpv_prefixes=["77310000"])]
    matched = matching_subscribers(notice(), subs)
    assert [s.email for s, _ in matched] == ["lyon@b.fr", "fr@b.fr"]
    assert matched[1][1].cpv_match == "exact"
