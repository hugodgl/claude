from newsletter_pipeline.dedup import canonical_url, content_hash, normalize_title, title_hash


def test_canonical_url_strips_tracking_and_fragment():
    url = "HTTPS://Blog.Exemple.fr/articles/ia/?utm_source=rss&utm_medium=feed&fbclid=xyz&b=2&a=1#section"
    assert canonical_url(url) == "https://blog.exemple.fr/articles/ia?a=1&b=2"


def test_canonical_url_same_article_two_tracking_variants():
    a = "https://ex.fr/a/b?utm_campaign=x"
    b = "https://ex.fr/a/b/?gclid=1&mc_cid=2"
    assert canonical_url(a) == canonical_url(b) == "https://ex.fr/a/b"


def test_canonical_url_keeps_root_and_default_ports():
    assert canonical_url("https://ex.fr:443/") == "https://ex.fr/"
    assert canonical_url("http://ex.fr:8080/x/") == "http://ex.fr:8080/x"
    assert canonical_url("") == ""


def test_title_hash_close_titles_match():
    a = "Facturation électronique : ce qui change au 1er septembre"
    b = "FACTURATION ELECTRONIQUE – ce qui change au 1er septembre !"
    assert title_hash(a) == title_hash(b)
    assert title_hash(a) != title_hash("Facturation électronique : ce qui change au 1er octobre")


def test_normalize_title_removes_source_suffix():
    assert normalize_title("Mon article - Compta Online", "Compta Online") == "mon article"
    assert normalize_title("Mon article | Compta Online", "Compta Online") == "mon article"
    assert normalize_title("Mon article - Autre", "Compta Online") == "mon article autre"


def test_content_hash():
    assert content_hash("  Bonjour   monde ") == content_hash("bonjour monde")
    assert content_hash("") is None
