# Avis Clients — SaaS « plus d'avis, une réponse à chacun » (plan 1)

Application web + jobs pour les commerces de proximité (restaurant, coiffeur, garage, cabinet) :

- **Collecter** : page publique d'avis `/r/{slug}` mobile-first, QR code (PNG, SVG, affiche A6 imprimable), demandes d'avis par SMS / WhatsApp / email avec modèle éditable, quota mensuel par formule et liste STOP.
- **Répondre** : récupération des avis Google toutes les 15 minutes, brouillon de réponse rédigé par LLM dans le ton de l'établissement (3 presets, 3 exemples validés par le commerçant), alerte email immédiate sur les avis à 1-2 étoiles, boîte de réception HTMX (publier / modifier / régénérer / ignorer), option d'auto-publication des réponses aux avis ≥ 4 étoiles (désactivée par défaut).
- **Suivre** : rapport mensuel HTML par établissement (volume, note, évolution, mots fréquents, délai de réponse, 3 recommandations LLM).
- **Vendre** : connexion par lien magique, essai 14 jours, Stripe Checkout + portail client + webhooks signés, formules Solo 19 € / Pro 29 € / Réseau 59 € HT, lecture seule après l'essai sans abonnement, landing, pages légales à compléter.

Tout ce qui touche l'extérieur a un mode simulé par défaut : LLM `mock`, email `console`, SMS `dry-run`, Google Business Profile `mock` (fixtures), Stripe désactivé sans clé. **Rien n'est envoyé ni publié tant que les clés ne sont pas renseignées.**

## Installation

```bash
cd apps/avis-clients
uv venv .venv
uv pip install -e ../../packages/core -e ".[dev]"
.venv/bin/pytest -q          # 95 tests, aucun appel réseau
.venv/bin/ruff check .
```

Python ≥ 3.11. Dépendances : FastAPI, Jinja2, HTMX (CDN côté navigateur), Typer, qrcode + Pillow, stripe, google-auth(-oauthlib), itsdangerous, et `packages/core` (LLM, mail, réglages, SQLite).

## Démarrage rapide (mode démo, zéro clé)

```bash
cp .env.example .env            # puis LLM_PROVIDER=mock si Ollama n'est pas lancé
.venv/bin/avis demo             # compte demo@exemple.fr + « Boulangerie Dupont » + 8 avis de fixtures → 7 brouillons, 2 alertes
.venv/bin/uvicorn avis_clients.web:app --reload
```

Ouvrir http://localhost:8000, cliquer **Connexion**, saisir `demo@exemple.fr` : en mode `MAIL_PROVIDER=console`, le lien de connexion est imprimé dans la sortie du serveur (`[avis] lien de connexion pour …`). Ensuite : tableau de bord → établissement (QR, affiche, réglages) → **Boîte de réception** (publier un brouillon : la publication part dans le mock Google) → **Demandes d'avis** (envoi SMS dry-run, import CSV, liste STOP) → **Abonnement** (Checkout Stripe si configuré).

Parcours de bout en bout testé : inscription par lien magique → création d'établissement avec exemples de ton générés → QR / page publique / affiche → demande SMS dry-run (quota, STOP) → poll des avis mock → brouillons + alerte 1 étoile → publication (mock) → webhook Stripe signé → rapport mensuel.

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
| `REPLY_MAX_WORDS`, `ALERT_MAX_RATING`, `AUTO_PUBLISH_MIN_RATING` | garde-fous des réponses | 60, 2, 4 |

## Lancement et jobs

- **Web** : `uvicorn avis_clients.web:app --host 127.0.0.1 --port 8000 --proxy-headers` (ou `avis serve`). Les migrations SQL (`src/avis_clients/migrations/*.sql`) s'appliquent au démarrage et via `avis init-db`.
- **`avis poll-reviews`** (toutes les 15 min) : nouveaux avis → brouillon LLM → `draft` ; avis ≤ 2 étoiles → brouillon « désolé + invitation à nous contacter » + email d'alerte immédiat ; réponses déjà présentes sur Google → `published` ; avis modifiés par le client (texte ou note) → mise à jour, nouveau brouillon s'il n'était pas encore validé, alerte s'il devient négatif ; auto-publication si l'option est activée, note ≥ 4 **et brouillon sorti conforme du modèle** (`reply_draft_source = llm` ; un brouillon générique ou nettoyé mécaniquement attend toujours une validation) ; republication des réponses `approved` dont la publication avait échoué. Les comptes en lecture seule (essai terminé sans abonnement) sont ignorés : ni brouillon, ni alerte, ni publication.
- **`avis monthly-report [--month AAAA-MM] [--dry-run] [--out dossier] [--force]`** (le 1er du mois) : un email HTML par établissement des comptes Pro / Réseau (et en essai).
- Administration : `avis accounts list|create|set-plan|extend-trial`, `avis establishments`, `avis events`, `avis optouts add|list`, `avis sms-test 06…`, `avis google auth|locations|link`, `avis demo`.

### Planification launchd (Mac mini)

Les plists sont dans `deploy/launchd/` (adapter les chemins) :

```bash
mkdir -p data/logs
cp deploy/launchd/fr.avisclients.*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/fr.avisclients.poll-reviews.plist    # StartInterval 900 s
launchctl load ~/Library/LaunchAgents/fr.avisclients.monthly-report.plist  # le 1er à 07:30
launchctl load ~/Library/LaunchAgents/fr.avisclients.web.plist             # si le web tourne aussi sur le Mac
```

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

