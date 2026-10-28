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


# ----------------------------------------------------------------------------------------------
# Revue croisée : Email, SMTP, Resend
# ----------------------------------------------------------------------------------------------
import email as _email
import smtplib
import sqlite3
import sys
from typing import ClassVar

import httpx
import pytest

from core.db import connect as _connect
from core.mail import MailError, ResendMailer


def test_email_recipient_validation():
    assert Email(to="a@b.fr", subject="s", html="h").to == ["a@b.fr"]
    assert Email(to=[" a@b.fr ", "Jean <j@d.fr>"], subject="s", html="h").to == ["a@b.fr", "Jean <j@d.fr>"]
    for bad in ([], [""], ["pas-une-adresse"], [None], "x"):
        with pytest.raises(ValueError, match="destinataire"):
            Email(to=bad, subject="s", html="h")


def test_smtp_build_sets_message_id_date_and_encodes_accents():
    m = SMTPMailer("h")
    msg = m.build(Email(to=["a@b.fr"], subject="Résumé : marchés — été", html="<p>é</p>", text="é",
                        headers={"Reply-To": "z@b.fr", "X-Tag": "t"}, reply_to="r@b.fr"), "Veille marchés <v@exemple.fr>")
    assert msg["Message-ID"].endswith("@exemple.fr>") and msg["Date"]
    assert msg.get_all("Reply-To") == ["z@b.fr"] and msg["X-Tag"] == "t"
    raw = msg.as_bytes()
    raw.decode("ascii")  # en-têtes encodés (RFC 2047), rien de brut en UTF-8
    parsed = _email.message_from_bytes(raw, policy=_email.policy.default)
    assert parsed["Subject"] == "Résumé : marchés — été" and parsed["From"] == "Veille marchés <v@exemple.fr>"


class _FakeSMTP:
    instances: ClassVar[list] = []
    fail: ClassVar[str | None] = None

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout, self.calls = host, port, timeout, []
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.calls.append("quit")

    def starttls(self):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user, password))
        if _FakeSMTP.fail == "auth":
            raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Authentication credentials invalid")

    def send_message(self, msg):
        self.calls.append(("send", msg["Message-ID"]))
        if _FakeSMTP.fail == "rcpt":
            raise smtplib.SMTPRecipientsRefused({"a@b.fr": (550, b"User unknown")})


