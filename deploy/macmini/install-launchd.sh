#!/bin/bash
# Installe (ou réinstalle) les services launchd du projet pour l'utilisateur courant.
# Usage : deploy/macmini/install-launchd.sh [--only label] [--remove]
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
TPL_DIR="$REPO/deploy/macmini/launchd"
DEST="$HOME/Library/LaunchAgents"
UID_NUM="$(id -u)"
ONLY=""; REMOVE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --only) ONLY="$2"; shift 2;;
    --remove) REMOVE=1; shift;;
    *) echo "argument inconnu : $1"; exit 1;;
  esac
done
mkdir -p "$DEST" "$REPO/logs"
for tpl in "$TPL_DIR"/*.plist.tmpl; do
  label="$(basename "$tpl" .plist.tmpl)"
  [ -n "$ONLY" ] && [ "$ONLY" != "$label" ] && continue
  [ -z "$ONLY" ] && [ "$label" = "com.sideproject.nightshift" ] && continue   # géré par night-shift.sh enable
  plist="$DEST/$label.plist"
  launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true
  if [ "$REMOVE" = 1 ]; then rm -f "$plist"; echo "retiré  $label"; continue; fi
  sed -e "s#__REPO__#$REPO#g" -e "s#__HOME__#$HOME#g" "$tpl" > "$plist"
  plutil -lint "$plist" >/dev/null
  launchctl bootstrap "gui/$UID_NUM" "$plist"
  echo "installé $label"
done
echo
echo "Services actifs :"; launchctl list | grep sideproject || true
echo "Logs : $REPO/logs/"
