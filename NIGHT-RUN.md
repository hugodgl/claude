# Chantier de nuit : fonctionnement

## Ce qui tourne
- Une tâche planifiée réveille cette session Claude **toutes les heures à :45, de 21:45 à 06:45 (heure de Paris), chaque nuit**.
- À chaque réveil : `git pull`, lecture de `PROGRESS.md` et `BACKLOG.md`, prise des prochaines tâches non faites (jusqu'à 4 en parallèle quand elles sont indépendantes), implémentation avec tests, mise à jour du backlog et du journal, commit, push sur `claude/upbeat-davinci-lk5k7m`.
- Le passage de 06:45 ne démarre rien de nouveau : il finalise, teste, pousse et écrit le résumé du matin en tête de `PROGRESS.md`.

## Ce que tu peux faire
- **Arrêter** : écris « stop le chantier » dans cette session, ou désactive la tâche planifiée depuis l'interface Claude.
- **Réorienter** : change l'ordre dans `BACKLOG.md` et pousse, ou écris la consigne dans cette session ; elle est prise au réveil suivant.
- **Étendre en journée** : dis-le, la plage horaire passe en 24/7.
- **Lire l'avancement** : `PROGRESS.md` (journal horodaté) et `git log`.

## Garde-fous
- Aucune dépense engagée : pas de création de compte, pas d'achat, pas de clé API utilisée. Tout ce qui coûte est listé dans `ACTIONS-HUGO.md`.
- Aucune publication nulle part : les connecteurs tournent en `--dry-run` tant que les clés ne sont pas fournies.
- Jamais de secret dans le repo ; `.env` ignoré par git.
- Les deux dossiers `business-*.md` ne sont pas modifiés par le chantier.