def test_smtp_send_sequence_and_real_message_id(monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    _FakeSMTP.instances.clear()
    _FakeSMTP.fail = None
    m = SMTPMailer("smtp.exemple.fr", 587, user="u", password="p", default_sender="noreply@exemple.fr")
    mid = m.send(Email(to=["a@b.fr"], subject="S", html="<p>h</p>"))
    smtp = _FakeSMTP.instances[0]
    assert mid.startswith("<") and mid.endswith("@exemple.fr>")
    assert smtp.calls == ["starttls", ("login", "u", "p"), ("send", mid), "quit"] and smtp.timeout == 30
    SMTPMailer("h", 25, starttls=False).send(Email(to=["a@b.fr"], subject="S", html="h"))
    assert _FakeSMTP.instances[1].calls == [("send", _FakeSMTP.instances[1].calls[0][1]), "quit"]


def test_smtp_errors_are_typed(monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    mail = Email(to=["a@b.fr"], subject="S", html="h")
    _FakeSMTP.fail = "auth"
    with pytest.raises(MailError, match="authentification"):
        SMTPMailer("h", user="u", password="p").send(mail)
    _FakeSMTP.fail = "rcpt"
    with pytest.raises(MailError, match="a@b.fr"):
        SMTPMailer("h").send(mail)
    _FakeSMTP.fail = None

    def refused(*a, **k):
        raise ConnectionRefusedError(111, "Connection refused")

    monkeypatch.setattr(smtplib, "SMTP", refused)
    with pytest.raises(MailError, match="h:587") as exc:
        SMTPMailer("h").send(mail)
    assert isinstance(exc.value, RuntimeError)


def test_resend_payload_and_errors():
    seen = {}

    def ok(request: httpx.Request):
        import json

        seen["auth"] = request.headers["authorization"]
        seen.update(json.loads(request.read()))
        return httpx.Response(200, json={"id": "re_123"})

    m = ResendMailer("re_key", "Side <noreply@exemple.fr>", client=httpx.Client(transport=httpx.MockTransport(ok)))
    mid = m.send(Email(to=["a@b.fr"], subject="S", html="<p>h</p>", text="h", reply_to="r@b.fr", headers={"X-T": "1"}))
    assert mid == "re_123" and seen["auth"] == "Bearer re_key" and seen["from"] == "Side <noreply@exemple.fr>"
    assert seen["to"] == ["a@b.fr"] and seen["reply_to"] == "r@b.fr" and seen["headers"] == {"X-T": "1"}

    def bad(request):
        return httpx.Response(422, json={"statusCode": 422, "name": "validation_error", "message": "Invalid `to` field"})

    m = ResendMailer("re_key", "n@e.fr", client=httpx.Client(transport=httpx.MockTransport(bad)))
    with pytest.raises(MailError, match="Invalid `to` field"):
        m.send(Email(to=["a@b.fr"], subject="S", html="h"))

    def down(request):
        raise httpx.ConnectError("down")

    m = ResendMailer("re_key", "n@e.fr", client=httpx.Client(transport=httpx.MockTransport(down)))
    with pytest.raises(MailError, match="injoignable"):
        m.send(Email(to=["a@b.fr"], subject="S", html="h"))
    with pytest.raises(MailError, match="RESEND_API_KEY"):
        get_mailer(get_settings(mail_provider="resend", resend_api_key=None))


# ----------------------------------------------------------------------------------------------
# Revue croisée : migrations
# ----------------------------------------------------------------------------------------------
def _mig(tmp_path: Path, **files: str) -> Path:
    d = tmp_path / "migrations"
    d.mkdir(exist_ok=True)
    for name, content in files.items():
        (d / name).write_text(content, encoding="utf-8")
    return d


@pytest.mark.skipif(sys.version_info < (3, 12), reason="autocommit=False n'existe qu'à partir de Python 3.12")
def test_migrate_is_durable_with_autocommit_false(tmp_path: Path):
    mig = _mig(tmp_path, **{"001.sql": "CREATE TABLE t (id INTEGER PRIMARY KEY);"})
    db = tmp_path / "x.db"
    conn = sqlite3.connect(db, autocommit=False)
    assert migrate(conn, mig) == ["001.sql"]
    other = sqlite3.connect(db)
    assert other.execute("SELECT count(*) FROM sqlite_master WHERE name = 't'").fetchone()[0] == 1
    assert migrate(conn, mig) == []


def test_migrate_tolerates_empty_comment_only_and_trailing_comment_files(tmp_path: Path):
    mig = _mig(tmp_path, **{
        "001_empty.sql": "",
        "002_comments.sql": "-- à faire\n-- plus tard\n",
        "003_trailing.sql": "CREATE TABLE a (id INTEGER) -- pas de point-virgule final",
        "004_wrapped.sql": "BEGIN;\nCREATE TABLE b (id INTEGER);\nCOMMIT;\n-- fin du fichier\n",
        "005_block.sql": "CREATE TABLE c (id INTEGER) /* fin */",
    })
    conn = _connect(tmp_path / "x.db")
    assert migrate(conn, mig) == ["001_empty.sql", "002_comments.sql", "003_trailing.sql", "004_wrapped.sql",
                                  "005_block.sql"]
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"a", "b", "c"} <= tables and migrate(conn, mig) == []


def test_migrate_apostrophe_plain_connection_and_older_table(tmp_path: Path):
    mig = _mig(tmp_path, **{"001_l'init.sql": "CREATE TABLE t (id INTEGER);", "002_more.sql": "CREATE TABLE u (id INTEGER);"})
    plain = sqlite3.connect(":memory:")  # sans row_factory
    assert migrate(plain, mig) == ["001_l'init.sql", "002_more.sql"] and migrate(plain, mig) == []
    older = sqlite3.connect(":memory:")  # table créée par une version antérieure, colonnes supplémentaires
    older.execute("CREATE TABLE schema_migrations (id INTEGER PRIMARY KEY, name TEXT UNIQUE, applied_at TEXT)")
    older.execute("INSERT INTO schema_migrations (name, applied_at) VALUES ('001_l''init.sql', 'x')")
    assert migrate(older, mig) == ["002_more.sql"]


def test_migrate_missing_dir_and_memory(tmp_path: Path):
    conn = _connect(":memory:")
    with pytest.raises(FileNotFoundError):
        migrate(conn, tmp_path / "nope")
    assert migrate(conn, _mig(tmp_path, **{"001.sql": "CREATE TABLE t (id INTEGER);"})) == ["001.sql"]


def test_connect_falls_back_when_wal_is_impossible(tmp_path: Path, monkeypatch):
    real_connect = sqlite3.connect

    class ReadOnly(sqlite3.Connection):
        def execute(self, sql, *args):
            if "journal_mode" in sql:
                raise sqlite3.OperationalError("attempt to write a readonly database")
            return super().execute(sql, *args)

    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: real_connect(*a, factory=ReadOnly, **k))
    conn = _connect(tmp_path / "ro.db")
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
