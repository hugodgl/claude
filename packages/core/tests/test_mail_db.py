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
