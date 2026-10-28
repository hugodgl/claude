# `core` : socle commun des apps

Cinq modules, aucune dépendance entre apps : les quatre apps sous `apps/` installent ce paquet
(`uv pip install -e ../../packages/core`) et n'appellent jamais un fournisseur directement.

| Module | Rôle | API publique |
|---|---|---|
| `core.llm` | modèles de langage | `get_llm`, `complete_json`, `MockLLM`, `OllamaLLM`, `AnthropicLLM`, `LLMResult`, `LLMError`, `LLMRefusal` |
| `core.mail` | envoi d'emails | `get_mailer`, `Email`, `ConsoleMailer`, `SMTPMailer`, `ResendMailer`, `MailError` |
| `core.settings` | réglages (pydantic-settings) | `Settings`, `get_settings` |
| `core.db` | SQLite + migrations | `connect`, `migrate` |
| `core.jsonutil` | JSON dans une sortie de modèle | `extract_json`, `strip_think` |

Tests : `cd packages/core && .venv/bin/pytest -q` (aucun appel réseau ; le SDK Anthropic n'est pas
requis, le test qui l'exerce se saute s'il est absent). Lint : `.venv/bin/ruff check .`.

## Réglages (`core.settings`)

`Settings` lit, par ordre de priorité : surcharges explicites > variables d'environnement > fichier
`.env` du dossier courant (ignoré s'il manque) > défauts. Les apps héritent de la classe pour ajouter
leurs réglages. Les choix (`LLM_PROVIDER`, `MAIL_PROVIDER`, `ANTHROPIC_EFFORT`) sont insensibles à la
casse et une valeur inconnue produit une erreur qui nomme la variable et les valeurs possibles.

| Variable | Défaut | Rôle |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `mock` (tests), `ollama` (local), `anthropic` (option payante) |
| `LLM_TIMEOUT_S` | `180` | délai par appel, tous fournisseurs |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` / `OLLAMA_THINK` | `http://localhost:11434` / `qwen3:14b` / `false` | `OLLAMA_THINK=true` exige un modèle qui gère la réflexion |
| `ANTHROPIC_MODEL` / `ANTHROPIC_EFFORT` / `ANTHROPIC_FALLBACKS` | `claude-opus-5-5` / `low` / `true` | la clé `ANTHROPIC_API_KEY` est lue par le SDK |
| `MAIL_PROVIDER` / `MAIL_FROM` | `console` / `Side project <noreply@example.com>` | `console`, `smtp`, `resend` |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_STARTTLS` | `localhost` / `587` / – / – / `true` | port 587 + STARTTLS (le 465 n'est pas géré) |
| `RESEND_API_KEY` | – | obligatoire si `MAIL_PROVIDER=resend` |
| `DATA_DIR` | `data` | dossier des bases et fichiers produits |

```python
from core.settings import Settings, get_settings

class AppSettings(Settings):
    app_name: str = "Mon app"

settings = get_settings(llm_provider="mock")   # surcharge explicite, pratique dans les tests
```

## Modèles de langage (`core.llm`)

Contrat unique : `llm.complete(prompt, system=None, max_tokens=1024, json_mode=False) -> LLMResult`.

```python
from core.llm import LLMError, LLMRefusal, complete_json, get_llm

llm = get_llm(settings)                        # MockLLM, OllamaLLM ou AnthropicLLM selon LLM_PROVIDER
result = llm.complete("Résume ce texte.", system="Tu es concis.", max_tokens=400)
result.text, result.model, result.stop_reason, result.truncated

try:
    data = complete_json(llm, "Donne {\"score\": 0-100}", system="…", max_tokens=300)
except LLMRefusal as e:                        # refus de sécurité (Anthropic) : e.category, e.explanation
    ...
except LLMError as e:                          # réseau, délai, modèle absent, JSON invalide après relance
    ...
```

- `LLMResult.truncated` vaut True quand la réponse a été coupée par `max_tokens` (`stop_reason`
  natif : `max_tokens` chez Anthropic, `length` chez Ollama). Le texte partiel est retourné ; seule une
  réponse coupée *avant tout texte* lève LLMError (message explicite). Chez Anthropic, les jetons de
  réflexion comptent dans `max_tokens` : prévoir de la marge au-delà du JSON attendu.
- `complete_json` relance une fois (`retries=1`) avec une consigne plus stricte (plus concise si la
  réponse était tronquée) et nomme la troncature dans son message d'erreur. Il retourne un `dict` ou
  une `list`, jamais un scalaire.
- `OllamaLLM` : `num_predict = max_tokens`, `format=json` en `json_mode`, `think` envoyé explicitement.
  Messages d'erreur ciblés : modèle absent (`ollama pull …`), Ollama arrêté (`ollama serve`), délai
  dépassé (`LLM_TIMEOUT_S`), modèle sans réflexion (`OLLAMA_THINK=false`).
- `AnthropicLLM` (extra `uv pip install 'core[anthropic]'`) : `output_config={"effort": …}`, aucun
  paramètre d'échantillonnage ; avec `ANTHROPIC_FALLBACKS=true`, appel
  `client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", …)`
  (un refus est rejoué côté serveur sur un autre modèle), sinon `client.messages.create`.
  `stop_reason == "refusal"` lève `LLMRefusal`. Un `client` peut être injecté (tests sans réseau).

### `MockLLM` dans les tests

```python
from core.llm import MockLLM

MockLLM('{"ok": true}')                        # toujours la même réponse
MockLLM(["pas du json", '{"ok": 1}'])          # file consommée dans l'ordre ; LLMError une fois vide
MockLLM(lambda prompt, system: "…")            # réponse calculée
MockLLM("…", stop_reason="max_tokens")         # simule une troncature
llm.calls                                      # [{"prompt", "system", "max_tokens", "json_mode"}, …]
```

## Emails (`core.mail`)

```python
from core.mail import Email, MailError, get_mailer

mailer = get_mailer(settings)                  # ConsoleMailer, SMTPMailer ou ResendMailer
email = Email(to=["client@exemple.fr"], subject="Votre récapitulatif", html="<p>…</p>", text="…",
              reply_to="contact@exemple.fr", headers={"List-Unsubscribe": "<mailto:…>"})
try:
    message_id = mailer.send(email, sender=settings.mail_from)
except MailError as e:                         # connexion, authentification, destinataire refusé, API en erreur
    ...
```

- `Email` nettoie les destinataires (une chaîne seule devient une liste) et refuse à la construction
  une adresse vide ou sans `@` (`ValueError`).
- `ConsoleMailer(quiet=True)` garde les envois dans `.sent` : c'est le mailer des tests et du dry-run.
- `SMTPMailer` : STARTTLS puis authentification si `SMTP_USER` est renseigné ; `Message-ID` réel
  (domaine de l'expéditeur, retourné par `send`), `Date`, en-têtes accentués encodés, corps en
  quoted-printable. `build(email, sender)` rend l'`EmailMessage` sans l'envoyer.
- `ResendMailer` : `POST https://api.resend.com/emails` (`from`, `to`, `subject`, `html`, `text`,
  `reply_to`, `headers`) ; retourne l'`id` Resend.

## SQLite (`core.db`)

```python
from core.db import connect, migrate

conn = connect(settings.data_dir / "app.db")   # dossier créé, sqlite3.Row, clés étrangères, WAL
applied = migrate(conn, Path(__file__).parent / "migrations")   # ["001_init.sql", …] ou []
```

- Les fichiers `*.sql` du dossier sont appliqués dans l'ordre alphabétique, une seule fois (table
  `schema_migrations`). Chaque migration est atomique : script et enregistrement dans la même
  transaction (SAVEPOINT) ; un script qui échoue ne laisse rien et sera rejoué.
- Accepte une transaction déjà ouverte (validée d'abord), une connexion `autocommit=False`
  (Python 3.12+), une connexion brute sans `row_factory`, `:memory:`, un fichier vide ou réduit à des
  commentaires, un BEGIN/COMMIT écrit dans le fichier, un commentaire `--` final sans point-virgule.
- `connect` sur une base en lecture seule ignore le passage en WAL au lieu d'échouer.

## JSON (`core.jsonutil`)

```python
from core.jsonutil import extract_json, strip_think

extract_json('Voici :\n```json\n{"score": 7,}\n```')   # {"score": 7}
```

`extract_json` retourne le premier objet ou tableau JSON d'un texte : blocs ``` (avec ou sans
langage) essayés en premier, blocs `<think>` retirés (même non refermés), virgules finales tolérées,
`NaN`/`Infinity` convertis en `None`. Les scalaires isolés (`42`, `null`) lèvent `ValueError`.
