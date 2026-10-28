# Veille marchés publics (plan 2)

Un email par jour, par abonné, avec les nouveaux appels d'offres de son métier et de sa zone, **résumés en langage clair et scorés** ; un brief hebdomadaire « qui a gagné quoi » tiré des données d'attribution (DECP). Le produit est un email, un site d'inscription minimal avec paiement Stripe (`vm web`), un espace de réglage sans mot de passe et une CLI de gestion des abonnés.

Niche d'exemple : entreprises d'espaces verts et paysagistes (CPV `773xxxxx`). Changer de métier = changer les préfixes CPV des abonnés (et `TRADE_LABEL` pour le ton des résumés).

## Ce que fait l'app

| Étape | Commande | Détail |
|---|---|---|
| Collecte | `vm collect` | BOAMP (portail Opendatasoft de la DILA), TED (API v3, requête experte), DECP (data.economie.gouv.fr) ; normalisation en `Notice` / `Award`, stockage SQLite sans doublon (`source` + `source_id`) |
| Score | `vm score` | règles déterministes 0-100 (CPV exact > préfixe, département, montant dans la fourchette, délai ≥ 10 jours, acheteur déjà vu) + résumé structuré et verdict par LLM local ; score final = 0,7 × règles + 0,3 × verdict |
| Digest | `vm digest --send` | HTML lisible sur mobile + version texte, sections « À regarder en priorité » (score ≥ 70) et « Autres marchés », lien vers l'avis source à chaque fois, mention « résumé assisté par IA ». Zéro email s'il n'y a rien de nouveau ; un avis n'est jamais envoyé deux fois au même abonné (table `deliveries`) |
| Brief hebdo | `vm brief-weekly --send` | attributions de la semaine par département, montants cumulés, acheteurs actifs et titulaires récurrents sur 12 mois (abonnés Pro) |
| Abonnés | `vm subscribers add\|list\|disable\|enable\|link\|sync-stripe` | email, libellé, préfixes CPV, départements, montant min/max, formule `essentiel` (2 départements) ou `pro` (6) ; lien signé vers l'espace abonné ; resynchronisation des statuts Stripe |
| Site et paiement | `vm web` | page d'offre, inscription → Stripe Checkout (abonnement mensuel ou annuel), webhook signé qui active l'abonné, email de bienvenue, espace `/compte` (réglages, portail client Stripe), pages légales. Voir « Site et paiement » |
| Suivi | `vm stats` | compteurs et dernières collectes, avec les signaux « sans CPV détecté » / « sans département » qui révèlent un mapping à corriger |

Le résumé LLM d'un avis est calculé **une fois** et partagé entre tous les abonnés concernés ; seul le score de règles est recalculé par abonné (ses critères diffèrent). Le LLM n'est appelé que pour les avis qui intéressent au moins un abonné actif et dont la date limite n'est pas passée.

## Installation

```bash
cd apps/veille-marches
uv venv .venv && uv pip install -e ../../packages/core -e ".[dev]"
cp .env.example .env            # puis ajuster
.venv/bin/pytest -q             # 102 tests, aucun appel réseau (Stripe et le SDK sont remplacés par des faux)
.venv/bin/ruff check .
```

Ou depuis la racine : `make setup-veille-marches && make test-veille-marches`.

## Configuration (`.env`)

Toutes les variables sont documentées dans `.env.example`. Les plus utiles :

