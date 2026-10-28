# Revue croisée (QA-1) — veille-marches

Revue de sécurité, de robustesse et de correction fonctionnelle de l'app, faite sans rien réécrire : chaque défaut
réel est couvert par un test dans `tests/test_review.py` (24 tests ajoutés), corrigé, puis la suite complète est
relancée. État avant : 78 tests verts, ruff propre. État après : **102 tests verts, ruff propre**, aucun appel réseau.

Gravités : **H** (haute : argent, accès ou données d'un abonné en jeu), **M** (moyenne : comportement faux en
production, panne d'un job), **B** (basse : qualité, hygiène). Les numéros de ligne renvoient au code corrigé.

## 1. Sécurité du site et du paiement

| # | Gravité | Défaut | Où | Correction | Test |
|---|---|---|---|---|---|
| 1 | H | **Événement périmé qui réactive un abonné résilié** : un `checkout.session.completed` livré après `customer.subscription.deleted` du même abonnement (livraison en retard, rejeu après une panne) repassait l'abonné `active`. | `billing.py:266-285` (`_apply_event`) | Si la fiche référence déjà ce même abonnement avec un statut terminal (`canceled`, `unpaid`, `paused`), le checkout répond `stale` sans rien changer. `customer.subscription.deleted` mémorise désormais les identifiants Stripe pour que la règle s'applique. | `test_stale_checkout_after_subscription_deleted_does_not_reactivate` |
| 2 | H | **Fin d'un ancien abonnement appliquée au nouveau** : après un réabonnement (même client Stripe), `deleted` / `updated → unpaid` de l'ancien abonnement résiliait le nouvel abonnement actif (résolution par `customer`). | `billing.py:287-296` | Un événement désactivant qui concerne un autre identifiant d'abonnement que celui suivi répond `stale`. | `test_events_of_an_old_subscription_do_not_touch_the_new_one` |
| 3 | H | **Idempotence qui avale les échecs** : l'identifiant d'événement était mémorisé avant traitement ; si le traitement levait (base verrouillée, bug), le rejeu de Stripe répondait `duplicate` et l'abonné n'était jamais activé. | `billing.py:298-325`, `db.py:248` | L'événement est oublié (`forget_stripe_event`) quand le traitement échoue ; l'exception remonte (500) et Stripe rejoue. | `test_failed_processing_is_not_recorded_as_already_seen` |
| 4 | H | **Email de bienvenue jamais envoyé dans l'ordre habituel de Stripe** : `customer.subscription.created` arrive en général avant `checkout.session.completed` ; le premier activait l'abonné sans email, le second voyait « déjà actif » et n'envoyait rien. | `billing.py:217-263` | `apply_subscription_status` envoie l'email lors de la transition `pending_payment → actif` ; `activate_subscriber` l'envoie seulement si l'abonné était inactif. Un seul email quel que soit l'ordre ; `sync-stripe` (filet si un webhook manque) l'envoie aussi. | `test_welcome_email_sent_once_whatever_the_event_order`, `test_sync_sends_welcome_when_webhook_was_missed` |
| 5 | H | **`APP_SECRET_KEY` et `STRIPE_WEBHOOK_SECRET` facultatifs en production** : `vm web` démarrait avec une clé Stripe réelle et une clé de signature aléatoire (liens des emails morts au redémarrage) ou sans secret de webhook (aucun paiement n'activait jamais personne, argent encaissé sans service). | `settings.py:113`, `web.py:86`, `cli.py:301` | `VMSettings.web_startup_problems()` ; `vm web` refuse (code 2, message explicite) et le `lifespan` FastAPI lève une `RuntimeError` claire dès qu'une clé Stripe existe sans ces deux secrets. Le mode démonstration tolère la clé temporaire. | `test_web_refuses_to_start_with_stripe_key_but_without_secrets`, `test_cli_refuses_links_and_web_without_secret_key_and_invalid_criteria` |
| 6 | H | **Mode démonstration : données et lien d'accès de n'importe quel abonné** : identifiants devinables (`/demo/checkout/<id>`, `/merci?session_id=cs_demo_<id>` donnait le récapitulatif **et un lien signé valide** de tout abonné actif), `POST /demo/portal/<id>` résiliait n'importe qui et **forgeait un jeton** si aucun n'était fourni. Le README recommande justement de tester ce mode derrière un tunnel public. | `billing.py:154`, `web.py:315-350` | Identifiant de session non devinable (`cs_demo_` + 24 caractères aléatoires) qui protège `/demo/checkout/<session>` et `/merci` comme chez Stripe ; le portail simulé exige le lien signé de l'abonné concerné (403 sinon). Les pages restent 404 dès qu'une clé Stripe existe. | `test_demo_pages_need_unguessable_session_and_valid_token` (+ `test_demo_pages_hidden_in_live_mode` existant) |
| 7 | M | **Statut Stripe inconnu ⇒ abonné actif** : `SUBSCRIPTION_STATUS_MAP.get(..., ("active", True))`. | `billing.py:246` | Statut inconnu journalisé, `status` / `active` conservés (prix et identifiants toujours mis à jour). | `test_unknown_stripe_status_keeps_local_state` |
| 8 | M | **`vm subscribers link` sans `APP_SECRET_KEY`** produisait un lien signé avec une clé aléatoire du processus CLI, que le site (autre processus) refuse toujours. | `cli.py:280` | Refus explicite (code 2). | `test_cli_refuses_links_and_web_without_secret_key_and_invalid_criteria` |
| 9 | M | **Lien forgé ⇒ erreur 500** : `str.isdigit()` accepte les chiffres Unicode (« ² », « ١ ») puis `int()` / `.encode("ascii")` levaient. | `accounts.py:23,66` | Chiffres ASCII seulement, longueur bornée ; comparaison HMAC toujours en temps constant. | `test_token_with_unicode_digits_is_rejected_cleanly` |
| 10 | M | **Aucun en-tête de sécurité** et pages privées cachables : le jeton « espace abonné » est dans l'URL (`Referer`, caches partagés). | `web.py:37-45,107-114` | Middleware : `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, CSP sans script ; `Cache-Control: no-store` sur `/compte*`, `/merci`, `/demo/*`. | `test_security_headers_and_private_pages_not_cached` |
| 11 | M | **Jetons dans les journaux d'accès** d'uvicorn (`GET /compte?token=…`, valable 7 jours). | `web.py:47-63` | Filtre `RedactTokensFilter` (`token=[masqué]`) installé sur `uvicorn.access` / `uvicorn.error` dès l'import de l'app. | `test_access_log_filter_masks_account_tokens` |
| 12 | M | **Formulaires : montants `inf`, `nan`, `1e308`, `1_000` acceptés** (`float()`), préfixes CPV en chiffres Unicode (`isdigit()`), listes non bornées. | `forms.py:13-17,36-62`, `models.py:20-21` | Expressions régulières ASCII strictes, plafond `MAX_AMOUNT`, 200 valeurs de 40 caractères au plus par liste ; même règle dans le modèle `Subscriber`. | `test_form_amounts_and_cpv_prefixes_are_strict` |
| 13 | M | **Réinscription d'un abonné impayé ou en pause** : son abonnement Stripe existe toujours, un second Checkout créait un double abonnement (double prélèvement possible). | `web.py:208` | Refus avec renvoi vers le lien d'accès (régularisation dans le portail). | `test_signup_refuses_unpaid_or_paused_subscriber` |
| 14 | B | **Réponse du webhook qui révèle la configuration** (`STRIPE_WEBHOOK_SECRET manquant`, détails du SDK). | `web.py:310` | Message générique ; le détail reste dans le journal. | `test_webhook_errors_do_not_leak_configuration` |
| 15 | B | **Pages publiques `/` et `/exemple` rendaient un lien signé** (abonné fictif `id=0`) dès que `APP_SECRET_KEY` était défini. | `sample.py:27` | Abonné d'exemple sans identifiant : aucun lien rendu. | `test_public_example_pages_do_not_expose_a_signed_link` |
| 16 | B | `/compte/lien` acceptait une adresse de taille illimitée. | `web.py:293` | Bornée à 254 caractères. | couvert par les tests existants |

Vérifié sans correction nécessaire : signature Stripe (`stripe.Webhook.construct_event`, tolérance 5 min, 400 sinon),
comparaison HMAC en temps constant (`hmac.compare_digest`), expiration des liens, autoescape Jinja sur tous les
`.html.j2` (aucun `|safe`), aucun secret rendu dans les pages, `token ⇒ id` : chaque page privée charge l'abonné à partir
du jeton, jamais d'un paramètre libre.

## 2. Injection de prompt et sorties du LLM

| # | Gravité | Défaut | Où | Correction | Test |
|---|---|---|---|---|---|
| 17 | M | **Sortie LLM mal typée ⇒ `vm score` s'arrête** : `pieces_a_fournir: 5` levait `TypeError` (non converti par pydantic) et `summarize` ne capturait que `LLMError` : toute autre exception du fournisseur tuait le passage entier. | `models.py:223-245`, `scoring.py:179-199` | Types inattendus tolérés (entier, booléen, objet) ; `summarize` journalise et retourne le résumé de repli pour toute exception ou validation en échec (l'avis est repris au passage suivant). | `test_llm_summary_tolerates_wrong_types_and_removes_urls`, `test_summarize_survives_bad_llm_output_and_unexpected_exceptions` |
| 18 | M | **URL inventées par le LLM** : un texte injecté dans un avis pouvait faire écrire « voir http://… » dans `resume` / `raison` / pièces, rendu dans l'email (autoliens des clients mail). | `models.py:49` | Toute URL est remplacée par `[lien retiré]` dans les champs textuels ; le lien du digest vient exclusivement de `notice.url`. | idem |
| 19 | M | **Lien de l'avis non validé** : une `url_avis` ou un `links.html` de l'API en `javascript:` / `data:` aurait été rendu tel quel dans `href`. | `models.py:39,93`, `collectors/boamp.py:62`, `collectors/ted.py:76` | Seules les URL `http(s)` absolues sont gardées, sinon l'URL de la source est reconstruite depuis l'identifiant. | `test_notice_url_must_be_http` |
| 20 | B | **Champs non tronqués dans le prompt** (titre, acheteur, procédure, identifiant source) : seule la description l'était. | `scoring.py:138-156` | Bornes par champ, identifiant source neutralisé comme les autres. | `test_prompt_truncates_external_fields` |

Vérifié : isolement par balises `<avis>` (balises présentes dans le texte neutralisées), consigne système explicite,
`verdict` borné par `Literal` + normalisation, 10 pièces maximum, repli déterministe `fallback_summary`.

## 3. Correction fonctionnelle

| # | Gravité | Défaut | Où | Correction | Test |
|---|---|---|---|---|---|
| 21 | M | **Jours calendaires et dates calculés en UTC** : une date limite « 5 novembre à minuit (Paris) » est stockée `04T23:00Z` ; le digest affichait « 04/11 » et le délai perdait un jour (un avis à 10 jours pleins tombait en « délai court »). | `dates.py:17,62-92` | `local()` : affichage et calcul de délai en heure de Paris (`PARIS` défini dans `dates.py`, réutilisé par `catalog.py`) ; libellés de date du digest et du brief également. | `test_deadlines_use_paris_calendar_days` |
| 22 | M | **Un email en échec arrêtait toute la tournée** : `mailer.send` levait, les abonnés suivants ne recevaient rien ce jour-là. | `digest.py:138-150`, `brief.py` | Échec journalisé par abonné (`outcome.error`), rien d'enregistré pour lui (resservi au passage suivant), tournée poursuivie ; `vm digest` / `vm brief-weekly` affichent `ERREUR` et sortent en code 1. | `test_previews_do_not_collide_and_a_failed_send_does_not_stop_the_run`, `test_cli_digest_reports_failed_sends` |
| 23 | M | **`vm subscribers add` écartait en silence un préfixe CPV invalide** (`--cpv 7`) : abonné créé **sans aucun filtre CPV** (il recevait tout) ; départements inconnus acceptés, montants non vérifiés. | `cli.py:168-186` | Validation stricte (code 2) : préfixes, départements, montants (bornes et min ≤ max). | `test_cli_refuses_links_and_web_without_secret_key_and_invalid_criteria` |
| 24 | B | **Aperçus HTML/texte écrasés entre abonnés** : `Path.with_suffix(".html")` remplaçait le `.fr` de l'adresse (`a@x.fr` et `a@x.com` → même fichier) ; brief et digest ne nettoyaient pas les noms de la même façon. | `digest.py:128` | `write_previews` partagé, suffixe ajouté sans toucher à l'adresse nettoyée. | `test_previews_do_not_collide_and_a_failed_send_does_not_stop_the_run` |

Vérifié sans correction : filtrage (préfixes CPV, départements normalisés, montant inconnu gardé et signalé, avis sans
département écarté sauf abonné « toute la France » ou `MATCH_UNKNOWN_DEPARTMENT`), bornes 0-100 du score (somme des poids
= 100, clamp), aucun doublon via `deliveries` (envois seulement avec `--send`), abonnés inactifs exclus partout
(`active_only=True`), fenêtre `DIGEST_LOOKBACK_DAYS`, brief Pro seulement (fenêtre `--since-days`, historique 12 mois),
pagination Opendatasoft / TED, `since-days`, erreurs par source consignées dans `collect_runs`, `sync-stripe` (dry-run,
statut mock ignoré), migration 002 sur une base 001 (test existant).

## 4. Robustesse

| # | Gravité | Défaut | Où | Correction | Test |
|---|---|---|---|---|---|
| 25 | M | **Un enregistrement inattendu de l'API faisait échouer toute la source** (élément non-dictionnaire, `donnees` entier, champs de types imprévus) : exception hors `CollectorError`, collecte interrompue. | `collectors/boamp.py:110`, `ted.py:147`, `decp.py:111` | Conversion protégée par enregistrement : l'enregistrement est écarté (compté `excluded`, journalisé), la source continue ; le reste du mapping dégrade déjà proprement (vérifié champ par champ dans le test). | `test_collectors_survive_malformed_records` |

Vérifié : démarrage sans `.env` (`vm stats`, import de `veille_marches.web` en mode mock), base vide (digest / brief /
score sans rien), LLM en échec (repli), `vm web` sans clé Stripe (démonstration) et avec clé (démo coupée, test existant).

## 5. Qualité

| # | Gravité | Défaut | Correction |
|---|---|---|---|
| 26 | B | Code mort : `catalog.SampleAlert`, chaîne `{% elif %}` vide dans `site/account_link.html.j2`, `json.loads("{}")` oublié dans `test_cli.py`, `\d` (Unicode) dans `mapping._CPV_RE`. | Supprimés / corrigés. |
| 27 | B | Fixtures web définies dans `test_web.py` et nécessaires ailleurs. | Déplacées dans `tests/conftest.py`. |
| 28 | B | README et `.env.example` : nombre de tests, URL de démo, `APP_SECRET_KEY` « vide (clé temporaire) », résultats de webhook (`stale`, `pending`), réinscription impayé / pause, envois en échec, `sync-stripe` et email de bienvenue, journaux. | Mis à jour. |

**Bilan : 28 défauts corrigés — 6 hauts, 14 moyens, 8 bas.**

## À faire plus tard

- **Ordre des événements Stripe en général** : les règles ajoutées couvrent les cas réalistes (checkout périmé, ancien
  abonnement). Pour un tri complet, mémoriser par abonné le `created` du dernier événement appliqué (migration 003) et
  ignorer tout événement plus ancien.
- **Jeton dans l'URL** : le filtre masque le jeton dans les journaux d'uvicorn, mais un reverse proxy (Cloudflare, Caddy)
  garde ses propres journaux d'accès. Variante plus sûre : au premier `GET /compte?token=…`, poser un cookie de session
  court et rediriger vers `/compte` sans paramètre.
- **Limitation de débit** (`/inscription`, `/compte/lien`, `/webhooks/stripe`) et taille maximale du corps des requêtes :
  à poser au niveau du proxy (Starlette n'impose aucune limite).
- **Réabonnement** : la fiche garde l'ancien `stripe_subscription_id` jusqu'au nouveau checkout ; entre-temps
  `sync-stripe` peut remplacer `pending_payment` par `canceled` (sans effet sur les envois, mais trompeur dans
  `vm subscribers list`).
- **Double soumission de `/inscription`** : deux sessions Checkout sont créées, seule la dernière est mémorisée ; si
  l'abonné termine la première, `/merci` affiche le message générique (le webhook active quand même correctement).
- **`core.db.migrate`** (hors de cette app) exécute les scripts avec `executescript`, qui valide avant d'exécuter : une
  migration qui échoue à mi-chemin peut rester à moitié appliquée.
- **`vm web`** passe `forwarded_allow_ips="*"` à uvicorn : sans conséquence tant que l'app n'utilise pas l'adresse du
  client, à restreindre si un jour elle sert à la limitation de débit.
- **CSP** : `style-src 'unsafe-inline'` reste nécessaire tant que les gabarits utilisent des attributs `style=` ; passer par
  des classes permettrait de le retirer.
- `vm brief-weekly --subscriber` sur un abonné Essentiel ne fait rien sans `--all-plans` (comportement muet).
- `Subscriber._norm_status` ramène un statut inconnu en base à `active` : seulement atteignable par une modification SQL
  manuelle, mais une erreur explicite serait plus sûre.
