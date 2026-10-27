# Journal du chantier de nuit

## Résumé du matin
_(rempli lors du dernier passage, vers 06:45 Paris)_

## Journal (heure de Paris)

### 27/10 23:50 — ouverture du chantier
- Décision : ordre de construction = plan 2 (veille marchés publics, construisible de bout en bout sans autorisation externe) → plan 4 (moteur de contenu) → plan 1 (SaaS avis, l'accès API Google dépend d'Hugo) → plan 3 (newsletter) → déploiement.
- Contrainte sandbox : les API publiques (BOAMP, TED, data.economie) sont injoignables depuis cet environnement ; les clients sont écrits d'après la documentation et testés sur des fixtures. Premier appel réel à faire depuis le Mac mini (voir `ACTIONS-HUGO.md`).
- Socle créé : arborescence, README, Makefile, backlog, journal, `packages/core` en cours.