| Variable | Rôle | Défaut |
|---|---|---|
| `LLM_PROVIDER`, `OLLAMA_MODEL` | fournisseur de résumé (`ollama` en prod, `mock` dans les tests, `anthropic` en option) | `ollama`, `qwen3:14b` |
| `LLM_ENABLED` | `false` = score par règles seulement (premier essai, panne d'Ollama) | `true` |
| `LLM_MAX_NOTICES_PER_RUN` | plafond d'appels LLM par passage de `vm score` | `200` |
| `MAIL_PROVIDER`, `MAIL_FROM`, `REPLY_TO` | `console` (affiche), `smtp`, `resend` ; les réponses des abonnés arrivent sur `REPLY_TO` | `console` |
| `DB_PATH`, `OUT_DIR` | base SQLite ; aperçus HTML/texte écrits par `vm digest` sans `--send` | `data/…` |
| `TRADE_LABEL`, `DEFAULT_CPV_PREFIXES` | métier (ton des résumés) et préfixes collectés quand aucun abonné n'est actif | espaces verts, `773` |
| `PRIORITY_THRESHOLD`, `DIGEST_LOOKBACK_DAYS` | seuil « priorité », ancienneté maximale d'un avis dans un digest | `70`, `7` |
| `MATCH_UNKNOWN_DEPARTMENT` | `true` = un avis sans département connu est proposé à tous les abonnés CPV (mention « zone non précisée ») | `false` |
| `COLLECT_SINCE_DAYS`, `COLLECT_LIMIT` | fenêtre de publication et plafond d'enregistrements par source | `2`, `500` |
| `BOAMP_*`, `TED_*`, `DECP_*` | URL de base, jeu de données, clé optionnelle, pays TED, taille de page | voir `.env.example` |
| `APP_BASE_URL`, `APP_SECRET_KEY`, `WEB_HOST`, `WEB_PORT`, `ACCOUNT_LINK_DAYS` | URL publique du site, clé de signature des liens « espace abonné », écoute d'uvicorn, validité des liens | `http://localhost:8000`, vide en démonstration (clé temporaire) mais **obligatoire dès qu'une clé Stripe existe**, `127.0.0.1`, `8000`, `7` |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_*` | clés Stripe (test puis réelles) et les 4 prix ; vide = **mode démonstration** (paiement simulé) | vide |
| `LEGAL_*` | identité de l'éditeur pour `/legal/*` (placeholders surlignés tant que vide) | vide |

## Commandes

```bash
vm subscribers add contact@paysages69.fr --label "Paysages 69" --cpv 773 --dept 69 --dept 01 --amount-max 500000 --plan pro
vm subscribers list                                 # état, formule, abonnement Stripe éventuel
vm subscribers disable contact@paysages69.fr        # (et enable) : coupe / rétablit les envois à la main
vm subscribers link contact@paysages69.fr [--days 7]  # lien signé vers /compte, à envoyer à la main si besoin (exige APP_SECRET_KEY)
vm subscribers sync-stripe [--dry-run]              # relit chaque abonnement chez Stripe, aligne status / active, envoie l'email de bienvenue manqué

vm web [--host 127.0.0.1] [--port 8000] [--reload]  # site public + espace abonné + webhook Stripe (uvicorn)

vm collect [--source boamp|ted|decp|all] [--since-days 2] [--limit 500] [--cpv 773] [--dry-run]
vm score   [--limit N] [--dry-run]
vm digest  [--send] [--dry-run] [--subscriber EMAIL]  # sans option : aperçus dans OUT_DIR, rien d'enregistré
vm brief-weekly [--send] [--dry-run] [--since-days 7] [--subscriber EMAIL] [--all-plans]
vm stats
```

`--dry-run` affiche sans envoyer ni écrire. Sans abonné actif, `vm score` utilise un profil par défaut (CPV `DEFAULT_CPV_PREFIXES`, toute la France) pour que les premiers essais produisent des résumés. Une source en erreur n'empêche pas les autres (code de sortie 1 seulement si toutes échouent) ; l'erreur est consignée dans `collect_runs` et visible dans `vm stats`. De même, un email en échec n'arrête pas la tournée de `vm digest --send` ni de `vm brief-weekly --send` : l'abonné concerné est affiché `ERREUR` (code de sortie 1), rien n'est enregistré pour lui et il est resservi au passage suivant.

## Planification suggérée (Mac mini, heure de Paris)

Les plists sont dans `deploy/macmini/launchd/` (`com.sideproject.veille.*`) et passent par `deploy/macmini/run.sh`, qui charge le `.env` de l'app.

| Heure | Commande | Pourquoi |
|---|---|---|
| 06:00 et 14:00 | `vm collect --source all --since-days 2` | le BOAMP publie deux fois par jour ; la fenêtre de 2 jours absorbe un passage raté |
| 06:30 | `vm score` | après la collecte, avant le digest ; ~5 à 15 s par avis avec `qwen3:14b` |
| 07:00 | `vm digest --send` | un email par abonné, seulement s'il y a du nouveau |
| dimanche 18:00 | `vm brief-weekly --send` | les DECP arrivent avec retard ; le dimanche laisse la semaine se remplir |

## Site et paiement

### Lancer

```bash
cd apps/veille-marches && .venv/bin/vm web            # http://127.0.0.1:8000 ; équivalent : .venv/bin/uvicorn veille_marches.web:app
```

Sans `STRIPE_SECRET_KEY`, le site tourne en **mode démonstration** (bandeau visible sur toutes les pages) : l'inscription crée l'abonné puis redirige vers `/demo/checkout/<session>` (identifiant de session non devinable, comme chez Stripe), une page locale qui joue le rôle de Stripe Checkout ; le bouton « Simuler un paiement réussi » applique exactement ce que ferait le webhook `checkout.session.completed` (activation, email de bienvenue). Le portail client est lui aussi simulé (`/demo/portal/<id>`, accessible seulement avec le lien signé de l'abonné, résiliation locale). Ces pages renvoient 404 dès qu'une clé Stripe est configurée. Cela permet de tester tout le parcours sur le Mac mini avant d'avoir un compte Stripe.

### Parcours

| Page | Rôle |
|---|---|
| `/` | promesse, cibles, fonctionnement, **exemple d'alerte** rendu depuis `fixtures/sample_notices.json` avec le vrai pipeline (filtrage, règles, score), les 2 formules HT, FAQ (couverture, données, IA, résiliation, facture, données personnelles) |
| `/exemple` | l'email complet tel qu'un abonné le reçoit (gabarit du digest) |
| `/inscription` | email, entreprise, métier (liste courte → préfixes CPV) + préfixes libres, départements (multi), montants min/max, formule, mensuel/annuel, acceptation des CGV, champ piège anti-robot. Crée un `Subscriber` **inactif** (`active=0`, `status=pending_payment`) puis redirige vers Stripe Checkout (`mode=subscription`, `client_reference_id` = id abonné, `customer_email`, `success_url=/merci?session_id={CHECKOUT_SESSION_ID}`, `cancel_url=/inscription`). Une adresse déjà active est refusée ; une adresse impayée ou en pause est renvoyée vers son lien d'accès (le paiement se régularise dans le portail, un second Checkout créerait un double abonnement) ; une fiche en attente ou résiliée est réutilisée (même client Stripe) |
| `/merci?session_id=…` | confirmation ; tant que le webhook n'est pas arrivé la page se rafraîchit toute seule, puis affiche le récapitulatif, la date du premier digest et le lien vers l'espace |
| `/compte?token=…` | espace sans mot de passe : modifier métier/CPV, départements (limite de la formule), montants ; bouton « Gérer mon abonnement » → portail client Stripe (carte, factures, changement de formule, résiliation). Lien signé HMAC-SHA256 (`<id>.<expiration>.<signature>`, 7 jours) envoyé dans l'email de bienvenue, dans le pied de chaque digest/brief (si `APP_SECRET_KEY` est défini) et sur demande via `/compte/lien` (réponse identique que l'adresse existe ou non) |
| `/webhooks/stripe` | signature vérifiée par `stripe.Webhook.construct_event` (tolérance 5 min) → 400 sinon ; idempotence par la table `stripe_events` (un `evt_…` rejoué répond `duplicate` et n'envoie rien ; un événement dont le traitement a échoué est oublié pour que le rejeu de Stripe soit appliqué). Événements hors ordre : un `checkout.session.completed` reçu après la résiliation ou la suspension du même abonnement, ou la fin d'un ancien abonnement d'un client réabonné, répondent `stale` sans rien changer ; un paiement différé (SEPA) répond `pending` jusqu'à `async_payment_succeeded`. Le détail d'un refus de signature n'apparaît que dans le journal |
| `/legal/mentions`, `/legal/cgv`, `/legal/confidentialite` | textes prêts avec les passages à compléter **surlignés en jaune** (variables `LEGAL_*` et quelques crochets dans les gabarits) |
| `/health`, `/robots.txt` | supervision ; `/compte`, `/merci`, `/demo/` exclus de l'indexation |

### États d'un abonné

`active` (colonne) décide seul des envois : `vm digest`, `vm brief-weekly`, `vm score` et la collecte ne regardent que les abonnés `active = 1` (vérifié par les tests). `status` explique pourquoi :

| Événement Stripe | `status` | `active` |
|---|---|---|
| inscription web, avant paiement | `pending_payment` | 0 |
| `checkout.session.completed` (ou `async_payment_succeeded`) | `active` | 1, email de bienvenue (une seule fois) |
| `customer.subscription.created` / `updated` → `active` / `trialing` | `active` | 1 ; email de bienvenue si l'abonné attendait son paiement (Stripe envoie souvent `created` avant le checkout), jamais deux fois |
| → `past_due` (impayé, Stripe relance) | `past_due` | 1 : accès maintenu pendant les réessais |
| → `unpaid` (relances épuisées), `paused`, `incomplete` | `unpaid` / `paused` / `pending_payment` | 0 |
| `customer.subscription.deleted` (ou `canceled`, `incomplete_expired`) | `canceled` | 0 |
| `vm subscribers disable` / `enable` | `disabled` / `active` | 0 / 1 |

Un changement de formule ou de périodicité fait depuis le portail Stripe est répercuté grâce à l'identifiant de prix (`STRIPE_PRICE_*` → formule, période). Un statut Stripe inconnu laisse l'état local tel quel (jamais d'activation par défaut). `vm subscribers sync-stripe` relit tous les abonnements connus : filet de sécurité si un webhook a été manqué (à planifier une fois par jour en production) ; un abonné en attente de paiement qui s'avère actif reçoit alors l'email de bienvenue.

### Créer les produits et prix Stripe (mode test)

1. Tableau de bord Stripe, bascule « Mode test », *Catalogue de produits* → deux produits : **Veille marchés Essentiel** et **Veille marchés Pro**.
2. Pour chacun, deux prix récurrents **hors taxes** : 29 € / mois et 290 € / an (Essentiel), 49 € / mois et 490 € / an (Pro). Copier les quatre identifiants `price_…` dans `.env` (`STRIPE_PRICE_ESSENTIEL_MONTHLY`, `…_YEARLY`, `STRIPE_PRICE_PRO_MONTHLY`, `…_YEARLY`).
3. *Développeurs → Clés API* : copier la clé secrète de test `sk_test_…` dans `STRIPE_SECRET_KEY`.
4. *Paramètres → Facturation → Portail client* : activer la mise à jour du moyen de paiement, la résiliation (à la fin de la période) et, si souhaité, le changement d'abonnement entre les quatre prix. Sans ce dernier réglage, un abonné écrit pour changer de formule.
5. Optionnel : *Paramètres → Taxes* (Stripe Tax) pour appliquer la TVA automatiquement, ou laisser les prix HT tels quels si franchise en base (mention à mettre dans `LEGAL_VAT`). Les cartes de test : `4242 4242 4242 4242`, date future, CVC quelconque.

### Webhook

En local :

```bash
stripe login                                              # CLI Stripe (brew install stripe/stripe-cli/stripe)
stripe listen --forward-to localhost:8000/webhooks/stripe # affiche un secret whsec_… → STRIPE_WEBHOOK_SECRET, puis relancer vm web
stripe trigger checkout.session.completed                 # événement factice : répond unmatched (aucun abonné), c'est normal
```

Le vrai test : s'inscrire sur `http://localhost:8000/inscription` avec la carte `4242…` ; la fenêtre `stripe listen` montre `checkout.session.completed` → `[200]`, l'abonné passe `active`, l'email de bienvenue part (en `MAIL_PROVIDER=console`, il s'affiche dans le terminal de `vm web`).

En production : *Développeurs → Webhooks → Ajouter un endpoint* `https://<domaine>/webhooks/stripe`, événements `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted` ; copier le secret de signature dans `STRIPE_WEBHOOK_SECRET`. Les autres types d'événements répondent `ignored` (200) ; un événement sans abonné correspondant répond `unmatched` (200, journalisé) pour que Stripe ne le rejoue pas indéfiniment.

### Déploiement

La base SQLite est partagée entre le site (écrit les inscriptions) et les jobs (`vm digest` lit les abonnés) : **le site doit tourner sur la machine qui héberge la base**, donc sur le Mac mini avec les jobs. Deux façons de l'exposer :

- **Cloudflare Tunnel depuis le Mac mini (recommandé, gratuit, aucun port ouvert)** : `brew install cloudflared`, `cloudflared tunnel login`, `cloudflared tunnel create veille`, route DNS `veille.<domaine>` → `http://localhost:8000`, `cloudflared service install` pour le lancer au démarrage. `vm web` reste sur `127.0.0.1:8000`. `APP_BASE_URL=https://veille.<domaine>`. Ajouter un service launchd `com.sideproject.veille.web` sur le modèle des plists de `deploy/macmini/launchd/` qui lance `run.sh veille-marches vm web` en permanence (`KeepAlive`).
- **VPS derrière Caddy** (si un jour toute l'app migre sur le VPS, par exemple avec `LLM_PROVIDER=anthropic` ou Ollama via Tailscale) : même schéma que `deploy/vps` pour `avis-clients` — service `veille-web` qui exécute `uvicorn veille_marches.web:app --host 0.0.0.0 --port 8000 --proxy-headers`, volume pour `data/`, et dans le `Caddyfile` : `veille.mondomaine.fr { reverse_proxy veille-web:8000 }` ; les jobs (`vm collect/score/digest/brief-weekly`, `vm subscribers sync-stripe`) dans une boucle cron du même compose, sur le même volume.

Dans les deux cas : `APP_SECRET_KEY` stable et obligatoire (`vm web` refuse de démarrer sans lui, ni sans `STRIPE_WEBHOOK_SECRET`, dès que `STRIPE_SECRET_KEY` est renseignée ; sans clé, les liens des emails mourraient à chaque redémarrage), `WEB_HOST=0.0.0.0` seulement dans Docker, `MAIL_PROVIDER=smtp|resend` avec un domaine d'envoi vérifié, sauvegarde quotidienne de `data/veille-marches.db`.

### À compléter par Hugo avant la mise en ligne

Compte Stripe (clés, quatre prix, portail client, endpoint webhook), nom de domaine et `APP_BASE_URL`, `APP_SECRET_KEY`, variables `LEGAL_*` et les crochets restants dans `templates/site/legal_cgv.html.j2` / `legal_confidentialite.html.j2` (politique de remboursement, juridiction, prestataire email, hébergeur, durée des journaux), choix de la TVA, relecture des CGV, prestataire d'email transactionnel.

## Champs à vérifier lors du premier appel réel

Les API BOAMP, TED et data.economie.gouv.fr n'étaient **pas joignables** depuis l'environnement de développement. Les clients sont écrits d'après la documentation officielle et testés sur des fixtures réalistes (`tests/fixtures/`). Toutes les correspondances de champs sont dans `src/veille_marches/mapping.py` : chaque clé liste des chemins candidats essayés dans l'ordre, il suffit d'ajouter ou de réordonner un chemin.

Procédure : `vm collect --source boamp --limit 20 --dry-run` (puis `ted`, `decp`), comparer la sortie avec les fixtures, puis `vm stats` après une vraie collecte : si « sans CPV détecté » ou « sans département » est élevé, un chemin manque.

**BOAMP** (`boamp-datadila.opendatasoft.com`, jeu `boamp`, API Explore v2.1)
- Identifiant : `idweb` (puis `id`). Date : `dateparution` (clause `where` : `dateparution >= date'AAAA-MM-JJ'`). Date limite : `datelimitereponse`.
- **CPV** : il n'existe pas toujours de champ de premier niveau. Chemins essayés : `cpv`, `code_cpv`, `descripteur_code` (ce sont en général des descripteurs BOAMP à 2 chiffres, ignorés par la validation « 8 chiffres »), puis dans le JSON `donnees` : `OBJET.CPV.PRINCIPAL.CODE`, `OBJET.CPV.SUPPLEMENTAIRE.CODE`, `OBJET.LOTS.LOT.CPV.PRINCIPAL.CODE`, et enfin un balayage de toutes les clés contenant « cpv ». Pour les avis eForms (depuis 2024) la structure de `donnees` peut différer : vérifier qu'au moins un chemin remonte un code.
- Département : `code_departement` (liste), `code_departement_prestation`, `donnees.OBJET.LIEU_EXEC_LIVR.CODE`.
- Montant : `donnees.OBJET.VALEUR.ESTIMEE` (souvent absent sur les MAPA).
- Nature : `nature_categorise_libelle` / `nature_libelle` ; les avis contenant « attribution », « annulation », « résultat » sont exclus (`exclude_nature_keywords`). Si les rectificatifs doivent aussi être exclus, ajouter le mot-clé.
- Lien : `url_avis`, sinon `https://www.boamp.fr/pages/avis/?q=idweb:"<idweb>"`.
- `BOAMP_SERVER_SIDE_CPV=true` ajoute `search(donnees, "773")` dans la clause `where` pour réduire le volume : à valider (la recherche plein texte peut ignorer les préfixes).

**TED** (`api.ted.europa.eu/v3/notices/search`, `POST`)
- Requête : `(classification-cpv=773*) AND place-of-performance=FRA AND publication-date>=AAAAMMJJ`, `paginationMode=PAGE_NUMBER`, `scope=ACTIVE`, 100 par page. Vérifier que les noms de champs de recherche (`place-of-performance`, `classification-cpv`) sont acceptés ; sinon utiliser les alias eForms (`place-of-performance-subdiv-lot`, `main-classification-proc`).
- Réponse : `notices[]`, `totalNoticeCount`. Champs multilingues (`notice-title`, `buyer-name`, `description-proc`) lus en `fra` puis `eng`.
- Département déduit des codes NUTS 3 (`place-of-performance`, table `nuts.py`, nomenclature 2021). Un code NUTS 2 ou pays donne « zone non précisée ».
- Montant : `estimated-value-proc` puis `estimated-value-lot` ; ignoré si la devise n'est pas l'euro. Date limite : la plus proche de `deadline-receipt-tender-date-lot`.
- Filtre : `form-type == competition` quand présent, sinon exclusion des `notice-type` `can-*`, `pin-*`, `veat`, `corr`.
- Clé API : la recherche fonctionne sans clé ; si `TED_API_KEY` est fournie elle est envoyée en `Authorization: Bearer` (à confirmer avec le portail développeur).

**DECP** (`data.economie.gouv.fr`, jeu `DECP_DATASET`)
- Jeu par défaut `decp-v3` ; alternatives : `decp-v3-marches-valides`, `decp_augmente`. En cas de 404, changer `DECP_DATASET`.
- Clause `where` : `datenotification >= date'…' AND (startswith(codecpv, "773"))` : vérifier les noms `datenotification` / `codecpv` (`dateNotification` / `codeCPV` dans le format v3) et le support de `startswith`. Les champs sont aussi configurables dans `DECP_MAPPING["date_field"]` et `["cpv_field"]`.
- Nom de l'acheteur et du titulaire : `acheteur_nom`, `titulaire_denominationsociale` (format augmenté) ou objets `acheteur` / `titulaires` (format v3, parfois sérialisés en JSON). Si le jeu ne fournit que des SIRET, le brief affiche « SIRET … » : prévoir un enrichissement SIRENE.
- Département : `lieuexecution_code` + `lieuexecution_typecode` (code commune, postal, département, région…).

## Décisions prises

- **Un résumé par avis, un score par abonné** : la table `summaries` garde le résumé LLM et un score de référence (meilleur abonné) ; le digest recalcule le score de règles pour chaque abonné et y ajoute le verdict stocké.
- **Montant inconnu = gardé** et marqué « montant non précisé » (10 points au lieu de 20). **Département inconnu = écarté** par défaut pour les abonnés qui ont une zone (réglable avec `MATCH_UNKNOWN_DEPARTMENT`), toujours proposé aux abonnés « toute la France ».
- Les avis **sans CPV détecté sont conservés** en base (ils ne correspondront à aucun abonné) : c'est le signal, dans `vm stats`, qu'un chemin de mapping manque.
- **Garde-fou injection** : le texte de l'avis est placé entre balises `<avis>` (toute balise `<avis>` présente dans le texte est neutralisée) ; le prompt système interdit d'en suivre les instructions ; le titre, l'acheteur, la procédure et la description sont tronqués avant d'entrer dans le prompt ; la sortie est validée et bornée par `LLMSummary` (verdict normalisé, types inattendus tolérés, longueurs limitées, 10 pièces maximum, URL retirées : le seul lien d'un digest est celui de l'avis, et il doit être en http(s)) ; une sortie inexploitable ou une erreur du fournisseur donnent le résumé de repli, repris au passage suivant ; les gabarits HTML échappent tout.
- Les avis **expirés** ne consomment pas de LLM et n'entrent pas dans les digests. Un avis résumé sans LLM (aucun abonné concerné à l'époque) est repris au passage suivant si un nouvel abonné y correspond.
- Le brief hebdo part aux abonnés **Pro** (option `--all-plans`), sur une fenêtre de 7 jours (`--since-days`), avec acheteurs actifs et titulaires récurrents calculés sur 12 mois d'historique.
- `vm digest` sans `--send` écrit des aperçus dans `OUT_DIR` et n'enregistre rien ; seul `--send` crée des `deliveries`.
- **Site et paiement (P2-3b)** : FastAPI sans JavaScript ni framework CSS (une feuille de style inline, mobile d'abord) ; `active` reste la seule colonne qui décide des envois, `status` documente la raison. Liens « espace abonné » en HMAC maison (`<id>.<expiration>.<signature>`) plutôt qu'itsdangerous : 20 lignes, aucune dépendance, expiration explicite et testable. Impayé en cours de relance (`past_due`) : envois maintenus ; relances épuisées (`unpaid`) : coupés. Le webhook vérifie la signature avec le SDK puis travaille sur le JSON brut (les objets du SDK ne sont pas des dicts), et répond 200 aux événements inconnus ou sans abonné pour que Stripe ne les rejoue pas. Sans clé Stripe, paiement et portail sont simulés sur des pages locales clairement marquées, afin de tester le parcours de bout en bout avant d'avoir un compte. L'inscription stocke l'identifiant de session Checkout pour que `/merci` reconnaisse l'abonné sans appel API. Les abonnés créés par la CLI restent « gérés à la main » (pas de client Stripe) : le bouton du portail renvoie vers l'email de contact. Les fonctions Pro non construites (résumé du DCE, export CSV) ne sont pas promises sur le site.

## Limites connues

- **Petits MAPA sur profils d'acheteurs non couverts** : les procédures de faible montant sont souvent publiées uniquement sur le profil de l'acheteur (AWS, Marchés sécurisés, PLACE…). Le MVP couvre BOAMP + TED, ce qui suffit pour les marchés de taille moyenne ; les profils régionaux sont une V2, département par département.
- Les DECP sont publiées par les acheteurs avec un retard variable (semaines, parfois mois) : le brief décrit « ce qui vient d'être publié », pas strictement « ce qui a été notifié cette semaine ».
- Le TED n'indique pas toujours un NUTS 3 : certains avis européens arrivent sans département.
- Le score de règles « acheteur déjà vu » dépend de l'historique accumulé : il est muet les premières semaines.
- Pas de dédoublonnage entre un avis BOAMP et le même avis sur TED (identifiants différents) : un gros marché peut apparaître deux fois le même jour, avec deux liens sources.
- Le lien « espace abonné » voyage dans l'URL : `Referrer-Policy: no-referrer`, `Cache-Control: no-store` sur les pages privées et un filtre qui masque `token=` dans les journaux d'uvicorn limitent les fuites ; un reverse proxy (Caddy, Cloudflare) garde ses propres journaux d'accès, à purger régulièrement.
- Le site n'a pas de limitation de débit : derrière Cloudflare Tunnel ou Caddy, activer un garde-fou (règle Cloudflare ou `rate_limit` Caddy) sur `/inscription` et `/compte/lien`. Le choix multiple de départements est un `<select multiple>` standard (pas de JavaScript) : correct sur mobile, moins confortable sur ordinateur sans Ctrl/Cmd.
- Le changement d'adresse email d'un abonné se fait à la main (`sqlite3` ou prochaine commande CLI) ; l'espace abonné ne le propose pas pour éviter de détourner un abonnement avec un lien intercepté.
- Le LLM local peut se tromper sur un montant ou une date : les champs clés du digest (montant, date limite, lien) viennent des données structurées, le texte libre du LLM est présenté comme une aide.

## Arborescence

```
src/veille_marches/
  settings.py      réglages (hérite de core.settings.Settings) : site, Stripe, mentions légales inclus
  models.py        Notice, Award, Subscriber (statut, période, identifiants Stripe), LLMSummary + normalisation
  mapping.py       correspondances de champs BOAMP / TED / DECP (à ajuster au premier appel réel)
  nuts.py          NUTS 3 → département
  db.py            SQLite : migrations, avis, abonnés, résumés, envois, attributions, journal de collecte
  collectors/      base (Opendatasoft, client HTTP), boamp.py, ted.py, decp.py, orchestration
  filtering.py     correspondance avis ↔ abonné
  scoring.py       règles, prompt LLM (garde-fou), score final, passage de scoring
  digest.py        digest quotidien ; brief.py : brief hebdo ; rendering.py + templates/ (Jinja2)
  web.py           site public, inscription, /merci, /compte, webhook Stripe, pages /demo (FastAPI)
  billing.py       passerelles Stripe (SDK / mock), application des événements, synchronisation
  accounts.py      liens signés HMAC, email de bienvenue, email « votre lien d'accès », récapitulatif
  forms.py         lecture et validation des formulaires ; catalog.py : formules, métiers → CPV, départements
  sample.py        exemple d'alerte de la page d'accueil (fixtures/sample_notices.json + vrai pipeline)
  templates/site/  gabarits du site (base, landing, signup, thanks, account, legal_*, demo_*)
  cli.py           commande `vm` (Typer) : collect, score, digest, brief-weekly, subscribers, stats, web
  migrations/      001_init.sql, 002_billing.sql (colonnes Stripe/statut, table stripe_events)
tests/             102 tests (test_review.py : revue croisée, voir REVIEW.md) ; fixtures/ : boamp_records.json, ted_search.json, decp_records.json
```
