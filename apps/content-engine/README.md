# content-engine — moteur de contenu du plan 4

Produit chaque jour, sur le Mac mini, des contenus courts et utiles (Shorts YouTube, TikTok,
épingles Pinterest, posts LinkedIn) qui répondent aux questions que tapent les prospects des trois
produits du projet, avec **15 minutes de validation humaine le matin** et zéro publication sans
relecture. Tout est en **dry-run** tant qu'aucune clé n'est fournie et que `--live` n'est pas passé.

```
topics.yaml ──► topics ──► ce script ──► drafts (3 variantes) ──► ce review / approve
                 ▲                                                       │
            ce ideas (LLM)                                               ▼
                                                   ce render (TTS + ffmpeg) ──► out/<id>/video.mp4
                                                                                   cover.jpg, thumb.jpg
                                                                                         │
      ce plan ──► schedule ──► ce run-publish ──► ce publish --platform … ──► out/<id>/publish-<plateforme>.json
                                                                        (--live : appel API réel)
      ce metrics --pull (API, 23:30) ─┐
      ce metrics --import export.csv ─┴► metrics (relevés datés) ──► ce angles (score par angle)
                                                                         │
                                        ce run-daily ◄── angles privilégiés / exploration / en pause
```

| Produit (`product`) | Ligne éditoriale | Formats privilégiés |
|---|---|---|
| `avis` | plus de clients pour ton commerce (avis Google) — tutoiement | Short, TikTok, Pin |
| `marches` | les marchés publics sans jargon (espaces verts, artisans) — vouvoiement | LinkedIn, Short, TikTok, Pin |
| `cabinets` | l'IA concrète en cabinet d'expertise comptable — vouvoiement | LinkedIn, Short, Pin |

La ligne éditoriale (promesse, public, ton, CTA, palette de couleurs) est dans
`src/content_engine/products.py` ; les questions d'amorçage dans `topics.yaml`.

## Installation

### Dans le sandbox ou sur Linux (tests)

```bash
cd apps/content-engine
uv venv .venv && uv pip install -e ../../packages/core -e ".[dev]"
.venv/bin/pytest -q          # 73 tests, dont un rendu vidéo de 3 s vérifié par ffprobe
.venv/bin/ruff check .
```

Pré-requis : Python 3.11+, `ffmpeg` et `ffprobe` dans le PATH (le rendu est testé avec ffmpeg 6.1,
libx264, libass, libfreetype). Sans ffmpeg, les tests de rendu sont ignorés.

### Sur le Mac mini

```bash
brew install ffmpeg uv            # ffmpeg Homebrew : libx264, libass, fontconfig inclus
cd apps/content-engine
uv venv .venv && uv pip install -e ../../packages/core -e ".[dev]"
cp .env.example .env              # puis compléter (voir Configuration)
say -v '?' | grep fr_             # voix françaises disponibles : Thomas, Amélie, Audrey…
.venv/bin/ce doctor               # ffmpeg, police, voix, LLM, clés
.venv/bin/ce init                 # crée data/content-engine.db et charge topics.yaml
```

Premier rendu réel : `ce script --topic-id 1`, `ce approve <id>`, `ce render --draft-id <id>` puis
ouvrir `out/<id>/video.mp4`. Avec `TTS_PROVIDER=say`, la voix macOS (Thomas par défaut) est
synthétisée phrase par phrase, ce qui donne des sous-titres parfaitement synchronisés.

Extras optionnels : `uv pip install -e ".[youtube]"` (OAuth Google pour la publication réelle),
`uv pip install -e ".[kokoro]"` (voix locale Kokoro : télécharger `kokoro-v1.0.onnx` et
`voices-v1.0.bin` dans `data/`, voix française `ff_siwis`).

## Configuration (`.env`)

Toutes les variables sont dans `.env.example`. Les plus importantes :

