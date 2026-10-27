#!/bin/bash
# Boucle de jobs pour le conteneur avis-jobs : polling des avis toutes les 15 min, rapport le 1er du mois.
set -u
LAST_REPORT=""
while true; do
  avis poll-reviews || echo "poll-reviews en erreur (code $?)"
  TODAY="$(date +%Y-%m-%d)"
  if [ "$(date +%d)" = "01" ] && [ "$LAST_REPORT" != "$TODAY" ] && [ "$(date +%H)" -ge 8 ]; then
    avis monthly-report && LAST_REPORT="$TODAY"
  fi
  sleep 900
done
