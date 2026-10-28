# Journal du chantier de nuit

## Résumé du matin
_(rempli lors du dernier passage, vers 06:45 Paris)_

## Journal (heure de Paris)

### 27/10 23:50 — ouverture du chantier
- Décision : ordre de construction = plan 2 (veille marchés publics, construisible de bout en bout sans autorisation externe) → plan 4 (moteur de contenu) → plan 1 (SaaS avis, l'accès API Google dépend d'Hugo) → plan 3 (newsletter) → déploiement.
- Contrainte sandbox : les API publiques (BOAMP, TED, data.economie) sont injoignables depuis cet environnement ; les clients sont écrits d'après la documentation et testés sur des fixtures. Premier appel réel à faire depuis le Mac mini (voir `ACTIONS-HUGO.md`).
- Socle créé : arborescence, README, Makefile, backlog, journal, `packages/core` en cours.

### 27/10 23:55 — lot 1 lancé
- `packages/core` terminé : 15 tests verts (LLM mock/Ollama/Anthropic, mail console/SMTP/Resend, settings, SQLite, extraction JSON). Poussé.
- Tâche planifiée créée : réveil toutes les heures à :45 de 21:45 à 06:45 (Paris), chaque nuit, dans cette session.
- 4 agents lancés en parallèle : `apps/veille-marches` (P2-1, P2-2, collecteur DECP en bonus), `apps/content-engine` (P4-1 à P4-3), `apps/avis-clients` (P1-1 à P1-3), `apps/newsletter-pipeline` (P3-1, P3-2).
- DEP-1 fait par la session principale : `deploy/macmini` (install.sh, run.sh, 10 services launchd dont caffeinate, install-launchd.sh), `deploy/vps` (Dockerfile, docker-compose, Caddy, boucle de jobs, README).
- Décision : `avis-clients` tourne entièrement sur le VPS (web + jobs), le Mac mini sert le LLM via Tailscale ; les trois autres apps tournent sur le Mac mini.
- Reste de la nuit : intégration des 4 apps (tests, corrections), puis P2-3 (brief DECP + page d'inscription Stripe), QA-1, DOC-1, P4-4, P1-4 selon le temps.

### 28/10 00:25 — veille-marches livrée (P2-1, P2-2, P2-3a)
- `apps/veille-marches` : 59 tests verts, ruff propre, CLI `vm` complète (collect BOAMP/TED/DECP, score règles + LLM, digest HTML/texte par abonné sans doublon, brief hebdo DECP, abonnés, stats). Vérifié par la session principale.
- Points à vérifier au premier appel réel listés dans le README de l'app (emplacement du CPV BOAMP, champs TED, identifiant du jeu DECP).
- Lancé : P2-3b (page d'inscription + Stripe) sur ce dossier.

### 28/10 00:27 — newsletter-pipeline livrée (P3-1, P3-2)
- `apps/newsletter-pipeline` : 60 tests verts, ruff propre, CLI `np` (collect RSS/pages avec trafilatura, dédoublonnage, rank LLM par lots, draft du numéro en markdown + HTML + texte, push beehiiv en dry-run, posts LinkedIn, stats, `run-monday` aligné sur le service launchd). 39 sources d'amorçage dont 36 à vérifier au premier passage réel. Vérifié par la session principale.
- Décisions de l'agent : markdown = source de vérité, 3 appels LLM courts par numéro avec replis `[À RELIRE]`, trafilatura pour l'extraction.

### 28/10 00:30 — avis-clients livrée (P1-1, P1-2, P1-3)
- `apps/avis-clients` : 57 tests verts, ruff propre, app FastAPI importable. Lien magique, onboarding avec QR et affiche A6, page publique sans filtrage d'avis, demandes SMS/WhatsApp/email avec quotas et liste STOP, client Google Business Profile (mock + réel), brouillons LLM avec garde-fous, boîte de réception HTMX, Stripe (Checkout, portail, webhook signé, garde d'accès), rapport mensuel, CLI `avis`. Vérifié par la session principale.
- Décision confirmée : web + jobs de cette app sur la même machine (SQLite) ; le `deploy/vps` racine fait tout tourner sur le VPS, l'app documente aussi l'option « tout sur le Mac mini derrière Cloudflare Tunnel ».
- Lancé : QA-1 (revue croisée) sur `avis-clients` et `newsletter-pipeline`.

### 28/10 00:35 — content-engine livré (P4-1, P4-2, P4-3)
- `apps/content-engine` : 41 tests verts (dont rendu d'un short 1080×1920 vérifié par ffprobe), ruff propre, CLI `ce` complète : sujets, idées, scripts en 3 variantes avec contrôles, file de validation, rendu vidéo (TTS `say`/Kokoro/ElevenLabs/silent, sous-titres ASS, barre de progression, miniatures), publication en dry-run (YouTube avec `containsSyntheticMedia`, Pinterest, LinkedIn, TikTok en stub), calendrier hebdo, `run-daily`, `run-publish`, import de métriques CSV, `angles`, `doctor`. Vérifié par la session principale.
- Les quatre apps sont livrées. Reste : P2-3b (en cours), QA-1 (2 revues en cours, 2 à lancer), DOC-1, P4-4, P1-4.

### 28/10 00:38 — DOC-1 : README racine
- README racine réécrit : tableau des apps avec commandes et nombre de tests, schéma des flux Mac mini / VPS, « démarrer en 15 minutes », variables de configuration à connaître, fichiers de pilotage.
- En cours : P2-3b (inscription + Stripe pour la veille), QA-1 sur avis-clients, newsletter-pipeline et content-engine. Reste à lancer : QA-1 sur veille-marches (après P2-3b), P4-4, P1-4.

### 28/10 00:41 — intégration racine
- Makefile corrigé : `make test` et `make setup` ne faisaient rien pour les apps (règles implicites ignorées sur des cibles `.PHONY`) ; passage en règles statiques, garde sur les venvs existants. `make test-core` vert, lint du socle corrigé.
- `ACTIONS-HUGO.md` : ajout des premiers essais réels app par app.

### 28/10 00:44 — chantier de nuit Mac mini aligné sur la documentation Claude Code
- Vérifié contre code.claude.com (headless, permissions, authentication, sessions) : mode `dontAsk` + liste blanche passée via `--settings`, jeton `claude setup-token` dans `CLAUDE_CODE_OAUTH_TOKEN` pour les lancements launchd, clé API retirée de l'environnement, `< /dev/null`, attente des sous-agents, journaux stream-json avec extraction des refus de permission, session neuve à chaque passage.
- Aucun planificateur local persistant n'existe dans Claude Code : launchd reste la bonne solution ; la tâche planifiée cloud ne peut pas lire le Mac.

### 28/10 00:46 — réveil horaire n°1 (session cloud)
- `NIGHT-SHIFT-OWNER` = cloud, la session cloud garde la main.
- Horodatages des entrées précédentes corrigés (ils avaient été estimés trop tard ; désormais pris sur l'horloge Paris).
- En cours : P2-3b (inscription + Stripe veille), QA-1 sur avis-clients, newsletter-pipeline, content-engine. Rien de nouveau à lancer : toutes les tâches restantes (QA-1 veille, P4-4, P1-4) touchent des dossiers occupés par ces agents.

### 28/10 00:52 — veille-marches : site, inscription, Stripe (P2-3b)
- `apps/veille-marches` : 78 tests verts (19 nouveaux), ruff propre. Site FastAPI (`vm web`) : landing avec exemple d'alerte réel, inscription → abonné en attente → Stripe Checkout, webhook signé et idempotent qui active l'abonné et envoie l'email de bienvenue, espace `/compte` par lien signé, portail Stripe, mode démonstration sans clé, pages légales à compléter. Vérifié par la session principale.
- Ajouté au déploiement Mac mini : services launchd `veille.web` (permanent) et `veille.syncstripe` (08:10).
- Lancé : QA-1 sur `veille-marches`.

### 28/10 01:00 — QA-1 newsletter-pipeline terminée
- 26 défauts corrigés (2 critiques, 10 hauts, 8 moyens, 6 bas), 60 → 93 tests verts, ruff propre, garde-fou anti-réseau dans les tests. Détail dans `apps/newsletter-pipeline/REVIEW.md`.
- Critiques : HTML brut des articles qui traversait jusqu'à l'email (scripts, iframes, liens `javascript:`) → filtre « email safe » ; URL glissées par le LLM dans le numéro → seules les URL des items sélectionnés sont conservées, le reste devient `[LIEN À VÉRIFIER]`.
- Revues encore en cours : avis-clients, content-engine, veille-marches.

### 28/10 01:06 — QA-1 content-engine terminée, P4-4 lancée
- 23 défauts corrigés (1 critique, 9 élevés, 9 moyens, 4 faibles), 41 → 57 tests verts, ruff propre. Détail dans `apps/content-engine/REVIEW.md`.
- Critique : `drawtext` interprétait les textes du modèle (un « 80 % » effaçait tout le texte de la vidéo) → `expansion=none`. Élevés : visibilité TikTok verrouillée en `SELF_ONLY` tant que l'app n'est pas auditée, étiquette IA jamais tronquée, bascule dry-run → live réparée (une simulation ne compte plus comme un envoi), contrôle « chiffre sans source » renforcé.
- Lancé : P4-4 (récupération automatique des métriques, sélection des angles).
