"""SQLite avec migrations SQL simples (fichiers numérotés, appliqués une fois)."""
from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

_BEGIN_RE = re.compile(r"^\s*BEGIN(\s+(DEFERRED|IMMEDIATE|EXCLUSIVE))?(\s+TRANSACTION)?\s*;", re.IGNORECASE)
# COMMIT/END final, éventuellement suivi de commentaires de fin de fichier.
_END_RE = re.compile(r";?\s*(COMMIT|END)(\s+TRANSACTION)?\s*;?(\s*--[^\n]*)*\s*$", re.IGNORECASE)


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
    """Ouvre (et crée au besoin) la base : dossier parent créé, lignes `sqlite3.Row`, clés étrangères, WAL.

    `:memory:` est accepté. Si la base est en lecture seule, le passage en WAL est impossible : il
    est ignoré et le mode de journal existant est conservé (la lecture fonctionne).
    """
    p = Path(path)
    memory = str(p) == ":memory:"
    if not memory:
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if not memory:
        try:
            conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError:
            pass  # base ou dossier en lecture seule : on garde le journal par défaut
    return conn


def migrate(conn: sqlite3.Connection, migrations_dir: str | Path) -> list[str]:
    """Applique les fichiers `*.sql` du dossier, dans l'ordre alphabétique, une seule fois chacun.

    Chaque migration est atomique : le script et l'enregistrement dans `schema_migrations` sont
    exécutés dans une seule transaction (SAVEPOINT), donc un script qui échoue ne laisse aucune table
    à moitié créée et sera rejoué au prochain appel. Fonctionne avec une connexion du module
    (`connect`), une connexion brute sans `row_factory`, une transaction déjà ouverte (elle est
    validée d'abord) ou une connexion `autocommit=False` (Python 3.12+ : chaque migration est validée).
    Un BEGIN/COMMIT écrit dans le fichier est retiré ; fichiers vides ou réduits à des commentaires
    sont acceptés. Lève FileNotFoundError si le dossier n'existe pas.
    """
    directory = Path(migrations_dir)
    if not directory.is_dir():
        raise FileNotFoundError(f"dossier de migrations introuvable : {directory}")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    conn.commit()
    done = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}
    applied: list[str] = []
    for f in sorted(directory.glob("*.sql")):
        if f.name in done:
            continue
        sql = _strip_transaction_wrapper(f.read_text(encoding="utf-8"))
        stamp = datetime.now(UTC).isoformat()
        name = f.name.replace("'", "''")
        # SAVEPOINT plutôt que BEGIN : fonctionne qu'une transaction soit déjà ouverte ou non.
        # Le point-virgule de fin est sur sa propre ligne : un commentaire `--` terminal ne l'avale pas.
        script = (
            "SAVEPOINT core_migration;\n" + sql + "\n;\n"
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
        if conn.in_transaction:  # autocommit=False : RELEASE ne valide rien, il faut un COMMIT explicite
            conn.commit()
        applied.append(f.name)
    return applied
