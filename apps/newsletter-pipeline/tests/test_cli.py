import json
import re
from datetime import date

import pytest
from conftest import write_sources_yaml
from typer.testing import CliRunner

from newsletter_pipeline import cli
from newsletter_pipeline.draft import next_tuesday

runner = CliRunner()


@pytest.fixture
def mock_llm(monkeypatch, llm):
    monkeypatch.setattr(cli, "get_llm", lambda settings: llm)
    return llm


def test_help_lists_commands():
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("collect", "rank", "draft", "push", "linkedin", "stats", "run-monday", "sources", "render"):
        assert cmd in result.output


def test_full_flow_through_cli(env, settings, mock_llm):
    r = runner.invoke(cli.app, ["sources"], env=env)
    assert r.exit_code == 0 and "3 sources" in r.output and "Éditeur test" in r.output

    r = runner.invoke(cli.app, ["collect", "--source", "Éditeur test", "--dry-run"], env=env)
    assert r.exit_code == 0 and "[dry-run]" in r.output and "7 nouveaux" in r.output

    r = runner.invoke(cli.app, ["collect"], env=env)
    assert r.exit_code == 0, r.output
    assert "Total : 12 nouveaux items, 1 source(s) en erreur." in r.output and "Source cassée" in r.output

    r = runner.invoke(cli.app, ["rank", "--limit", "20"], env=env)
    assert r.exit_code == 0 and "12 items notés en 3 lot(s)" in r.output

    r = runner.invoke(cli.app, ["draft", "--issue", "1", "--date", "2026-11-03"], env=env)
    assert r.exit_code == 0, r.output
    assert "Numéro 001 du 2026-11-03" in r.output and "001-2026-11-03.md" in r.output
    md_path = settings.issues_dir / "001-2026-11-03.md"
    assert md_path.exists() and (settings.issues_dir / "001-2026-11-03.html").exists()

    r = runner.invoke(cli.app, ["draft", "--issue", "1"], env=env)
    assert r.exit_code == 1 and "existe déjà" in r.output

    r = runner.invoke(cli.app, ["render", "--issue", "1"], env=env)
    assert r.exit_code == 0 and "html" in r.output

    r = runner.invoke(cli.app, ["push", "--issue", "1", "--target", "file"], env=env)
    assert r.exit_code == 0 and (settings.out_dir / "push-file-001.html").exists()

    r = runner.invoke(cli.app, ["push", "--issue", "1"], env=env)
    assert r.exit_code == 0 and "Dry-run" in r.output
    data = json.loads((settings.out_dir / "push-beehiiv-001.json").read_text(encoding="utf-8"))
    assert data["json"]["status"] == "draft"

    r = runner.invoke(cli.app, ["push", "--issue", "1", "--target", "beehiiv", "--live"], env=env)
    assert r.exit_code == 1 and "BEEHIIV_API_KEY" in r.output

    r = runner.invoke(cli.app, ["push", "--issue", "1", "--target", "substack"], env=env)
    assert r.exit_code == 1 and "cible inconnue" in r.output

    r = runner.invoke(cli.app, ["linkedin", "--issue", "1"], env=env)
    assert r.exit_code == 0 and "3 posts écrits" in r.output
    assert (settings.out_dir / "linkedin-001.md").exists()

    r = runner.invoke(cli.app, ["stats"], env=env)
    assert r.exit_code == 0, r.output
    assert "12 collectés, 12 classés, 5 utilisés" in r.output and "Numéros produits : 1" in r.output
    assert "Éditeur test" in r.output and "ERREUR" in r.output


def test_run_monday_end_to_end(env, settings, mock_llm):
    r = runner.invoke(cli.app, ["run-monday"], env=env)
    assert r.exit_code == 0, r.output
    m = re.search(r"Compte rendu : (\d+) items collectés \((\d+) source\(s\) en erreur\), (\d+) items classés, brouillon : (\S+)", r.output)
    assert m, r.output
    assert m.group(1) == "12" and m.group(2) == "1" and m.group(3) == "12"
    expected = next_tuesday(date.today())
    assert m.group(4).endswith(f"001-{expected.isoformat()}.md")
    assert (settings.issues_dir / f"001-{expected.isoformat()}.md").exists()

    # deuxième lundi : numéro suivant, rien de neuf à collecter, items restants réutilisés
    r = runner.invoke(cli.app, ["run-monday", "--date", "2026-11-10"], env=env)
    assert r.exit_code == 0, r.output
    assert "0 items collectés" in r.output and "n° 002 du 2026-11-10" in r.output
    assert (settings.issues_dir / "002-2026-11-10.md").exists()


def test_run_monday_fails_only_when_no_draft(env, settings, mock_llm, workdir):
    env = {**env, "SOURCES_FILE": str(write_sources_yaml(workdir / "empty.yaml", with_broken=False).write_text(
        "sources: []\n", encoding="utf-8") or workdir / "empty.yaml")}
    r = runner.invoke(cli.app, ["run-monday"], env=env)
    assert r.exit_code == 1
    assert "brouillon : ÉCHEC" in r.output and "aucun item classé" in r.output


def test_collect_fails_cleanly_without_sources_file(env, workdir):
    r = runner.invoke(cli.app, ["collect"], env={**env, "SOURCES_FILE": str(workdir / "absent.yaml")})
    assert r.exit_code == 1 and "introuvable" in r.output


def test_draft_rejects_bad_date(env, mock_llm):
    r = runner.invoke(cli.app, ["draft", "--issue", "1", "--date", "03/11/2026"], env=env)
    assert r.exit_code == 1 and "date invalide" in r.output


def test_render_missing_markdown_fails_cleanly(env, settings, mock_llm):
    runner.invoke(cli.app, ["collect"], env=env)
    runner.invoke(cli.app, ["rank"], env=env)
    r = runner.invoke(cli.app, ["draft", "--issue", "1", "--date", "2026-11-03"], env=env)
    assert r.exit_code == 0, r.output
    (settings.issues_dir / "001-2026-11-03.md").unlink()
    r = runner.invoke(cli.app, ["render", "--issue", "1"], env=env)
    assert r.exit_code == 1 and "markdown absent" in r.output
    r = runner.invoke(cli.app, ["linkedin", "--issue", "1"], env=env)
    assert r.exit_code == 1 and "absent" in r.output


def test_invalid_sources_yaml_fails_cleanly(env, workdir):
    bad = workdir / "bad.yaml"
    bad.write_text("sources:\n  - name: [oops\n", encoding="utf-8")
    r = runner.invoke(cli.app, ["collect"], env={**env, "SOURCES_FILE": str(bad)})
    assert r.exit_code == 1 and "YAML" in r.output and "Traceback" not in r.output
    r = runner.invoke(cli.app, ["sources"], env={**env, "SOURCES_FILE": str(bad)})
    assert r.exit_code == 1 and "YAML" in r.output


def test_rank_default_limit_comes_from_settings(env, mock_llm):
    runner.invoke(cli.app, ["collect"], env=env)
    r = runner.invoke(cli.app, ["rank"], env={**env, "RANK_DEFAULT_LIMIT": "4"})
    assert r.exit_code == 0 and "4 items notés en 1 lot(s)" in r.output
