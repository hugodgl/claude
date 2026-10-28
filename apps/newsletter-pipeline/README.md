# newsletter-pipeline — « L'IA en cabinet »

Pipeline semi-automatisé de la newsletter hebdomadaire **« l'IA pour les cabinets d'expertise comptable »** (plan 3). Le Mac mini collecte les sources le lundi à 5 h, classe les articles avec un modèle local, rédige un brouillon complet du numéro ; Hugo le relit en 45 minutes, le signe, et l'envoi part le mardi à 7 h depuis beehiiv (ou Kessel).

```
sources.yaml ──► np collect ──► items (SQLite) ──► np rank ──► np draft ──► issues/NNN-date.{md,html,txt}
                                                                              │
                                                     relecture d'Hugo (markdown) ──► np push (beehiiv | kessel | file)
                                                                              └──► np linkedin (3 posts)
```

## Ce qui est fait et ce qui est simulé

| Brique | État |
|---|---|
| Collecte RSS/Atom (feedparser) et pages (httpx + trafilatura), réponses lues en flux et plafonnées (`MAX_PAGE_BYTES`), dédoublonnage URL canonique (utm/xtor/at_… retirés, http/https et www confondus) + titre normalisé, délai entre requêtes, erreurs isolées par source et par article | fonctionne ; testé sur fixtures locales et transport httpx simulé (aucun flux n'a pu être appelé depuis le sandbox) |
| Classement LLM par lots, score pondéré, garde-fou injection, sorties bornées | fonctionne avec `MockLLM` ; à valider avec `qwen3:14b` sur le Mac mini |
| Sélection diversifiée (8 items, 2 max par thème, 3 max par source) | fonctionne |
| Brouillon complet (3 appels LLM courts) + rendu markdown, HTML email, texte ; URL du modèle vérifiées contre les items, chiffre vérifié dans l'item cité, HTML brut échappé | fonctionne ; replis `[À COMPLÉTER]` / `[À VÉRIFIER]` si le modèle répond mal |
| Push beehiiv API v2 | requête construite et testée sur transport simulé ; **jamais envoyée** (dry-run par défaut) ; champ `body_content` à confirmer sur la doc beehiiv au premier essai réel |
| Push Kessel | pas d'API publique connue : marche à suivre copier-coller |
| Posts LinkedIn | fonctionne (LLM), contrôle de longueur avec une relance |
| `np run-monday` | enchaîne collect → rank → draft, compte rendu en fin de log, code de sortie 1 seulement si le brouillon n'est pas produit ; relancé le même lundi, ne crée pas un second numéro pour le même mardi |

## Installation

```bash
cd apps/newsletter-pipeline
uv venv .venv && uv pip install -e ../../packages/core -e ".[dev]"
cp .env.example .env            # puis adapter
.venv/bin/pytest -q             # 90+ tests, sans réseau (tout transport httpx réel échoue)
.venv/bin/np --help
```

Prérequis sur le Mac mini : Ollama lancé avec le modèle de `.env` (`ollama pull qwen3:14b`). Dans les tests, `LLM_PROVIDER=mock`.

## Configuration

Tout passe par `.env` (voir `.env.example`, commenté). Les réglages héritent du socle (`LLM_PROVIDER`, `OLLAMA_*`, `ANTHROPIC_*`, `DATA_DIR`) et ajoutent :

- identité : `NEWSLETTER_NAME`, `NEWSLETTER_TAGLINE`, `AUTHOR_NAME`, `AUTHOR_SIGNATURE`, `REPLY_TO_EMAIL`, `ARCHIVE_URL` ;
- fichiers : `SOURCES_FILE` (défaut `sources.yaml`), `STYLE_FILE` (`style.md`), `CASES_DIR` (`cases/`), `SPONSOR_FILE` (`sponsor.yaml`), `ISSUES_DIR`, `OUT_DIR`, base SQLite dans `DATA_DIR/newsletter.db` ;
- collecte : `REQUEST_DELAY_S` (1,5 s), `HTTP_TIMEOUT_S`, `USER_AGENT`, `MAX_LINKS_PER_PAGE` (8 articles inconnus téléchargés par passage), `RSS_FETCH_PAGES` (false), `MAX_CONTENT_CHARS` (20 000 caractères stockés par item), `MAX_PAGE_BYTES` (5 000 000 octets par réponse HTTP) ;
- classement : `RANK_BATCH_SIZE` (5 items par appel), `RANK_MAX_CHARS`, `RANK_DEFAULT_LIMIT` (60 items par passage quand `--limit` est absent), `WEIGHT_PERTINENCE` / `WEIGHT_ACTIONNABLE` / `WEIGHT_NOUVEAUTE` (0,5 / 0,3 / 0,2) ;
- sélection : `ISSUE_ITEMS` (8), `MAX_PER_THEME` (2), `MAX_PER_SOURCE` (3), `MAX_ITEM_AGE_DAYS` (14, 0 = désactivé) ;
- push : `BEEHIIV_API_KEY`, `BEEHIIV_PUBLICATION_ID`, `BEEHIIV_BASE_URL`, `BEEHIIV_CONTENT_TAGS`, `KESSEL_PUBLICATION_URL`.

Les chemins relatifs sont résolus depuis `apps/newsletter-pipeline` (le lanceur launchd s'y place).

## Commandes

| Commande | Rôle |
|---|---|
| `np sources` | synchronise `sources.yaml` dans la base et liste les sources (`--no-sync` pour lire seulement) |
| `np collect [--source NAME] [--dry-run]` | collecte RSS/pages, dédoublonne, stocke les items `new` ; `--dry-run` affiche ce qui serait inséré |
| `np rank [--limit N]` | note les items `new` non classés par lots de `RANK_BATCH_SIZE` |
| `np draft --issue N [--date AAAA-MM-JJ] [--case SLUG] [--force]` | sélectionne 8 items, génère `issues/NNN-date.md`, `.html`, `.txt` ; date par défaut : mardi suivant |
| `np render --issue N` | régénère HTML et texte **depuis le markdown relu** (titre H1 et aperçu compris, la base est alignée) |
| `np push --issue N --target beehiiv\|kessel\|file [--live]` | dry-run par défaut : écrit `out/push-<cible>-NNN.json` avec la requête exacte |
| `np linkedin --issue N` | 3 posts LinkedIn dans `out/linkedin-NNN.md` |
| `np stats` | items par source, taux de sélection, thèmes, numéros produits |
| `np run-monday [--issue N] [--date …] [--limit N]` | routine du lundi : collect → rank → draft (numéro = dernier + 1 ; sans `--issue`, un brouillon déjà produit pour la date est signalé, pas doublé) |

Le **markdown est la source de vérité** : Hugo le corrige, puis `np render` ou `np push` reconstruisent le HTML et le texte. Le titre (H1) et l'aperçu (première citation `>` sous le titre) du markdown relu font foi : ils sont repris dans le HTML, dans la requête beehiiv (`title`, `preview_text`) et dans la base. Le HTML brut éventuellement présent dans le markdown est échappé, pas interprété : seuls le markdown, les blocs de code et les liens `http(s)`/`mailto` passent dans l'email (pas de `<script>`, `<iframe>`, `onclick`, `javascript:`). Le HTML est un template email simple (620 px, lisible sur mobile, styles inline + `<style>`), suffisant pour beehiiv qui applique ensuite sa propre mise en forme.

## Routine du lundi

| Heure | Quoi | Qui |
|---|---|---|
| lundi 05:00 | `np run-monday` : collecte de toutes les sources actives, classement, brouillon du numéro N+1 daté du mardi | launchd (`com.sideproject.newsletter.monday`) |
| lundi 05:30 | classement (inclus dans run-monday ; `np rank` seul pour relancer) | |
| lundi 06:00 | brouillon prêt dans `issues/` (inclus ; `np draft --issue N --force` pour regénérer) | |
| lundi matin | **relecture 45 min** : réécrire l'édito (marqué `[À RELIRE]`), vérifier chaque fait et chaque lien, remplacer la question de lecteur, compléter le chiffre ou l'outil s'ils sont en `[À …]`, puis `np push --issue N` (brouillon beehiiv) ou `np push --issue N --target file` et copier-coller | Hugo |
| lundi midi | `np linkedin --issue N`, programmer 3 posts (mardi, jeudi, vendredi) | Hugo |
| mardi 07:00 | envoi programmé dans beehiiv/Kessel (pas depuis cette app) | plateforme |
| mercredi | relance aux non-ouvreurs avec un autre objet (réglage de la plateforme) | plateforme |

Le compte rendu de `run-monday` est la dernière ligne du log (`logs/newsletter-pipeline-np.log` via `deploy/macmini/run.sh`) :
`Compte rendu : 37 items collectés (2 source(s) en erreur), 37 items classés, brouillon : issues/004-2026-11-24.md (…)`.
Code de sortie 1 seulement si aucun brouillon n'a pu être produit (par exemple aucun item classé). Relancé le même lundi sans `--issue`, il ne crée pas de second numéro pour le même mardi : il signale le brouillon existant (code 0) et rappelle `np draft --issue N --force` pour le regénérer.

### Planification launchd

Le service est fourni dans `deploy/macmini/launchd/com.sideproject.newsletter.monday.plist.tmpl` (lundi 05:00, `np run-monday` via `run.sh` qui charge `.env`). Installation : `deploy/macmini/install-launchd.sh --only com.sideproject.newsletter.monday`. Lancer à la main : `launchctl kickstart -k gui/$(id -u)/com.sideproject.newsletter.monday`. Si tu préfères trois jobs séparés (5 h collect, 5 h 30 rank, 6 h draft), duplique le plist en remplaçant `run-monday` par `collect`, `rank`, `draft --issue N`.

## Format du numéro (fixe)

1. Titre du numéro, ligne « n° N · date », aperçu (preheader).
2. **Édito** 120 mots, première personne, marqué `[À RELIRE]`.
3. **Trois actualités commentées** : titre, trois phrases, « Ce que ça change pour un cabinet », lien source.
4. **Cas d'usage** tiré de `cases/` avec le prompt ou le workflow prêt à copier.
5. **Le chiffre** sourcé (lien) ou `[CHIFFRE À TROUVER]`.
6. **L'outil testé** ou `[OUTIL À TESTER]`.
7. **La question de lecteur** : placeholder à remplacer.
8. Pied : « Veille assistée par IA, relue et signée par un humain », mention sponsor si `sponsor.yaml` présent et dans sa période, rappel double opt-in / désinscription (lien ajouté par la plateforme).

Le ton est fixé par `style.md` (règles + trois numéros d'exemple), injecté dans le system prompt de chaque appel de rédaction.

### Bibliothèque de cas d'usage

`cases/*.md` : en-tête YAML (`slug`, `title`, `themes`, `summary`, `duration`, `tools`) puis le corps markdown. Six cas d'amorçage : relance de pièces manquantes, lettre de mission (clause IA), bilan commenté, veille client sectorielle, questions récurrentes des clients, tri des emails du cabinet. Choix automatique : le cas dont les thèmes recoupent le plus les items de la semaine, hors cas utilisés dans les trois derniers numéros, rotation sur le numéro en cas d'égalité ; `--case SLUG` pour imposer.

## Ajouter une source

Ajouter un bloc dans `sources.yaml` :

```yaml
  - name: Nom unique
    url: https://exemple.fr/feed          # flux RSS/Atom, ou page de liste
    kind: rss                             # rss | page
    category: presse_pro                  # editeurs | presse_pro | institutions | ia_generale | newsletters_en | autre
    weight: 1.1                           # multiplie le score (institutions 1,2 ; presse 1,1 ; éditeurs 0,9 ; IA générale 0,8 ; EN 0,7)
    include_patterns: ["/actualites/"]    # kind=page seulement : regex des liens d'articles à suivre
    verify: true                          # à vérifier au premier passage
```

Puis `np collect --source "Nom unique" --dry-run` pour voir ce qui serait inséré. Le fichier est validé au chargement : clé inconnue (faute de frappe), `kind` ou `category` hors liste, `weight` non numérique ou hors ]0 ; 3], `active`/`verify` non booléens, regex invalide dans `include_patterns` arrêtent la commande avec un message qui nomme la source (`include_patterns` accepte une chaîne seule ou une liste). Une source retirée du YAML est désactivée (ses items restent) ; `active: false` la met en pause (`--source` explicite l'essaie quand même). Pour `kind: page`, sans `include_patterns`, le collecteur suit les liens du même site qui ressemblent à des articles (chemin à deux segments ou slug à tirets), télécharge au plus `MAX_LINKS_PER_PAGE` articles **inconnus** par passage (les liens déjà en base ne comptent pas), en ignorant tags, catégories, PDF, pages légales et les réponses qui ne sont pas du HTML ; un article illisible est ignoré sans mettre la source en erreur. Les liens relatifs des flux sont résolus, les dates futures ignorées, et un item sans date est daté de sa collecte pour le filtre d'ancienneté.

**Sources à vérifier** : toutes celles marquées `verify: true` (36 sur 39). Les URL de flux ont été écrites de mémoire ou par convention (WordPress `/feed/`, SPIP `backend`, beehiiv `/feed`, Substack `/feed`) et ne sont pas vérifiées depuis le sandbox. Premier passage réel : `np collect --dry-run`, puis corriger les URL en erreur dans `np stats` (colonne « erreur »).

## Classement : pondération et garde-fous

Pour chaque item, le modèle renvoie `pertinence_cabinet`, `nouveaute`, `actionnable` (0-10), `theme` (tenue, revision, social, fiscal, relation_client, recrutement, outils, reglementation, ia_generale), `resume_1_phrase`, `pourquoi_ca_compte`.
`score = min(10, (0,5 × pertinence + 0,3 × actionnable + 0,2 × nouveauté) × poids de la source)`.
Les articles sont envoyés par lots de 5 entre balises `<item id="…">` avec la consigne explicite de ne suivre aucune instruction qu'ils contiendraient (les balises sont neutralisées dans le contenu, l'extrait est tronqué à `RANK_MAX_CHARS` ; dans les attributs titre/source/URL, guillemets et chevrons sont remplacés pour qu'un titre ne puisse pas fermer la balise). Les notes sont ramenées dans [0 ; 10], le thème dans la liste, les deux phrases bornées à 400 caractères. Un lot en échec n'empêche pas les suivants ; les items sans réponse restent à classer au prochain passage.

## Brouillon : garde-fous

- Les URL du numéro viennent de la base (items sélectionnés), jamais du modèle. Si le modèle glisse un lien dans un texte (titre, actualité, chiffre, outil, édito), il n'est gardé que s'il pointe vers un item sélectionné ; sinon le lien markdown est réduit à son libellé, une URL nue devient `[LIEN À VÉRIFIER]`, et `np draft` l'annonce (« N lien(s) … retiré(s) »).
- Le chiffre doit figurer tel quel dans l'item cité (espaces ignorés) ; sinon sa phrase est préfixée `[À VÉRIFIER]`. Chiffre ou outil sans item identifiable : `[SOURCE À VÉRIFIER]` à la place du lien.
- Tous les champs du modèle sont bornés en longueur, les titres ramenés sur une ligne ; un type inattendu (liste, objet) vaut vide et déclenche le repli.

## Push

- **beehiiv** : `POST https://api.beehiiv.com/v2/publications/{BEEHIIV_PUBLICATION_ID}/posts`, en-tête `Authorization: Bearer <clé>`, corps `{title, subtitle, status: "draft", content_tags, body_content: <HTML>, email_settings.preview_text, web_settings}` (titre et aperçu pris dans le markdown relu). Dry-run : la requête exacte (clé masquée) est dans `out/push-beehiiv-NNN.json` ; `--live` sans `BEEHIIV_API_KEY`/`BEEHIIV_PUBLICATION_ID` refuse avant d'écrire quoi que ce soit. `--live` envoie et écrit la réponse dans `out/push-beehiiv-NNN.response.json`, puis passe le numéro en `pushed`. **Repli** si l'API renvoie 401/402/403/404 (la création de post par API est, à la date d'écriture, réservée aux plans supérieurs de beehiiv, et le nom du champ HTML doit être confirmé sur la doc) : `np push --issue N --target file`, ouvrir `out/push-file-NNN.html` dans le navigateur, tout sélectionner, copier, coller dans l'éditeur beehiiv (les titres, liens et blocs de code sont conservés), ou utiliser le bloc HTML de l'éditeur.
- **kessel** : pas d'API publique de création de brouillon connue ; `out/push-kessel-NNN.json` contient la marche à suivre ; `--live` refuse explicitement.
- **file** : copie le HTML dans `out/push-file-NNN.html`.

## Tests

`.venv/bin/pytest -q` : collecte RSS et Atom sur fixtures (`feedparser.parse(chemin)`), source `page` sur transport httpx simulé, cas limites de collecte (liens relatifs, dates futures, réponses trop grosses, contenus non HTML, erreurs d'extraction isolées, doublons intra-lot), validation de `sources.yaml`, dédoublonnage (utm/xtor, http/https/www, titres proches), classement avec `MockLLM` (lots, échecs, ids manquants, champs bornés, attributs neutralisés), sélection diversifiée, génération du numéro (sections markdown/HTML, sponsor, replis, URL inventées retirées, chiffre vérifié), HTML brut et liens dangereux neutralisés, push dry-run et live simulé (titre relu), extraction LinkedIn (contraintes et relance), CLI complète et `run-monday` via `CliRunner`. Aucun appel réseau : une fixture `autouse` fait échouer tout transport httpx réel. Lint : `.venv/bin/ruff check .`.

## Limites connues

- Aucune URL de flux n'a été vérifiée : prévoir 30 minutes de nettoyage de `sources.yaml` au premier passage réel.
- Les sources `page` dépendent de l'heuristique de découverte de liens ; pour les sites exotiques, renseigner `include_patterns` ou trouver le flux RSS.
- Pas de collecte LinkedIn ni X (pas d'API accessible sans compte développeur) : ces signaux passent par la relecture humaine.
- La qualité du brouillon dépend du modèle local ; `qwen3:14b` tient le JSON, `LLM_PROVIDER=anthropic` donne un meilleur premier jet pour l'édito.
- Les items qui dépassent `MAX_ITEM_AGE_DAYS` sans avoir été utilisés restent `new` en base mais ne sont plus sélectionnés.
- Le dédoublonnage par titre normalisé est global : deux articles différents de deux sources portant exactement le même titre générique seraient confondus.
- Un item que le modèle ne note jamais (id absent de sa réponse) est représenté à chaque `np rank` tant qu'il figure parmi les `RANK_DEFAULT_LIMIT` plus récents.
- La relance aux non-ouvreurs du mercredi est un réglage de la plateforme, pas de cette app.

## Cadre juridique

- **RGPD** : la liste d'abonnés vit chez la plateforme (beehiiv, Kessel), avec double opt-in, désinscription en un clic et mention de l'usage à l'inscription ; cette app ne stocke aucune donnée d'abonné. Les textes collectés sont des publications publiques, conservés pour la veille, sans données personnelles au-delà du nom d'auteur publié.
- **Sponsoring** : signalé comme tel dans chaque numéro (`sponsor.yaml` → encadré « Partenaire de ce numéro » et mention en pied, « contenu sponsorisé »).
- **IA** : mention « veille assistée par IA, relue et signée par un humain » dans chaque numéro (AI Act art. 50, recommandé ici), et une signature humaine.
- Pas de conseil fiscal ou social personnalisé : la newsletter informe ; le template le rappelle dans la question de lecteur.
- Citation des sources : chaque actualité renvoie vers l'article d'origine ; on résume, on ne reproduit pas.

## Décisions prises

- Extraction des pages : **trafilatura** (meilleure qualité sur la presse française, métadonnées auteur/date/description, mode précision) plutôt que readability-lxml.
- Markdown source de vérité ; HTML et texte dérivés par `python-markdown` dans un template email maison ; pas de MJML.
- Trois appels LLM courts pour le numéro (actualités, chiffre + outil, titre + édito) plutôt qu'un seul long : plus fiable avec un modèle local 14B en mode JSON, et chaque appel a un repli.
- Le cas d'usage est inséré tel quel depuis la bibliothèque (écrit à la main, relu), le modèle n'écrit que la phrase d'introduction.
- Items cités dans le numéro → `used` ; sélectionnés mais non cités → remis `new` ; filtre d'ancienneté à la sélection, pas à la collecte.
- `run-monday` ne s'arrête pas sur une collecte ou un classement en échec : il produit le brouillon avec ce qu'il y a en base, et n'échoue que si aucun brouillon ne sort.
- Dépôts `issues/` versionnés (les numéros sont un actif), `out/` et `data/` ignorés par git.
- HTML brut du markdown échappé à la conversion et liens `javascript:`/`data:` retirés : le numéro n'a besoin que du markdown, et une partie du texte vient du modèle ou de contenus externes.
- Les URL du numéro ne viennent jamais du modèle ; ce qu'il propose est vérifié contre les items sélectionnés (voir « Brouillon : garde-fous »).
