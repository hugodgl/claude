#!/bin/bash
# Installation complète sur un Mac mini (à lancer depuis la racine du repo cloné).
# Idempotent : relançable sans risque.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
MODEL="${OLLAMA_MODEL:-qwen3:14b}"
cd "$REPO"
if [ "$(uname -s)" != "Darwin" ]; then echo "Ce script est prévu pour macOS."; exit 1; fi
if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew manquant. Installe-le d'abord : https://brew.sh (puis relance ce script)."; exit 1
fi
echo "== Outils (uv, ffmpeg, ollama) =="
brew list uv >/dev/null 2>&1 || brew install uv
brew list ffmpeg >/dev/null 2>&1 || brew install ffmpeg
brew list ollama >/dev/null 2>&1 || brew install ollama
brew services start ollama >/dev/null 2>&1 || true
echo "== Modèle local $MODEL (téléchargement long la première fois) =="
for i in 1 2 3 4 5 6; do
  if curl -fsS http://localhost:11434/api/tags >/dev/null 2>&1; then break; fi; sleep 5
done
ollama pull "$MODEL"
echo "== Environnements Python =="
make setup
echo "== Fichiers .env =="
for d in apps/*/; do
  if [ -f "$d/.env.example" ] && [ ! -f "$d/.env" ]; then cp "$d/.env.example" "$d/.env"; echo "créé $d.env (à compléter)"; fi
done
mkdir -p logs
echo "== Services launchd =="
"$REPO/deploy/macmini/install-launchd.sh"
echo
echo "Terminé. Prochaines étapes :"
echo " 1. Compléter les apps/*/.env (voir ACTIONS-HUGO.md)."
echo " 2. Réglages macOS > Économie d'énergie : désactiver la mise en veille ; caffeinate est aussi lancé par launchd."
echo " 3. Premier appel réel : cd apps/veille-marches && .venv/bin/vm collect --limit 20"
