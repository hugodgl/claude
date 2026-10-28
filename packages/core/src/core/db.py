"""SQLite avec migrations SQL simples (fichiers numérotés, appliqués une fois)."""
from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

_BEGIN_RE = re.compile(r"^\s*BEGIN(\s+(DEFERRED|IMMEDIATE|EXCLUSIVE))?(\s+TRANSACTION)?\s*;", re.IGNORECASE)
_END_RE = re.compile(r";?\s*(COMMIT|END)(\s+TRANSACTION)?\s*;?\s*$", re.IGNORECASE)


def _strip_transaction_wrapper(sql: str) -> str:
    """Retire un BEGIN/COMMIT que le fichier aurait ajouté lui-même : la transaction est gérée ici."""
    sql = sql.strip()
    # commentaires d'en-tête avant un éventuel BEGIN
    lines = sql.splitlines()
    i = 0
    while i < len(lines) and (not lines[i].strip() or lines[i].strip().startswith("--")):
        i += 1
    head, body = "\n".join(lines[:i]), "\n".join(lines[i:])
    body = _BEGIN_RE.sub("", body, count=1)
    body = _END_RE.sub("", body, count=1)
    return ("\n".join(x for x in (head, body) if x)).strip().rstrip(";")


def connect(path: str | Path) -> sqlite3.Connection:
    p = Path(path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(p) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


def migrate(conn: sqlite3.Connection, migrations_dir: str | Path) -> list[str]:
    """Applique les fichiers `*.sql` du dossier, dans l'ordre alphabétique, une seule fois chacun.

    Chaque migration est atomique : le script et l'enregistrement dans `schema_migrations` sont
    exécutés dans une seule transaction, donc un script qui échoue ne laisse aucune table à moitié
    créée et sera rejoué au prochain appel.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    conn.commit()
    done = {row["name"] for row in conn.execute("SELECT name FROM schema_migrations")}
    applied: list[str] = []
    for f in sorted(Path(migrations_dir).glob("*.sql")):
        if f.name in done:
            continue
        sql = _strip_transaction_wrapper(f.read_text(encoding="utf-8"))
        stamp = datetime.now(UTC).isoformat()
        name = f.name.replace("'", "''")
        # SAVEPOINT plutôt que BEGIN : fonctionne qu'une transaction soit déjà ouverte ou non
        # (connexions en autocommit=False ou avec une écriture en attente).
        script = (
            "SAVEPOINT core_migration;\n" + sql + ";\n"
            f"INSERT INTO schema_migrations (name, applied_at) VALUES ('{name}', '{stamp}');\n"
            "RELEASE SAVEPOINT core_migration;"
        )
        try:
            conn.executescript(script)
        except Exception:
            try:
                conn.execute("ROLLBACK TO SAVEPOINT core_migration")
                conn.execute("RELEASE SAVEPOINT core_migration")
            except sqlite3.Error:
                pass
            raise
        applied.append(f.name)
    return applied
