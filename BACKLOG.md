# Backlog du chantier de nuit

Ordre de priorité de haut en bas. Une tâche est « faite » quand : les tests passent (`make test-<app>`), le README de l'app explique comment la lancer, `.env.example` est complet, aucun secret n'est commité.
Légende : `[ ]` à faire, `[~]` en cours (agent lancé, ne pas relancer : vérifier d'abord si le dossier existe et si ses tests passent), `[x]` fait.
Règles : une app par agent à la fois, pas de modification des dossiers d'un autre agent en cours, pas de nouvelle branche, pas de modification des deux dossiers `business-*.md`.

## Phase 0 : socle (session principale, soir du 27/10)
- [x] Arborescence, README racine, Makefile, .gitignore
- [x] `packages/core` : LLM (mock, Ollama, Anthropic), mail (console, SMTP, Resend), settings, db SQLite, extraction JSON, tests
- [x] Tâche planifiée horaire 21:45 → 06:45 (Paris) qui relance le chantier

## Phase 1 : lot 1 (nuit, en parallèle)
- [x] **P2-1** `apps/veille-marches` : collecteurs BOAMP (Opendatasoft) et TED (API v3), modèle `Notice` normalisé, stockage SQLite, filtres CPV + départements + montant, fixtures et tests
- [x] **P2-2** `apps/veille-marches` : score d'opportunité (règles + LLM), résumé structuré, digest HTML + texte par abonné, CLI `vm` (collect, score, digest, subscribers), envoi console/SMTP/Resend, tests
- [x] **P4-1** `apps/content-engine` : banque de sujets par produit, génération de scripts (3 variantes, hook/corps/CTA), file de validation (approve/reject), tests
- [x] **P4-2** `apps/content-engine` : rendu vidéo vertical 1080×1920 (TTS via `say` macOS / Kokoro / ElevenLabs, sous-titres incrustés, fond, miniature) avec ffmpeg, test de rendu court sans TTS
- [x] **P4-3** `apps/content-engine` : publication en dry-run (YouTube Data API v3 avec drapeau contenu synthétique, Pinterest API v5, LinkedIn Posts API, TikTok Content Posting API en stub documenté), planification, README
- [x] **P1-1** `apps/avis-clients` : FastAPI + Jinja/HTMX, comptes (lien magique), établissements, page publique d'avis avec QR code, demandes d'avis SMS (adaptateurs smsmode/Twilio/dry-run), tests
- [x] **P1-2** `apps/avis-clients` : client Google Business Profile (OAuth + mode mock sur fixtures), boîte de réception des avis, brouillons de réponse LLM selon le ton, validation et publication, job de polling 15 min
- [x] **P1-3** `apps/avis-clients` : Stripe (Checkout, portail client, webhooks signés), formules Solo/Pro/Réseau, rapport mensuel HTML, README

## Phase 2 : lot 2
- [x] **P3-1** `apps/newsletter-pipeline` : sources (RSS/Atom, pages), collecte, dédoublonnage, classement LLM « pertinence cabinet », brouillon de numéro hebdo en markdown, tests
- [x] **P3-2** `apps/newsletter-pipeline` : push beehiiv (API) ou export HTML prêt à coller, extraction de 3 posts LinkedIn par numéro, README
- [x] **P2-3a** `apps/veille-marches` : brief hebdo DECP (collecteur data.economie.gouv.fr) — fait avec P2-2
- [x] **P2-3b** `apps/veille-marches` : page d'inscription publique + Stripe Checkout + webhook (FastAPI minimal), README complet
- [x] **DEP-1** `deploy/macmini` : `install.sh` (brew, uv, ffmpeg, ollama + modèle), plists launchd par job, `caffeinate`, rotation des logs ; `deploy/vps` : docker-compose + Caddy pour `avis-clients` et la page `veille-marches` ; Makefile racine à jour

## Phase 3 : lot 3 (si le temps le permet)
- [x] **QA-1** revue croisée de chaque app par un agent différent : bugs, secrets, validation des entrées, injection de prompt dans les textes externes (avis, annonces), corrections
- [x] **DOC-1** README racine : « démarrer en 15 minutes sur le Mac mini », schéma des flux, tableau des variables d'environnement
- [~] **P4-4** `apps/content-engine` : récupération des métriques (YouTube Analytics, TikTok), sélection automatique des angles qui marchent
- [~] **P1-4** `apps/avis-clients` : adaptateurs Facebook et Tripadvisor, mode auto-publication pour les avis ≥ 4 étoiles

## Matin (dernier passage à 06:45)
- [ ] Tout tester, tout pousser, résumé du matin en tête de `PROGRESS.md`, `ACTIONS-HUGO.md` à jour
