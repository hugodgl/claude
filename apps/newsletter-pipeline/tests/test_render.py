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


def test_markdown_to_html_neutralizes_raw_html_and_unsafe_links():
    from newsletter_pipeline.render import markdown_to_html
    md = ('Texte <script>alert(1)</script> et <iframe src="x"></iframe>\n\n<div onclick="x">bloc</div>\n\n'
          '[js](javascript:alert(1)) [ok](https://ok.fr/a) ![pix](http://tracker.test/p.gif) [data](data:text/html,x)\n\n'
          '```text\nprompt <b>brut</b>\n```\n')
    html = markdown_to_html(md)
    assert "<script" not in html and "<iframe" not in html and "<div" not in html and "onclick" not in html
    assert "&lt;script&gt;" in html and "&lt;div onclick=" in html
    assert 'href="https://ok.fr/a"' in html and "javascript:" not in html and "data:" not in html
    assert "<pre><code" in html and "prompt &lt;b&gt;brut&lt;/b&gt;" in html
    assert 'src="http://tracker.test/p.gif"' in html  # les images http restent (choix de l'auteur du markdown)


def test_render_email_html_title_and_preheader_follow_markdown():
    from newsletter_pipeline.render import preheader_from_markdown
    md = "# Titre relu\n\n*Test · n° 1 · mardi 3 novembre 2026*\n\n> Aperçu relu\n\n## Édito\n\nBonjour."
    html = render_email_html(md, {"number": 1, "date_fr": "mardi 3 novembre 2026", "newsletter_name": "Test",
                                  "newsletter_tagline": "t", "preheader": "ancien", "title": "Ancien titre"})
    assert "<title>Titre relu</title>" in html and "Ancien titre" not in html
    assert preheader_from_markdown(md) == "Aperçu relu"
    assert preheader_from_markdown("# T\n\n> **Partenaire de ce numéro :** [S](https://s.fr)\n\n## Édito") == ""
    assert preheader_from_markdown("# T\n\n## Édito\n\n> citation") == ""
    assert preheader_from_markdown("pas de titre") is None
