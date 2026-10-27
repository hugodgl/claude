#!/bin/bash
# Lanceur commun des jobs launchd : run.sh <app> <commande> [args...]
# - se place dans apps/<app>, charge .env, exécute .venv/bin/<commande>
# - journalise dans logs/<app>-<commande>.log avec horodatage, rotation à 10 Mo
set -uo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
APP="$1"; shift
CMD="$1"; shift
APP_DIR="$REPO/apps/$APP"
LOG_DIR="$REPO/logs"
LOG="$LOG_DIR/$APP-$CMD.log"
mkdir -p "$LOG_DIR"
if [ -f "$LOG" ] && [ "$(stat -f%z "$LOG" 2>/dev/null || stat -c%s "$LOG")" -gt 10485760 ]; then
  mv "$LOG" "$LOG.1"
fi
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
cd "$APP_DIR" || { echo "$(date '+%F %T') app introuvable : $APP_DIR" >> "$LOG"; exit 1; }
if [ -f .env ]; then set -a; . ./.env; set +a; fi
BIN="$APP_DIR/.venv/bin/$CMD"
[ -x "$BIN" ] || { echo "$(date '+%F %T') commande introuvable : $BIN (lancer make setup-$APP)" >> "$LOG"; exit 1; }
{
  echo "=== $(date '+%F %T') $CMD $* ==="
  "$BIN" "$@"
  echo "=== fin $(date '+%F %T') code=$? ==="
} >> "$LOG" 2>&1
