# Déploiement Mac mini

## Installation
```bash
git clone <repo> ~/sideproject && cd ~/sideproject
deploy/macmini/install.sh          # brew (uv, ffmpeg, ollama), modèle, venvs, .env, launchd
```
Variables : `OLLAMA_MODEL=qwen3:8b deploy/macmini/install.sh` sur un Mac mini 16 Go si le 14B est trop lent.

## Services launchd installés
| Service | Quand | Commande |
|---|---|---|
| veille.collect | 06:00 et 14:00 | `vm collect --source all --since-days 2` |
| veille.score | 06:30 | `vm score` |
| veille.digest | 07:00 | `vm digest --send` |
| veille.brief | dimanche 18:00 | `vm brief-weekly --send` |
| content.daily | 05:30 | `ce run-daily` (idées, scripts, export de relecture) |
| content.publish | toutes les 30 min | `ce run-publish` (dry-run tant que pas de clés) |
| avis.poll | toutes les 15 min | `avis poll-reviews` |
| avis.monthly | le 1er à 08:00 | `avis monthly-report` |
| newsletter.monday | lundi 05:00 | `np run-monday` (collecte, classement, brouillon) |
| caffeinate | permanent | empêche la mise en veille |

Chaque job passe par `deploy/macmini/run.sh`, qui charge le `.env` de l'app et écrit dans `logs/<app>-<commande>.log` (rotation à 10 Mo).

## Commandes utiles
```bash
launchctl list | grep sideproject                         # état
launchctl kickstart -k gui/$(id -u)/com.sideproject.veille.collect   # lancer maintenant
tail -f logs/veille-marches-vm.log                        # suivre
deploy/macmini/install-launchd.sh --only com.sideproject.avis.poll   # réinstaller un service
deploy/macmini/install-launchd.sh --remove                # tout retirer
```

## Sauvegardes
Les bases SQLite sont dans `apps/*/data/`. Time Machine suffit en local ; ajoute une copie hors site (rclone vers un stockage objet) avec un job quotidien si les données clients deviennent importantes.
