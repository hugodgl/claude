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
      ce metrics --import export.csv ──► metrics ──► ce angles (angles qui performent)
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
.venv/bin/pytest -q          # 57 tests, dont un rendu vidéo de 3 s vérifié par ffprobe
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
| `PINTEREST_ACCESS_TOKEN`, `PINTEREST_BOARD_ID` | API v5 | — |
| `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_AUTHOR_URN`, `LINKEDIN_VERSION` | Posts API, en-tête de version AAAAMM | `202510` |
| `TIKTOK_ACCESS_TOKEN`, `TIKTOK_PRIVACY_LEVEL`, `TIKTOK_APP_AUDITED` | Content Posting API ; tant que `TIKTOK_APP_AUDITED` est faux (app non auditée), la visibilité envoyée est forcée à `SELF_ONLY` quelle que soit `TIKTOK_PRIVACY_LEVEL` | `SELF_ONLY`, `false` |
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
| `ce run-daily` | idées si la banque < 20 par produit → scripts pour 5 sujets (formats selon les déficits du calendrier, 2 shorts minimum) → export de relecture |
| `ce run-publish [--live] [--no-render]` | rend les brouillons approuvés, puis publie les créneaux échus qui ont un brouillon prêt (dry-run : simulation journalisée ; `--live` : seules les publications réelles comptent, voir « Décisions ») |
| `ce metrics --import export.csv [--platform youtube\|tiktok]` · `ce angles [--list]` | boucle de sélection des angles |
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
4. Le soir ou la nuit : exporter les CSV de YouTube Studio / TikTok Studio, `ce metrics --import`,
   `ce angles` pour décliner les angles qui marchent et abandonner les autres.

## Planification launchd

Les services sont définis dans `deploy/macmini/launchd/` et installés par
`deploy/macmini/install-launchd.sh` (chaque job passe par `deploy/macmini/run.sh`, qui se place dans
`apps/content-engine`, charge `.env` et journalise dans `logs/content-engine-ce.log`) :

| Service | Quand | Commande |
|---|---|---|
| `com.sideproject.content.daily` | 05:30 | `ce run-daily` |
| `com.sideproject.content.publish` | toutes les 30 minutes (`StartInterval` 1800) | `ce run-publish` (ajouter `--live` dans le plist quand les clés sont en place et les premiers dry-run relus) |

`ce plan --days 7` se lance le dimanche (à la main ou en troisième plist). Sous launchd il n'y a pas
de terminal : le consentement OAuth YouTube (première publication réelle) doit être fait une fois à
la main dans un terminal, le job refuse proprement tant que le jeton n'existe pas.

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
  (titre, titre tronqué à 100 caractères, accroche) ; `ce angles` classe les angles par vues
  moyennes et ne recommande rien sous 3 contenus mesurés par angle.

## Ce qui est simulé ou non vérifié depuis le sandbox

- Aucun appel réseau réel : YouTube, Pinterest, LinkedIn et TikTok sont écrits d'après la
  documentation d'octobre 2026 et testés avec `httpx.MockTransport` (payloads, en-têtes, flux
  d'envoi reprenable YouTube, init + upload + statut TikTok). Les premières publications réelles
  sont à relire dans les JSON de dry-run avant `--live`.
- `say` n'existe pas dans le sandbox : l'adaptateur est écrit d'après la commande macOS
  (`say -v Thomas -r 175 -o x.aiff -f texte.txt`) et testé seulement via le chemin commun de
  concaténation (test ElevenLabs simulé). Kokoro n'est pas testé (dépendance optionnelle).
- L'OAuth YouTube (`google-auth-oauthlib`, consentement dans le navigateur, jeton dans
  `data/youtube-token.json`) n'est pas exécuté ici.
- Les miniatures sont fonctionnelles mais sobres (texte sur dégradé) : remplacer `thumb.jpg` par
  un visuel Canva avant publication si besoin.
- Pas de mode « ta voix enregistrée » : déposer un `voice.m4a` dans `out/<id>/` n'est pas encore
  pris en compte (prochaine étape avec P4-4).

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
routine quotidienne, import de métriques (cp1252, UTF-16, titres multi-lignes), CLI via `CliRunner`.
Voir `REVIEW.md` pour la revue croisée (défauts corrigés et reste à faire).
