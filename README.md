# Side project « Mac mini H24 »

Monorepo du projet side décrit dans `business-passif-mac-mini-2026.md` (analyse) et `business-plans-4-pistes-2026.md` (business plans).
Tout est pensé pour tourner sur un Mac mini allumé en permanence, avec des modèles de langage locaux (Ollama) par défaut, et un petit VPS pour les parties exposées au public.

## Arborescence

| Dossier | Plan | Rôle |
|---|---|---|
| `packages/core` | commun | fournisseurs LLM (mock, Ollama, Anthropic), envoi d'emails, réglages, SQLite, utilitaires JSON |
| `apps/veille-marches` | plan 2 | collecte BOAMP et TED, filtrage CPV et zone, résumé et score, digest quotidien, brief hebdo DECP, abonnés |
| `apps/content-engine` | plan 4 | banque de sujets, scripts, rendu vidéo vertical (TTS + ffmpeg), file de validation, publication YouTube / Pinterest / LinkedIn / TikTok |
| `apps/avis-clients` | plan 1 | SaaS : QR code et demandes d'avis, boîte de réception des avis, brouillons de réponse, Stripe, rapport mensuel |
| `apps/newsletter-pipeline` | plan 3 | collecte de sources, classement, brouillon de numéro hebdo, push beehiiv, extraction LinkedIn |
| `deploy/macmini` | | script d'installation, services launchd (jobs planifiés), logs |
| `deploy/vps` | | docker-compose + Caddy pour les parties publiques |

## Conventions

- Python 3.11+, un environnement virtuel par app (`uv venv`), dépendances dans `pyproject.toml`, tests `pytest`, lint `ruff`.
- Chaque app installe `packages/core` en mode éditable : `uv pip install -e ../../packages/core -e ".[dev]"`.
- Aucun secret dans le repo : chaque app a un `.env.example`, le vrai `.env` reste local.
- LLM par défaut : `LLM_PROVIDER=ollama` (modèle `qwen3:14b`), `mock` dans les tests, `anthropic` en option pour les cas qui exigent plus de qualité.
- Les tests ne font aucun appel réseau : les API publiques sont simulées par des fixtures dans `tests/fixtures/`.

## Démarrage rapide

```bash
make setup        # crée les venvs et installe toutes les apps
make test         # lance les tests de toutes les apps
make run-veille   # exemple : collecte + digest en mode dry-run
```

Le détail par app est dans le README de chaque dossier. La liste des actions qui ne peuvent être faites que par Hugo (comptes, clés, choix de niche) est dans `ACTIONS-HUGO.md`. L'avancement du chantier de nuit est dans `PROGRESS.md`, le fonctionnement du chantier dans `NIGHT-RUN.md`.
