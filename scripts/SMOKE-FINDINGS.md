# Constats du test de fumée (`scripts/smoke.sh`)

Dernière exécution : 28/10/2026 01:45 (Paris), sandbox Linux, branche `claude/upbeat-davinci-lk5k7m` (commit `3c4695b`),
`LLM_PROVIDER=mock`, `TTS_PROVIDER=silent` (pas de `say` sous Linux). **44 étapes : 42 ok, 0 échec, 2 ignorées, 29 s.**
Relancer : `make smoke` (ou `scripts/smoke.sh --keep vm ce np avis` pour garder rendus et journaux).

Ce fichier liste ce que le test a révélé **dans les apps** (il ne corrige rien : chaque point est à traiter dans l'app
concernée) et ce qu'il ne couvre pas.

## Limites et défauts d'app constatés

### 1. newsletter-pipeline — `LLM_PROVIDER=mock` ne permet pas d'aller au-delà de la collecte
- Commandes (sur deux flux locaux, 12 items) : `np rank` → `Classement : 0 items notés en 3 lot(s) (0 lot(s) en échec,
  12 item(s) sans réponse).` puis `np draft --issue 1` → `Erreur : aucun item classé disponible : lance `np collect` puis
  `np rank`` (code 1). `np push`, `np render`, `np linkedin` sont donc inaccessibles hors ligne.
- Cause : `core.llm.get_llm()` (`packages/core/src/core/llm.py`) renvoie un `MockLLM()` dont la réponse par défaut est `{}` ;
  `parse_rank_response({})` (`apps/newsletter-pipeline/src/newsletter_pipeline/rank.py`) n'y trouve aucun item.
  content-engine a résolu le même problème avec un répondeur déterministe (`apps/content-engine/src/content_engine/llm.py`,
  `FakeResponder` branché sur `MockLLM`) ; les tests de newsletter-pipeline ont déjà un équivalent
  (`tests/conftest.py::scripted_response`) qui n'est pas exposé à la CLI.
- Conséquence pour le smoke : `np draft --issue 1` et `np push --issue 1 --target file` sont marqués « ignorés » (refus
  propre, sans traceback). Le script les rejouera automatiquement le jour où `np draft` passe en mode mock.

### 2. veille-marches — en mode `mock`, un résumé vide est compté « avec LLM »
- `vm score` : `71/100 (LLM, règles 80) BOAMP 26-145201 …`, `5 avis scorés, 4 avec LLM` ; le digest affiche
  `Résumé : Résumé indisponible.` et `Avis de l'assistant : peut-etre`.
- Cause : `summarize()` (`apps/veille-marches/src/veille_marches/scoring.py`) valide `{}` comme `LLMSummary` (verdict par
  défaut `peut-etre`), ne remplace que `resume` par le repli et renvoie `llm_used=True` : `llm_provider=mock` est écrit en
  base et le verdict neutre pèse 30 % du score final. Non bloquant, mais un vrai modèle qui répondrait `{}` serait traité
  de la même façon (compté comme résumé LLM, jamais repris au passage suivant). Piste : traiter une réponse sans `resume`
  ni `verdict` comme un repli (`llm_used=False`), et/ou brancher un simulateur mock comme content-engine.

### 3. veille-marches — pas de mode fixtures pour `vm collect`
- Sans réseau, `vm collect --dry-run` se termine proprement (`boamp  ERREUR : boamp : erreur réseau — [Errno 111]
  Connection refused`, idem TED et DECP, code 1), mais rien ne permet de rejouer `tests/fixtures/` depuis la CLI.
- Le smoke contourne avec `scripts/smoke_vm_stub.py` : un serveur HTTP local (bibliothèque standard) qui renvoie
  `boamp_records.json`, `ted_search.json` et `decp_records.json` aux chemins attendus, dates décalées pour rester
  « d'actualité », et `BOAMP_BASE_URL` / `TED_BASE_URL` / `DECP_BASE_URL` pointées dessus. Une option
  `vm collect --fixtures DIR` rendrait ce stub inutile. Suggestion, pas un bug.

