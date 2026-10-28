#!/bin/bash
# -------------------------------------------------------------------------------------------------
# Test de fumée de bout en bout du monorepo « Mac mini H24 » : hors ligne, sans aucune clé, ~2 minutes.
#
#   scripts/smoke.sh [--keep] [vm] [ce] [np] [avis]          (ou : make smoke)
#
# À lancer après deploy/macmini/install.sh (ou `make setup`). Chaque app déroule sa chaîne complète en
# mode simulation (LLM mock, emails console, SMS dry-run, Google Business Profile mock) dans un dossier
# temporaire : les dossiers data/ et out/ des apps ne sont jamais touchés, aucun appel réseau n'est fait.
#
#   veille-marches      abonné → collecte (cas « sans réseau », puis fixtures BOAMP/TED/DECP rejouées par
#                       scripts/smoke_vm_stub.py sur un port local) → score → digest → brief hebdo →
#                       stats → `vm web` (/health, /, /exemple) démarré puis arrêté proprement
#   content-engine      doctor → init → script → approbation → rendu vidéo (vérifié par ffprobe) →
#                       publication YouTube en dry-run (JSON sans secret) → calendrier → export relecture
#   newsletter-pipeline sources (flux RSS/Atom locaux des tests) → collecte → classement → brouillon et
#                       push --target file quand le fournisseur mock le permet (voir SMOKE-FINDINGS.md) → stats
#   avis-clients        init-db → démo → poll des avis (mock) → rapport mensuel (dry-run) → serveur web
#                       (/healthz, /, /r/<slug>) démarré puis arrêté proprement
#
# Chaque étape écrit sa sortie dans <dossier temporaire>/logs/NN-etape.log ; seul le résumé s'affiche,
# plus les 20 dernières lignes du journal en cas d'échec. Code de sortie 1 dès qu'une étape échoue.
# Voix : `say` (macOS) si la voix configurée est installée, sinon TTS_PROVIDER=silent ; SMOKE_TTS=silent
# pour forcer. Compatible bash 3.2 (macOS) : pas de tableau associatif, pas de mapfile, pas de `timeout`.
# -------------------------------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STARTED_AT=$(date +%s)
KEEP=0
APPS=""

usage() {
  cat <<USAGE
Usage : scripts/smoke.sh [--keep] [vm] [ce] [np] [avis]
  --keep        conserve le dossier temporaire même si tout passe (rendus, logs, bases)
  vm ce np avis ne lancer que ces apps (défaut : les quatre, dans cet ordre)
Variables : SMOKE_DIR (dossier de travail, défaut mktemp -d), SMOKE_TTS=silent|say (défaut : say si disponible)
USAGE
}

for arg in "$@"; do
  case "$arg" in
    --keep) KEEP=1 ;;
    -h|--help) usage; exit 0 ;;
    vm|ce|np|avis) APPS="$APPS $arg" ;;
    *) echo "argument inconnu : $arg" >&2; usage >&2; exit 2 ;;
  esac
done
[ -n "$APPS" ] || APPS="vm ce np avis"

# ---- affichage -----------------------------------------------------------------------------------
if [ -t 1 ] && [ "${TERM:-dumb}" != "dumb" ]; then
  C_OK=$'\033[32m'; C_KO=$'\033[31m'; C_WARN=$'\033[33m'; C_DIM=$'\033[2m'; C_BOLD=$'\033[1m'; C_END=$'\033[0m'
else
  C_OK=""; C_KO=""; C_WARN=""; C_DIM=""; C_BOLD=""; C_END=""
fi

STEP_N=0; OK_N=0; FAIL_N=0; SKIP_N=0
FAILED=""      # libellés des étapes en échec (une par ligne)
NOTES=""       # remarques à rappeler dans le résumé (une par ligne)
STEP_RC=0; STEP_LOG=""; STEP_SECS=0; STEP_TIMED_OUT=0; STEP_CWD="$ROOT"
ALLOW_RC=""; EXPECT=""
SERVER_PID=0; SERVER_PIDS=""