| Variable | Rôle | Défaut |
|---|---|---|
| `LLM_PROVIDER`, `OLLAMA_MODEL` | modèle (socle commun) ; `mock` = simulateur hors ligne | `ollama`, `qwen3:14b` |
| `TTS_PROVIDER` | `say` (macOS), `kokoro`, `elevenlabs`, `silent` | `say` |
| `SAY_VOICE`, `SAY_RATE` | voix et débit de `say` | `Thomas`, `175` |
| `BRAND_NAME` | handle affiché en bas des vidéos et images | `@moncompte` |
| `LANDING_URL_AVIS/MARCHES/CABINETS` | pages de capture par produit (dans les descriptions) | `https://example.com/…` |
| `AI_DISCLOSURE` | étiquette ajoutée à chaque description / légende (une valeur vide est remplacée par le défaut ; jamais tronquée, même si le texte du LLM est long) | « Contenu créé avec l'aide d'IA, relu par un humain. » |
| `VIDEO_CODEC`, `VIDEO_PRESET`, `VIDEO_CRF`, `VIDEO_MAX_SECONDS` | encodage (`h264_videotoolbox` sur Mac pour aller plus vite) | `libx264`, `medium`, `20`, `60` |
| `FONT_PATH` | police (DejaVu Sans Bold détectée seule sur Linux ; Arial/Helvetica sur Mac) ; si la variable pointe vers un fichier absent, le rendu refuse avec un message clair | détection automatique |
| `ASSETS_DIR`, `ASSETS_SYNTHETIC` | images de fond `assets/<produit>.jpg` ; sont-elles générées par IA ? | `assets`, `true` |
| `YOUTUBE_CLIENT_SECRETS_FILE`, `YOUTUBE_TOKEN_FILE`, `YOUTUBE_PRIVACY_STATUS` | OAuth « application de bureau », jeton dans `data/`, visibilité | `private` |
| `YOUTUBE_ANALYTICS` | demander aussi la portée `yt-analytics.readonly` au consentement (rétention et partages dans `ce metrics --pull`) | `true` |
| `PINTEREST_ACCESS_TOKEN`, `PINTEREST_BOARD_ID` | API v5 | — |
| `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_AUTHOR_URN`, `LINKEDIN_VERSION` | Posts API, en-tête de version AAAAMM | `202510` |
| `TIKTOK_ACCESS_TOKEN`, `TIKTOK_PRIVACY_LEVEL`, `TIKTOK_APP_AUDITED` | Content Posting API ; tant que `TIKTOK_APP_AUDITED` est faux (app non auditée), la visibilité envoyée est forcée à `SELF_ONLY` quelle que soit `TIKTOK_PRIVACY_LEVEL` | `SELF_ONLY`, `false` |
| `ANGLE_EXPLORATION_RATE`, `ANGLE_PRIOR_WEIGHT`, `ANGLE_PAUSE_MIN_CONTENTS`, `ANGLE_PAUSE_RATIO` | sélection des angles dans `ce run-daily` (voir « Métriques et angles ») | `0.3`, `5`, `6`, `0.5` |
| `DATA_DIR`, `OUT_DIR`, `TIMEZONE` | base SQLite et jetons / rendus et exports / heure des créneaux | `data`, `out`, `Europe/Paris` |

Aucune clé n'est nécessaire pour dérouler la chaîne complète en dry-run.

## Commandes `ce`

