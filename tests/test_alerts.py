import smtplib
import sqlite3
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from openaq_pipeline import alerts, guidelines, notify, queries, store

END = datetime(2026, 10, 15, 8, tzinfo=timezone.utc)


class Recorder:
    name = "fake"

    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, subject, body):
        if self.fail:
            raise RuntimeError("down")
        self.sent.append((subject, body))


def seed(path, value, hours=24, parameter="pm25", sensor_id=1):
    conn = store.init(path)
    conn.execute("INSERT OR IGNORE INTO stations(location_id,name,city) VALUES (10,'Kadikoy','istanbul')")
    conn.execute("INSERT OR IGNORE INTO sensors VALUES (?,10,?,'µg/m³')", (sensor_id, parameter))
    for h in range(hours):
        stamp = (END - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute("INSERT INTO measurements VALUES (?,?,NULL,?,?,'µg/m³',?,'µg/m³',0)",
                     (sensor_id, stamp, parameter, value, value))
    conn.commit()
    return conn


def test_who_values_match_2021_table():
    assert guidelines.WHO_2021["pm25"]["24h"][0] == 15 and guidelines.WHO_2021["pm25"]["annual"][0] == 5
    assert guidelines.WHO_2021["no2"]["24h"][0] == 25 and guidelines.WHO_2021["no2"]["annual"][0] == 10
    assert guidelines.WHO_2021["pm10"]["24h"][0] == 45 and guidelines.WHO_2021["o3"]["8h"][0] == 100
    assert guidelines.daily_limit("co") is None and guidelines.daily_limit("pm25") == 15


def test_exceedance_detected_and_message(tmp_path):
    conn = seed(tmp_path / "a.db", 30.0)
    found = alerts.exceedances(conn, now=END + timedelta(hours=1))
    assert [(f["sensor_id"], f["mean"], f["limit"]) for f in found] == [(1, 30.0, 15.0)]
    subject, body = alerts.format_email(found)
    assert "1 station above" in subject and "PM2.5 30.0" in subject and "2.0x" in subject
    assert "Kadikoy" in subject and "Kadikoy" in body and "WHO 24h" in body and "15" in body


def test_at_guideline_is_not_exceedance_and_sparse_or_stale_ignored(tmp_path):
    conn = seed(tmp_path / "a.db", 15.0)
    assert alerts.exceedances(conn, now=END) == []
    sparse = seed(tmp_path / "b.db", 99.0, hours=10)
    assert alerts.exceedances(sparse, now=END) == []
    stale = seed(tmp_path / "c.db", 99.0)
    assert alerts.exceedances(stale, now=END + timedelta(hours=7)) == []


def test_no2_uses_its_own_limit(tmp_path):
    conn = seed(tmp_path / "a.db", 26.0, parameter="no2")
    assert alerts.exceedances(conn, now=END)[0]["limit"] == 25.0


def test_alert_sent_once_per_day_and_retried_after_failure(tmp_path):
    conn = seed(tmp_path / "a.db", 30.0)
    now = END + timedelta(hours=1)
    bad = Recorder(fail=True)
    assert alerts.check_and_notify(conn, bad, now)["alerts_failed"] == 1
    good = Recorder()
    assert alerts.check_and_notify(conn, good, now)["alerts_sent"] == 1
    again = alerts.check_and_notify(conn, good, now)
    assert again["alerts_sent"] == 0 and again["alerts_duplicate"] == 1 and len(good.sent) == 1


def test_dry_run_does_not_consume_the_daily_alert(tmp_path):
    conn = seed(tmp_path / "a.db", 30.0)
    now = END + timedelta(hours=1)
    dry = notify.DryRunTransport(lambda text: None)
    assert alerts.check_and_notify(conn, dry, now)["alerts_sent"] == 1
    assert conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 0
    assert alerts.check_and_notify(conn, Recorder(), now)["alerts_sent"] == 1


ENV = {"SMTP_HOST": "smtp.example.org", "SMTP_USER": "u", "SMTP_PASSWORD": "SECRETPW",
       "ALERT_EMAIL_FROM": "a@example.org", "ALERT_EMAIL_TO": "b@example.org"}


def clear_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no .env here
    for name in (*notify.REQUIRED, "SMTP_PORT"):
        monkeypatch.delenv(name, raising=False)


def test_dry_run_when_smtp_env_missing_and_logged(monkeypatch, tmp_path, caplog):
    clear_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.org")
    transport = notify.make_transport()
    assert transport.name == "dry-run"
    assert "SMTP_PASSWORD" in caplog.text and "dry-run only" in caplog.text
    lines = []
    notify.DryRunTransport(lines.append).send("subj", "body")
    assert lines == ["Subject: subj\n\nbody"]


class FakeSMTP:
    instances = []

    def __init__(self, host, port):
        self.host, self.port, self.log, self.fail = host, port, [], False
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        self.log.append(("login", user, password))
        if self.fail:
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials for u")

    def send_message(self, message):
        self.log.append(("send", message))


def test_email_transport_message_and_default_port(monkeypatch, tmp_path):
    clear_env(monkeypatch, tmp_path)
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    FakeSMTP.instances.clear()
    transport = notify.make_transport(smtp=FakeSMTP)
    assert transport.name == "email"
    transport.send("Subject line", "Body text")
    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.example.org", 587)
    message = smtp.log[1][1]
    assert message["To"] == "b@example.org" and message["From"] == "a@example.org"
    assert message["Subject"] == "Subject line" and "Body text" in message.get_content()


def test_email_failure_does_not_leak_credentials(monkeypatch, tmp_path):
    clear_env(monkeypatch, tmp_path)
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)

    def failing(host, port):
        smtp = FakeSMTP(host, port)
        smtp.fail = True
        return smtp

    with pytest.raises(RuntimeError) as error:
        notify.make_transport(smtp=failing).send("s", "b")
    assert "SECRETPW" not in str(error.value) and "bad credentials" not in str(error.value)
    assert "SMTPAuthenticationError" in str(error.value)


def test_one_email_per_run_covers_all_stations(tmp_path):
    conn = seed(tmp_path / "a.db", 30.0)
    seed(tmp_path / "a.db", 60.0, sensor_id=2)
    recorder = Recorder()
    result = alerts.check_and_notify(conn, recorder, END + timedelta(hours=1))
    assert result["alerts_sent"] == 2 and len(recorder.sent) == 1
    subject, body = recorder.sent[0]
    assert "2 stations above" in subject and "4.0x" in subject  # worst first
    assert body.index("60.0") < body.index("30.0")


def test_dashboard_queries(tmp_path):
    path = tmp_path / "a.db"
    seed(path, 30.0).close()
    conn = queries.connect(path)
    assert len(queries.stations(conn)) == 1
    assert len(queries.series(conn, [1])) == 24 and queries.series(conn, []).empty
    assert queries.latest(conn).value.iloc[0] == 30.0
    assert queries.last_run(conn) is None
    assert alerts.daily_means(conn)["mean"].iloc[0] == 30.0
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM measurements")


def test_cli_alerts_dry_run(tmp_path, monkeypatch, capsys, caplog):
    import json
    import sys
    from openaq_pipeline import __main__ as cli
    path = tmp_path / "a.db"
    seed(path, 30.0).close()
    monkeypatch.chdir(tmp_path)
    clear_env(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["x", "--db", str(path), "--skip-fetch"])
    monkeypatch.setattr(alerts, "MAX_AGE_HOURS", 10**6)  # fixture data is old
    assert cli.main() == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["transport"] == "dry-run" and summary["alerts_sent"] == 1
    assert "would send" in caplog.text
