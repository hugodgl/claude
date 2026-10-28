# Avis Clients — SaaS « plus d'avis, une réponse à chacun » (plan 1)

Application web + jobs pour les commerces de proximité (restaurant, coiffeur, garage, cabinet) :

- **Collecter** : page publique d'avis `/r/{slug}` mobile-first (bouton Google en premier, puis, si elles sont reliées, les liens Facebook et Tripadvisor, toujours sans filtrage par note), QR code (PNG, SVG, affiche A6 imprimable), demandes d'avis par SMS / WhatsApp / email avec modèle éditable, quota mensuel par formule et liste STOP.
- **Répondre** : récupération des avis **Google, Facebook et Tripadvisor** toutes les 15 minutes (une boîte de réception unique, badge et filtre par plateforme), brouillon de réponse rédigé par LLM dans le ton de l'établissement (3 presets, 3 exemples validés par le commerçant), alerte email immédiate sur les avis à 1-2 étoiles quelle que soit la plateforme, boîte de réception HTMX (publier / modifier / régénérer / ignorer), option d'auto-publication des réponses aux avis ≥ 4 étoiles (désactivée par défaut, jamais pour Tripadvisor qui n'a pas d'API de réponse).
- **Suivre** : rapport mensuel HTML par établissement (volume, note, évolution, ventilation par plateforme, mots fréquents, délai de réponse, 3 recommandations LLM).
- **Vendre** : connexion par lien magique, essai 14 jours, Stripe Checkout + portail client + webhooks signés, formules Solo 19 € / Pro 29 € / Réseau 59 € HT, lecture seule après l'essai sans abonnement, landing, pages légales à compléter.

Tout ce qui touche l'extérieur a un mode simulé par défaut : LLM `mock`, email `console`, SMS `dry-run`, Google Business Profile `mock` (fixtures), Facebook `mock`, Tripadvisor `mock`, Stripe désactivé sans clé. **Rien n'est envoyé ni publié tant que les clés ne sont pas renseignées.**

## Installation

```bash
cd apps/avis-clients
uv venv .venv
uv pip install -e ../../packages/core -e ".[dev]"
.venv/bin/pytest -q          # 118 tests, aucun appel réseau
.venv/bin/ruff check .
```

Python ≥ 3.11. Dépendances : FastAPI, Jinja2, HTMX (CDN côté navigateur), Typer, qrcode + Pillow, stripe, google-auth(-oauthlib), httpx (Facebook, Tripadvisor), cryptography (chiffrement des jetons), itsdangerous, et `packages/core` (LLM, mail, réglages, SQLite).

## Démarrage rapide (mode démo, zéro clé)

```bash
cp .env.example .env            # puis LLM_PROVIDER=mock si Ollama n'est pas lancé
.venv/bin/avis demo             # compte demo@exemple.fr + « Boulangerie Dupont » reliée à Google, Facebook et Tripadvisor (fixtures)
                                # → 19 avis lus (8 Google, 6 Facebook, 5 Tripadvisor), 17 brouillons, 5 alertes ; `--google-only` pour Google seul
.venv/bin/uvicorn avis_clients.web:app --reload
```

Ouvrir http://localhost:8000, cliquer **Connexion**, saisir `demo@exemple.fr` : en mode `MAIL_PROVIDER=console`, le lien de connexion est imprimé dans la sortie du serveur (`[avis] lien de connexion pour …`). Ensuite : tableau de bord → établissement (QR, affiche, réglages, **plateformes d'avis**) → **Boîte de réception** (publier un brouillon : la publication part dans le mock Google ou Facebook ; pour Tripadvisor, « Copier la réponse et ouvrir Tripadvisor » puis confirmation) → **Demandes d'avis** (envoi SMS dry-run, import CSV, liste STOP) → **Abonnement** (Checkout Stripe si configuré).

Parcours de bout en bout testé : inscription par lien magique → création d'établissement avec exemples de ton générés → QR / page publique / affiche → demande SMS dry-run (quota, STOP) → liaison d'une Page Facebook et d'une fiche Tripadvisor → poll des avis mock des trois plateformes → brouillons + alertes 1-2 étoiles → publication (mock Google, commentaire mock Facebook, confirmation manuelle Tripadvisor) → webhook Stripe signé → rapport mensuel ventilé par plateforme.

## Configuration (`.env`)