### 4. veille-marches — `DATA_DIR` ne pilote ni la base ni les aperçus
- `VMSettings` (`apps/veille-marches/src/veille_marches/settings.py`) garde `db_path = data/veille-marches.db` et
  `out_dir = data/out` indépendants de `data_dir` : avec `DATA_DIR=/tmp/x`, `vm stats` lit toujours
  `apps/veille-marches/data/veille-marches.db` (vérifié : `data_dir=/tmp/nulle-part | db_path=data/veille-marches.db`).
  Les trois autres apps dérivent leurs chemins de `DATA_DIR`. Le smoke règle donc `DB_PATH` et `OUT_DIR` explicitement.
  Incohérence de configuration (documentée dans `.env.example`), pas un bug fonctionnel.

### 5. content-engine — sortie de `ce doctor` repliée à 80 colonnes hors terminal (cosmétique)
- Quand stdout n'est pas un terminal (journal, `grep`), rich coupe les chemins sur plusieurs lignes :
  `base : ⏎ /tmp/…/ ⏎ content-engine/data/content-engine.db`. Un `Console(soft_wrap=True)` (ou une largeur fixe) pour
  les lignes qui contiennent des chemins rendrait les journaux launchd lisibles d'un `grep`.

## Choix du smoke qui s'écartent de la configuration de production

Tout se passe dans un dossier `mktemp -d` (`DATA_DIR`, `DB_PATH`, `OUT_DIR`, `ISSUES_DIR`, bases SQLite, rendus),
les `.env` des apps sont lus mais surchargés par l'environnement :
`LLM_PROVIDER=mock`, `MAIL_PROVIDER=console`, `SMS_PROVIDER=dry-run`, `GBP_MODE=mock`, `FACEBOOK_MODE=mock`,
`TRIPADVISOR_MODE=mock` ; veille-marches : `HTTP_TIMEOUT_S=5`, URLs des trois API vers le stub local (ou un port fermé
pour le cas « sans réseau ») ; content-engine : `TTS_PROVIDER=say` si la voix configurée est installée sinon `silent`
avec `TTS_SILENT_DURATION_S=8` (vidéo de 8 s), `VIDEO_PRESET=veryfast` ; newsletter-pipeline : `sources.yaml` dédié
(deux flux locaux des tests), `REQUEST_DELAY_S=0`, `MAX_ITEM_AGE_DAYS=0`, `MAX_PER_SOURCE=4` ; avis-clients :
`APP_BASE_URL` = l'adresse du serveur de test.

## Ce que le smoke ne couvre pas (et pourquoi)

- Les API réelles (BOAMP, TED, DECP, Google Business Profile, beehiiv, Stripe, smsmode/Twilio, YouTube…) : hors ligne par
  construction ; le premier appel réel reste la procédure du README de chaque app (`vm collect --limit 20`, etc.).
- `np draft` / `np render` / `np push` / `np linkedin` / `np run-monday` : bloqués par le point 1 tant que le mode mock
  n'a pas de simulateur ; les 39 vraies sources de `sources.yaml` ne sont pas lues (réseau).
- La voix macOS `say` et `h264_videotoolbox` : non testables depuis le sandbox ; sur le Mac mini, le smoke bascule sur
  `say` dès que `say -v '?'` liste la voix (`SAY_VOICE`, défaut `Thomas`), sinon il le signale et rend en `silent`.
- Les parcours web avec écriture (inscription + Stripe Checkout simulé de `vm web`, connexion par lien magique et boîte
  de réception HTMX d'avis-clients) : seules les pages GET publiques et les routes de santé sont vérifiées.
- Les services launchd (`install-launchd.sh`), `ce run-daily` / `ce run-publish`, `vm brief-weekly --send`,
  `avis monthly-report` sans `--dry-run` : pas d'envoi ni de planification dans un test de fumée.
