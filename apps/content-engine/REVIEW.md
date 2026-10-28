# Revue croisée QA-1 — `apps/content-engine`

Date : 28 octobre 2026. Périmètre : uniquement ce dossier. Méthode : lecture complète du code, des
templates `deploy/macmini` et des tests ; pour chaque défaut, un test qui le met en évidence, puis la
correction ; aucune dépendance ajoutée, architecture inchangée.

| | Avant | Après |
|---|---|---|
| `pytest -q` | 41 verts | **57 verts** (16 tests ajoutés, 1 test découpé en deux) |
| `ruff check .` | propre | propre |

Échelle : **critique** = contenu publié incorrect ou surface d'injection ; **élevée** = défaillance
du flux nominal (routine, calendrier, publication) ; **moyenne** = robustesse ou qualité avec
contournement ; **faible** = cosmétique, documentation, code mort.

Bilan : 1 critique, 9 élevées, 9 moyennes, 4 faibles (23 défauts corrigés).

## Critique

1. **`drawtext` interprète les textes du LLM.** Sans `expansion=none`, un « % » dans un titre, un
   CTA ou la marque (« Pourquoi 80 % des avis… ») déclenche « Stray % » : ffmpeg sort en code 0 et
   **n'écrit aucun texte** dans l'image (vérifié : 0 pixel de texte) ; `%{localtime}`, `%{eif:…}`
   et les antislashs seraient développés dans la vidéo. Le contrôle « chiffre sans source » n'est
   pas bloquant, donc un tel titre approuvé donnait une vidéo sans titre, publiable.
   `src/content_engine/render/video.py:102` → `expansion=none` sur chaque `drawtext`.
   Tests : `test_render.py::test_drawtext_keeps_percent_and_never_expands` (pixels du titre),
   assertion `expansion=none` dans `test_render_short_three_seconds`.

## Élevée

2. **Visibilité TikTok non verrouillée.** `TIKTOK_PRIVACY_LEVEL` était une chaîne libre et rien
   n'empêchait `PUBLIC_TO_EVERYONE` avant l'audit Content Posting.
   `settings.py:70-91` (Literal + `TIKTOK_APP_AUDITED=false` + `tiktok_effective_privacy`),
   `publish/tiktok.py:38,64` (valeur forcée, note dans le JSON, `audit_required` exact).
   Tests : `test_publish.py::test_tiktok_privacy_forced_to_self_only_until_audit`,
   `test_settings_guards_privacy_and_disclosure` (valeurs TikTok/YouTube invalides refusées,
   `private` par défaut).
3. **Étiquette IA, lien et hashtags tronqués** quand le texte du LLM est long : `truncate()` coupait
   la fin des descriptions (Pinterest 800, TikTok 2 200, YouTube 5 000, LinkedIn 3 000), c'est-à-dire
   l'étiquette « Contenu créé avec l'aide d'IA ». Une `AI_DISCLOSURE` vide dans `.env` supprimait
   aussi l'étiquette. `texts.py:27` (`join_within` : la tête est sacrifiée, jamais la queue),
   `settings.py:80` (repli sur le défaut). Test :
   `test_publish.py::test_disclosure_link_and_hashtags_survive_long_llm_texts`.
4. **Contrôle « chiffre sans source » contournable.** La description (publiée telle quelle) n'était
   pas contrôlée ; le mot « ressource » valait une source ; « pour cent », « 9 clients sur 10 »,
   « 3x plus », « 2500€ », `$`, « milliards » passaient. `scripts.py:111-152` (regex étendue,
   `SOURCE_RE` exige « Source : », description incluse). Test :
   `test_scripts.py::test_number_check_is_not_bypassed_by_wording_or_field`.
5. **Bascule dry-run → `--live` inopérante.** Une publication simulée comptait comme un envoi : un
   brouillon passé en dry-run (le job launchd tourne toutes les 30 min) n'était plus jamais candidat
   en `--live` sur cette plateforme ; la routine décrite dans le README ne publiait donc rien.
   `planning.py:130` (`candidate_draft(live=…)` : en live, seules les publications réelles
   comptent). Idempotence vérifiée : deux passages `--live` → un seul envoi. Test :
   `test_planning.py::test_live_run_publishes_drafts_only_simulated_before_and_is_idempotent`.
6. **Calendrier et fuseau.** `run_publish(now=…)` comparait l'heure reçue (UTC possible) aux
   créneaux locaux sans la convertir ; l'ancienneté d'un créneau était une soustraction d'heures
   murales (faux de 1 h au changement d'heure) ; un créneau dont la publication réelle échoue (jeton
   absent…) était retenté indéfiniment. `planning.py:46,54,176,192` (`as_local`, `slot_age` en UTC,
   `skipped` avec motif après 24 h). Tests :
   `test_run_publish_normalizes_timezone_and_gives_up_on_stale_failures`,
   `test_slot_age_counts_real_elapsed_time_across_dst_change`.