| Variable | Rôle | Défaut |
|---|---|---|
| `APP_BASE_URL` | URL publique (liens des emails, QR, Stripe, URL signée des webhooks) | `http://localhost:8000` |
| `SESSION_SECRET` | signature du cookie de session (itsdangerous) ; **obligatoire et ≥ 32 caractères dès que `APP_BASE_URL` est en https** : l'app refuse de démarrer sinon | valeur de dev tolérée en http |
| `APP_TIMEZONE` | fuseau métier : mois des quotas et des rapports, affichage des dates | `Europe/Paris` |
| `DATA_DIR`, `DB_PATH` | dossier de données / base SQLite | `data/`, `data/avis-clients.db` |
| `TRIAL_DAYS`, `TRIAL_SMS_QUOTA` | durée d'essai, SMS offerts pendant l'essai | 14, 10 |
| `LLM_PROVIDER` (+ `OLLAMA_*`, `ANTHROPIC_*`) | fournisseur LLM via `core.llm.get_llm()` | `ollama` |
| `MAIL_PROVIDER` (+ `SMTP_*`, `RESEND_API_KEY`), `MAIL_FROM` | emails (liens magiques, alertes, rapports) | `console` |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_SOLO/PRO/RESEAU` | Stripe (clés de test d'abord) | vide = désactivé |
| `SMS_PROVIDER` | `dry-run` \| `smsmode` \| `twilio` | `dry-run` |
| `SMS_WEBHOOK_TOKEN` | jeton partagé exigé par le webhook SMS entrant (paramètre `token`) ; indispensable avec smsmode, facultatif avec Twilio (signature vérifiée) | vide |
| `SMS_SENDER`, `SMSMODE_API_KEY`, `SMSMODE_API` | smsmode (`rest` ou `http16`) | — |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`, `TWILIO_WHATSAPP_FROM` | Twilio (SMS + WhatsApp) | — |
| `GBP_MODE` | `mock` (fixtures) \| `live` (API Google) | `mock` |
| `GBP_FIXTURES_FILE` | fixtures du mode mock | fixtures livrées |
| `GOOGLE_OAUTH_CLIENT_SECRETS_FILE`, `GOOGLE_TOKEN_FILE` | identifiants « application de bureau », jeton écrit par `avis google auth` | — |
| `FACEBOOK_MODE` | `mock` (fixtures) \| `live` (Graph API, jeton de Page par établissement) | `mock` |
| `FACEBOOK_FIXTURES_FILE`, `FACEBOOK_GRAPH_VERSION` | fixtures du mode mock, version de la Graph API | fixtures livrées, `v21.0` |
| `TRIPADVISOR_MODE` | `mock` (fixtures) \| `live` (Content API, lecture seule) | `mock` |
| `TRIPADVISOR_API_KEY` | clé Content API (obligatoire en `live`) | — |
| `TRIPADVISOR_POLL_INTERVAL_MIN` | délai minimal entre deux lectures d'une même fiche (quota mensuel de la clé) ; `0` = à chaque poll | 360 |
| `TRIPADVISOR_FIXTURES_FILE` | fixtures du mode mock | fixtures livrées |
| `TOKENS_KEY` | clé Fernet de chiffrement des jetons de plateforme stockés en base (jetons de Page Facebook) ; **obligatoire en `FACEBOOK_MODE=live`** ; distincte de `SESSION_SECRET` | vide = chiffrement indisponible (liaison avec jeton refusée) |
| `REPLY_MAX_WORDS`, `ALERT_MAX_RATING`, `AUTO_PUBLISH_MIN_RATING` | garde-fous des réponses | 60, 2, 4 |

## Lancement et jobs