| Commande | Effet |
|---|---|
| `ce init` | migrations + chargement de `topics.yaml` (idempotent) |
| `ce topics [-p produit] [--status new]` · `ce add-topic "question" -p produit [--angle …]` | banque de sujets |
| `ce ideas -p produit -n 10` | nouvelles questions via LLM (JSON), dédoublonnées (clé normalisée + similarité) |
| `ce script --topic-id N [-f short\|long\|linkedin\|pin]` | 3 variantes (`hook`, `body`, `cta`, `title`, `description`, `hashtags`, `duration_s`) + contrôles automatiques |
| `ce review` · `ce show ID` · `ce approve ID…` · `ce reject ID --reason "…"` | file de validation |
| `ce export-review [--date AAAA-MM-JJ]` | `out/review-AAAA-MM-JJ.md` pour la relecture du matin |
| `ce render --draft-id N` / `ce render --approved` / `--force` (aperçu) | short : `video.mp4` 1080×1920 30 fps ≤ 60 s + `cover.jpg` + `thumb.jpg` ; pin et long : images + `script.txt` ; linkedin : `post.txt` |
| `ce publish --draft-id N --platform youtube\|pinterest\|linkedin\|tiktok [--live]` | dry-run : `out/N/publish-<plateforme>.json` décrit exactement la requête ; `--live` : envoi réel |
| `ce plan --days 7 [--start AAAA-MM-JJ]` · `ce schedule` | calendrier : 1 short/jour (YouTube 12:00), 1 TikTok/jour (18:00), 5 pins/jour (9h-17h), LinkedIn lun/mer/ven 8:30, long YouTube le jeudi 17:00, rotation des produits |
| `ce run-daily` | scores des angles (pause automatique des angles qui ne marchent pas) → idées si la banque < 20 par produit → scripts pour 5 sujets choisis à 70 % sur les angles privilégiés et 30 % en exploration (formats selon les déficits du calendrier, 2 shorts minimum) → export de relecture |
| `ce run-publish [--live] [--no-render]` | rend les brouillons approuvés, puis publie les créneaux échus qui ont un brouillon prêt (dry-run : simulation journalisée ; `--live` : seules les publications réelles comptent, voir « Décisions ») |
| `ce metrics --pull [--platform youtube\|pinterest\|tiktok\|linkedin\|all] [--days 90] [--dry-run]` | relève les métriques des publications réelles via les API et les historise (un relevé daté par contenu et par jour) |
| `ce metrics --import export.csv [--platform youtube\|tiktok]` | import d'un export CSV (YouTube Studio, TikTok Studio) |
| `ce angles [-p produit] [--explain]` · `ce angles --pause ANGLE [-p produit]` · `ce angles --reactivate ANGLE [-p produit]` · `ce angles --list` | score par angle (vues normalisées par plateforme et par âge, lissées), statut privilégié / à explorer / en pause, explication du calcul, pause et réactivation manuelles |
| `ce doctor` | diagnostic (ffmpeg, police, `say`, LLM, clés) |

Codes de sortie : 0 ok, 1 erreur métier lisible (sujet introuvable, brouillon non approuvé, fichier
absent, clé manquante…).

## La routine du matin en 15 minutes

1. 05:30 (launchd, voir `deploy/macmini`) : `ce run-daily` a tourné → `out/review-<date>.md` contient les brouillons du jour,
   avec pour chacun le sujet, l'angle, l'accroche, le corps, le CTA, la description, la durée
   estimée et les **alertes** (chiffre sans source, mots anglais, trop long, mauvais nombre de
   parties, titre trop long…).
2. Lire le fichier (ou `ce review`), choisir une variante par sujet : `ce approve 12 15 18`,
   `ce reject 13 --reason "trop générique"`. Corriger un texte : éditer le JSON du brouillon n'est pas
   prévu, on rejette et on relance `ce script` ; le motif de rejet reste en base (`ce show ID`), il
   n'est pas encore réinjecté dans les prompts.
3. `ce render --approved` (environ 20 à 40 s par short sur un Mac mini M-series avec `say`), regarder
   une vidéo sur deux, puis `ce run-publish` (dry-run : vérifier les JSON) et, quand les clés sont
   en place, passer le job launchd en `--live` : un brouillon seulement simulé en dry-run est alors
   publié pour de bon à son prochain créneau (la simulation ne compte pas comme un envoi).