fmt_secs() {
  if [ "$1" -ge 60 ]; then printf '%d min %02d s' $(( $1 / 60 )) $(( $1 % 60 ))
  elif [ "$1" -eq 0 ]; then printf '< 1 s'
  else printf '%d s' "$1"; fi
}
section() { printf '\n%s== %s ==%s\n' "$C_BOLD" "$1" "$C_END"; }
note() { NOTES="${NOTES}${1}"$'\n'; printf '  %s· %s%s\n' "$C_DIM" "$1" "$C_END"; }
ok() {
  OK_N=$((OK_N + 1))
  printf '%s✔%s %s %s(%s)%s\n' "$C_OK" "$C_END" "$1" "$C_DIM" "$(fmt_secs "$STEP_SECS")" "$C_END"
}
skip() {  # skip <libellé> <raison>
  SKIP_N=$((SKIP_N + 1))
  printf '%s⚠%s %s — ignoré : %s\n' "$C_WARN" "$C_END" "$1" "$2"
  NOTES="${NOTES}ignoré : $1 — $2"$'\n'
}
fail() {  # fail <libellé> <raison>  (journal : STEP_LOG)
  FAIL_N=$((FAIL_N + 1))
  FAILED="${FAILED}${1}"$'\n'
  printf '%s✘%s %s — %s %s(%s)%s\n' "$C_KO" "$C_END" "$1" "$2" "$C_DIM" "$(fmt_secs "$STEP_SECS")" "$C_END"
  if [ -n "$STEP_LOG" ] && [ -f "$STEP_LOG" ]; then
    printf '    %sjournal : %s (20 dernières lignes)%s\n' "$C_DIM" "$STEP_LOG" "$C_END"
    tail -n 20 "$STEP_LOG" | sed 's/^/    │ /'
  fi
}

# ---- outils --------------------------------------------------------------------------------------
need_bin() {  # need_bin <commande> <comment l'installer>
  command -v "$1" >/dev/null 2>&1 || { echo "outil manquant : $1 ($2)" >&2; exit 1; }
}
need_bin curl "fourni avec macOS ; apt install curl sous Linux"
need_bin ffmpeg "brew install ffmpeg (deploy/macmini/install.sh l'installe)"
need_bin ffprobe "brew install ffmpeg"

PY="$ROOT/apps/veille-marches/.venv/bin/python"       # python du socle : sert au port libre et au stub
[ -x "$PY" ] || PY="$(command -v python3 || true)"
[ -n "$PY" ] || { echo "python3 introuvable (le venv de veille-marches ou python3 est nécessaire)" >&2; exit 1; }

for pair in "veille-marches:vm" "content-engine:ce" "newsletter-pipeline:np" "avis-clients:avis"; do
  app=${pair%%:*}; cli=${pair##*:}
  case " $APPS " in *" $cli "*) ;; *) continue ;; esac
  if [ ! -x "$ROOT/apps/$app/.venv/bin/$cli" ]; then
    echo "apps/$app/.venv/bin/$cli introuvable : lancer deploy/macmini/install.sh ou make setup-$app" >&2; exit 1
  fi
done

