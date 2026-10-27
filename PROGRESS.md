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
