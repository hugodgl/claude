"""SQLite avec migrations SQL simples (fichiers numérotés, appliqués une fois)."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path


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
        sql = f.read_text(encoding="utf-8").strip().rstrip(";")
        stamp = datetime.now(timezone.utc).isoformat()
        name = f.name.replace("'", "''")
        script = (
            "BEGIN;\n" + sql + ";\n"
            f"INSERT INTO schema_migrations (name, applied_at) VALUES ('{name}', '{stamp}');\n"
            "COMMIT;"
        )
        try:
            conn.executescript(script)
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        applied.append(f.name)
    return applied