free_port() {
  "$PY" -c 'import socket
s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()'
}
http_code() {  # http_code <url> : code HTTP ou 000
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' --noproxy '*' --max-time 10 "$1" 2>/dev/null || true)
  [ -n "$code" ] || code=000
  printf '%s' "$code"
}
http_is() {  # http_is <code attendu> <url>
  local code; code=$(http_code "$2")
  echo "GET $2 → $code"
  [ "$code" = "$1" ]
}
first_file_exists() {  # first_file_exists <dossier> <motif glob>
  set -- "$1"/$2
  if [ -e "$1" ]; then echo "présent : $1"; else echo "aucun fichier $* trouvé"; return 1; fi
}
video_ok() {  # video_ok <fichier> : 1080×1920, piste audio, durée > 0
  [ -s "$1" ] || { echo "fichier absent ou vide : $1"; return 1; }
  local info
  info=$(ffprobe -v error -show_entries stream=codec_type,width,height:format=duration -of default=nw=1 "$1") || return 1
  echo "$info"
  echo "$info" | grep -q '^width=1080$' || { echo "largeur attendue 1080"; return 1; }
  echo "$info" | grep -q '^height=1920$' || { echo "hauteur attendue 1920"; return 1; }
  echo "$info" | grep -q '^codec_type=audio$' || { echo "pas de piste audio"; return 1; }
  echo "$info" | awk -F= '/^duration=/ { if ($2 + 0 > 0.5) found = 1 } END { exit !found }' \
    || { echo "durée nulle"; return 1; }
}
publish_json_ok() {  # publish_json_ok <fichier> : JSON valide, dry_run=true, plateforme renseignée
  [ -s "$1" ] || { echo "fichier absent ou vide : $1"; return 1; }
  "$PY" - "$1" <<'PYEOF'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
assert data.get("dry_run") is True, "dry_run devrait être true"
assert data.get("platform"), "plateforme absente"
assert data.get("requests"), "aucune requête décrite"
print("dry_run=true, plateforme", data["platform"], ",", len(data["requests"]), "requête(s) décrite(s)")
PYEOF
}
SECRET_RE='ya29\.[0-9A-Za-z_.-]{20,}|AIza[0-9A-Za-z_-]{20,}|sk_(live|test)_[0-9A-Za-z]{8,}|whsec_[0-9A-Za-z]{8,}|Bearer [0-9A-Za-z_.~+/=-]{20,}|"(access_token|refresh_token|client_secret|api_key)": "[^<*][^"]{8,}"'
no_secret_in() {  # no_secret_in <fichier> : aucun motif de jeton ou de clé en clair
  [ -s "$1" ] || { echo "fichier absent ou vide : $1"; return 1; }
  if grep -nE "$SECRET_RE" "$1"; then echo "motif de secret trouvé (ci-dessus) dans $1"; return 1; fi
  echo "aucun motif de secret dans $1"
}

