# Revue croisée QA-1 — `apps/avis-clients`

Revue de sécurité, d'injection de prompt, de correction fonctionnelle, de robustesse et de qualité de
l'application « Avis Clients », faite sans changer l'architecture ni les dépendances.

- **Avant** : 57 tests verts, `ruff check .` propre.
- **Après** : 95 tests verts (38 ajoutés, tous dans `tests/test_qa_review.py` sauf une adaptation de
  `tests/test_gbp_cli.py`), `ruff check .` propre, aucun appel réseau dans les tests.
- **Bilan** : 41 défauts corrigés — 2 critiques, 7 hauts, 15 moyens, 17 bas — plus une liste « à faire plus tard ».
- Méthode : pour chaque défaut, un test qui le met en évidence (quand c'est possible), puis la correction, puis
  la suite complète. Une migration `002_review_draft_source.sql` a été ajoutée (rejouable, testée sur une base
  n'ayant que `001`).

Les numéros de ligne renvoient à l'état final des fichiers sous `src/avis_clients/`.

---

## Critique

### C1. Un compte pouvait relier la fiche Google d'un autre commerçant (lecture de ses avis, réponses publiées en son nom)
- **Où** : `routes/app.py:217` (`establishment_settings`), `routes/app.py:57` (`_location_error`), `repo.py:143`
  (`get_establishment_by_location`), `cli.py:252` (`google link`).
- **Défaut** : le champ « Fiche Google » (`google_location_name`) était enregistré tel quel. En mode `live`, le
  jeton OAuth opérateur accède à toutes les fiches des clients : saisir `accounts/…/locations/…` d'un autre
  commerçant suffisait à importer ses avis, à recevoir ses alertes et à publier des réponses sur sa fiche via
  `PUT …/reviews/*/reply`. Aucune contrainte de format non plus (chemin injecté dans l'URL Google).
- **Correction** : format imposé (`^accounts/…/locations/…$`), une fiche ne peut être reliée qu'à un seul
  établissement (vérifié dans l'interface et dans `avis google link`), et en mode `live` la fiche doit figurer
  parmi les fiches accessibles **avec le Place ID de l'établissement**. Risque résiduel documenté en fin de fichier.
- **Tests** : `test_location_name_cannot_point_to_another_establishment`, `test_live_mode_location_must_match_place_id`.

### C2. Un abonné actif qui cliquait sur une autre formule créait un second abonnement facturé
- **Où** : `routes/billing.py:59`, `templates/billing.html:38`.
- **Défaut** : les boutons « Changer pour Pro/Réseau » lançaient un nouveau Stripe Checkout en mode
  `subscription` ; Stripe ouvre alors un second abonnement en parallèle du premier (double prélèvement), la note
  de bas de page renvoyant pourtant au portail.
- **Correction** : pour un compte `active`, `/billing/checkout` redirige vers le portail client (prorata géré par
  Stripe) ; le gabarit propose « Changer via le portail » ; cas sans client Stripe (formule attribuée à la main)
  → message explicite.
- **Test** : `test_checkout_is_refused_for_active_subscriber`.

## Haute

### H1. `SESSION_SECRET` par défaut accepté en production
- **Où** : `settings.py:86` (`_require_real_secret_in_production`), `.env.example`.
- **Défaut** : `change-me-en-production` (ou le placeholder du `.env.example`) servait silencieusement à signer
  les cookies en https.
- **Correction** : dès que `APP_BASE_URL` est en https, l'app refuse de démarrer si le secret est absent, factice
  ou < 32 caractères (message en français avec la commande de génération). Démarrage sans `.env` en http inchangé.
- **Test** : `test_session_secret_is_required_in_production`.

### H2. Webhook SMS entrant (STOP) sans aucune authentification
- **Où** : `routes/webhooks.py:49-77`, `sms.py:115-126` (`twilio_signature`, `verify_twilio_signature`),
  `settings.py:54` (`sms_webhook_token`).
- **Défaut** : n'importe qui connaissant l'URL pouvait inscrire n'importe quel numéro en liste d'opposition
  (`From=+33…&Body=STOP`), y compris en opposition **globale**, et donc bloquer les envois des commerçants.
- **Correction** : Twilio → vérification de `X-Twilio-Signature` (HMAC-SHA1 sur l'URL publique `APP_BASE_URL`
  + paramètres POST triés, `hmac.compare_digest`) ; smsmode (callbacks non signés) → jeton partagé
  `SMS_WEBHOOK_TOKEN` obligatoire (`?token=`) ; sinon 403. `dry-run` sans jeton reste ouvert pour la démo.
- **Tests** : `test_sms_inbound_webhook_requires_twilio_signature`, `test_sms_inbound_webhook_shared_token_for_smsmode`.

### H3. « Synchroniser » sans établissement lançait le poll de **tous** les comptes
- **Où** : `routes/inbox.py:52`, `reviews.py:178`.
- **Défaut** : `poll_reviews(establishment_ids=[])` retombait sur « tous les établissements » (liste vide =
  falsy) : un compte sans établissement déclenchait brouillons LLM, alertes et publications pour les autres
  tenants, et voyait les compteurs agrégés dans le flash.
- **Correction** : `establishment_ids is not None` dans le poll, et message « Ajoutez d'abord un établissement »
  dans la route.
- **Test** : `test_inbox_sync_without_establishment_does_not_poll_other_accounts`.

### H4. La fin d'un ancien abonnement coupait l'accès d'un abonnement courant
- **Où** : `billing.py:206`.
- **Défaut** : `customer.subscription.deleted` (ou `updated` en `canceled/unpaid`) était appliqué sans vérifier
  l'identifiant d'abonnement : un ancien abonnement résilié à échéance, arrivant après un nouveau Checkout,
  passait le compte en `plan=none`.
- **Correction** : les événements de fin concernant un autre abonnement que l'abonnement courant sont ignorés
  et journalisés (`stripe_event_ignored`).
- **Test** : `test_stripe_events_for_another_subscription_are_ignored`.

### H5. Auto-publication de brouillons génériques ou nettoyés mécaniquement
- **Où** : `reviews.py:70-77` (`create_draft`), `reviews.py:129` (`_auto_publish`), `models.py:89-98`,
  `migrations/002_review_draft_source.sql`, `templates/partials/review_card.html:16`.
- **Défaut** : avec l'option « auto-publication ≥ 4 étoiles », le texte publié sur Google pouvait être le modèle
  de repli (LLM indisponible) ou une sortie LLM dont on avait retiré lien/coordonnées/longueur après coup —
  sans aucun statut explicite ni validation humaine.
- **Correction** : la provenance du brouillon est stockée (`reply_draft_source` = `llm` | `llm-cleaned` |
  `fallback`) ; seul `llm` est auto-publiable, les autres restent `draft` (événement `auto_publish_skipped`)
  et la boîte de réception affiche « à personnaliser avant publication ».
- **Test** : `test_auto_publish_only_clean_llm_drafts`.

### H6. Les STOP reçus de smsmode n'étaient jamais pris en compte
- **Où** : `sms.py:72` (`normalize_phone`).
- **Défaut** : smsmode transmet `numero=33612345678` (international sans `+`) ; `normalize_phone` refusait ce
  format, donc `handle_inbound_sms` ignorait tout STOP smsmode (le test existant passait pour la mauvaise raison).
- **Correction** : 11 à 15 chiffres sans zéro initial → `+` + chiffres.
- **Test** : `test_normalize_phone_prefixes_and_trunk_zero` (cas `33612345678`), `test_sms_inbound_webhook_shared_token_for_smsmode`.

### H7. STOP WhatsApp ignoré (`From=whatsapp:+33…`)
- **Où** : `sms.py:55`.
- **Défaut** : Twilio préfixe l'expéditeur WhatsApp par `whatsapp:` ; le numéro n'était pas normalisé, le STOP
  était ignoré alors que le canal WhatsApp est proposé.
- **Correction** : préfixes `whatsapp:` / `tel:` / `sms:` retirés avant normalisation.
- **Test** : `test_whatsapp_stop_is_honored`.

## Moyenne

### M1. Redirection ouverte via `next=/\evil.example`
- **Où** : `routes/auth.py:26` (`_safe_next`). Les navigateurs normalisent `/\` en `//`. Correction : refus de
  `//`, `/\`, de tout antislash et de toute URL absolue. **Test** : `test_safe_next_blocks_open_redirects`.

### M2. Événements Stripe marqués « reçus » avant traitement (perdus en cas d'échec) et doublon concurrent → 500
- **Où** : `billing.py:166-175`. `SELECT` puis `INSERT` : deux livraisons simultanées → `IntegrityError` ; un
  échec après l'insertion rendait la relance de Stripe « duplicate » sans jamais appliquer l'événement (compte
  payé sans accès). Correction : `INSERT OR IGNORE` + libération de l'identifiant si le traitement lève.
  **Test** : `test_stripe_event_is_replayable_when_processing_fails`.

### M3. Recommandations LLM du rapport sans contrôle de sortie
- **Où** : `reports.py:153` (`_clean_recommendation`). Les avis du mois entrent dans le prompt ; une
  recommandation contenant un lien, un email ou un numéro (injection probable) partait telle quelle dans l'email
  du commerçant, sans limite de longueur. Correction : écartée si lien/email/téléphone, tronquée à 40 mots,
  repli si moins de 3 valides. **Test** : `test_recommendations_are_sanitized_and_bounded`.

### M4. `render_message` reposait sur `str.format_map` (page en 500, accès aux attributs)
- **Où** : `sms.py:92-112`. Un modèle avec une accolade mal fermée plantait la page « Demandes d'avis » et
  chaque envoi ; `{lien.__class__…}` donnait accès aux attributs des objets. Correction : substitution par regex
  des trois seuls jetons autorisés, `validate_request_template` partagé (`{lien}`, STOP, 320 caractères) et
  utilisé par les deux routes (la route « réglages » n'exigeait pas la mention STOP). **Test** :
  `test_render_message_tolerates_braces_and_blocks_attribute_access`.

### M5. Avis modifiés par le client jamais répercutés
- **Où** : `reviews.py:143` (`_sync_existing`). Un avis déjà connu n'était mis à jour que pour la réponse
  Google : une note passée de 5 à 2 étoiles ou un texte réécrit restaient invisibles (brouillon obsolète,
  pas d'alerte). Correction : mise à jour texte/note/`updated_at`, nouveau brouillon si non validé, alerte si
  l'avis devient négatif, compteur `updated`. **Test** : `test_poll_updates_modified_reviews`.

### M6. Les jobs continuaient à payer le LLM pour les comptes en lecture seule
- **Où** : `reviews.py:190`. Essai terminé sans abonnement : brouillons, alertes et publications continuaient
  toutes les 15 minutes. Correction : établissements de comptes sans droit d'écriture ignorés
  (`skipped_readonly`). **Test** : `test_poll_skips_readonly_accounts`.

### M7. Aperçu du rapport : un appel LLM à chaque affichage, même en lecture seule ; mois invalide → 500
- **Où** : `routes/app.py:298-300`, `reports.py:28` (`is_valid_month`), `reports.py:167-175` (cache par
  `services.report_cache`). `?month=abcdefg` levait `ValueError` dans `previous_month` (500). Correction :
  validation stricte du mois, recommandations génériques sans appel au modèle en lecture seule, cache mémoire
  borné par (établissement, mois, contenu) pour les autres. **Tests** : `test_report_month_parameter_is_validated`,
  `test_report_preview_caches_llm_and_skips_it_in_readonly`.

### M8. Mois des quotas et des rapports calculé en UTC
- **Où** : `db.py:47-70` (`local_tz`, `local_month`, `month_bounds_utc`), `repo.py:247`, `repo.py:316`,
  `requests_service.py:40`, `reports.py:86`. Le 1er du mois entre minuit et 1 h/2 h (Paris), les envois
  comptaient encore sur le mois précédent et les avis étaient rangés dans le mauvais mois. Correction : bornes
  du mois dans `APP_TIMEZONE` (Europe/Paris), comparées en ISO UTC. **Test** : `test_monthly_boundaries_follow_paris_time`.

### M9. Import CSV sans limite de taille
- **Où** : `routes/requests.py:82`. `await file.read()` chargeait n'importe quel volume en mémoire (Starlette ne
  limite que les champs, pas les fichiers). Correction : 1 Mo maximum, message explicite, 500 contacts.
  **Test** : `test_csv_import_rejects_oversized_file`.

### M10. Oppositions globales exposées à tous les commerçants
- **Où** : `repo.py:367` (`list_optouts`), `routes/requests.py:139`. Les numéros en opposition globale (STOP
  reçus sans envoi préalable, `avis optouts add`) étaient listés dans l'interface de chaque compte (données
  personnelles d'autres tenants), et « retirer » prétendait réussir sans rien faire. Correction : l'interface ne
  liste que les oppositions du compte, l'envoi continue de respecter les globales, le retrait explique le cas
  global. **Test** : `test_global_optouts_are_enforced_but_not_listed_to_merchants`.

### M11. En-têtes de sécurité absents, pages privées mises en cache
- **Où** : `web.py:85-89`. Rien hors de Caddy (l'option recommandée est Cloudflare Tunnel, sans Caddy) : pas
  de `nosniff`, framing autorisé (clickjacking du formulaire public), pages `/app` cachables après déconnexion.
  Correction : `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Cache-Control: no-store`
  sur `/app`, `/billing`, `/auth/`. **Test** : `test_security_headers_and_no_store_on_private_pages`.

### M12. Client Google live : pas de délai d'attente, erreurs réseau non converties
- **Où** : `gbp.py:128`, `gbp.py:161`, `gbp.py:170` (`_call`). `AuthorizedSession` sans `timeout` (blocage
  infini possible) ; `ConnectionError`/`RefreshError` n'étaient pas des `GBPError` et faisaient échouer tout le
  poll pour tous les établissements. Correction : `timeout=30`, toute exception réseau/jeton → `GBPError`
  (l'établissement est noté en erreur, les autres continuent). **Test** : `test_live_client_wraps_network_errors_and_sets_timeout`.

### M13. `+33 (0)6 12 34 56 78` normalisé en `+330612345678`
- **Où** : `sms.py:60`. Format très courant en France → numéro invalide chez les fournisseurs. Correction :
  suppression du zéro national après l'indicatif. **Test** : `test_normalize_phone_prefixes_and_trunk_zero`.

### M14. Dictionnaire des promesses commerciales incomplet et limite de mots incohérente
- **Où** : `drafts.py:37-46`. « geste commercial », « nous vous offrons », « dédommager », « compenser »,
  « à nos frais » passaient le contrôle ; la consigne système disait « 60 mots » quelle que soit
  `REPLY_MAX_WORDS`. Correction : regex étendue, `system_reply(max_words)`. **Test** :
  `test_commercial_promises_and_system_prompt_word_limit`.

### M15. Message flash contenant `/` renvoyé entre guillemets par le module cookie
- **Où** : `deps.py:94`. `quote()` laissait `/` en clair ; le module `http.cookies` entourait alors la valeur de
  guillemets, que certains clients renvoient tels quels (décodage JSON en échec). Correction : `safe=""`.
  Couvert par les tests de flash (`test_location_name_cannot_point_to_another_establishment`).

## Basse

- **B1** `auth.py:38` — consommation du lien magique non atomique (`SELECT` puis `UPDATE`) : un double clic
  simultané pouvait ouvrir deux sessions. Correction : `UPDATE … WHERE used_at IS NULL AND expires_at > ?` et
  contrôle de `rowcount`. Couvert par `test_magic_link_is_single_use_and_expires`.
- **B2** `routes/auth.py:52`, `auth.py:55` — aucune limite d'émission de liens : spam d'une adresse tierce et
  coût d'envoi. Correction : un lien non utilisé par adresse et par minute, même page de confirmation (pas
  d'indice sur l'existence du compte). **Test** : `test_login_is_throttled_per_email`.
- **B3** `repo.py:187-213` — deux polls simultanés (job + bouton) → `IntegrityError` sur `UNIQUE`. Correction :
  `INSERT OR IGNORE` + relecture. **Test** : `test_insert_review_is_idempotent`.
- **B4** `repo.py:208-210`, `db.py:41` — horodatages Google (`Z`, millisecondes) mélangés au format `+00:00`
  dans les mêmes colonnes. Correction : normalisation à l'insertion (`normalize_iso`).
- **B5** `routes/app.py:42`, `repo.py:101` — Place ID non validé dans les réglages et non encodé dans l'URL
  d'avis. Correction : même regex à la création et à la modification, `quote(..., safe="")`. **Test** :
  `test_review_url_encodes_place_id`.
- **B6** `routes/app.py:121-122`, `routes/app.py:184`, `routes/app.py:185-186`, `routes/app.py:200` — nom,
  signature, consignes et exemples de ton sans limite de taille côté serveur (prompts et SMS gonflés).
  Correction : bornes (80 / 200 × 20 / 1 000 caractères).
- **B7** `sms.py:76`, `requests_service.py:68` — prénom (saisie ou CSV) multiligne ou commençant par `= + - @`
  injecté tel quel dans le SMS (et dans un futur export tableur). Correction : `clean_first_name`.
- **B8** `requests_service.py:86` — « quota mensuel atteint (0/0) » pour la formule Solo. Correction : message
  explicite « votre formule n'inclut pas de demandes par SMS ».
- **B9** `billing.py:45` — « 0 jour(s) restant(s) » le dernier jour d'essai. Correction : minimum 1 tant que
  l'essai est actif. **Test** : `test_trial_days_left_never_shows_zero_while_active`.
- **B10** `routes/app.py:89`, `repo.py:400` — les vues de la page publique (robots compris) noyaient le fil
  « Activité récente ». Correction : exclues du fil (toujours comptées), index `events(account_id, id)` dans
  la migration 002. **Test** : `test_public_page_views_do_not_flood_activity_feed`.
- **B11** `templating.py:20-33` — dates et heures affichées en UTC au commerçant. Correction : conversion dans
  `APP_TIMEZONE`.
- **B12** `cli.py:104` — nom de fichier du rapport construit à partir du nom de l'établissement (caractères
  arbitraires, `/`). Correction : `slugify`.
- **B13** `cli.py:252` — `avis google link` pouvait relier une fiche déjà reliée à un autre établissement.
  Correction : refus explicite (voir C1).
- **B14** `billing.py` (`Access.sms_quota_plan`), `models.py` (`Review.created`), `sms.py` (`_SafeDict`) —
  code mort supprimé ; `billing.py:149` (`_customer_id`) factorise trois copies de la même extraction.
- **B15** `repo.py:360` — `remove_optout` ne disait pas si quelque chose avait été retiré. Correction : retourne
  un booléen, journalisation `optout_removed`.
- **B16** `drafts.py:44` — consigne système figée à 60 mots (voir M14) ; `services.py:30` — cache de rapport
  porté par `Services` plutôt que par un global de module (isolation entre tests et instances).
- **B17** `README.md`, `.env.example` — nombre de tests, `SESSION_SECRET` obligatoire en https,
  `APP_TIMEZONE`, `SMS_WEBHOOK_TOKEN`, authentification du webhook, provenance des brouillons, portail
  plutôt que second Checkout, lecture seule dans les jobs, avis modifiés, limites d'import.

---

## À faire plus tard (non prioritaire ou hors périmètre d'une revue)

1. **Limitation de débit** sur `/login`, `/r/{slug}/message`, `/webhooks/*` et `/app/inbox/sync` : à faire
   devant l'app (Caddy `rate_limit`, règles Cloudflare) ; en interne, seul l'anti-rafale par adresse existe.
2. **Lien magique consommé par les scanners d'emails** (prévisualisation des liens) : passer par une page de
   confirmation en POST plutôt que de consommer le jeton sur le GET.
3. **Ordre des événements Stripe** : pas de garde sur `created` ; `checkout.session.completed` pose
   optimistement `active` (corrigé ensuite par `customer.subscription.*`, mais pas si ces événements arrivent
   dans le désordre).
4. **Traitements longs dans la requête web** : import CSV (jusqu'à 500 envois séquentiels), « Synchroniser »
   (poll + brouillons LLM), création d'établissement (génération des exemples) peuvent dépasser le `--timeout 60`
   de gunicorn. Un job de fond (file en base + `avis` en cron) serait plus sûr.
5. **Pagination** : `LiveGBPClient.list_reviews` relit toutes les pages à chaque poll (quota 300 req/min) ;
   un arrêt anticipé quand une page ne contient que des avis connus et inchangés s'impose au-delà de quelques
   fiches. La boîte de réception coupe à 200 avis sans pagination.
6. **htmx chargé depuis unpkg sans `integrity`** : vendre le fichier dans `static/` ou ajouter un hash SRI.
7. **`settings` entier exposé aux gabarits** (`deps.render_template`) : passer un sous-ensemble sans secrets.
8. **`SUPPORT_EMAIL`** est lu mais utilisé nulle part (mentions légales à compléter) ; à brancher ou retirer.
9. **Purge** des sessions expirées et des liens magiques ; croissance de `events` (vues de page publique :
   agréger par jour plutôt qu'une ligne par vue).
10. **Risque résiduel C1** : un Place ID est public ; un commerçant malveillant peut déclarer le Place ID d'un
    concurrent *avant* celui-ci et relier sa fiche (si le compte opérateur y a accès). L'unicité bloque le
    détournement d'une fiche déjà reliée, mais la première liaison en mode `live` mérite toujours la
    vérification humaine prévue (`avis google link` après invitation comme gestionnaire).
11. Courses rares non traitées : `unique_slug` et `get_or_create_account` (erreur `UNIQUE` → 500), quota vérifié
    hors transaction (deux envois parallèles peuvent dépasser d'une unité).
12. `Reply-To` des demandes par email = email de connexion du commerçant si aucun email de notification :
    décision produit à confirmer (le client final voit cette adresse).
