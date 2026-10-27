#!/bin/bash
# Chantier de nuit sur le Mac mini : un passage de Claude Code par heure (launchd), dans ce repo uniquement.
# Garde-fous : pas d'invite de confirmation (personne n'est là la nuit) MAIS liste blanche d'outils dans
# .claude/settings.json (mode dontAsk : tout ce qui n'est pas listé est refusé), fenêtre horaire, verrou
# anti-chevauchement, plafond de tours, journal complet, aucune clé API dans ce script.
# Usage : deploy/macmini/night-shift.sh run|enable|disable|status|test
set -uo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
BRANCH="${NIGHT_SHIFT_BRANCH:-claude/upbeat-davinci-lk5k7m}"
PROMPT_FILE="$REPO/deploy/macmini/NIGHT-SHIFT-PROMPT.md"
LOG_DIR="$REPO/logs"; LOG="$LOG_DIR/night-shift.log"; LOCK="$LOG_DIR/night-shift.lock"
MAX_TURNS="${NIGHT_SHIFT_MAX_TURNS:-300}"
MODEL="${NIGHT_SHIFT_MODEL:-}"           # vide = modèle par défaut de Claude Code
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.claude/local:$PATH"
mkdir -p "$LOG_DIR"
log() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

need_claude() {
  command -v claude >/dev/null 2>&1 && return 0
  log "Claude Code introuvable. Installe-le (https://code.claude.com/docs) puis lance 'claude' une fois pour te connecter."
  return 1
}

need_settings() {
  [ -f "$REPO/.claude/settings.json" ] && return 0
  log "Liste blanche absente. Relis puis copie-la toi-même : cp deploy/macmini/claude-settings.template.json .claude/settings.json"
  return 1
}

run_claude() { # $1 = prompt, $2 = max turns
  claude -p "$1" --permission-mode dontAsk --max-turns "$2" --output-format text ${MODEL:+--model "$MODEL"}
}

case "${1:-run}" in
  enable)
    need_claude || exit 1
    need_settings || exit 1
    cd "$REPO" && git pull --ff-only origin "$BRANCH" || exit 1
    echo macmini > NIGHT-SHIFT-OWNER
    git add NIGHT-SHIFT-OWNER && git commit -q -m "Chantier de nuit : le Mac mini prend la main" && git push origin "$BRANCH" || exit 1
    "$REPO/deploy/macmini/install-launchd.sh" --only com.sideproject.nightshift
    log "Mac mini propriétaire du chantier. Prochain passage à l'heure :45 entre 21:45 et 06:45. Passage immédiat : NIGHT_SHIFT_ALWAYS=1 $0 run"
    ;;
  disable)
    cd "$REPO" && git pull --ff-only origin "$BRANCH"
    echo cloud > NIGHT-SHIFT-OWNER
    git add NIGHT-SHIFT-OWNER && git commit -q -m "Chantier de nuit : le Mac mini rend la main" && git push origin "$BRANCH"
    "$REPO/deploy/macmini/install-launchd.sh" --only com.sideproject.nightshift --remove
    log "Service retiré, propriétaire = cloud."
    ;;
  status)
    launchctl list | grep nightshift || echo "service non installé"
    echo "propriétaire : $(cat "$REPO/NIGHT-SHIFT-OWNER" 2>/dev/null || echo inconnu)"
    [ -f "$LOG" ] && tail -n 30 "$LOG"
    ;;
  test)
    need_claude || exit 1
    need_settings || exit 1
    cd "$REPO"
    out="$(run_claude "Réponds exactement : OK" 1 2>&1)"
    echo "$out" | tail -n 3
    echo "$out" | grep -q "OK" && log "test Claude Code : OK" || { log "test Claude Code : échec (connecte-toi avec 'claude' dans un terminal)"; exit 1; }
    ;;
  run)
    if [ -e "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then log "passage déjà en cours, je ne relance pas"; exit 0; fi
    echo $$ > "$LOCK"; trap 'rm -f "$LOCK"' EXIT
    hour=$(TZ=Europe/Paris date +%H)
    if [ "${NIGHT_SHIFT_ALWAYS:-0}" != 1 ] && [ "$hour" -ge 7 ] && [ "$hour" -lt 21 ]; then log "hors fenêtre de nuit ($hour h), rien à faire"; exit 0; fi
    need_claude || exit 1
    need_settings || exit 1
    cd "$REPO" || exit 1
    git fetch -q origin "$BRANCH" && git checkout -q "$BRANCH" && git pull -q --ff-only origin "$BRANCH" || log "attention : pull impossible, je continue sur l'état local"
    if [ "$(cat NIGHT-SHIFT-OWNER 2>/dev/null)" != "macmini" ]; then log "propriétaire = $(cat NIGHT-SHIFT-OWNER 2>/dev/null), le Mac mini n'a pas la main (lance '$0 enable')"; exit 0; fi
    log "=== début du passage ==="
    run_claude "$(cat "$PROMPT_FILE")" "$MAX_TURNS" >> "$LOG" 2>&1
    code=$?
    git push -q origin "$BRANCH" 2>>"$LOG" || log "push de secours impossible"
    if [ -n "$(git status --porcelain)" ]; then log "fichiers non commités laissés par le passage :"; git status --short | head -20 | tee -a "$LOG"; fi
    log "=== fin du passage (code $code) ==="
    ;;
  *) echo "usage : $0 run|enable|disable|status|test"; exit 1;;
esac
