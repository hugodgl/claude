# Side project « Mac mini H24 »

Monorepo du projet side décrit dans `business-passif-mac-mini-2026.md` (analyse du marché) et `business-plans-4-pistes-2026.md` (business plans).
Tout tourne sur un Mac mini allumé en permanence, avec des modèles de langage locaux (Ollama) par défaut, plus un petit VPS pour la partie exposée au public. Aucun connecteur n'envoie ni ne publie quoi que ce soit tant que les clés ne sont pas fournies : tout est en dry-run.

## Les quatre apps

| Dossier | Plan | Ce que ça fait | Commande | Tests |
|---|---|---|---|---|
| `apps/veille-marches` | 2 | collecte BOAMP, TED et DECP, filtre par métier (CPV) et zone, résume et note chaque avis, envoie un digest quotidien par abonné et un brief hebdo d'attribution ; site d'inscription + Stripe | `vm` | 59 |
| `apps/content-engine` | 4 | banque de sujets, scripts en 3 variantes, file de validation du matin, rendu vidéo vertical (TTS + ffmpeg + sous-titres), publication YouTube / Pinterest / LinkedIn / TikTok en dry-run, calendrier, métriques | `ce` | 39 |
| `apps/avis-clients` | 1 | SaaS pour commerces : QR code et demandes d'avis par SMS, boîte de réception des avis Google avec brouillons de réponse, Stripe, rapport mensuel | `avis` (+ web FastAPI) | 49 |
| `apps/newsletter-pipeline` | 3 | collecte de 39 sources, classement par pertinence pour les cabinets comptables, brouillon du numéro hebdo (markdown, HTML, texte), push beehiiv, posts LinkedIn | `np` | 60 |
| `packages/core` | commun | fournisseurs LLM (mock, Ollama, Anthropic), envoi d'emails (console, SMTP, Resend), réglages, SQLite, extraction JSON | | 15 |

Les chiffres de tests datent du 28/10 ; `make test` donne l'état courant.

## Comment ça s'enchaîne

```
                 ┌──────────────── Mac mini (launchd, H24) ────────────────┐
  BOAMP / TED ──►│ vm collect 06:00, 14:00 ─► vm score 06:30 ─► vm digest 07:00 │──► email aux abonnés
  DECP ─────────►│ vm brief-weekly dim. 18:00                               │
                 │ ce run-daily 05:30 ─► relecture 15 min ─► ce run-publish /30 min │──► YouTube, Pinterest, LinkedIn, TikTok
  39 sources ───►│ np run-monday lun. 05:00 ─► relecture 45 min ─► np push   │──► beehiiv (mardi 07:00)
                 │ Ollama (qwen3:14b) sert tous les prompts, gratuitement   │
                 └──────────────────────────────────────────────────────────┘
                 ┌──────────────── VPS (docker, Caddy) ─────────────────────┐
  commerçants ──►│ avis-clients web ◄─► avis poll-reviews /15 min, rapport mensuel │◄── Google, SMS, Stripe
                 └──────────────────────────────────────────────────────────┘
```

Le contenu (plan 4) amène l'audience, la newsletter (plan 3) la qualifie, les deux produits par abonnement (plans 1 et 2) la monétisent.

## Démarrer en 15 minutes sur le Mac mini

```bash
git clone https://github.com/hugodgl/claude ~/sideproject && cd ~/sideproject
git checkout claude/upbeat-davinci-lk5k7m
deploy/macmini/install.sh        # Homebrew requis ; installe uv, ffmpeg, Ollama + qwen3:14b, les venvs, les .env, les services launchd
make test                        # tout doit être vert
```
Puis, app par app, un premier essai à blanc :
```bash
cd apps/veille-marches  && .venv/bin/vm collect --limit 20 && .venv/bin/vm stats          # premier appel réel aux API publiques
cd apps/content-engine  && .venv/bin/ce doctor && .venv/bin/ce init && .venv/bin/ce script --topic-id 1
cd apps/newsletter-pipeline && .venv/bin/np collect --dry-run && .venv/bin/np stats       # corriger les sources en erreur
cd apps/avis-clients    && .venv/bin/avis demo && .venv/bin/avis serve                    # http://localhost:8000
```
Les `.env` sont créés à partir des `.env.example` ; sans clés, tout reste en mode console / dry-run / mock. La liste des comptes et clés à créer, et des décisions à prendre, est dans `ACTIONS-HUGO.md`.

## Variables de configuration à connaître

| Variable | Apps | Rôle |
|---|---|---|
| `LLM_PROVIDER` | toutes | `ollama` (défaut, gratuit), `anthropic` (qualité, coût), `mock` (tests) |
| `OLLAMA_MODEL` | toutes | `qwen3:14b` ; `qwen3:8b` sur un Mac mini 16 Go si trop lent |
| `MAIL_PROVIDER`, `MAIL_FROM` | veille, avis | `console` tant que Resend ou SMTP n'est pas configuré |
| `DEFAULT_CPV_PREFIXES`, `TRADE_LABEL` | veille | métier suivi (défaut : espaces verts, CPV `773`) |
| `TTS_PROVIDER`, `SAY_VOICE` | content | `say` + voix française macOS (`Thomas`, `Amélie`) |
| `YOUTUBE_PRIVACY_STATUS`, `TIKTOK_PRIVACY_LEVEL` | content | `private` / `SELF_ONLY` tant que la première publication n'est pas relue |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_*` | avis, veille | clés de test d'abord |
| `SMS_PROVIDER` | avis | `dry-run`, puis `smsmode` ou `twilio` |
| `GBP_MODE` | avis | `mock` jusqu'à l'approbation de l'API Google Business Profile |
| `SESSION_SECRET`, `APP_BASE_URL` | avis | obligatoires en production |
| `BEEHIIV_API_KEY`, `BEEHIIV_PUBLICATION_ID` | newsletter | sinon export HTML à coller |

Le détail complet est dans le `.env.example` de chaque app.

## Conventions

- Python 3.11+, un environnement virtuel par app (`uv venv`), dépendances dans `pyproject.toml`, tests `pytest`, lint `ruff`.
- Chaque app installe `packages/core` en mode éditable : `uv pip install -e ../../packages/core -e ".[dev]"`.
- Aucun secret dans le repo : `.env` ignoré, `.env.example` à jour.
- Les tests ne font aucun appel réseau : les API publiques sont simulées par des fixtures dans `tests/fixtures/`.
- Chaque app a un `README.md` détaillé et, après revue croisée, un `REVIEW.md` qui liste les défauts trouvés et corrigés.

## Fichiers de pilotage

| Fichier | Rôle |
|---|---|
| `ACTIONS-HUGO.md` | ce que seul Hugo peut faire : comptes, clés, choix de niche, Mac mini |
| `BACKLOG.md` | tâches ordonnées, cases cochées au fil du chantier |
| `PROGRESS.md` | journal horodaté du chantier de nuit, résumé du matin en tête |
| `NIGHT-RUN.md` | fonctionnement du chantier de nuit (cloud ou Mac mini), arrêt, réorientation |
| `CLAUDE.md` | règles pour Claude Code dans ce repo |
| `deploy/macmini/` | installation, services launchd, chantier de nuit local |
| `deploy/vps/` | Docker, Caddy, sauvegardes pour la partie publique |