run_logged() {  # run_logged <slug> <délai s> <commande…> → STEP_RC, STEP_LOG, STEP_SECS, STEP_TIMED_OUT
  local slug=$1 limit=$2; shift 2
  local started pid elapsed
  STEP_N=$((STEP_N + 1))
  STEP_LOG="$LOG_DIR/$(printf '%02d' "$STEP_N")-$slug.log"
  STEP_TIMED_OUT=0
  printf '$ cd %s && %s\n\n' "$STEP_CWD" "$*" > "$STEP_LOG"
  started=$(date +%s)
  ( cd "$STEP_CWD" && exec "$@" ) >> "$STEP_LOG" 2>&1 &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    sleep 0.2
    elapsed=$(( $(date +%s) - started ))
    if [ "$elapsed" -ge "$limit" ]; then
      STEP_TIMED_OUT=1
      kill "$pid" 2>/dev/null || true; sleep 2; kill -9 "$pid" 2>/dev/null || true
      break
    fi
  done
  STEP_RC=0; wait "$pid" || STEP_RC=$?
  STEP_SECS=$(( $(date +%s) - started ))
  printf '\n[code de sortie %s, %s s]\n' "$STEP_RC" "$STEP_SECS" >> "$STEP_LOG"
}
rc_allowed() { local a; for a in $2; do [ "$a" = "$1" ] && return 0; done; return 1; }
step() {  # step <slug> <libellé> <délai s> <commande…> ; avant l'appel : ALLOW_RC="0 1" (défaut 0), EXPECT=<motif grep -E attendu>
  local slug=$1 label=$2 limit=$3; shift 3
  local allow=${ALLOW_RC:-0} expect=${EXPECT:-} why=""
  ALLOW_RC=""; EXPECT=""
  run_logged "$slug" "$limit" "$@"
  if [ "$STEP_TIMED_OUT" = 1 ]; then why="délai de ${limit} s dépassé"
  elif ! rc_allowed "$STEP_RC" "$allow"; then why="code de sortie $STEP_RC"
  elif grep -q 'Traceback (most recent call last)' "$STEP_LOG"; then why="traceback Python dans la sortie"
  elif [ -n "$expect" ] && ! grep -Eq -- "$expect" "$STEP_LOG"; then why="sortie attendue absente (« $expect »)"
  fi
  if [ -z "$why" ]; then ok "$label"; else fail "$label" "$why"; fi
}
check() {  # check <slug> <libellé> <fonction ou commande…> : vérification rapide, journalisée elle aussi
  local slug=$1 label=$2 started; shift 2
  STEP_N=$((STEP_N + 1))
  STEP_LOG="$LOG_DIR/$(printf '%02d' "$STEP_N")-$slug.log"
  started=$(date +%s); STEP_RC=0
  "$@" > "$STEP_LOG" 2>&1 || STEP_RC=$?
  STEP_SECS=$(( $(date +%s) - started ))
  if [ "$STEP_RC" = 0 ]; then ok "$label"; else fail "$label" "vérification échouée"; fi
}
start_server() {  # start_server <slug> <libellé> <url de santé> <commande…> ; SERVER_PID ; attend 30 s au plus
  local slug=$1 label=$2 url=$3 started i=0 code=000; shift 3
  STEP_N=$((STEP_N + 1))
  STEP_LOG="$LOG_DIR/$(printf '%02d' "$STEP_N")-$slug.log"
  printf '$ cd %s && %s\n\n' "$STEP_CWD" "$*" > "$STEP_LOG"
  started=$(date +%s)
  ( cd "$STEP_CWD" && exec "$@" ) >> "$STEP_LOG" 2>&1 &
  SERVER_PID=$!
  SERVER_PIDS="$SERVER_PIDS $SERVER_PID"
  while [ "$i" -lt 60 ]; do
    code=$(http_code "$url")
    [ "$code" = "200" ] && break
    kill -0 "$SERVER_PID" 2>/dev/null || break
    sleep 0.5; i=$((i + 1))
  done
  STEP_SECS=$(( $(date +%s) - started ))
  if [ "$code" = "200" ]; then ok "$label"; return 0; fi
  if kill -0 "$SERVER_PID" 2>/dev/null; then fail "$label" "GET $url → $code après 30 s"
  else fail "$label" "le processus s'est arrêté avant de répondre"; fi
  return 1
}
stop_server() {  # stop_server <pid> <libellé> [journal du serveur] : SIGTERM, 10 s pour s'arrêter, sinon SIGKILL (= échec)
  local pid=$1 label=$2 i=0 started
  STEP_LOG=${3:-}
  started=$(date +%s)
  kill "$pid" 2>/dev/null || true
  while kill -0 "$pid" 2>/dev/null && [ "$i" -lt 100 ]; do sleep 0.1; i=$((i + 1)); done
  STEP_SECS=$(( $(date +%s) - started ))
  if kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true
    fail "$label" "pas d'arrêt après SIGTERM en 10 s (tué de force)"
  else
    wait "$pid" 2>/dev/null || true
    ok "$label"
  fi
}
cleanup() {
  local pid
  for pid in $SERVER_PIDS; do kill "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT
trap 'echo; echo "interrompu"; exit 130' INT TERM

# ---- dossier de travail et environnement commun ----------------------------------------------------
if [ -n "${SMOKE_DIR:-}" ]; then
  mkdir -p "$SMOKE_DIR"; SMOKE_DIR="$(cd "$SMOKE_DIR" && pwd)"
else
  SMOKE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/sideproject-smoke.XXXXXX")"
fi
LOG_DIR="$SMOKE_DIR/logs"; mkdir -p "$LOG_DIR"

export LLM_PROVIDER=mock MAIL_PROVIDER=console SMS_PROVIDER=dry-run GBP_MODE=mock
export FACEBOOK_MODE=mock TRIPADVISOR_MODE=mock
export PYTHONUTF8=1
export NO_PROXY="127.0.0.1,localhost${NO_PROXY:+,$NO_PROXY}"; export no_proxy="$NO_PROXY"
# variables propres à une app : remises à zéro entre deux sections pour qu'aucune ne déteigne sur la suivante
clear_app_env() {
  unset DATA_DIR DB_PATH OUT_DIR ISSUES_DIR SOURCES_FILE SPONSOR_FILE HTTP_TIMEOUT_S APP_BASE_URL \
        BOAMP_BASE_URL TED_BASE_URL DECP_BASE_URL TTS_PROVIDER TTS_SILENT_DURATION_S VIDEO_PRESET \
        REQUEST_DELAY_S MAX_ITEM_AGE_DAYS MAX_PER_SOURCE
}

# voix : `say` seulement si la voix configurée est installée (sinon rendu muet, timings estimés)
TTS=silent
if [ "${SMOKE_TTS:-}" = "silent" ]; then
  TTS=silent
elif command -v say >/dev/null 2>&1; then
  VOICE="${SAY_VOICE:-}"
  if [ -z "$VOICE" ] && [ -f "$ROOT/apps/content-engine/.env" ]; then
    VOICE=$(sed -n 's/^SAY_VOICE=[[:space:]]*\([^#[:space:]]*\).*/\1/p' "$ROOT/apps/content-engine/.env" | head -1)
  fi
  [ -n "$VOICE" ] || VOICE=Thomas
  if say -v '?' 2>/dev/null | grep -q "^$VOICE[[:space:]]"; then TTS=say; else TTS=silent; fi
  [ "$TTS" = say ] || NOTES="${NOTES}voix macOS « $VOICE » absente (say -v '?') : rendu avec TTS_PROVIDER=silent"$'\n'
fi

printf '%sTest de fumée%s — %s\n' "$C_BOLD" "$C_END" "$ROOT"
printf 'dossier de travail : %s\n' "$SMOKE_DIR"
printf 'mode : LLM_PROVIDER=mock · MAIL_PROVIDER=console · SMS_PROVIDER=dry-run · GBP_MODE=mock · TTS_PROVIDER=%s · aucun réseau\n' "$TTS"

# ---- veille-marches --------------------------------------------------------------------------------
smoke_vm() {
  local app="$ROOT/apps/veille-marches" dir="$SMOKE_DIR/veille-marches" vm fixtures dead stub port stub_pid stub_log web_pid web_log
  vm="$app/.venv/bin/vm"; fixtures="$app/tests/fixtures"
  section "veille-marches (vm)"
  mkdir -p "$dir/data" "$dir/out"
  clear_app_env; STEP_CWD="$app"
  export DATA_DIR="$dir/data" DB_PATH="$dir/data/veille-marches.db" OUT_DIR="$dir/out" HTTP_TIMEOUT_S=5
  dead=$(free_port); stub=$(free_port); port=$(free_port)

  EXPECT='abonné #[0-9]+ ajouté'
  step vm-subscribers-add "vm subscribers add — abonné espaces verts (CPV 773), départements 69 et 01" 60 \
    "$vm" subscribers add smoke@exemple.fr --label "Paysages Smoke" --cpv 773 --dept 69 --dept 01 --plan essentiel
  EXPECT='smoke@exemple\.fr'
  step vm-subscribers-list "vm subscribers list" 60 "$vm" subscribers list

  # sans réseau : les trois sources tombent en erreur propre (code 1 attendu, jamais de traceback)
  export BOAMP_BASE_URL="http://127.0.0.1:$dead/boamp" TED_BASE_URL="http://127.0.0.1:$dead/ted" DECP_BASE_URL="http://127.0.0.1:$dead/decp"
  ALLOW_RC="0 1"; EXPECT='ERREUR'
  step vm-collect-offline "vm collect --dry-run sans réseau — erreur propre par source, pas de plantage" 60 "$vm" collect --dry-run

  # fixtures rejouées par un stub local : le vrai code de collecte (pagination, mapping, filtres) tourne
  if ! start_server vm-stub "stub local des API BOAMP / TED / DECP (tests/fixtures, port $stub)" "http://127.0.0.1:$stub/health" \
       "$PY" "$ROOT/scripts/smoke_vm_stub.py" "$fixtures" "$stub"; then
    skip "vm collect / score / digest / brief / stats / web" "stub indisponible"
    return 0
  fi
  stub_pid=$SERVER_PID; stub_log=$STEP_LOG
  export BOAMP_BASE_URL="http://127.0.0.1:$stub/boamp" TED_BASE_URL="http://127.0.0.1:$stub/ted" DECP_BASE_URL="http://127.0.0.1:$stub/decp"
  EXPECT='boamp .*à insérer \(dry-run\)'
  step vm-collect-dry "vm collect --dry-run — fixtures BOAMP, TED, DECP affichées, rien n'est écrit" 60 "$vm" collect --dry-run
  EXPECT='boamp .*nouveaux'
  step vm-collect "vm collect — avis et attributions enregistrés dans la base temporaire" 60 "$vm" collect
  EXPECT='avis scorés.*dry-run'
  step vm-score-dry "vm score --dry-run — règles + LLM mock, rien n'est enregistré" 60 "$vm" score --dry-run
  EXPECT='avis scorés'
  step vm-score "vm score — résumés et scores enregistrés" 60 "$vm" score
  EXPECT='smoke@exemple\.fr : [0-9]+ avis'
  step vm-digest-dry "vm digest --dry-run — digest de l'abonné affiché, aucun email" 60 "$vm" digest --dry-run
  EXPECT='attribution'
  step vm-brief-dry "vm brief-weekly --dry-run --all-plans — brief DECP affiché, aucun email" 60 "$vm" brief-weekly --dry-run --all-plans
  EXPECT='abonnés : 1 actifs'
  step vm-stats "vm stats — compteurs et dernières collectes" 60 "$vm" stats

  if start_server vm-web "vm web — site d'inscription démarré sur 127.0.0.1:$port (GET /health → 200)" \
       "http://127.0.0.1:$port/health" "$vm" web --host 127.0.0.1 --port "$port"; then
    web_pid=$SERVER_PID; web_log=$STEP_LOG
    check vm-web-root "GET / → 200 (page d'offre avec l'exemple d'alerte)" http_is 200 "http://127.0.0.1:$port/"
    check vm-web-exemple "GET /exemple → 200 (email complet)" http_is 200 "http://127.0.0.1:$port/exemple"
    stop_server "$web_pid" "vm web — arrêt propre (SIGTERM)" "$web_log"
  fi
  stop_server "$stub_pid" "stub BOAMP / TED / DECP — arrêt" "$stub_log"
}

# ---- content-engine --------------------------------------------------------------------------------
smoke_ce() {
  local app="$ROOT/apps/content-engine" dir="$SMOKE_DIR/content-engine" ce draft
  ce="$app/.venv/bin/ce"
  section "content-engine (ce)"
  mkdir -p "$dir/data" "$dir/out"
  clear_app_env; STEP_CWD="$app"
  export DATA_DIR="$dir/data" OUT_DIR="$dir/out" TTS_PROVIDER="$TTS" VIDEO_PRESET=veryfast
  if [ "$TTS" = silent ]; then export TTS_SILENT_DURATION_S=8; fi    # vidéo courte (8 s) : le test reste rapide

  EXPECT='LLM : mock'
  step ce-doctor "ce doctor — ffmpeg, police, voix ($TTS), LLM mock, clés absentes = dry-run" 60 "$ce" doctor
  EXPECT='sujets'
  step ce-init "ce init — base et banque de sujets (topics.yaml)" 60 "$ce" init
  EXPECT='Brouillons créés'
  step ce-script "ce script --topic-id 1 -f short — 3 variantes par le LLM mock" 120 "$ce" script --topic-id 1 -f short
  draft=$(sed -n 's/.*Brouillons créés : #\([0-9][0-9]*\).*/\1/p' "$STEP_LOG" | head -1)
  [ -n "$draft" ] || draft=1
  EXPECT='approuvé'
  step ce-approve "ce approve $draft — approbation du premier brouillon" 60 "$ce" approve "$draft"
  EXPECT='rendu'
  step ce-render "ce render --draft-id $draft — short vertical (TTS $TTS + ffmpeg + sous-titres)" 600 "$ce" render --draft-id "$draft"
  check ce-video "out/$draft/video.mp4 : 1080×1920, piste audio, durée > 0 (ffprobe)" video_ok "$dir/out/$draft/video.mp4"
  EXPECT='Dry-run youtube'
  step ce-publish "ce publish --platform youtube — dry-run, aucun envoi" 60 "$ce" publish --draft-id "$draft" --platform youtube
  check ce-publish-json "out/$draft/publish-youtube.json : JSON valide, dry_run=true" publish_json_ok "$dir/out/$draft/publish-youtube.json"
  check ce-publish-secret "out/$draft/publish-youtube.json : aucun jeton ni clé en clair" no_secret_in "$dir/out/$draft/publish-youtube.json"
  EXPECT='créneau'
  step ce-plan "ce plan --days 1 — calendrier de publication" 60 "$ce" plan --days 1
  EXPECT='Relecture écrite'
  step ce-export-review "ce export-review — fichier de relecture du matin" 60 "$ce" export-review
  check ce-review-file "out/review-AAAA-MM-JJ.md écrit" first_file_exists "$dir/out" 'review-*.md'
}

# ---- newsletter-pipeline ---------------------------------------------------------------------------
smoke_np() {
  local app="$ROOT/apps/newsletter-pipeline" dir="$SMOKE_DIR/newsletter-pipeline" np fixtures
  np="$app/.venv/bin/np"; fixtures="$app/tests/fixtures"
  section "newsletter-pipeline (np)"
  mkdir -p "$dir/data" "$dir/issues" "$dir/out"
  clear_app_env; STEP_CWD="$app"
  # sources.yaml de fumée : les flux RSS/Atom des tests, lus en local (aucune des 39 vraies sources)
  cat > "$dir/sources.yaml" <<YAML
# Sources du test de fumée : fichiers locaux des tests, aucun réseau.
defaults:
  lang: fr
  weight: 1.0
sources:
  - name: Éditeur test (fixture locale)
    url: "$fixtures/feed_editeur.xml"
    kind: rss
    category: editeurs
    weight: 0.9
  - name: Institution test (fixture locale)
    url: "$fixtures/feed_institution.atom"
    kind: rss
    category: institutions
    weight: 1.2
YAML
  export DATA_DIR="$dir/data" ISSUES_DIR="$dir/issues" OUT_DIR="$dir/out" SOURCES_FILE="$dir/sources.yaml" \
         SPONSOR_FILE="$dir/sponsor.yaml" REQUEST_DELAY_S=0 MAX_ITEM_AGE_DAYS=0 MAX_PER_SOURCE=4

  EXPECT='2 sources'
  step np-sources "np sources — 2 flux locaux (RSS + Atom) synchronisés dans la base temporaire" 60 "$np" sources
  EXPECT='0 source\(s\) en erreur'
  step np-collect-dry "np collect --dry-run — lecture des flux, rien n'est écrit" 60 "$np" collect --dry-run
  EXPECT='[1-9][0-9]* nouveaux items'
  step np-collect "np collect — items stockés" 60 "$np" collect
  EXPECT='Classement :'
  step np-rank "np rank — classement par le LLM mock" 120 "$np" rank
  if grep -Eq 'Classement : 0 items' "$STEP_LOG"; then
    note "np rank : 0 item noté avec LLM_PROVIDER=mock (le MockLLM générique répond {}) — voir scripts/SMOKE-FINDINGS.md"
  fi
  run_logged np-draft 120 "$np" draft --issue 1
  if [ "$STEP_RC" = 0 ] && ! grep -q 'Traceback (most recent call last)' "$STEP_LOG"; then
    ok "np draft --issue 1 — brouillon du numéro 1 (markdown, HTML, texte)"
    EXPECT='push-file'
    step np-push "np push --issue 1 --target file — HTML à coller, dry-run" 60 "$np" push --issue 1 --target file
    check np-push-file "out/push-file-001.html écrit" first_file_exists "$dir/out" 'push-file-*.html'
  elif grep -q 'aucun item classé' "$STEP_LOG"; then
    skip "np draft --issue 1" "refus propre « aucun item classé disponible » : le fournisseur mock ne note aucun item"
    skip "np push --issue 1 --target file" "pas de numéro à pousser (dépend de np draft)"
  else
    fail "np draft --issue 1 — brouillon du numéro 1" "code de sortie $STEP_RC"
  fi
  EXPECT='Items :'
  step np-stats "np stats — items par source, numéros produits" 60 "$np" stats
}

# ---- avis-clients ----------------------------------------------------------------------------------
smoke_avis() {
  local app="$ROOT/apps/avis-clients" dir="$SMOKE_DIR/avis-clients" avis port slug web_pid web_log
  avis="$app/.venv/bin/avis"
  section "avis-clients (avis)"
  mkdir -p "$dir/data" "$dir/reports"
  clear_app_env; STEP_CWD="$app"
  port=$(free_port)
  export DATA_DIR="$dir/data" DB_PATH="$dir/data/avis-clients.db" APP_BASE_URL="http://127.0.0.1:$port"

  EXPECT='Base prête'
  step avis-init-db "avis init-db — base et migrations" 60 "$avis" init-db
  EXPECT='page /r/'
  step avis-demo "avis demo — compte démo, établissement, avis de fixtures (Google, Facebook, Tripadvisor mock), alertes console" 120 "$avis" demo
  slug=$(sed -n 's#.*page /r/\([^[:space:]]*\).*#\1#p' "$STEP_LOG" | head -1)
  [ -n "$slug" ] || slug=boulangerie-dupont
  EXPECT='"establishments"'
  step avis-poll "avis poll-reviews — relecture des avis mock (brouillons, alertes)" 120 "$avis" poll-reviews
  EXPECT='status=dry-run'
  step avis-report "avis monthly-report --dry-run — rapport HTML rendu, non envoyé" 120 "$avis" monthly-report --dry-run --out "$dir/reports"
  check avis-report-file "rapport HTML écrit dans reports/" first_file_exists "$dir/reports" 'rapport-*.html'

  if start_server avis-web "avis serve — serveur web démarré sur 127.0.0.1:$port (GET /healthz → 200)" \
       "http://127.0.0.1:$port/healthz" "$avis" serve --host 127.0.0.1 --port "$port"; then
    web_pid=$SERVER_PID; web_log=$STEP_LOG
    check avis-web-root "GET / → 200 (landing)" http_is 200 "http://127.0.0.1:$port/"
    check avis-web-slug "GET /r/$slug → 200 (page publique d'avis de la démo)" http_is 200 "http://127.0.0.1:$port/r/$slug"
    stop_server "$web_pid" "avis serve — arrêt propre (SIGTERM)" "$web_log"
  fi
}

for app in $APPS; do
  case "$app" in
    vm) smoke_vm ;;
    ce) smoke_ce ;;
    np) smoke_np ;;
    avis) smoke_avis ;;
  esac
