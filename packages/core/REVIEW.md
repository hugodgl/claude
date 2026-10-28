# Revue croisée du socle `packages/core` (2026-10-28)

Périmètre : `src/core/{llm,mail,db,jsonutil,settings}.py`. Méthode : test d'abord (sonde puis test
pytest rouge), correction minimale, suite complète verte, `ruff check .` propre, suites des quatre
apps relancées en lecture seule. API publique inchangée (ajouts seulement : `MailError`,
`LLMResult.truncated`, `MockLLM(stop_reason=…)`, `SMTPMailer(timeout_s=…)`, `strip_think` exporté).

Tests du socle : 17 → 50 (49 + 1 sauté sans le SDK Anthropic ; 50 verts avec le SDK installé).
Vérification SDK : le corps de requête réellement émis par `AnthropicLLM` a été observé à travers un
`MockTransport` avec `anthropic` 2.3.0 (en-tête `anthropic-beta: server-side-fallback-2026-07-01`,
`fallbacks: "default"`, `output_config: {"effort": …}`, pas de `temperature`, chemin non bêta sans
`fallbacks`) : conforme, aucune correction nécessaire sur la forme des appels.

## Défauts corrigés

### Gravité haute

| # | Défaut | Où (après correction) | Correction | Test |
|---|---|---|---|---|
| 1 | `migrate` n'était pas durable avec une connexion `autocommit=False` (Python 3.12+) : `RELEASE SAVEPOINT` ne valide rien dans une transaction ouverte, les tables créées restaient invisibles aux autres connexions jusqu'à un `commit()` du code appelant (seule `schema_migrations` était validée). | `db.py:91` | `conn.commit()` après chaque migration si `conn.in_transaction`. | `test_migrate_is_durable_with_autocommit_false` |
| 2 | `SMTPMailer.send` retournait toujours la chaîne `"smtp"` : aucun `Message-ID` n'était généré (`smtplib` n'en ajoute pas) et `Date` manquait ; les apps stockaient `"smtp"` comme identifiant de message. | `mail.py:100-101,134` | `Message-ID` via `make_msgid(domain=<domaine expéditeur>)`, `Date` via `formatdate`, `send` retourne l'identifiant réel. | `test_smtp_build_sets_message_id_date_and_encodes_accents`, `test_smtp_send_sequence_and_real_message_id` |
| 3 | `Email(to="a@b.fr")` (chaîne au lieu de liste) était accepté : `", ".join` produisait l'en-tête `To: a, <>, b, ., f, r`, envoi cassé sans erreur ; `[None]` ou `[]` plantaient plus tard dans le mailer. | `mail.py:40-48` | `__post_init__` : chaîne → liste, nettoyage, `ValueError` si vide ou sans `@`. | `test_email_recipient_validation` |
| 4 | Troncature silencieuse : une réponse coupée par `max_tokens` n'était pas identifiable (`complete_json` échouait avec « JSON invalide » sans cause et relançait à l'identique) ; chez Anthropic une réponse coupée avant tout texte (réflexion adaptative consommant le budget) était signalée « réponse sans texte ». | `llm.py:54,167,260,332-345` | `LLMResult.truncated` (`max_tokens` Anthropic, `length` Ollama) ; `complete_json` relance avec une consigne de concision et nomme la troncature et `max_tokens` dans l'erreur ; messages explicites quand aucun texte n'est revenu. | `test_llmresult_truncated_covers_both_vocabularies`, `test_complete_json_reports_truncation_and_asks_for_concision`, `test_anthropic_refusal_and_truncation`, `test_ollama_truncated_and_empty_responses` |
| 5 | Fichier SQL terminé par un commentaire `--` sans point-virgule : le `;` ajouté par `migrate` était avalé par le commentaire → `syntax error`. Fichier `BEGIN…COMMIT;` suivi d'un commentaire : le `COMMIT` restait, validait la transaction englobante puis `RELEASE` échouait (« no such savepoint ») alors que la migration était appliquée **et** enregistrée. | `db.py:11,78` | Terminateur sur sa propre ligne (`"\n;\n"`) ; `_END_RE` tolère les commentaires de fin de fichier. | `test_migrate_tolerates_empty_comment_only_and_trailing_comment_files` |

### Gravité moyenne

