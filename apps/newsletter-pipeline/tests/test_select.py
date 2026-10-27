from datetime import date

from newsletter_pipeline.selection import min_published_iso, select_diverse


def _rows(spec):
    return [{"id": i + 1, "score": 10 - i * 0.5, "theme": theme, "source_id": src} for i, (theme, src) in enumerate(spec)]


def test_select_max_two_per_theme_and_eight_items():
    rows = _rows([("fiscal", 1), ("fiscal", 1), ("fiscal", 2), ("social", 2), ("social", 3), ("social", 3),
                  ("outils", 4), ("tenue", 4), ("revision", 5), ("recrutement", 5), ("ia_generale", 6), ("fiscal", 6)])
    chosen = select_diverse(rows, limit=8, max_per_theme=2, max_per_source=3)
    ids = [r["id"] for r in chosen]
    assert len(ids) == 8
    assert 3 not in ids and 6 not in ids  # 3e fiscal et 3e social écartés
    assert ids == [1, 2, 4, 5, 7, 8, 9, 10]
    assert [r["score"] for r in chosen] == sorted((r["score"] for r in chosen), reverse=True)


def test_select_respects_source_cap_and_fills_when_short():
    rows = _rows([("fiscal", 1)] * 6)
    chosen = select_diverse(rows, limit=8, max_per_theme=2, max_per_source=3)
    assert [r["id"] for r in chosen] == [1, 2, 3]  # 2 par thème puis complément, jamais plus de 3 par source
    rows = _rows([("fiscal", 1), ("fiscal", 2), ("fiscal", 3), ("fiscal", 4)])
    assert [r["id"] for r in select_diverse(rows, limit=3, max_per_theme=2)] == [1, 2, 3]


def test_min_published_iso():
    assert min_published_iso(0) is None
    assert min_published_iso(14, date(2026, 11, 3)) == "2026-10-20"