- **A. Tout sur le Mac mini, exposé par Cloudflare Tunnel** (recommandé pour démarrer, LLM local gratuit) : `launchd` lance le web (plist fourni) et les jobs ; `cloudflared tunnel` publie `127.0.0.1:8000` sur `avis.exemple.fr` (TLS et protection DDoS gérés par Cloudflare). Le VPS n'est pas nécessaire.
- **B. Tout sur le VPS** : `deploy/vps/avis-clients.service` (gunicorn + UvicornWorker) derrière Caddy (`deploy/vps/Caddyfile`, TLS automatique), jobs par timers systemd (`deploy/vps/avis-clients-poll.timer`). Le LLM est alors soit Anthropic (`LLM_PROVIDER=anthropic`, plafond de dépense), soit Ollama sur le Mac mini exposé au VPS via un tunnel privé (`OLLAMA_BASE_URL`). Sauvegarder `data/` (SQLite en WAL : `sqlite3 data/avis-clients.db ".backup …"`).

Séparer web (VPS) et jobs (Mac mini) demanderait Postgres ou une API interne : non fait, volontairement, pour cette première tranche.

Installation VPS : `apt install caddy`, utilisateur `avis`, clone dans `/srv/avis-clients`, `uv venv && uv pip install -e packages/core -e "apps/avis-clients[dev]" gunicorn`, `.env` complet (`APP_BASE_URL=https://…`, cookies `Secure` automatiques), `systemctl enable --now avis-clients`, Caddyfile dans `/etc/caddy/`.

## Points juridiques (voir aussi `/legal/*`, modèles à compléter)

- **RGPD** : pour les numéros et emails des clients finaux, le commerçant est responsable de traitement et le service **sous-traitant** (DPA dans les CGV, hébergement UE, suppression à la résiliation). Seuls les textes d'avis publics sont transmis au LLM, jamais les coordonnées.
- **SMS** : message **sans contenu commercial**, émetteur identifié, désinscription STOP respectée automatiquement, pas de relance ; le commerçant atteste que les destinataires sont des clients réels ayant accepté d'être contactés (rappel affiché dans l'interface).
- **Aucun filtrage des avis** : la page publique mène tous les clients au même formulaire Google, sans question préalable ; le formulaire « nous écrire en privé » est présenté **après** le bouton Google et ne conditionne rien (règles Google, code de la consommation / directive Omnibus). Jamais d'avis rédigé à la place du client.
- **Réponses IA** : brouillons toujours validés par un humain (sauf option explicite pour les ≥ 4 étoiles, et seulement si le brouillon est sorti conforme du modèle) ; le prompt interdit promesses commerciales et données personnelles, limite à `REPLY_MAX_WORDS` mots, et traite le texte de l'avis comme une donnée non fiable (injection de prompt) avec contrôles et nettoyage mécanique a posteriori ; les recommandations du rapport mensuel subissent le même contrôle (lien, email ou numéro → écartée ; 40 mots max).

## Décisions prises (à discuter)

- Essai 14 jours = fonctions Pro avec 1 établissement et 10 SMS, sans carte bancaire ; ensuite lecture seule.
- `past_due` compté comme actif (Stripe relance le paiement) ; `canceled`/`unpaid` → formule `none`.
- Rapport mensuel réservé aux formules Pro et Réseau (et à l'essai, pour montrer la valeur) ; aperçu dans l'interface pour tous (`/app/establishments/{id}/report`).
- En mode `mock`, chaque établissement est relié automatiquement à une fiche fictive (`accounts/mock/locations/{slug}`) servie par les fixtures, pour un parcours complet sans API.
- Un seul compte Google opérateur (invitation comme gestionnaire) plutôt qu'un OAuth par commerçant.
- Canal WhatsApp uniquement via Twilio ; emails de demande d'avis sans quota.
- Le bouton de la page publique pointe **directement** vers l'URL Google (pas de redirection intermédiaire) ; seules les vues de page sont comptées.
- Une connexion SQLite par requête, WAL, `busy_timeout` 5 s ; protection CSRF légère par cookie `SameSite=Lax` + contrôle de l'en-tête `Origin` sur les écritures ; en-têtes `X-Content-Type-Options`, `X-Frame-Options: DENY` et `Referrer-Policy` sur toutes les réponses, `Cache-Control: no-store` sur les pages privées ; un lien de connexion par adresse et par minute, consommé atomiquement (usage unique garanti même en cas de double clic).

## Ce qui est simulé ou non vérifié

- Appels Google (approbation en attente), smsmode, Twilio, Stripe : implémentés d'après la documentation, testés hors ligne (transport httpx factice, session factice, signature HMAC calculée localement). Premier appel réel à vérifier pour chacun.
- Facebook / Tripadvisor (P1-4) : non implémentés (colonne `platform` prête).
- Pas de limitation de débit sur le formulaire public ni sur `/login` (au-delà d'un lien par adresse et par minute ; pot de miel seulement) ; à ajouter derrière Caddy/Cloudflare si abus. Voir `REVIEW.md` (revue croisée QA-1) pour les défauts corrigés et ceux laissés « à faire plus tard ».

## Dépend d'Hugo

Compte Stripe (produits, prix, webhook), fournisseur SMS (smsmode ou Twilio, émetteur déclaré), email transactionnel (Resend/SMTP avec SPF/DKIM), projet Google Cloud + **demande d'accès à l'API Business Profile** (fiche vérifiée depuis 60 jours + site), nom de domaine, textes légaux à compléter (`[CROCHETS]`), choix Mac mini + Cloudflare Tunnel ou VPS.
