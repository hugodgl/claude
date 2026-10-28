from pathlib import Path

from core.db import connect, migrate
from core.mail import ConsoleMailer, Email, SMTPMailer, get_mailer
from core.settings import get_settings


def test_console_mailer_records():
    m = ConsoleMailer(quiet=True)
    mid = m.send(Email(to=["a@b.fr"], subject="Test", html="<b>x</b>", text="x"), sender="s@b.fr")
    assert mid == "console-1" and m.sent[0].subject == "Test"


def test_smtp_build_message():
    m = SMTPMailer("h")
    msg = m.build(Email(to=["a@b.fr", "c@d.fr"], subject="S", html="<p>h</p>", text="t", reply_to="r@b.fr"), "me@b.fr")
    assert msg["To"] == "a@b.fr, c@d.fr" and msg["Reply-To"] == "r@b.fr"
    assert msg.get_body(preferencelist=("html",)).get_content().strip() == "<p>h</p>"


def test_get_mailer_default_console():
    assert isinstance(get_mailer(get_settings(mail_provider="console")), ConsoleMailer)


def test_migrate_is_idempotent(tmp_path: Path):
    mig = tmp_path / "migrations"
    mig.mkdir()
    (mig / "001_init.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);")
    (mig / "002_more.sql").write_text("ALTER TABLE t ADD COLUMN w TEXT;")
    conn = connect(tmp_path / "data" / "x.db")
    assert migrate(conn, mig) == ["001_init.sql", "002_more.sql"]
    assert migrate(conn, mig) == []
    conn.execute("INSERT INTO t (v, w) VALUES ('a', 'b')")
    assert conn.execute("SELECT v, w FROM t").fetchone()["w"] == "b"


def test_failed_migration_leaves_nothing(tmp_path: Path):
    import sqlite3 as _sqlite3

    import pytest

    mig = tmp_path / "migrations"
    mig.mkdir()
    (mig / "001_ok.sql").write_text("CREATE TABLE a (id INTEGER PRIMARY KEY);")
    (mig / "002_bad.sql").write_text("CREATE TABLE b (id INTEGER PRIMARY KEY); CREATE TABLE c (id INTEGER PRIMARY KEY); INSERT INTO nope VALUES (1);")
    conn = connect(tmp_path / "x.db")
    with pytest.raises(_sqlite3.OperationalError):
        migrate(conn, mig)
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "a" in tables and "b" not in tables and "c" not in tables
    assert {r["name"] for r in conn.execute("SELECT name FROM schema_migrations")} == {"001_ok.sql"}
    (mig / "002_bad.sql").write_text("CREATE TABLE b (id INTEGER PRIMARY KEY);")
    assert migrate(conn, mig) == ["002_bad.sql"]


def test_migration_with_own_transaction(tmp_path: Path):
    mig = tmp_path / "migrations"
    mig.mkdir()
    (mig / "001_wrapped.sql").write_text("-- en-tête\nBEGIN TRANSACTION;\nCREATE TABLE t (id INTEGER PRIMARY KEY);\nCOMMIT;\n")
    (mig / "002_plain.sql").write_text("ALTER TABLE t ADD COLUMN v TEXT")
    conn = connect(tmp_path / "x.db")
    conn.execute("CREATE TABLE pending (id INTEGER)")
    conn.execute("INSERT INTO pending VALUES (1)")  # transaction ouverte au moment de migrer
    assert migrate(conn, mig) == ["001_wrapped.sql", "002_plain.sql"]
    conn.execute("INSERT INTO t (v) VALUES ('ok')")
    assert conn.execute("SELECT v FROM t").fetchone()["v"] == "ok"
