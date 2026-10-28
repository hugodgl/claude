from pathlib import Path

from typer.testing import CliRunner

from content_engine.cli import app
from tests.conftest import HAVE_FFMPEG

runner = CliRunner()


def run(*args):
    result = runner.invoke(app, list(args))
    return result.exit_code, result.output


def test_full_pipeline_via_cli(env: Path):
    code, out = run("init")
    assert code == 0 and "sujets ajoutés : 43" in out
    code, out = run("ideas", "--product", "marches", "--count", "3")
    assert code == 0 and "3 nouveau(x) sujet(s)" in out
    code, out = run("script", "--topic-id", "1")
    assert code == 0 and "#1, #2, #3" in out
    code, out = run("script", "--topic-id", "30", "--format", "pin")
    assert code == 0
    code, out = run("review")
    assert code == 0 and "│  1 │" in out and "pin" in out
    code, out = run("approve", "1", "4")
    assert code == 0 and "#1 approuvé" in out and "#4 approuvé" in out
    code, out = run("reject", "2", "--reason", "trop générique")
    assert code == 0 and "rejeté" in out
    code, out = run("export-review", "--date", "2026-10-28")
    assert code == 0 and (env / "out" / "review-2026-10-28.md").exists()
    code, out = run("show", "1")
    assert code == 0 and "Statut : approved" in out
    code, out = run("publish", "--draft-id", "1", "--platform", "youtube")
    assert code == 1 and "Erreur" in out  # pas encore rendu
    if HAVE_FFMPEG:
        code, out = run("render", "--approved")
        assert code == 0 and "#1 rendu (short)" in out and "#4 rendu (pin)" in out
        assert (env / "out" / "1" / "video.mp4").exists()
        code, out = run("publish", "--draft-id", "1", "--platform", "youtube")
        assert (
            code == 0 and "Dry-run" in out and (env / "out" / "1" / "publish-youtube.json").exists()
        )
        code, out = run("publish", "--draft-id", "4", "--platform", "pinterest")
        assert code == 0 and (env / "out" / "4" / "publish-pinterest.json").exists()
    code, out = run("plan", "--days", "7", "--start", "2026-10-26")
    assert code == 0 and "53 créneau(x)" in out
    code, out = run("schedule", "--from", "2026-10-26", "--to", "2026-10-26")
    assert code == 0 and "Créneaux (8)" in out
    code, out = run("run-publish", "--no-render")
    assert code == 0
    code, out = run("run-daily", "--scripts", "2")
    assert code == 0 and "Relecture" in out and "Scripts : sujet" in out
    code, out = run("angles", "--list")
    assert code == 0 and "script-pret-a-dire" in out
    code, out = run("angles")
    assert code == 0 and "Pas encore de métriques" in out


def test_metrics_import_and_doctor(env: Path):
    run("init")
    csv_path = env / "yt.csv"
    csv_path.write_text(
        "Content,Video title,Views,Watch time (hours)\nTotal,,10,1\nid1,Titre,10,1\n",
        encoding="utf-8",
    )
    code, out = run("metrics", "--import", str(csv_path))
    assert code == 0 and "1 ligne(s) importée(s)" in out
    # un seul contenu mesuré par angle : pas de recommandation hâtive
    run("script", "--topic-id", "1")
    title = "Comment demander un avis Google à un client sans le gêner"  # variante 1 du simulateur
    csv_path.write_text(
        f'Content,Video title,Views,Watch time (hours)\nid2,"{title}",50,2\n', encoding="utf-8"
    )
    code, out = run("metrics", "--import", str(csv_path))
    assert code == 0 and "1 liée(s)" in out
    code, out = run("angles")
    assert code == 0 and "Trop peu de données" in out and "À décliner" not in out
    code, out = run("add-topic", "Question avec un angle inventé ?", "-p", "avis", "--angle", "x")
    assert code == 1 and "angle inconnu" in out
    code, out = run("doctor")
    assert code == 0 and "TTS : silent" in out and "LLM : mock" in out and "dry-run" in out
    assert "SELF_ONLY forcé" in out and "YouTube : visibilité private" in out
    code, out = run("--version")
    assert code == 0 and "content-engine" in out
    code, out = run("script", "--topic-id", "999")
    assert code == 1 and "introuvable" in out
    code, out = run(
        "add-topic", "Une question toute neuve ?", "--product", "avis", "--angle", "mythe"
    )
    assert code == 0 and "ajouté" in out
    code, out = run("add-topic", "Une question toute neuve ?", "--product", "avis")
    assert code == 0 and "déjà présent" in out


def test_metrics_pull_and_angle_status_via_cli(env: Path):
    run("init")
    code, out = run("metrics")
    assert code == 1 and "préciser --import" in out
    code, out = run("metrics", "--pull", "--dry-run")
    assert code == 0 and "Dry-run" in out and "aucune publication réelle" in out
    assert out.count("publication(s)") == 4
    code, out = run("metrics", "--pull", "--platform", "mastodon")
    assert code == 1 and "plateforme inconnue" in out
    code, out = run("metrics", "--pull", "--platform", "youtube", "--days", "7")
    assert code == 0 and "youtube : 0 publication(s)" in out and "pinterest" not in out
    code, out = run("angles", "--pause", "mythe", "-p", "avis")
    assert code == 0 and "avis/mythe : mis en pause" in out
    code, out = run("angles", "--explain")
    assert code == 0 and "en pause (manuel)" in out and "--reactivate mythe -p avis" in out
    code, out = run("angles", "--reactivate", "mythe", "-p", "avis")
    assert code == 0 and "réactivé" in out
    code, out = run("angles", "--pause", "inconnu")
    assert code == 1 and "angle inconnu" in out
    code, out = run("angles", "-p", "mastodon")
    assert code == 1 and "produit inconnu" in out
    code, out = run("run-daily", "--scripts", "1")
    assert code == 0 and "ancienneté" in out
    code, out = run("doctor")
    assert code == 0 and "dernier relevé API" in out and "exploration 30%" in out
