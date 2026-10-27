#!/bin/bash
# Chantier de nuit sur le Mac mini : un passage de Claude Code par heure (launchd), dans ce repo uniquement.
# Garde-fous : mode dontAsk (aucune invite ; tout appel hors de la liste blanche est refusé), liste blanche
# relue et copiée par Hugo dans .claude/settings.json et passée explicitement, fenêtre horaire, verrou
# anti-chevauchement, plafond de tours, journal complet, aucune clé API dans ce script (abonnement Claude).
# Usage : deploy/macmini/night-shift.sh run|enable|disable|status|test
set -uo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
BRANCH="${NIGHT_SHIFT_BRANCH:-claude/upbeat-davinci-lk5k7m}"
PROMPT_FILE="$REPO/deploy/macmini/NIGHT-SHIFT-PROMPT.md"
SETTINGS_FILE="$REPO/.claude/settings.json"
LOG_DIR="$REPO/logs"; LOG="$LOG_DIR/night-shift.log"; LOCK="$LOG_DIR/night-shift.lock"
MAX_TURNS="${NIGHT_SHIFT_MAX_TURNS:-300}"
MODEL="${NIGHT_SHIFT_MODEL:-}"                                   # vide = modèle par défaut de Claude Code
TOKEN_FILE="${NIGHT_SHIFT_TOKEN_FILE:-$HOME/.config/sideproject/claude-oauth-token}"  # sortie de `claude setup-token`, chmod 600
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN                      # rester sur l'abonnement Claude, jamais sur une clé API
export CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1                     # attendre chaque sous-agent avant de terminer le passage
export BASH_DEFAULT_TIMEOUT_MS=300000 BASH_MAX_TIMEOUT_MS=600000  # suites de tests longues
mkdir -p "$LOG_DIR"
log() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

need_claude() {
  command -v claude >/dev/null 2>&1 && return 0
  log "Claude Code introuvable. Installation : curl -fsSL https://claude.ai/install.sh | bash ; puis 'claude' une fois dans ce dossier."
  return 1
}
need_settings() {
  [ -f "$SETTINGS_FILE" ] && return 0
  log "Liste blanche absente. Relis puis copie-la toi-même : cp deploy/macmini/claude-settings.template.json .claude/settings.json"
  return 1
}
load_auth() {
  if [ -f "$TOKEN_FILE" ]; then
    CLAUDE_CODE_OAUTH_TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"; export CLAUDE_CODE_OAUTH_TOKEN
  fi
  if ! claude auth status --text >/dev/null 2>&1; then
    log "Claude Code n'est pas connecté pour cet environnement. Soit 'claude setup-token' et coller le jeton dans $TOKEN_FILE (chmod 600), soit 'claude auth login'."
    return 1
  fi
}
run_claude() { # $1 = prompt, $2 = max turns, $3 = fichier jsonl
  claude -p "$1" \
    --permission-mode dontAsk \
    --settings "$SETTINGS_FILE" \
    --max-turns "$2" \
    --output-format stream-json --verbose \
    ${MODEL:+--model "$MODEL"} \
    < /dev/null > "$3" 2>>"$LOG"
}
summarize() { # extrait lisible du dernier événement stream-json
  python3 - "$1" <<'PY' 2>/dev/null || tail -n 3 "$1"
import json, sys
last = None
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    line = line.strip()
    if not line: continue
    try: ev = json.loads(line)
    except Exception: continue
    if ev.get("type") == "result": last = ev
if last:
    print("résultat :", (last.get("result") or "")[:1500])
    print("tours :", last.get("num_turns"), "| durée s :", round((last.get("duration_ms") or 0)/1000), "| sous-type :", last.get("subtype"))
    den = last.get("permission_denials") or []
    if den:
        print("refus de permission :", len(den))
        for d in den[:15]:
            print("  -", d.get("tool_name"), json.dumps(d.get("tool_input"), ensure_ascii=False)[:160])
PY
}

case "${1:-run}" in
  enable)
    need_claude || exit 1; need_settings || exit 1; load_auth || exit 1
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
    claude auth status --text 2>/dev/null || echo "Claude Code : non connecté dans cet environnement"
    [ -f "$LOG" ] && tail -n 30 "$LOG"
    ;;
  test)
    need_claude || exit 1; need_settings || exit 1; load_auth || exit 1
    cd "$REPO"
    tmp="$LOG_DIR/night-shift-test.jsonl"
    run_claude "Réponds exactement : OK" 1 "$tmp"
    summarize "$tmp" | tee -a "$LOG"
    grep -q '"result"' "$tmp" && grep -q "OK" "$tmp" && log "test Claude Code : OK" || { log "test Claude Code : échec, voir $tmp"; exit 1; }
    ;;
  run)
    if [ -e "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then log "passage déjà en cours, je ne relance pas"; exit 0; fi
    echo $$ > "$LOCK"; trap 'rm -f "$LOCK"' EXIT
    hour=$(TZ=Europe/Paris date +%H)
    if [ "${NIGHT_SHIFT_ALWAYS:-0}" != 1 ] && [ "$hour" -ge 7 ] && [ "$hour" -lt 21 ]; then log "hors fenêtre de nuit ($hour h), rien à faire"; exit 0; fi
    need_claude || exit 1; need_settings || exit 1; load_auth || exit 1
    cd "$REPO" || exit 1
    git fetch -q origin "$BRANCH" && git checkout -q "$BRANCH" && git pull -q --ff-only origin "$BRANCH" || log "attention : pull impossible, je continue sur l'état local"
    if [ "$(cat NIGHT-SHIFT-OWNER 2>/dev/null)" != "macmini" ]; then log "propriétaire = $(cat NIGHT-SHIFT-OWNER 2>/dev/null), le Mac mini n'a pas la main (lance '$0 enable')"; exit 0; fi
    stamp="$(date '+%Y%m%dT%H%M')"; jsonl="$LOG_DIR/night-shift-$stamp.jsonl"
    log "=== début du passage ($jsonl) ==="
    run_claude "$(cat "$PROMPT_FILE")" "$MAX_TURNS" "$jsonl"
    code=$?
    summarize "$jsonl" | tee -a "$LOG"
    git push -q origin "$BRANCH" 2>>"$LOG" || log "push de secours impossible"
    if [ -n "$(git status --porcelain)" ]; then log "fichiers non commités laissés par le passage :"; git status --short | head -20 | tee -a "$LOG"; fi
    find "$LOG_DIR" -name 'night-shift-*.jsonl' -mtime +14 -delete 2>/dev/null
    log "=== fin du passage (code $code) ==="
    ;;
  *) echo "usage : $0 run|enable|disable|status|test"; exit 1;;
esac
