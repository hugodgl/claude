# Chantier de nuit : fonctionnement

## Deux exécutants possibles, un seul à la fois
Le fichier `NIGHT-SHIFT-OWNER` à la racine dit qui a la main : `cloud` ou `macmini`.

| | Cloud (session Claude sur claude.ai) | Mac mini (Claude Code en local) |
|---|---|---|
| Comment ça tourne | tâche planifiée qui réveille cette session toutes les heures | service launchd qui lance `deploy/macmini/night-shift.sh run` toutes les heures |
| Fenêtre | 21:45 → 06:45 Paris | 21:45 → 06:45 Paris (24/7 avec `NIGHT_SHIFT_ALWAYS=1`) |
| Accès | pas d'accès aux API publiques ni à Ollama | API publiques, Ollama, ffmpeg, `say` : tout est réel (en lecture) |
| Garde-fous | permissions de la session | pas d'invite, mais liste blanche d'outils dans `.claude/settings.json` : le reste est refusé |
| Prise en main | déjà actif cette nuit | `deploy/macmini/night-shift.sh enable` |

**Passer sur le Mac mini** (une fois, 15 minutes) :
```bash
git clone https://github.com/hugodgl/claude ~/sideproject && cd ~/sideproject
git checkout claude/upbeat-davinci-lk5k7m
deploy/macmini/install.sh                 # outils, Ollama, venvs, Claude Code
claude                                    # DANS ce dossier : connexion au compte Claude + accepter la confiance du dossier, puis quitter
claude setup-token                        # jeton d'un an pour les lancements sans terminal (Pro/Max) ; le coller dans :
mkdir -p ~/.config/sideproject && pbpaste > ~/.config/sideproject/claude-oauth-token && chmod 600 ~/.config/sideproject/claude-oauth-token
gh auth login                             # ou une clé SSH GitHub : le Mac doit pouvoir pousser
cp deploy/macmini/claude-settings.template.json .claude/settings.json   # relis la liste blanche d'outils avant de la copier
deploy/macmini/night-shift.sh test        # vérifie connexion + permissions sans terminal
deploy/macmini/night-shift.sh enable      # le Mac prend la main : la session cloud se met en veille toute seule
```
Points vérifiés dans la documentation Claude Code (octobre 2026) :
- `--permission-mode dontAsk` + liste blanche = le mode documenté pour les exécutions verrouillées sans personne devant l'écran ; le fichier est passé explicitement (`--settings`) pour être pris en compte même si le dossier n'a pas encore été « approuvé » en interactif.
- Le jeton de `claude setup-token` passe par `CLAUDE_CODE_OAUTH_TOKEN`, fonctionne sans trousseau et sans terminal, et compte sur l'abonnement. Le script retire toute `ANTHROPIC_API_KEY` de l'environnement pour ne jamais basculer sur une facturation API.
- Chaque passage est une session neuve ; l'état vit dans les fichiers du repo (`BACKLOG.md`, `PROGRESS.md`). Journaux détaillés : `logs/night-shift-<horodatage>.jsonl` (14 jours), résumé lisible et refus de permission dans `logs/night-shift.log`.
- Claude Code se met à jour tout seul entre deux lancements (installeur natif) ; pour figer la version : `DISABLE_AUTOUPDATER=1` dans l'environnement du service.

Prérequis macOS : session utilisateur ouverte en permanence (Réglages → Utilisateurs → ouverture de session automatique ; FileVault désactivé ou déverrouillé), mise en veille désactivée, Mac branché en Ethernet de préférence.

Journal : `logs/night-shift.log`. État : `deploy/macmini/night-shift.sh status`. Rendre la main au cloud : `deploy/macmini/night-shift.sh disable`.


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
