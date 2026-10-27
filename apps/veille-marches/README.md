# Veille marchés publics (plan 2)

Un email par jour, par abonné, avec les nouveaux appels d'offres de son métier et de sa zone, **résumés en langage clair et scorés** ; un brief hebdomadaire « qui a gagné quoi » tiré des données d'attribution (DECP). Pas d'interface : le produit est un email, une CLI de gestion des abonnés et, plus tard, une facture Stripe.

Niche d'exemple : entreprises d'espaces verts et paysagistes (CPV `773xxxxx`). Changer de métier = changer les préfixes CPV des abonnés (et `TRADE_LABEL` pour le ton des résumés).

## Ce que fait l'app

| Étape | Commande | Détail |
|---|---|---|
| Collecte | `vm collect` | BOAMP (portail Opendatasoft de la DILA), TED (API v3, requête experte), DECP (data.economie.gouv.fr) ; normalisation en `Notice` / `Award`, stockage SQLite sans doublon (`source` + `source_id`) |
| Score | `vm score` | règles déterministes 0-100 (CPV exact > préfixe, département, montant dans la fourchette, délai ≥ 10 jours, acheteur déjà vu) + résumé structuré et verdict par LLM local ; score final = 0,7 × règles + 0,3 × verdict |
| Digest | `vm digest --send` | HTML lisible sur mobile + version texte, sections « À regarder en priorité » (score ≥ 70) et « Autres marchés », lien vers l'avis source à chaque fois, mention « résumé assisté par IA ». Zéro email s'il n'y a rien de nouveau ; un avis n'est jamais envoyé deux fois au même abonné (table `deliveries`) |
| Brief hebdo | `vm brief-weekly --send` | attributions de la semaine par département, montants cumulés, acheteurs actifs et titulaires récurrents sur 12 mois (abonnés Pro) |
| Abonnés | `vm subscribers add\|list\|disable\|enable` | email, libellé, préfixes CPV, départements, montant min/max, formule `essentiel` (2 départements) ou `pro` (6) |
| Suivi | `vm stats` | compteurs et dernières collectes, avec les signaux « sans CPV détecté » / « sans département » qui révèlent un mapping à corriger |

Le résumé LLM d'un avis est calculé **une fois** et partagé entre tous les abonnés concernés ; seul le score de règles est recalculé par abonné (ses critères diffèrent). Le LLM n'est appelé que pour les avis qui intéressent au moins un abonné actif et dont la date limite n'est pas passée.

## Installation

```bash
cd apps/veille-marches
uv venv .venv && uv pip install -e ../../packages/core -e ".[dev]"
cp .env.example .env            # puis ajuster
.venv/bin/pytest -q             # 59 tests, aucun appel réseau
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

## Commandes

```bash
vm subscribers add contact@paysages69.fr --label "Paysages 69" --cpv 773 --dept 69 --dept 01 --amount-max 500000 --plan pro
vm subscribers list
vm subscribers disable contact@paysages69.fr        # (et enable)

