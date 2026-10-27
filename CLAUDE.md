# Repères pour Claude Code dans ce repo

Monorepo d'un projet side « Mac mini H24 » (voir `README.md`). Quatre apps Python indépendantes sous `apps/`, un socle commun `packages/core`, le déploiement sous `deploy/`.

## Règles
- Branche de travail : `claude/upbeat-davinci-lk5k7m`. Ne jamais créer d'autre branche, ne jamais réécrire l'historique, jamais de `git push --force`.
- Une app = un environnement virtuel (`uv venv .venv` dans `apps/<app>`), installation `uv pip install -e ../../packages/core -e ".[dev]"`, tests `.venv/bin/pytest -q`. `make setup` et `make test` à la racine font tout.
- LLM uniquement via `core.llm.get_llm()` ; `MockLLM` dans les tests ; aucun appel réseau dans les tests.
- Aucun secret dans le repo (`.env` ignoré, `.env.example` à jour). Aucune dépense, aucune création de compte, aucun envoi ni publication réels : les connecteurs restent en dry-run tant que les clés ne sont pas fournies par Hugo.
- Textes visibles, README et journaux en français ; identifiants de code en anglais.
- Ne pas modifier `business-passif-mac-mini-2026.md` ni `business-plans-4-pistes-2026.md`.
- Avancement : cocher `BACKLOG.md`, ajouter une entrée horodatée (heure de Paris) dans `PROGRESS.md`, commit clair, push.

## Chantier de nuit
- Procédure détaillée dans `deploy/macmini/NIGHT-SHIFT-PROMPT.md` et `NIGHT-RUN.md`.
- `NIGHT-SHIFT-OWNER` indique qui exécute le chantier : `cloud` (session Claude dans le cloud) ou `macmini` (Claude Code sur le Mac mini). Un seul exécutant à la fois.
- Sur le Mac mini, Claude Code tourne sans invite de confirmation mais avec une liste blanche d'outils (`.claude/settings.json`) : tout ce qui n'y est pas est refusé. Si une commande utile est refusée, note-le dans `PROGRESS.md` au lieu de contourner.
