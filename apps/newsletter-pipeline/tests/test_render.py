from datetime import date

from newsletter_pipeline.render import date_fr, issue_basename, markdown_to_text, render_email_html


def test_date_fr_and_basename():
    assert date_fr(date(2026, 11, 3)) == "mardi 3 novembre 2026"
    assert date_fr(date(2026, 12, 1)) == "mardi 1er décembre 2026"
    assert issue_basename(7, date(2026, 11, 3)) == "007-2026-11-03"


def test_markdown_to_text():
    md = "# Titre\n\n## Section\n\nTexte **gras** et *italique* avec [un lien](https://ex.fr/a) et `code`.\n\n> citation\n\n---\n\n```text\nprompt ici\n```\n"
    txt = markdown_to_text(md)
    assert "TITRE\n=====" in txt and "SECTION\n-------" in txt
    assert "Texte gras et italique avec un lien (https://ex.fr/a) et code." in txt
    assert "citation" in txt and "```" not in txt and "prompt ici" in txt and "-" * 40 in txt


def test_render_email_html_is_mobile_friendly():
    html = render_email_html("# Mon numéro\n\n## Édito\n\nBonjour.", {"number": 1, "date_fr": "mardi 3 novembre 2026",
                                                                       "newsletter_name": "Test", "newsletter_tagline": "t",
                                                                       "preheader": "Aperçu"})
    assert '<meta name="viewport"' in html and "@media (max-width: 480px)" in html
    assert "<h1>Mon numéro</h1>" in html and "<h2>Édito</h2>" in html and "<title>Mon numéro</title>" in html
    assert 'class="preheader"' in html and "Aperçu" in html