- **Web** : `uvicorn avis_clients.web:app --host 127.0.0.1 --port 8000 --proxy-headers` (ou `avis serve`). Les migrations SQL (`src/avis_clients/migrations/*.sql`) s'appliquent au démarrage et via `avis init-db`.
- **`avis poll-reviews [--platform google|facebook|tripadvisor|all] [--force] [-e ID]`** (toutes les 15 min) : parcourt **toutes les sources reliées** de chaque établissement (table `review_sources`). Nouveaux avis → brouillon LLM → `draft` ; avis ≤ 2 étoiles → brouillon « désolé + invitation à nous contacter » + email d'alerte immédiat (même règle sur les trois plateformes) ; réponses déjà présentes sur la plateforme (Google, réponse du propriétaire Tripadvisor) → `published` ; avis modifiés par le client (texte ou note) → mise à jour, nouveau brouillon s'il n'était pas encore validé, alerte s'il devient négatif ; auto-publication si l'option est activée, note ≥ 4, plateforme avec API de réponse (Google, Facebook) **et brouillon sorti conforme du modèle** (`reply_draft_source = llm` ; un brouillon générique ou nettoyé mécaniquement attend toujours une validation) ; republication des réponses `approved` dont la publication avait échoué. **Erreurs isolées** par source et par établissement : une source en échec (jeton Facebook expiré, quota Tripadvisor, réseau) passe en statut `error` avec le message, les autres continuent ; **compteurs par plateforme** dans le résumé et l'événement `poll_done` (`by_platform`). Les fiches Tripadvisor ne sont relues qu'après `TRIPADVISOR_POLL_INTERVAL_MIN` (`--force` l'ignore). Les comptes en lecture seule (essai terminé sans abonnement) sont ignorés : ni brouillon, ni alerte, ni publication.
- **`avis monthly-report [--month AAAA-MM] [--dry-run] [--out dossier] [--force]`** (le 1er du mois) : un email HTML par établissement des comptes Pro / Réseau (et en essai), avec la ventilation par plateforme.
- Administration : `avis accounts list|create|set-plan|extend-trial`, `avis establishments` (sources reliées), `avis events`, `avis optouts add|list`, `avis sms-test 06…`, `avis google auth|locations|link`, `avis sources list|link|unlink`, `avis demo [--google-only]`.

### Planification launchd (Mac mini)

Les plists sont dans `deploy/launchd/` (adapter les chemins) :

```bash
mkdir -p data/logs
cp deploy/launchd/fr.avisclients.*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/fr.avisclients.poll-reviews.plist    # StartInterval 900 s
launchctl load ~/Library/LaunchAgents/fr.avisclients.monthly-report.plist  # le 1er à 07:30
launchctl load ~/Library/LaunchAgents/fr.avisclients.web.plist             # si le web tourne aussi sur le Mac
```

## Plateformes d'avis

### Modèle commun