| # | Défaut | Où | Correction | Test |
|---|---|---|---|---|
| 6 | Ollama : modèle absent (404) remonté comme `Ollama HTTP 404 : {"error":…}` sans piste ; délai dépassé confondu avec « injoignable » ; `r.json()` non protégé (page HTML d'un proxy → `JSONDecodeError` brut) ; `think=true` sur un modèle sans réflexion → 400 brut. | `llm.py:147-191` | Messages ciblés : `ollama pull <modèle>`, `ollama serve`, `LLM_TIMEOUT_S`, `OLLAMA_THINK=false` ; corps non JSON → `LLMError`. | `test_ollama_missing_model_hints_pull`, `test_ollama_think_unsupported_hint`, `test_ollama_timeout_and_unreachable_messages`, `test_ollama_truncated_and_empty_responses` |
| 7 | Anthropic : `import anthropic` à l'intérieur de `complete()` rendait la classe inutilisable (donc intestable) avec un client injecté sans l'extra installé ; 401 (clé absente/invalide) et 404 (modèle) sans indication utile ; bêta `server-side-fallback` refusée par le compte → 400 opaque. | `llm.py:243-289` | Traduction des erreurs isolée dans `_anthropic_error_message` (SDK importé paresseusement, exceptions non-SDK relancées telles quelles) ; messages nommant `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `ANTHROPIC_FALLBACKS=false`. | `test_anthropic_request_shape_with_and_without_fallbacks`, `test_anthropic_sdk_errors_are_translated` (SDK réel + `httpx2.MockTransport`, sauté si le SDK manque) |
| 8 | Erreurs d'envoi non typées : SMTP laissait fuir `OSError`/`SMTPException`, Resend `httpx.HTTPStatusError` (sans le message d'erreur de l'API) ; `get_mailer` levait `RuntimeError`. | `mail.py:24,122-132,163-165,172-182,194` | `MailError(RuntimeError)` partout, avec cause (authentification, destinataires refusés, hôte:port, message JSON Resend, piste `RESEND_API_KEY`/domaine). | `test_smtp_errors_are_typed`, `test_resend_payload_and_errors` |
| 9 | Un en-tête fourni dans `Email.headers` déjà posé par `build` (ex. `Reply-To`) levait `ValueError: at most 1 Reply-To headers`. | `mail.py:105` | L'en-tête explicite remplace l'existant. | `test_smtp_build_sets_message_id_date_and_encodes_accents` |
| 10 | Corps texte/HTML accentué émis en `8bit` brut alors que `smtplib.send_message` n'annonce pas `8BITMIME` (les sujets, eux, étaient bien encodés RFC 2047). | `mail.py:108-109` | Parties en `quoted-printable` : message 7 bits propre. | idem (`as_bytes()` entièrement ASCII, aller-retour du sujet et du nom accentués) |
| 11 | `connect` sur une base ou un dossier en lecture seule échouait sur `PRAGMA journal_mode = WAL` au lieu de permettre la lecture. | `db.py:44` | `OperationalError` ignorée, mode de journal existant conservé. | `test_connect_falls_back_when_wal_is_impossible` (simulation : le test réel sur système de fichiers est inopérant sous root) |
| 12 | `migrate` avec une connexion brute (sans `row_factory`) plantait au second appel (`row["name"]` sur un tuple). | `db.py:67` | `row[0]`. | `test_migrate_apostrophe_plain_connection_and_older_table` |
| 13 | `extract_json("null")`/`"42"` retournaient un scalaire : `complete_json` pouvait rendre `None` et faire planter l'app plus loin ; `NaN`/`Infinity` devenaient des `float('nan')` propagés dans les scores. | `jsonutil.py:14,36-45` | Seuls objets et tableaux sont acceptés ; `parse_constant` → `None`. | `test_scalars_are_not_json_answers`, `test_nan_and_infinity_become_none`, `test_complete_json_rejects_scalar_answers` |
| 14 | `LLM_PROVIDER=openai` ou `Ollama` : erreur pydantic brute (`literal_error`) sans nommer la variable, et sensible à la casse. | `settings.py:43-52` | Validateur `before` : normalisation (`strip().lower()`) et message `LLM_PROVIDER='openai' inconnu : valeurs possibles mock, ollama, anthropic` (idem `MAIL_PROVIDER`, `ANTHROPIC_EFFORT`), hérité par les sous-classes des apps. | `tests/test_settings.py` (4 tests : message, normalisation, `.env` absent / variables / surcharges, sous-classe) |

### Gravité basse

| # | Défaut | Où | Correction | Test |
|---|---|---|---|---|
| 15 | `MockLLM(("a", "b"))` : un tuple était traité comme une réponse fixe (retournait le tuple lui-même). | `llm.py:94,102` | `list` et `tuple` consommés dans l'ordre ; message d'épuisement avec le nombre d'appels. | `test_mock_tuple_callable_and_stop_reason` |
| 16 | `OllamaLLM(timeout_s=…)` ignoré dès qu'un `client` était injecté. | `llm.py:147` | Délai passé à chaque requête. | `test_ollama_timeout_and_unreachable_messages` |
| 17 | Dossier de migrations inexistant (chemin mal écrit) : `migrate` retournait `[]` sans bruit, l'app échouait plus tard sur « no such table ». | `db.py:62` | `FileNotFoundError` explicite. | `test_migrate_missing_dir_and_memory` |
| 18 | `<think>` ouvert et jamais refermé (réponse coupée pendant la réflexion) : le JSON était pêché dans la réflexion ; `_FENCE` ne reconnaissait que `json` comme langage ; correction des virgules finales et découpage `cand[i:]` refaits à chaque accolade (quadratique sur les longues réponses). | `jsonutil.py:8,10,41-44` | Bloc ouvert retiré jusqu'à la fin ; tout tag de langage accepté ; `raw_decode(texte, position)` et variante « virgules corrigées » calculée une fois par candidat. | `test_unterminated_think_block_is_dropped`, `test_fence_without_language_or_with_other_language_wins_over_prose`, `test_long_response_with_many_stray_braces` |
| 19 | Prose contenant `[1]` avant un bloc ```…``` : le tableau `[1]` l'emportait sur la fence. | `jsonutil.py:36` | Les fences sont essayées avant le texte entier. | `test_fence_without_language_or_with_other_language_wins_over_prose` |
| 20 | Qualité : docstrings incomplètes ou inexactes (contrat `stop_reason`, `think`, STARTTLS), pas de README du socle, `strip_think`/`MailError` absents de `core.__all__`. | `README.md`, `__init__.py`, docstrings | README avec l'API publique et des exemples ; exports ajoutés. | — |

## Les 5 corrections qui comptent le plus

1. Migrations durables en `autocommit=False` (#1) : sans cela, une app qui ouvrirait ses connexions
   avec le nouveau mode transactionnel perdrait silencieusement son schéma.
2. `Message-ID` réel et `Date` (#2) : identifiants exploitables en base, délivrabilité (beaucoup de
   filtres pénalisent l'absence de `Date`/`Message-ID`).
3. Validation des destinataires (#3) : un oubli de crochets n'envoie plus un email à « a, <>, b ».
4. Troncature signalée (#4) : `max_tokens` trop bas (fréquent avec la réflexion adaptative) devient
   un message actionnable au lieu d'un « JSON invalide » mystérieux.
5. Messages Ollama/Anthropic actionnables (#6, #7) : `ollama pull`, `ollama serve`, `LLM_TIMEOUT_S`,
   `ANTHROPIC_API_KEY`, `ANTHROPIC_FALLBACKS=false` — le Mac mini tourne sans personne devant, les
   journaux doivent dire quoi faire.

## Vérifications

- `cd packages/core && .venv/bin/pytest -q` : 49 passed, 1 skipped (SDK absent) ; 50 passed avec
  `anthropic` 2.3.0 installé dans un venv jetable.
- `.venv/bin/ruff check .` : propre.
- `make test` (racine, apps en lecture seule, aucune app modifiée par cette revue) : core 49 passed +
  1 skipped, veille-marches 102, content-engine 73, avis-clients 118, newsletter-pipeline 93, sortie 0.
  Avant la revue : 17 / 102 / 73 / 95 / 93 (les tests avis-clients supplémentaires viennent d'un
  chantier parallèle sur cette app, pas du socle).

## À faire plus tard (hors périmètre de cette revue)

- SMTP sur le port 465 (TLS implicite, `SMTP_SSL`) : non géré, documenté ; ajouter un réglage
  `SMTP_SSL=true` ou le déduire du port si un fournisseur l'exige.
- Ollama : exposer `num_ctx` dans les réglages (Ollama tronque silencieusement les prompts plus longs
  que le contexte par défaut) et `keep_alive` (évite de recharger le modèle entre deux passages).
- Anthropic : sorties structurées (`output_config.format`) à la place de la consigne JSON en système
  quand les apps auront des schémas stables ; streaming pour des `max_tokens` élevés ; relance
  applicative sur 429/529 au-delà des 2 tentatives du SDK.
- `extract_json` : hors fence, un tableau de prose (`[1]`) placé avant l'objet attendu l'emporte
  encore (sémantique « premier trouvé ») ; si cela arrive en pratique, préférer le candidat le plus long.
- `migrate` : pas de verrou inter-processus (deux processus migrant en même temps s'appuient sur le
  `busy_timeout` de 5 s de sqlite3) ; à surveiller si plusieurs lanceurs launchd partagent une base.
- Test de lecture seule sur un vrai système de fichiers (le test actuel simule l'échec du PRAGMA car
  les permissions sont sans effet sous root) : à exécuter une fois sur le Mac mini.
- `MockLLM._queue` reste un champ d'initialisation visible du dataclass ; sans conséquence pour les apps.
