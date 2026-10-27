# Journal du chantier de nuit

## Résumé du matin
_(rempli lors du dernier passage, vers 06:45 Paris)_

## Journal (heure de Paris)

### 27/10 23:50 — ouverture du chantier
- Décision : ordre de construction = plan 2 (veille marchés publics, construisible de bout en bout sans autorisation externe) → plan 4 (moteur de contenu) → plan 1 (SaaS avis, l'accès API Google dépend d'Hugo) → plan 3 (newsletter) → déploiement.
- Contrainte sandbox : les API publiques (BOAMP, TED, data.economie) sont injoignables depuis cet environnement ; les clients sont écrits d'après la documentation et testés sur des fixtures. Premier appel réel à faire depuis le Mac mini (voir `ACTIONS-HUGO.md`).
- Socle créé : arborescence, README, Makefile, backlog, journal, `packages/core` en cours.

### 28/10 00:10 — lot 1 lancé
- `packages/core` terminé : 15 tests verts (LLM mock/Ollama/Anthropic, mail console/SMTP/Resend, settings, SQLite, extraction JSON). Poussé.
- Tâche planifiée créée : réveil toutes les heures à :45 de 21:45 à 06:45 (Paris), chaque nuit, dans cette session.
- 4 agents lancés en parallèle : `apps/veille-marches` (P2-1, P2-2, collecteur DECP en bonus), `apps/content-engine` (P4-1 à P4-3), `apps/avis-clients` (P1-1 à P1-3), `apps/newsletter-pipeline` (P3-1, P3-2).
- DEP-1 fait par la session principale : `deploy/macmini` (install.sh, run.sh, 10 services launchd dont caffeinate, install-launchd.sh), `deploy/vps` (Dockerfile, docker-compose, Caddy, boucle de jobs, README).
- Décision : `avis-clients` tourne entièrement sur le VPS (web + jobs), le Mac mini sert le LLM via Tailscale ; les trois autres apps tournent sur le Mac mini.
- Reste de la nuit : intégration des 4 apps (tests, corrections), puis P2-3 (brief DECP + page d'inscription Stripe), QA-1, DOC-1, P4-4, P1-4 selon le temps.

### 28/10 00:50 — veille-marches livrée (P2-1, P2-2, P2-3a)
- `apps/veille-marches` : 59 tests verts, ruff propre, CLI `vm` complète (collect BOAMP/TED/DECP, score règles + LLM, digest HTML/texte par abonné sans doublon, brief hebdo DECP, abonnés, stats). Vérifié par la session principale.
- Points à vérifier au premier appel réel listés dans le README de l'app (emplacement du CPV BOAMP, champs TED, identifiant du jeu DECP).
- Lancé : P2-3b (page d'inscription + Stripe) sur ce dossier.

### 28/10 01:10 — newsletter-pipeline livrée (P3-1, P3-2)
- `apps/newsletter-pipeline` : 60 tests verts, ruff propre, CLI `np` (collect RSS/pages avec trafilatura, dédoublonnage, rank LLM par lots, draft du numéro en markdown + HTML + texte, push beehiiv en dry-run, posts LinkedIn, stats, `run-monday` aligné sur le service launchd). 39 sources d'amorçage dont 36 à vérifier au premier passage réel. Vérifié par la session principale.
- Décisions de l'agent : markdown = source de vérité, 3 appels LLM courts par numéro avec replis `[À RELIRE]`, trafilatura pour l'extraction.

### 28/10 01:25 — avis-clients livrée (P1-1, P1-2, P1-3)
- `apps/avis-clients` : 57 tests verts, ruff propre, app FastAPI importable. Lien magique, onboarding avec QR et affiche A6, page publique sans filtrage d'avis, demandes SMS/WhatsApp/email avec quotas et liste STOP, client Google Business Profile (mock + réel), brouillons LLM avec garde-fous, boîte de réception HTMX, Stripe (Checkout, portail, webhook signé, garde d'accès), rapport mensuel, CLI `avis`. Vérifié par la session principale.
- Décision confirmée : web + jobs de cette app sur la même machine (SQLite) ; le `deploy/vps` racine fait tout tourner sur le VPS, l'app documente aussi l'option « tout sur le Mac mini derrière Cloudflare Tunnel ».
- Lancé : QA-1 (revue croisée) sur `avis-clients` et `newsletter-pipeline`.

### 28/10 01:45 — content-engine livré (P4-1, P4-2, P4-3)
- `apps/content-engine` : 41 tests verts (dont rendu d'un short 1080×1920 vérifié par ffprobe), ruff propre, CLI `ce` complète : sujets, idées, scripts en 3 variantes avec contrôles, file de validation, rendu vidéo (TTS `say`/Kokoro/ElevenLabs/silent, sous-titres ASS, barre de progression, miniatures), publication en dry-run (YouTube avec `containsSyntheticMedia`, Pinterest, LinkedIn, TikTok en stub), calendrier hebdo, `run-daily`, `run-publish`, import de métriques CSV, `angles`, `doctor`. Vérifié par la session principale.
- Les quatre apps sont livrées. Reste : P2-3b (en cours), QA-1 (2 revues en cours, 2 à lancer), DOC-1, P4-4, P1-4.