4. 23:30 (launchd) : `ce metrics --pull` relève les vues, j'aime, commentaires, partages,
   impressions, clics et rétention des publications réelles ; le lendemain, `ce run-daily` s'en
   sert pour choisir les sujets (angles qui marchent, part d'exploration) et mettre en pause les
   angles qui ne marchent pas. `ce angles --explain` montre le calcul ; TikTok avant audit et
   LinkedIn ne sont pas relevables : exporter les CSV des Studios et `ce metrics --import`.

## Planification launchd

Les services sont définis dans `deploy/macmini/launchd/` et installés par
`deploy/macmini/install-launchd.sh` (chaque job passe par `deploy/macmini/run.sh`, qui se place dans
`apps/content-engine`, charge `.env` et journalise dans `logs/content-engine-ce.log`) :

| Service | Quand | Commande |
|---|---|---|
| `com.sideproject.content.daily` | 05:30 | `ce run-daily` |
| `com.sideproject.content.publish` | toutes les 30 minutes (`StartInterval` 1800) | `ce run-publish` (ajouter `--live` dans le plist quand les clés sont en place et les premiers dry-run relus) |
| `com.sideproject.content.metrics` | 23:30 | `ce metrics --pull` (relevé quotidien des métriques des publications réelles ; gabarit `com.sideproject.content.metrics.plist.tmpl`, installé par `install-launchd.sh`) |

Le job de métriques n'a besoin d'aucun terminal : il réutilise le jeton YouTube déjà consenti
(`data/youtube-token.json`, qui doit porter `youtube.readonly` : voir « Métriques et angles ») et
les jetons Pinterest / TikTok du `.env` ; sans publication réelle il se termine en code 0 sans
rien écrire, et `ce run-daily` du lendemain (05:30) tolère l'absence totale de métriques
(comportement inchangé dans ce cas). Son code de sortie est 1 seulement si toutes les plateformes
tentées ont échoué (visible dans `logs/content-engine-ce.log`).

`ce plan --days 7` se lance le dimanche (à la main ou en plist supplémentaire). Sous launchd il n'y a pas
de terminal : le consentement OAuth YouTube (première publication réelle) doit être fait une fois à
la main dans un terminal, le job refuse proprement tant que le jeton n'existe pas.

## Métriques et angles

### Relevé (`ce metrics --pull`)

Pour chaque publication réelle (`publications.dry_run = 0`, identifiant distant connu, brouillon
`published`) des `--days` derniers jours (90 par défaut), l'adaptateur de la plateforme interroge
son API et le relevé est ajouté à la table `metrics` avec sa date (`measured_at`, `source = 'api'`) :
un relevé par contenu et par jour, relancer le même jour met à jour le relevé du jour, les jours
précédents sont conservés (historique). Les classements n'utilisent que le dernier relevé de chaque
contenu. `--dry-run` affiche le tableau sans rien écrire ; les erreurs (réseau, quota, jeton) sont
isolées par plateforme : les autres continuent, le message est affiché, et `ce metrics --pull`
sort en code 1 seulement si toutes les plateformes tentées ont échoué.

| Plateforme | Appel | Stocké | Portée / condition |
|---|---|---|---|
| YouTube | `videos.list?part=statistics,contentDetails&id=…` (Data API v3, 50 vidéos par appel, 1 unité de quota) ; en option `reports.query` (YouTube Analytics API v2 : `ids=channel==MINE`, `dimensions=video`, `filters=video==…`, `metrics=views,estimatedMinutesWatched,averageViewPercentage,shares`, fenêtre `--days`) | vues, j'aime, commentaires ; partages, rétention moyenne (`avg_view_pct`) et heures vues si Analytics | jeton OAuth du publisher : `youtube.readonly` obligatoire (vidéos privées), `yt-analytics.readonly` optionnel : sans lui, Analytics est ignoré avec une note |
| Pinterest | `GET /v5/pins/{pin_id}/analytics?start_date&end_date&metric_types=IMPRESSION,PIN_CLICK,OUTBOUND_CLICK,SAVE` (un appel par épingle, fenêtre bornée à 90 jours) | `views` = `impressions` = IMPRESSION (une épingle n'a pas de vues), `clicks` = OUTBOUND_CLICK, `shares` = SAVE, `ctr` = clics sortants / impressions, PIN_CLICK dans `extra_json` ; métriques « lifetime » si l'API les renvoie, sinon cumul de la fenêtre | `PINTEREST_ACCESS_TOKEN` avec la portée `pins:read` ; une épingle supprimée ou trop récente (HTTP 4xx) est notée, les autres continuent |
| TikTok | `POST /v2/post/publish/status/fetch/` pour résoudre le `publish_id` en identifiant public (`publicaly_available_post_id`, gardé dans `publications.post_id`), puis `POST /v2/video/query/?fields=id,like_count,comment_count,share_count,view_count` (20 vidéos par appel) | vues, j'aime, commentaires, partages | portée `video.list` ; **tant que `TIKTOK_APP_AUDITED=false`, la source journalise « non disponible » sans erreur** (Display API réservée aux apps auditées) |
| LinkedIn | aucun : stub documenté | rien | les statistiques de posts (`organizationalEntityShareStatistics`, `memberCreatorPostAnalytics`) sont réservées à la Marketing API (programme partenaire) : la source journalise « non disponible » |

Un jeton YouTube consenti avant P4-4 ne porte que `youtube.upload` : `ce metrics --pull` le refuse
avec un message clair ; supprimer `data/youtube-token.json` et relancer une publication `--live`
dans un terminal pour reconsentir (`ce doctor` affiche les portées du jeton). La rétention et les
partages YouTube sont calculés sur la fenêtre `--days` (Analytics a 2 à 3 jours de retard) ; les
vues, j'aime et commentaires sont les compteurs à vie de `videos.list`.

### Score des angles (`ce angles`, `ce run-daily`)

Le score d'un angle, par produit, est calculé dans `src/content_engine/angles.py` :

1. **Âge** : les vues s'accumulent vite puis saturent ; chaque contenu est ramené à des vues
   « projetées » en divisant par `1 − exp(−âge / 7 jours)` (63 % des vues à 7 jours, 95 % à
   21 jours). Un relevé de moins de 2 jours est trop précoce : signalé, pas compté.
2. **Plateforme** : `x = log2(projetées + 1) − médiane de la plateforme` (tous produits). 5 000
   impressions Pinterest et 300 vues YouTube valent toutes deux 0 si c'est la médiane de leur
   plateforme ; +1 = deux fois la médiane, −1 = la moitié. Une plateforme avec un seul contenu ne
   donne aucune information (x = 0).
3. **Petits effectifs** : lissage bayésien `score = (n × moyenne + k × a priori) / (n + k)`, avec
   `a priori` = moyenne des x du produit et `k = ANGLE_PRIOR_WEIGHT` (5). Un angle vu 2 fois à
   2,3× la médiane ne dépasse que de peu un angle vu 20 fois à 1,2× ; il ne l'écrase pas.
4. **Décision** par produit : les angles dont le score est ≥ la médiane des scores du produit
   sont **privilégiés** (inclusif : avec un ou deux angles mesurés, ils le sont tous), les autres
   sont **à explorer**. Un angle mesuré sur ≥ `ANGLE_PAUSE_MIN_CONTENTS` (6) contenus et à plus de
   `log2(1 / ANGLE_PAUSE_RATIO)` (1, soit des vues lissées sous 50 % de l'angle médian) sous la
   médiane est **mis en pause** (`angle_status`) : ses sujets attendent, le LLM ne le propose plus
   dans les idées. Il est réactivé automatiquement s'il remonte à mi-chemin du seuil, ou à la main
   (`ce angles --reactivate ANGLE -p PRODUIT`, auquel cas il n'est remis en pause qu'après 6
   nouveaux contenus mesurés). `ce angles --pause` met en pause à la main (jamais levée
   automatiquement). `ANGLE_PAUSE_RATIO=0` désactive la pause automatique. Avec seulement deux
   angles mesurés, la médiane est à mi-chemin : il faut un écart lissé de 4× pour une pause, ce
   qui est voulu (on ne met pas la moitié des angles en pause sur si peu de données).

`ce run-daily` : les sujets du jour sont pris, produit par produit et par ancienneté, à
`1 − ANGLE_EXPLORATION_RATE` (70 %) sur les angles privilégiés (« exploitation ») et
`ANGLE_EXPLORATION_RATE` (30 %) sur les autres angles, y compris sans angle (« exploration ») ; un
produit sans métriques garde le comportement historique (« ancienneté »). Sans aucune métrique,
rien ne change. `ce angles --explain` détaille chaque angle : contenus par plateforme, écart brut,
a priori, score lissé, médiane du produit, seuil de pause, statut et date.

Limites : les épingles n'ont pas de vues (impressions utilisées) ; LinkedIn n'est pas mesuré ;
TikTok ne l'est qu'après audit ; un contenu mesuré par CSV (lié par titre) compte avec l'âge du
CSV s'il donne la date de publication, sinon comme un contenu mûr ; les scores sont relatifs à la
médiane de chaque plateforme, pas des valeurs absolues de performance.

## Règles des plateformes (résumé, état octobre 2026, à vérifier sur les pages officielles)

- **YouTube** : contenu « inauthentique » (templaté, produit à la chaîne, sans apport d'auteur)
  démonétisé ; voix synthétique sur script original acceptée ; étiquetage du contenu synthétique
  obligatoire → `status.containsSyntheticMedia` est vrai dès que la voix ou l'image sont générées,
  `selfDeclaredMadeForKids` faux. Seuils Partner Program : 500 abonnés + 3 000 h (ou 3 M de vues
  Shorts / 90 j) pour le premier palier, 1 000 abonnés + 4 000 h (ou 10 M de vues Shorts) pour le
  palier complet ; relèvement annoncé au 1er février 2027. Première vidéo publiée en `private`
  (vérifier, puis `YOUTUBE_PRIVACY_STATUS=public`). Miniature personnalisée : chaîne vérifiée par téléphone.
- **TikTok** : label IA obligatoire (`post_info.is_aigc`), originalité exigée (un compte entièrement
  synthétique est exclu de Creator Rewards et bridé) : prévoir ta voix et ton visage sur une partie
  des contenus. Content Posting API : l'app doit passer l'audit ; avant, `SELF_ONLY` uniquement
  (forcé par le code tant que `TIKTOK_APP_AUDITED=false`).
  Creator Rewards : 18 ans, 10 000 abonnés, 100 000 vues / 30 j, vidéos > 1 min.
- **Pinterest** : pas de monétisation directe ; la programmation massive et répétitive déclenche
  le filtre anti-spam → 5 épingles/jour maximum, titres et descriptions distincts (les 3 variantes
  servent à ça), mention « lien affilié » en tête de description si affiliation.
- **LinkedIn** : pas de règle IA, mais le contenu générique est ignoré ; un cas d'usage par post,
  150 à 220 mots, hashtags cliquables via la syntaxe `{hashtag|\#|mot}`, en-tête `LinkedIn-Version`
  à rafraîchir tous les ~6 mois.
- **Partout** : étiquette « Contenu créé avec l'aide d'IA, relu par un humain. » dans chaque
  description, sources citées dès qu'un chiffre apparaît, jamais de personne réelle, musique et
  images libres de droits ou générées (AI Act art. 50 pour le synthétique).

## Décisions prises (à discuter si besoin)

- **3 appels LLM par sujet** (une variante par appel, avec une approche imposée : méthode directe /
  erreur fréquente / cas concret) plutôt qu'un seul JSON de 3 variantes : plus robuste avec un modèle
  local 14B, variantes réellement différentes, relance ciblée en cas de JSON invalide ou de schéma
  non respecté (une relance, puis erreur).
- **Garde-fous** dans le system prompt (français, pas de chiffre non sourcé, pas de personne réelle,
  pas de promesse, pas de « tendance IA ») + validation stricte du JSON (types, longueurs maximales :
  400 caractères pour l'accroche et le CTA, 200 pour le titre, 12 entrées de corps, hashtags de
  30 caractères au plus ; une variante hors schéma après relance est abandonnée sans condamner les
  autres) + contrôles automatiques stockés dans `payload_json.checks` et affichés à la relecture
  (chiffre, pourcentage — y compris « pour cent », « 9 sur 10 », « 3x » — ou montant sans
  « Source : » explicite dans la description, description comprise) ; ils alertent, ils ne bloquent
  pas : rien n'est rendu ni publié sans `ce approve`. Les sujets (y compris ceux générés par le LLM)
  sont bornés à 300 caractères et nettoyés avant d'être réinjectés dans un prompt.
- **Mode `mock` utilisable** : `LLM_PROVIDER=mock` branche un simulateur déterministe (idées et
  scripts plausibles) sur `core.llm.MockLLM`, ce qui permet de tester toute la chaîne sans Ollama.
- **TTS phrase par phrase** (`say`, Kokoro, ElevenLabs) puis concaténation ffmpeg avec 0,3 s de
  pause : timings exacts des sous-titres sans dépendre d'un alignement fourni par le TTS. Repli
  proportionnel à la longueur des phrases si un adaptateur ne renvoie pas de timings.
- **Rendu** : une seule commande ffmpeg lancée dans `out/<id>/` avec des chemins relatifs et les
  textes passés par fichiers (`textfile=`, `expansion=none` : un « % » ou un `%{…}` venu du LLM n'est
  jamais interprété), fond dégradé animé par produit (`gradients`) ou image `assets/<produit>.jpg`
  assombrie, titre en haut (`drawtext`), sous-titres ASS centrés (accroche en couleur d'accent),
  encart CTA à partir de la phrase de CTA, barre de progression (overlay animé, évalué à chaque
  image quelle que soit la version de ffmpeg), handle en bas. La police est copiée dans le dossier
  de rendu ; la durée du fichier final est revérifiée après encodage (≤ `VIDEO_MAX_SECONDS`). `cover.jpg` (1080×1920, Pinterest) et `thumb.jpg` (1280×720, YouTube)
  sont composés par ffmpeg aussi (pas de Pillow).
- **Formats non vidéo** : `pin` → image seule ; `long` → plan en 5 parties + `script.txt`
  téléprompteur + miniature (la vidéo longue reste humaine : copier le fichier enregistré sous
  `out/<id>/video.mp4` avant `ce publish --platform youtube`) ; `linkedin` → `post.txt`.
- **Dry-run réaliste** : chaque publication (dry-run ou réelle) est journalisée dans `publications`.
  En dry-run, un brouillon déjà simulé sur une plateforme n'est pas réassigné à un autre créneau de
  cette plateforme (le calendrier simulé reste fidèle) ; en `--live`, seules les publications
  réelles comptent : un brouillon seulement simulé la veille est publié pour de bon à son prochain
  créneau, et un brouillon déjà publié pour de bon n'est jamais renvoyé (sauf `ce publish --force`).
  Un short peut servir YouTube **et** TikTok. Le statut `published` n'est posé que par un envoi
  réel. Les secrets sont masqués dans les JSON ; une coupure réseau pendant un envoi est une erreur
  métier (créneau retenté au passage suivant), pas un plantage.
- **Calendrier** : créneaux en heure locale (`TIMEZONE`), uniques par (heure, plateforme, format) ;
  l'heure courante est toujours ramenée dans ce fuseau et l'ancienneté d'un créneau est calculée en
  UTC (changement d'heure sans effet). Un créneau échu sans brouillon prêt, ou dont la publication
  échoue à chaque passage, attend 24 h puis passe en `skipped` avec le motif. Les formats de
  `run-daily` sont attribués à des sujets dont le produit est servi sur la plateforme visée (pas de
  post LinkedIn pour `avis`).
- **Métriques** : import tolérant des exports CSV (en-têtes FR/EN de YouTube Studio et TikTok,
  séparateurs `,` `;` `\t`, encodages UTF-8 / UTF-16 / cp1252, titres multi-lignes entre guillemets,
  nombres « 1 234 » / « 12,5 »), ligne « Total » et lignes sans identifiant ni titre ignorées,
  liaison aux brouillons par identifiant distant (publications réelles) ou par titre normalisé
  (titre, titre tronqué à 100 caractères, accroche) ; un réimport CSV remplace les lignes CSV du
  même contenu sans toucher à l'historique API. `ce angles` ne recommande rien sous 3 contenus
  mesurés par angle.
- **Historique des relevés** (P4-4) : `metrics` est un journal daté (`measured_at`, `source`
  csv/api) ; les classements et scores regardent le dernier relevé de chaque contenu par
  plateforme. Les adaptateurs de relevé (`src/content_engine/pull/`) suivent le même contrat que
  les publishers : une source par plateforme, erreurs confinées, stubs explicites quand l'API
  n'est pas accessible (TikTok avant audit, LinkedIn). Le jeton YouTube demande désormais
  `youtube.upload` + `youtube.readonly` (+ `yt-analytics.readonly` si `YOUTUBE_ANALYTICS`) au
  consentement, et chaque opération vérifie les portées enregistrées dans le jeton.
- **Sélection des angles** (P4-4) : score relatif (log2 par rapport à la médiane de la
  plateforme, âge corrigé) plutôt que vues brutes, lissage bayésien vers la moyenne du produit
  plutôt qu'un seuil dur, médiane inclusive pour décider qui est privilégié, pause seulement
  « nettement » sous la médiane et après assez de contenus, part d'exploration déterministe
  (3 sujets sur 10 avec 30 %) plutôt que tirée au sort, pour des routines reproductibles.

## Ce qui est simulé ou non vérifié depuis le sandbox

- Aucun appel réseau réel : YouTube, Pinterest, LinkedIn et TikTok sont écrits d'après la
  documentation d'octobre 2026 et testés avec `httpx.MockTransport` (payloads, en-têtes, flux
  d'envoi reprenable YouTube, init + upload + statut TikTok). Les premières publications réelles
  sont à relire dans les JSON de dry-run avant `--live`.
- Les relevés de métriques (`videos.list`, `reports.query`, `pins/{id}/analytics`,
  `video/query`, `status/fetch`) sont eux aussi écrits d'après la documentation et testés sur des
  réponses simulées réalistes ; la forme exacte des réponses (clé `all.lifetime_metrics` de
  Pinterest, `columnHeaders` d'Analytics) est à vérifier au premier relevé réel avec
  `ce metrics --pull --dry-run`.
- `say` n'existe pas dans le sandbox : l'adaptateur est écrit d'après la commande macOS
  (`say -v Thomas -r 175 -o x.aiff -f texte.txt`) et testé seulement via le chemin commun de
  concaténation (test ElevenLabs simulé). Kokoro n'est pas testé (dépendance optionnelle).
- L'OAuth YouTube (`google-auth-oauthlib`, consentement dans le navigateur, jeton dans
  `data/youtube-token.json`) n'est pas exécuté ici.
- Les miniatures sont fonctionnelles mais sobres (texte sur dégradé) : remplacer `thumb.jpg` par
  un visuel Canva avant publication si besoin.
- Pas de mode « ta voix enregistrée » : déposer un `voice.m4a` dans `out/<id>/` n'est pas encore
  pris en compte (à planifier).

## Tests

`.venv/bin/pytest -q` : banque de sujets (amorçage, doublons, idées, bornes et nettoyage des
questions), scripts (3 variantes, formats, contrôles de chiffres non contournables, bornes du schéma,
relance puis abandon d'une seule variante), file de validation et export markdown, découpage et
timings des sous-titres (somme exacte, aucun chevauchement), **rendu d'un short de 3 s vérifié par
ffprobe** (1080×1920, 30 fps, piste audio, barre de progression animée, `expansion=none`), titre
avec « % » bien dessiné, refus clairs (narration trop longue, `FONT_PATH` absent, ffmpeg absent),
formats pin/long/linkedin, adaptateur ElevenLabs simulé, publication dry-run des quatre plateformes
(fichiers JSON, drapeaux `containsSyntheticMedia` / `is_aigc`, `SELF_ONLY` forcé avant audit,
masquage des secrets, étiquette IA jamais tronquée) et envois réels simulés (y compris coupure
réseau), calendrier, `run-publish` dry-run puis `--live` idempotent, fuseau et changement d'heure,
routine quotidienne, import de métriques (cp1252, UTF-16, titres multi-lignes), relevé des
métriques via les API (réponses simulées YouTube Data + Analytics, Pinterest, TikTok avec
résolution du `publish_id`, stubs TikTok avant audit et LinkedIn, historique daté, réimport CSV
sans perte, erreurs réseau et quota isolées par plateforme, dry-run), score des angles (formules,
petits effectifs, normalisation plateforme et âge, pause / réactivation automatiques et manuelles,
exploitation / exploration, `run-daily` avec et sans métriques), CLI via `CliRunner`.
Voir `REVIEW.md` pour la revue croisée (défauts corrigés et reste à faire).