done
clear_app_env

# ---- résumé ----------------------------------------------------------------------------------------
TOTAL=$(( $(date +%s) - STARTED_AT ))
printf '\n%sRésumé :%s %d étapes — %s%d ok%s, %s%d échec(s)%s, %d ignorée(s) · durée totale %s\n' \
  "$C_BOLD" "$C_END" $(( OK_N + FAIL_N + SKIP_N )) "$C_OK" "$OK_N" "$C_END" "$C_KO" "$FAIL_N" "$C_END" "$SKIP_N" "$(fmt_secs "$TOTAL")"
if [ -n "$NOTES" ]; then
  printf '%s' "$NOTES" | sed 's/^/  · /'
fi
if [ "$FAIL_N" -gt 0 ]; then
  printf '%s' "$FAILED" | sed "s/^/  ${C_KO}✘${C_END} /"
  printf 'journaux et données conservés : %s\n' "$SMOKE_DIR"
  exit 1
fi
if [ "$KEEP" = 1 ] || [ -n "${SMOKE_DIR_KEEP:-}" ]; then
  printf 'tout est vert. Dossier conservé : %s (vidéo : content-engine/out/<id>/video.mp4, journaux : logs/)\n' "$SMOKE_DIR"
else
  rm -rf "$SMOKE_DIR"
  printf 'tout est vert. Dossier temporaire supprimé (--keep pour garder rendus et journaux).\n'
fi
