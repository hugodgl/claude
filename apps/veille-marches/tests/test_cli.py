"""CLI `vm` de bout en bout avec Typer CliRunner : abonnés, collecte (API simulées), score, digest, brief, stats."""
import json

import pytest
from typer.testing import CliRunner

from veille_marches import cli

runner = CliRunner()


@pytest.fixture
def env(tmp_path, monkeypatch, apis):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("veille_marches.collectors.build_client", lambda settings, transport=None: apis.client())
    for key in ("LLM_PROVIDER", "MAIL_PROVIDER", "DB_PATH", "OUT_DIR", "DATA_DIR", "LLM_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    return {"DB_PATH": str(tmp_path / "vm.db"), "OUT_DIR": str(tmp_path / "out"), "DATA_DIR": str(tmp_path),
            "LLM_PROVIDER": "mock", "MAIL_PROVIDER": "console", "REPLY_TO": "hugo@example.com"}


def run(args, env, code=0):
    result = runner.invoke(cli.app, args, env=env)
    assert result.exit_code == code, result.output
    return result.output


def test_subscribers_lifecycle(env):
    out = run(["subscribers", "add", "contact@paysages69.fr", "--label", "Paysages 69", "--cpv", "773",
               "--dept", "69", "--dept", "01", "--amount-max", "500000"], env)
    assert "abonné #1 ajouté" in out and "CPV 773" in out and "dép. 69,01" in out
    assert "déjà présent" in run(["subscribers", "add", "contact@paysages69.fr"], env, code=1)
    out = run(["subscribers", "add", "pro@ev.fr", "--plan", "pro", "--dept", "69,38,01,26,07,42,74"], env)
    assert "6 départements maximum" in out
    run(["subscribers", "add", "x@y.fr", "--plan", "gold"], env, code=2)
    out = run(["subscribers", "list"], env)
    assert "#1 contact@paysages69.fr [essentiel, actif] Paysages 69" in out and "montant 0-500000" in out
    assert "#2 pro@ev.fr [pro, actif]" in out
    assert "désactivé" in run(["subscribers", "disable", "pro@ev.fr"], env)
    assert "[pro, inactif]" in run(["subscribers", "list"], env)
    assert "réactivé" in run(["subscribers", "enable", "pro@ev.fr"], env)
    run(["subscribers", "disable", "nobody@nowhere.fr"], env, code=1)


def test_end_to_end_collect_score_digest_brief_stats(env, apis):
    run(["subscribers", "add", "contact@paysages69.fr", "--label", "Paysages 69", "--cpv", "773",
         "--dept", "69", "--dept", "01", "--plan", "pro"], env)
    out = run(["collect", "--source", "all", "--since-days", "3", "--dry-run"], env)
    assert "boamp  5 reçus, 3 retenus, 3 à insérer (dry-run)" in out and "[26-145201]" in out
    assert "decp   6 reçus, 6 retenus" in out
    out = run(["collect", "--source", "all", "--since-days", "3"], env)
    assert "boamp  5 reçus, 3 retenus, 3 nouveaux, 2 exclus (1 requête(s))" in out
    assert "ted    4 reçus, 2 retenus, 2 nouveaux" in out
    bodies = apis.ted_bodies()
    assert "classification-cpv=773*" in bodies[-1]["query"]
    out = run(["collect", "--source", "boamp", "--since-days", "3"], env)
    assert "0 nouveaux" in out
    run(["collect", "--source", "nope"], env, code=2)

    out = run(["score"], env)
    assert "avis scorés" in out and "BOAMP 26-145201" in out
    # LLM mock répond "{}" → résumé validé avec valeurs par défaut, verdict peut-être
    assert "(LLM" in out
    assert run(["score"], env).startswith("0 avis scorés")

    out = run(["digest", "--dry-run"], env)
    assert "contact@paysages69.fr : " in out and "VOS MARCHÉS DU" in out
    assert "Entretien des espaces verts des bâtiments communaux" in out and "Avis original : https://" in out
    out = run(["digest"], env)
    assert "aperçu :" in out and ".html" in out
    out = run(["digest", "--send"], env)
    assert "envoyé (console-1)" in out
    assert run(["digest", "--send"], env).strip() == "rien de nouveau : aucun digest à envoyer"

    out = run(["brief-weekly", "--dry-run", "--since-days", "10"], env)
    assert "contact@paysages69.fr : 3 attribution(s)" in out and "Parcs et Jardins du Rhône SARL" in out
    out = run(["brief-weekly", "--send", "--since-days", "10"], env)
    assert "envoyé (console-1)" in out

    out = run(["stats"], env)
    assert "avis : 5 (boamp 3, ted 2)" in out and "abonnés : 1 actifs / 1" in out
    assert "attributions DECP : 6" in out and "dernières collectes :" in out
    assert "sans département : 1" in out


def test_collect_reports_failure(env, apis):
    apis.fail_hosts.update({"boamp-datadila.opendatasoft.com", "api.ted.europa.eu", "data.economie.gouv.fr"})
    out = run(["collect"], env, code=1)
    assert out.count("ERREUR") == 3
    apis.fail_hosts.discard("api.ted.europa.eu")
    out = run(["collect", "--source", "ted"], env)
    assert "ted    4 reçus" in out


def test_version_and_help(env):
    assert "veille-marches 0.1.0" in run(["version"], env)
    out = run(["--help"], env)
    for cmd in ("collect", "score", "digest", "subscribers", "brief-weekly", "stats"):
        assert cmd in out


def test_cli_without_subscribers_scores_default_profile(env):
    run(["collect", "--source", "boamp"], env)
    out = run(["score", "--dry-run"], env)
    assert "3 avis scorés, 3 avec LLM (dry-run, rien d'enregistré)" in out
    assert run(["digest", "--dry-run"], env).strip() == "rien de nouveau : aucun digest à envoyer"
    json.loads("{}")
