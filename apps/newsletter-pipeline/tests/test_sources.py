from pathlib import Path

import pytest

from newsletter_pipeline import db
from newsletter_pipeline.collect import Collector
from newsletter_pipeline.sources import load_sources

BASE = """
defaults:
  lang: fr
sources:
  - name: Flux
    url: https://ex.fr/feed
    kind: rss
    category: presse_pro
"""


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "sources.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_invalid_yaml_gives_clear_error(tmp_path):
    with pytest.raises(ValueError, match="sources.yaml.*YAML"):
        load_sources(_write(tmp_path, "sources:\n  - name: [oops\n"))


def test_sources_must_be_a_list_of_mappings(tmp_path):
    with pytest.raises(ValueError, match="liste"):
        load_sources(_write(tmp_path, "sources:\n  Flux:\n    url: https://ex.fr\n"))
    with pytest.raises(ValueError, match="mapping"):
        load_sources(_write(tmp_path, "sources:\n  - juste une chaîne\n"))


def test_unknown_key_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="'Flux'.*include_pattern\\b"):
        load_sources(_write(tmp_path, BASE + "    include_pattern: ['/x/']\n"))


def test_field_types_are_checked(tmp_path):
    with pytest.raises(ValueError, match="'Flux'.*weight"):
        load_sources(_write(tmp_path, BASE + "    weight: lourd\n"))
    with pytest.raises(ValueError, match="'Flux'.*active"):
        load_sources(_write(tmp_path, BASE + "    active: peut-être\n"))
    with pytest.raises(ValueError, match="'Flux'.*motif invalide"):
        load_sources(_write(tmp_path, BASE + "    include_patterns: ['[oops']\n"))
    # une chaîne seule est acceptée comme liste d'un motif
    specs = load_sources(_write(tmp_path, BASE + "    include_patterns: '/actualites/'\n"))
    assert specs[0].include_patterns == ["/actualites/"]


def test_inactive_source_is_skipped_unless_named(conn, settings, workdir):
    from conftest import write_sources_yaml
    settings.sources_file = write_sources_yaml(workdir / "s.yaml", with_broken=False, extra="""
  - name: En pause
    url: https://ex.fr/feed
    kind: rss
    category: presse_pro
    active: false
""")
    collector = Collector(conn, settings)
    collector.sync_from_yaml()
    assert db.get_source(conn, "En pause")["active"] == 0
    assert "En pause" not in {s.name for s in collector.run().sources}
    assert collector.run("En pause").sources[0].name == "En pause"  # explicite : on l'essaie quand même