7. **Timings des sous-titres.** Dans `proportional_segments`, le plancher de 0,6 s par phrase
   faisait déborder la somme : derniers segments avec fin < début (invisibles) et phrase précédente
   coupée. `render/subtitles.py:52` (plancher puis remise à l'échelle : somme exacte, dernière fin =
   durée, aucun chevauchement). Test : `test_render.py::test_proportional_segments_sum_and_no_overlap`.
8. **Schéma JSON sans bornes.** `hook`, `cta`, `title`, `description`, entrées de `body`, nombre
   d'entrées et longueur des hashtags étaient illimités ; un objet à la place d'un texte devenait
   `str(dict)`. `scripts.py:40-100` (longueurs maximales, types, hashtags ≤ 30 caractères,
   `duration_s` borné) ; budget de 400 caractères de tags YouTube (`publish/youtube.py:27`).
   Test : `test_scripts.py::test_payload_bounds_reject_oversized_or_mistyped_fields`.
9. **Coupure réseau pendant un envoi `--live`** : exception `httpx` non gérée → `run-publish`
   plantait et les créneaux suivants n'étaient pas traités. `publish/__init__.py:141`
   (→ `PublishError`, rien n'est journalisé, le créneau est retenté). Test :
   `test_publish.py::test_live_network_error_is_a_publish_error_and_leaves_no_trace`.
10. **OAuth YouTube sous launchd.** Sans jeton valide, `run_local_server` attendait un navigateur
    sans fin dans un job sans terminal ; un jeton révoqué (`RefreshError`) donnait une trace brute.
    `publish/youtube.py:50,62` (erreur lisible si pas de TTY, consentement à faire une fois à la
    main). Non testé ici : `google-auth-oauthlib` est un extra non installé.

## Moyenne

11. **Injection de prompt par les sujets.** Les questions (manuelles ou générées par le LLM) n'avaient
    pas de longueur maximale et étaient réinjectées telles quelles dans `ideas_prompt` (jusqu'à 80)
    et `script_prompt`, où « » servent de délimiteurs. `topics.py:17-18` (300 caractères, idées entre
    12 et 200, entrées non-objet ignorées), `prompts.py:70` (`clean_question`). Test :
    `test_topics.py::test_question_length_bounds_and_prompt_sanitizing`.
12. **Une variante hors schéma condamnait le sujet** : exception après 1 ou 2 brouillons déjà
    écrits et sujet laissé `new`, donc rescripté le lendemain (doublons). `scripts.py:45,209,222`
    (`ScriptSchemaError` : la variante est abandonnée, les autres continuent ; le sujet est marqué
    `used` dès qu'un brouillon existe ; une erreur de transport remonte toujours). Test :
    `test_scripts.py::test_schema_failure_drops_only_that_variant`.
13. **Barre de progression statique.** `drawbox` n'évalue `t` qu'une fois sur ffmpeg < 7 (6.1 ici :
    barre pleine dès la première image). `render/video.py:223,259` (bande `color` + `overlay`
    animé, toutes versions). Test : mesure de la barre à 0,1 s et 2,8 s dans
    `test_render_short_three_seconds`.
14. **Import CSV fragile.** `splitlines()` cassait les titres multi-lignes entre guillemets ; une
    ligne avec une colonne en trop levait `AttributeError` (`restkey` liste) ; UTF-8 seul (cp1252 ou
    UTF-16 → plantage) ; `csv.Sniffer` sur des titres pleins de virgules ; lignes sans identifiant ni
    titre dupliquées à chaque import ; `--platform` ni validé ni normalisé ; liaison par titre ratant
    les titres tronqués à 100 et les légendes TikTok. `metrics.py:141-237`. Test :
    `test_metrics.py::test_read_csv_tolerates_excel_exports`.
15. **Déficits et formats de `run-daily`.** `format_deficits` comptait les brouillons déjà envoyés
    (en dry-run prolongé, tout finissait en `short`) ; les formats étaient attribués aux sujets dans
    l'ordre, d'où des posts LinkedIn pour `avis`, produit sans créneau LinkedIn. `planning.py:243,309`
    (`pair_topics_with_formats`, qui réutilise `platform_for_format` jusque-là mort). Test :
    `test_planning.py::test_format_deficits_ignore_consumed_drafts_and_formats_follow_products`.
16. **Messages de rendu.** ffmpeg absent n'était détecté qu'après la synthèse vocale ; un `FONT_PATH`
    pointant vers un fichier absent était ignoré en silence ; sans aucune police, l'erreur ffmpeg
    était brute ; la durée finale n'était pas revérifiée après encodage. `render/video.py:300,463,
    470,494`. Test : `test_render.py::test_render_rejects_long_narration_missing_font_and_absent_ffmpeg`.
17. **`ce angles` avec peu de données** recommandait « à décliner / à revoir » dès un contenu par
    angle. `metrics.py:18`, `cli.py:483` (seuil de 3 contenus). Test : `test_cli.py` (« Trop peu de
    données »).
18. **CLI.** Disque plein ou base verrouillée → trace Python (`OSError`, `sqlite3.Error` hors du
    garde) ; `ce render --approved` s'arrêtait au premier brouillon en échec ; `--angle` inconnu
    accepté en silence ; « Statuts : … » n'affichait jamais « aucun » (précédence). `cli.py:43,137,
    195,278`. Test : `test_cli.py` (angle inconnu).
19. **YouTube refuse `<` et `>`** dans titre et description (`invalidTitle`). `texts.py:45`
    (`youtube_safe`). Test : dans `test_disclosure_link_and_hashtags_survive_long_llm_texts`.

## Faible

20. `say` sans délai : une phrase bloquée figeait le job launchd. `tts/say.py:34` (180 s).
21. Pinterest : `open()` jamais fermé. `publish/pinterest.py:77`.
22. Nom de police contenant une virgule → ligne `Style:` ASS invalide. `render/subtitles.py:99`
    (test dans `test_write_ass_and_srt`).
23. Documentation et code mort : README à 06:30 et plists inline divergents de `deploy/macmini`
    (05:30 `run-daily`, `run-publish` toutes les 30 min via `run.sh`) ; « le motif nourrit les
    prochains scripts » (README, aide CLI, export de relecture) alors que rien ne le réinjecte ;
    section « Juridique » inexistante citée par `assets/README.md` ; nombre de tests ; sémantique
    dry-run / live ; `.env.example` (`TIKTOK_APP_AUDITED`) ; suppression de `get_settings`,
    `FORMAT_LABELS`, `load_render_info` (jamais référencés) et de deux lignes mortes dans
    `test_render.py`.

## Vérifié sans correction nécessaire

- Aucune publication sans `--live` explicite (`publish_draft(live=False)` par défaut, CLI et
  `run-publish`) ; statut `published` posé seulement par un envoi réel.
- Secrets : en-têtes `Authorization` / `xi-api-key` masqués dans `out/<id>/publish-*.json` (vérifié
  aussi dans le JSON écrit avant un envoi réel en échec) ; aucun jeton dans `render.json`,
  `ffmpeg-command.txt`, `publications.response_json` ni dans les messages d'erreur affichés.
- `containsSyntheticMedia` / `is_aigc` vrais dès que la voix ou l'image sont synthétiques, et vrais
  par défaut sans `render.json` ; `selfDeclaredMadeForKids` faux ; `YOUTUBE_PRIVACY_STATUS` est un
  Literal, `private` par défaut.
- `subprocess` toujours en liste, jamais `shell=True` ; textes `drawtext` passés par `textfile=` et
  chemins relatifs dans `out/<id>/` ; échappement ASS (`\`, `{`, `}`, retours à la ligne) ; noms de
  fichiers dérivés d'identifiants entiers, de plateformes validées ou de dates parsées ; écritures
  limitées à `out/`, `data/` (jeton OAuth) et au dossier de rendu (copie de la police).
- Durée ≤ `VIDEO_MAX_SECONDS` : refus avant rendu si la narration dépasse, `-t` à l'encodage, et
  désormais revérification après encodage.
- Migrations rejouables (`IF NOT EXISTS`, table `schema_migrations`) ; démarrage sans `.env` ;
  `.env.example` complet.

## À faire plus tard

- `redact()` laisse les 4 premiers caractères d'un jeton dans les JSON de dry-run (lisibilité) : à
  masquer entièrement si ces fichiers sont partagés.
- Limite YouTube de la description : 5 000 **octets** (les accents comptent double) ; on tronque en
  caractères. Idem titre : 100 caractères mais l'API compte des points de code.
- Envoi partiel (YouTube : init ok puis upload en échec ; TikTok : init ok puis statut) : le créneau
  est retenté au passage suivant, donc doublon possible côté plateforme. Journaliser l'étape d'init
  (`Location`, `publish_id`) pour reprendre plutôt que recommencer.
- TikTok : `publish_id` n'est pas l'identifiant de la vidéo publiée ; interroger `status/fetch`
  jusqu'à `PUBLISH_COMPLETE` et stocker `publicaly_available_post_id` pour lier les métriques par
  identifiant (aujourd'hui la liaison TikTok ne marche que par accroche).
- `run_daily` avec Ollama arrêté : jusqu'à deux appels (délai 180 s chacun) par variante avant
  abandon ; sonder le LLM une fois au début de la routine et s'arrêter proprement.
- `export_review` et `run_daily` datent les fichiers avec `date.today()` (horloge système) et non
  `TIMEZONE` ; sans effet sur le Mac mini réglé à Paris.
- Motif de rejet : conservé en base mais jamais réinjecté dans les prompts suivants (promesse
  retirée de l'aide ; à implémenter si utile).
- Accroche en plusieurs phrases : seule la première est en couleur d'accent dans les sous-titres.
- `madeForKids` est envoyé en plus de `selfDeclaredMadeForKids` (ignoré par l'API en insertion).
- Les années (« 2024 ») déclenchent l'alerte « chiffre sans source » (faux positif assumé, l'alerte
  n'est pas bloquante).
- Non testables dans ce bac à sable : `say` (macOS), flux OAuth YouTube (extra non installé),
  Kokoro.