vm collect [--source boamp|ted|decp|all] [--since-days 2] [--limit 500] [--cpv 773] [--dry-run]
vm score   [--limit N] [--dry-run]
vm digest  [--send] [--dry-run] [--subscriber EMAIL]  # sans option : aperçus dans OUT_DIR, rien d'enregistré
vm brief-weekly [--send] [--dry-run] [--since-days 7] [--subscriber EMAIL] [--all-plans]
vm stats
```

`--dry-run` affiche sans envoyer ni écrire. Sans abonné actif, `vm score` utilise un profil par défaut (CPV `DEFAULT_CPV_PREFIXES`, toute la France) pour que les premiers essais produisent des résumés. Une source en erreur n'empêche pas les autres (code de sortie 1 seulement si toutes échouent) ; l'erreur est consignée dans `collect_runs` et visible dans `vm stats`.

## Planification suggérée (Mac mini, heure de Paris)

Les plists sont dans `deploy/macmini/launchd/` (`com.sideproject.veille.*`) et passent par `deploy/macmini/run.sh`, qui charge le `.env` de l'app.

| Heure | Commande | Pourquoi |
|---|---|---|
| 06:00 et 14:00 | `vm collect --source all --since-days 2` | le BOAMP publie deux fois par jour ; la fenêtre de 2 jours absorbe un passage raté |
| 06:30 | `vm score` | après la collecte, avant le digest ; ~5 à 15 s par avis avec `qwen3:14b` |
| 07:00 | `vm digest --send` | un email par abonné, seulement s'il y a du nouveau |
| dimanche 18:00 | `vm brief-weekly --send` | les DECP arrivent avec retard ; le dimanche laisse la semaine se remplir |

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
- **Garde-fou injection** : le texte de l'avis est placé entre balises `<avis>` (toute balise `<avis>` présente dans le texte est neutralisée) ; le prompt système interdit d'en suivre les instructions ; la sortie est validée et bornée par `LLMSummary` (verdict normalisé, longueurs limitées, 10 pièces maximum) ; les gabarits HTML échappent tout.
- Les avis **expirés** ne consomment pas de LLM et n'entrent pas dans les digests. Un avis résumé sans LLM (aucun abonné concerné à l'époque) est repris au passage suivant si un nouvel abonné y correspond.
- Le brief hebdo part aux abonnés **Pro** (option `--all-plans`), sur une fenêtre de 7 jours (`--since-days`), avec acheteurs actifs et titulaires récurrents calculés sur 12 mois d'historique.
- `vm digest` sans `--send` écrit des aperçus dans `OUT_DIR` et n'enregistre rien ; seul `--send` crée des `deliveries`.
- Stripe et la page d'inscription (P2-3) ne sont pas dans cette tranche : les abonnés se gèrent par la CLI.

## Limites connues

- **Petits MAPA sur profils d'acheteurs non couverts** : les procédures de faible montant sont souvent publiées uniquement sur le profil de l'acheteur (AWS, Marchés sécurisés, PLACE…). Le MVP couvre BOAMP + TED, ce qui suffit pour les marchés de taille moyenne ; les profils régionaux sont une V2, département par département.
- Les DECP sont publiées par les acheteurs avec un retard variable (semaines, parfois mois) : le brief décrit « ce qui vient d'être publié », pas strictement « ce qui a été notifié cette semaine ».
- Le TED n'indique pas toujours un NUTS 3 : certains avis européens arrivent sans département.
- Le score de règles « acheteur déjà vu » dépend de l'historique accumulé : il est muet les premières semaines.
- Pas de dédoublonnage entre un avis BOAMP et le même avis sur TED (identifiants différents) : un gros marché peut apparaître deux fois le même jour, avec deux liens sources.
- Le LLM local peut se tromper sur un montant ou une date : les champs clés du digest (montant, date limite, lien) viennent des données structurées, le texte libre du LLM est présenté comme une aide.

## Arborescence

```
src/veille_marches/
  settings.py      réglages (hérite de core.settings.Settings)
  models.py        Notice, Award, Subscriber, LLMSummary + normalisation CPV / département
  mapping.py       correspondances de champs BOAMP / TED / DECP (à ajuster au premier appel réel)
  nuts.py          NUTS 3 → département
  db.py            SQLite : migrations, avis, abonnés, résumés, envois, attributions, journal de collecte
  collectors/      base (Opendatasoft, client HTTP), boamp.py, ted.py, decp.py, orchestration
  filtering.py     correspondance avis ↔ abonné
  scoring.py       règles, prompt LLM (garde-fou), score final, passage de scoring
  digest.py        digest quotidien ; brief.py : brief hebdo ; rendering.py + templates/ (Jinja2)
  cli.py           commande `vm` (Typer)
  migrations/      001_init.sql
tests/             59 tests ; fixtures/ : boamp_records.json, ted_search.json, decp_records.json
```