- Une **source** = un établissement × une plateforme (table `review_sources` : identifiant externe, nom affiché, URL publique « laisser un avis », jeton chiffré ou rien, statut `active` / `error` / `disabled`, dernière synchronisation, dernière erreur). Au plus une source par plateforme et par établissement.
- **Isolation entre comptes** (même règle que celle imposée pour Google en revue QA-1) : format de l'identifiant validé avant tout appel (fiche `accounts/…/locations/…`, identifiant numérique de Page, identifiant numérique de fiche), **un identifiant externe ne peut être relié qu'à un seul établissement** (contrôle applicatif + contrainte `UNIQUE (platform, external_id)` en base), et un compte ne relie que ce qu'il prouve posséder : fiche Google accessible au compte opérateur avec le bon Place ID, jeton de Page Facebook dont `GET /me` renvoie l'identifiant saisi. Tripadvisor est public et en lecture seule : aucune réponse n'est publiée en son nom.
- Google reste relié par les réglages (`google_location_name`) ou `avis google link` ; la colonne est **recopiée automatiquement** dans `review_sources` (migration 003 pour l'existant, puis à chaque modification). Un seul adaptateur par plateforme (`platforms.build_platform_clients` : `GoogleAdapter`, `facebook.py`, `tripadvisor.py`), tous sous le même protocole (`fetch_reviews`, `publish_reply`, `verify_source`, `can_reply`).
- Boîte de réception : badge de plateforme sur chaque avis, filtre par plateforme dès que deux plateformes sont reliées, mention explicite quand une recommandation Facebook sans note a été convertie en étoiles. Page publique : liens secondaires « Laisser un avis sur Facebook / Tripadvisor » **sous** le bouton Google, qui reste premier et sans question préalable. Rapport mensuel : tableau « Par plateforme » (volume, note moyenne, réponses).
- CLI : `avis sources list`, `avis sources link <établissement> facebook <id-page> --token-file jeton.txt` (ou `--token …`, qui reste dans l'historique du shell), `avis sources link <établissement> tripadvisor <location-id>`, `avis sources unlink <établissement> <plateforme>`, `avis poll-reviews --platform facebook`.

### Facebook (Graph API) — dépend d'une app Meta (Hugo)

- **Lecture** : `GET /{page-id}/ratings?fields=reviewer{name,id},rating,recommendation_type,review_text,created_time,open_graph_story{id},has_rating,has_review` avec un **jeton de Page** (permissions `pages_read_user_content` pour lire, `pages_manage_engagement` pour commenter, `pages_show_list` pour obtenir le jeton via `/me/accounts`), pagination `paging.next`, délai d'attente 30 s, jeton passé en en-tête `Authorization: Bearer` (jamais dans l'URL). **Réponse** : `POST /{open_graph_story_id}/comments` `{"message": …}` : la réponse est un commentaire public de la Page sous la publication de l'avis.
- **Recommandations sans note** (format Facebook depuis 2018) : `positive` → 5 étoiles, `negative` → 1 étoile, avec la mention « Recommandation Facebook sans note (« positive ») : comptée 5 étoiles » dans la boîte de réception et l'email d'alerte ; un avis sans note ni recommandation compte 3 étoiles. Les avis dont la publication est masquée (`open_graph_story` absent) sont importés mais ne peuvent pas recevoir de réponse par API.
- **Liaison** (réglages de l'établissement ou `avis sources link`) : saisir l'identifiant numérique de la Page (Page → À propos → Transparence de la Page) et un **jeton de Page longue durée**. En `live`, le jeton est vérifié par `GET /me?fields=id,name` : l'identifiant renvoyé doit être celui saisi (un jeton de Page ne prouve la possession que de sa propre Page), puis il est chiffré (Fernet, `TOKENS_KEY`) et stocké ; il n'est jamais réaffiché. Jeton expiré ou révoqué (erreur `OAuthException` / code 190) → source en `error` avec le message, le poll continue pour les autres sources ; il suffit d'enregistrer un nouveau jeton.
- **Obtenir un jeton de Page longue durée** : (1) créer une app Meta (type Business) sur developers.facebook.com, ajouter le produit « Facebook Login for Business » ou simplement utiliser l'**Explorateur de l'API Graph** ; (2) dans l'Explorateur, choisir l'app, « Jeton d'accès utilisateur », cocher `pages_show_list`, `pages_read_user_content`, `pages_manage_engagement`, générer et accepter ; (3) échanger ce jeton utilisateur court contre un jeton longue durée (`GET /oauth/access_token?grant_type=fb_exchange_token&client_id=…&client_secret=…&fb_exchange_token=…`, ou bouton « Prolonger le jeton » dans l'outil de débogage des jetons) ; (4) `GET /me/accounts?fields=id,name,access_token` avec ce jeton longue durée : chaque Page apparaît avec son **jeton de Page**, qui n'expire pas tant que le jeton utilisateur reste valide et que l'utilisateur garde son rôle sur la Page ; copier `id` et `access_token` dans les réglages. Business Suite : Paramètres → Rôles de la Page pour vérifier que l'utilisateur est bien administrateur.
- **Revue d'app Meta** : tant que l'app est en mode développement, seuls ses rôles (administrateurs, développeurs, testeurs) peuvent générer des jetons ; pour relier les Pages de commerçants quelconques (usage multi-pages), les permissions `pages_read_user_content` et `pages_manage_engagement` doivent passer l'**App Review** (vidéo de démonstration, politique de confidentialité `/legal/confidentialite`), avec **vérification de l'entreprise** (Business Verification) pour l'accès avancé. En attendant, chaque commerçant peut être ajouté comme testeur de l'app, ou nous ajouter comme administrateur de sa Page (le jeton est alors généré avec notre compte).
- **Limites connues** : les réponses déjà publiées directement sur Facebook avant la liaison ne sont pas détectées (une lecture des commentaires coûterait un appel par avis) : marquer l'avis « ignoré » ; `GET /{page-id}/ratings` ne renvoie pas d'identifiant d'avis stable au-delà de `open_graph_story.id`, utilisé comme identifiant externe.

### Tripadvisor (Content API) — dépend d'une clé API (Hugo)

- **Pas d'API publique pour répondre aux avis** : c'est une limite de Tripadvisor, pas de l'outil. Le brouillon est généré normalement (mêmes garde-fous, mêmes alertes ≤ 2 étoiles) ; dans la boîte de réception, le bouton « Publier » devient **« Copier la réponse et ouvrir Tripadvisor »** (copie du texte dans le presse-papiers + ouverture de la page de l'avis dans un nouvel onglet, où le propriétaire connecté dispose du bouton « Répondre » ; à défaut l'espace propriétaire https://www.tripadvisor.fr/Owners → Centre de gestion → Avis), puis **« J'ai publié la réponse sur Tripadvisor »** passe l'avis en statut `published_manually` (compté comme publié dans le tableau de bord et le rapport). L'auto-publication ne s'applique jamais à Tripadvisor (événement `auto_publish_skipped`, raison `platform_no_reply_api`). Au poll suivant, si l'API renvoie une `owner_response`, l'avis passe en `published`.
- **Lecture** : `GET https://api.content.tripadvisor.com/api/v1/location/{locationId}/reviews?key=…&language=fr` renvoie les **5 avis les plus récents** (titre + texte, note, auteur, URL de l'avis, réponse du propriétaire éventuelle) ; `…/location/{locationId}/details` sert à vérifier la fiche au moment de la liaison et fournit `web_url` / `write_review` (lien « laisser un avis » de la page publique). La clé est globale à l'application (paramètre `key`, exigé ainsi par l'API) et doit être **autorisée pour l'adresse IP sortante** du serveur dans le portail développeur (sinon 401/403 → source en `error`).
- **Quota** : la clé gratuite est limitée (de l'ordre de 5 000 appels par mois au moment de la rédaction ; vérifier dans le portail). Un poll toutes les 15 minutes ferait ~2 900 appels par mois **par fiche** : les fiches Tripadvisor ne sont donc relues qu'après `TRIPADVISOR_POLL_INTERVAL_MIN` (6 h par défaut, soit ~120 appels par mois et par fiche ; après une erreur, même délai avant un nouvel essai). Le bouton « Synchroniser maintenant » respecte ce délai ; `avis poll-reviews --platform tripadvisor --force` l'ignore. HTTP 429 → source en `error` jusqu'au prochain intervalle.
- **Liaison** : identifiant numérique de la fiche (le nombre après `d` dans l'URL `…-d1234567-…`), vérifié par `location/{id}/details` en `live` ; la fiche étant publique, la vérification ne prouve pas la propriété : il n'y a de toute façon **aucune écriture** côté Tripadvisor, et un identifiant déjà relié à un autre établissement est refusé.

### Chiffrement des jetons (`TOKENS_KEY`)

Les jetons de Page Facebook sont chiffrés en base avec Fernet (`cryptography`) et une clé **dédiée** `TOKENS_KEY`, volontairement distincte de `SESSION_SECRET` : changer le secret de session (invalider les cookies après un incident) ne doit pas rendre les jetons illisibles, et la clé de chiffrement n'a pas à transiter par le module de signature des cookies. Génération : `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Sans clé, toute liaison avec jeton est refusée avec un message explicite (jamais de stockage en clair) ; `FACEBOOK_MODE=live` refuse de démarrer sans clé ; si la clé change, les sources concernées passent en `error` (« TOKENS_KEY a changé… ») et il faut enregistrer de nouveau le jeton. Pas de rotation automatisée.

## Accès à l'API Google Business Profile (dépend d'Hugo)

Le mode `mock` permet de tout construire et démontrer. Le mode `live` exige une approbation manuelle de Google :

1. **Prérequis** : une fiche Google Business Profile vérifiée **depuis au moins 60 jours** appartenant à l'entreprise qui demande l'accès, un site web présentant le service, un projet Google Cloud avec écran de consentement OAuth renseigné (nom, domaine, politique de confidentialité : `/legal/confidentialite`).
2. **Formulaire** « Business Profile APIs – Basic API Access » (Google Business Profile API Prerequisites / Request access) : décrire l'usage (lecture des avis et réponse au nom des commerçants qui nous ajoutent comme gestionnaire). Délai constaté : ~14 jours, parfois des allers-retours par email.
3. **Après approbation** : activer dans le projet *My Business Account Management API*, *My Business Business Information API* et *Google My Business API (v4)* ; le quota passe de **0 à 300 requêtes/minute** (demander une hausse si > 100 fiches). Créer des identifiants OAuth **« Application de bureau »**, télécharger le JSON → `GOOGLE_OAUTH_CLIENT_SECRETS_FILE`.
4. Sur le Mac mini : `GBP_MODE=live`, puis `avis google auth` (ouvre le navigateur, scope `https://www.googleapis.com/auth/business.manage`, jeton en `data/google_token.json`, mode 600), `avis google locations` pour lister les fiches accessibles, `avis google link <id>` pour relier un établissement par son Place ID (ou saisir `accounts/…/locations/…` dans les réglages : la fiche doit être accessible au compte opérateur, correspondre au Place ID de l'établissement et n'être reliée à aucun autre établissement, sans quoi un commerçant pourrait lire et répondre aux avis d'un autre).
5. **Modèle d'accès** retenu : un seul compte Google « opérateur » (le nôtre) ; chaque commerçant nous **invite comme gestionnaire** de sa fiche (Google Business Profile → Utilisateurs). C'est le modèle le plus simple pour démarrer ; un flux OAuth par commerçant (web) est la V2 si l'invitation freine les ventes.

Endpoints utilisés : `GET https://mybusiness.googleapis.com/v4/{accounts/*/locations/*}/reviews` (paginé), `PUT …/reviews/{reviewId}/reply` `{"comment": …}`, `GET https://mybusinessaccountmanagement.googleapis.com/v1/accounts`, `GET https://mybusinessbusinessinformation.googleapis.com/v1/{account}/locations?readMask=name,title,metadata`. Ils sont écrits d'après la documentation et testés sur une session factice : **le premier appel réel doit être vérifié** (`avis google locations`).

## SMS et WhatsApp

- `dry-run` (défaut) : rien n'est envoyé, la demande est enregistrée en base avec le statut `dry-run` et journalisée.
- `smsmode` : API REST v1 `POST https://rest.smsmode.com/sms/v1/messages` (en-tête `X-Api-Key`, numéro au format `33612345678`) ou API HTTP 1.6 `sendSMS.do` (`SMSMODE_API=http16`). Les deux sont écrites d'après la documentation publique : **vérifier au premier envoi** (`avis sms-test 06…`). smsmode ne gère que le SMS.
- `twilio` : `POST /2010-04-01/Accounts/{SID}/Messages.json` ; WhatsApp via les préfixes `whatsapp:` (`TWILIO_WHATSAPP_FROM`).
- **STOP** : webhook `GET|POST /webhooks/sms/inbound` (Twilio : `From`/`Body`, y compris `whatsapp:+33…` ; smsmode : `numero`/`message`, numéro au format `33612345678`). Le webhook est **authentifié** : avec Twilio, l'en-tête `X-Twilio-Signature` est vérifié (HMAC-SHA1 de l'URL publique `APP_BASE_URL/webhooks/sms/inbound` et des paramètres POST, clé `TWILIO_AUTH_TOKEN`) ; avec smsmode, qui ne signe pas ses callbacks, renseigner `SMS_WEBHOOK_TOKEN` et déclarer l'URL de callback avec `?token=<valeur>` ; sans signature ni jeton valide → 403 (seul `dry-run` sans jeton reste ouvert, pour la démo). Un STOP inscrit le numéro en opposition pour le compte du dernier envoi (sinon globalement) ; la liste est aussi gérable depuis l'interface (ses propres oppositions) et `avis optouts` (toutes). Tout envoi vérifie la liste avant le quota.
- **Quotas mensuels** (SMS + WhatsApp, emails illimités) : essai 10, Solo 0, Pro 100, Réseau 300. Le mois est celui du fuseau `APP_TIMEZONE` (Europe/Paris), pas le mois UTC. L'import CSV est limité à 1 Mo et 500 contacts par fichier.
- Les numéros sont normalisés en E.164 (`06 12 34 56 78` → `+33612345678`). Modèle par défaut : « Bonjour {prenom}, merci pour votre visite chez {etablissement}. Un avis en 30 s nous aide beaucoup : {lien}. Répondre STOP pour ne plus recevoir de message. » Le modèle édité doit garder `{lien}` et la mention STOP.

## Stripe

1. Créer 3 produits récurrents mensuels (Solo 19 €, Pro 29 €, Réseau 59 € HT) et copier les `price_…` dans `.env`.
2. Webhook → `https://<domaine>/webhooks/stripe`, événements `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted` ; copier `whsec_…`. En local : `stripe listen --forward-to localhost:8000/webhooks/stripe`.
3. Activer le portail client (Stripe Dashboard → Billing → Customer portal) pour le bouton « Gérer mon abonnement ».

La signature est vérifiée avec `stripe.Webhook.construct_event` ; les événements sont idempotents (table `stripe_events` : réservation de l'identifiant en `INSERT OR IGNORE`, libérée si le traitement échoue pour que la relance de Stripe rejoue l'événement). Le plan est déduit du `price` de l'abonnement (repli : `metadata.plan`). La fin d'un abonnement autre que l'abonnement courant du compte (ancien abonnement résilié à échéance après un nouveau Checkout) est ignorée. Un compte déjà abonné qui choisit une autre formule est envoyé vers le **portail client** : jamais un second Checkout, qui créerait un second abonnement facturé en parallèle. **Garde d'accès** : abonnement `active`/`trialing`/`past_due` → accès complet ; sinon essai de 14 jours (fonctions Pro, 1 établissement, 10 SMS) ; sinon **lecture seule** (toute écriture sous `/app` redirige vers `/billing`, 402 en HTMX ; les jobs n'appellent plus le modèle pour ces comptes et l'aperçu du rapport affiche des recommandations génériques).

## Déploiement

La base est **SQLite** : le web et les jobs doivent lire le même fichier, donc tourner sur la **même machine**. Deux options :

- **A. Tout sur le Mac mini, exposé par Cloudflare Tunnel** (recommandé pour démarrer, LLM local gratuit) : `launchd` lance le web (plist fourni) et les jobs ; `cloudflared tunnel` publie `127.0.0.1:8000` sur `avis.exemple.fr` (TLS et protection DDoS gérés par Cloudflare). Le VPS n'est pas nécessaire. L'adresse IP sortante à déclarer pour la clé Tripadvisor est alors celle de la box du Mac mini (une IP dynamique obligera à la mettre à jour dans le portail).
- **B. Tout sur le VPS** : `deploy/vps/avis-clients.service` (gunicorn + UvicornWorker) derrière Caddy (`deploy/vps/Caddyfile`, TLS automatique), jobs par timers systemd (`deploy/vps/avis-clients-poll.timer`). Le LLM est alors soit Anthropic (`LLM_PROVIDER=anthropic`, plafond de dépense), soit Ollama sur le Mac mini exposé au VPS via un tunnel privé (`OLLAMA_BASE_URL`). Sauvegarder `data/` (SQLite en WAL : `sqlite3 data/avis-clients.db ".backup …"`) **et** `TOKENS_KEY` (sans la clé, les jetons sauvegardés sont inutilisables).

Séparer web (VPS) et jobs (Mac mini) demanderait Postgres ou une API interne : non fait, volontairement, pour cette première tranche.

Installation VPS : `apt install caddy`, utilisateur `avis`, clone dans `/srv/avis-clients`, `uv venv && uv pip install -e packages/core -e "apps/avis-clients[dev]" gunicorn`, `.env` complet (`APP_BASE_URL=https://…`, cookies `Secure` automatiques), `systemctl enable --now avis-clients`, Caddyfile dans `/etc/caddy/`.

## Points juridiques (voir aussi `/legal/*`, modèles à compléter)

- **RGPD** : pour les numéros et emails des clients finaux, le commerçant est responsable de traitement et le service **sous-traitant** (DPA dans les CGV, hébergement UE, suppression à la résiliation). Seuls les textes d'avis publics sont transmis au LLM, jamais les coordonnées. Les jetons de Page Facebook sont chiffrés au repos et supprimés avec la source ou l'établissement.
- **SMS** : message **sans contenu commercial**, émetteur identifié, désinscription STOP respectée automatiquement, pas de relance ; le commerçant atteste que les destinataires sont des clients réels ayant accepté d'être contactés (rappel affiché dans l'interface).
- **Aucun filtrage des avis** : la page publique mène tous les clients au même formulaire Google, sans question préalable ; les liens Facebook et Tripadvisor viennent ensuite, pour tous, et le formulaire « nous écrire en privé » est présenté **après** et ne conditionne rien (règles Google, code de la consommation / directive Omnibus). Jamais d'avis rédigé à la place du client.
- **Réponses IA** : brouillons toujours validés par un humain (sauf option explicite pour les ≥ 4 étoiles, et seulement si le brouillon est sorti conforme du modèle, sur une plateforme avec API de réponse) ; le prompt interdit promesses commerciales et données personnelles, limite à `REPLY_MAX_WORDS` mots, et traite le texte de l'avis comme une donnée non fiable (injection de prompt) avec contrôles et nettoyage mécanique a posteriori ; les recommandations du rapport mensuel subissent le même contrôle (lien, email ou numéro → écartée ; 40 mots max). Les conditions d'utilisation de Facebook et Tripadvisor imposent que les réponses soient publiées par le propriétaire de la Page / de la fiche : c'est le cas (jeton de la Page du commerçant, publication manuelle Tripadvisor).

## Décisions prises (à discuter)

- Essai 14 jours = fonctions Pro avec 1 établissement et 10 SMS, sans carte bancaire ; ensuite lecture seule.
- `past_due` compté comme actif (Stripe relance le paiement) ; `canceled`/`unpaid` → formule `none`.
- Rapport mensuel réservé aux formules Pro et Réseau (et à l'essai, pour montrer la valeur) ; aperçu dans l'interface pour tous (`/app/establishments/{id}/report`).
- En mode `mock`, chaque établissement est relié automatiquement à une fiche Google fictive (`accounts/mock/locations/{slug}`) servie par les fixtures, pour un parcours complet sans API ; Facebook et Tripadvisor se relient explicitement (réglages ou `avis sources link`), sauf pour `avis demo` qui relie les trois.
- Un seul compte Google opérateur (invitation comme gestionnaire) plutôt qu'un OAuth par commerçant ; pour Facebook, un **jeton de Page par établissement** (saisi par le commerçant ou par nous), stocké chiffré, plutôt qu'un flux OAuth web : plus simple tant que l'app Meta n'a pas passé l'App Review ; pour Tripadvisor, une clé Content API unique (lecture seule).
- `TOKENS_KEY` dédiée au chiffrement des jetons plutôt qu'une clé dérivée de `SESSION_SECRET` (voir plus haut).
- Google reste dans `establishments.google_location_name` (saisie du commerçant, guard C1) et est **recopié** dans `review_sources`, ce que parcourt le poll : une seule table de sources, sans casser le flux Google existant.
- Tripadvisor : lecture au plus toutes les 6 h par fiche (quota), statut `published_manually` distinct de `published` pour tracer ce qui a été publié par le commerçant lui-même.
- Canal WhatsApp uniquement via Twilio ; emails de demande d'avis sans quota.
- Le bouton de la page publique pointe **directement** vers l'URL Google (pas de redirection intermédiaire) ; seules les vues de page sont comptées ; les liens Facebook (`facebook.com/{page}/reviews/`) et Tripadvisor (`write_review` de la fiche) sont secondaires et absents si la plateforme n'est pas reliée ou si l'URL publique est inconnue.
- Une connexion SQLite par requête, WAL, `busy_timeout` 5 s ; protection CSRF légère par cookie `SameSite=Lax` + contrôle de l'en-tête `Origin` sur les écritures ; en-têtes `X-Content-Type-Options`, `X-Frame-Options: DENY` et `Referrer-Policy` sur toutes les réponses, `Cache-Control: no-store` sur les pages privées ; un lien de connexion par adresse et par minute, consommé atomiquement (usage unique garanti même en cas de double clic).

## Ce qui est simulé ou non vérifié

- Appels Google (approbation en attente), smsmode, Twilio, Stripe : implémentés d'après la documentation, testés hors ligne (transport httpx factice, session factice, signature HMAC calculée localement). Premier appel réel à vérifier pour chacun.
- **Facebook et Tripadvisor** : clients `live` écrits d'après la documentation publique (Graph API v21.0, Content API v1) et testés sur `httpx.MockTransport` (pagination, erreurs 4xx/5xx, jeton expiré, clé refusée, quota) ; **aucun appel réel n'a été fait** (pas d'app Meta ni de clé Tripadvisor). À vérifier au premier appel : champs exacts renvoyés par `/{page-id}/ratings` (notamment `open_graph_story` sur les recommandations récentes), format de `owner_response` et présence de `write_review` dans `location/{id}/details`. Les réponses déjà publiées sur Facebook avant la liaison ne sont pas détectées. Le mode `mock` (fixtures `facebook_ratings.json`, `tripadvisor_reviews.json`) couvre tout le parcours.
- Pas de limitation de débit sur le formulaire public ni sur `/login` (au-delà d'un lien par adresse et par minute ; pot de miel seulement) ; à ajouter derrière Caddy/Cloudflare si abus. Voir `REVIEW.md` (revue croisée QA-1) pour les défauts corrigés et ceux laissés « à faire plus tard ».

## Dépend d'Hugo

Compte Stripe (produits, prix, webhook), fournisseur SMS (smsmode ou Twilio, émetteur déclaré), email transactionnel (Resend/SMTP avec SPF/DKIM), projet Google Cloud + **demande d'accès à l'API Business Profile** (fiche vérifiée depuis 60 jours + site), **app Meta** (création, permissions `pages_read_user_content` / `pages_manage_engagement`, App Review + vérification d'entreprise pour relier les Pages d'autres commerçants ; en attendant, jetons générés depuis notre compte ajouté comme administrateur de la Page), **clé Tripadvisor Content API** (portail développeur, adresse IP sortante à déclarer, quota à surveiller), génération de `TOKENS_KEY` sur la machine de production, nom de domaine, textes légaux à compléter (`[CROCHETS]`), choix Mac mini + Cloudflare Tunnel ou VPS.
