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

    def send(self, text):
        if self.fail:
            raise RuntimeError("down")
        self.sent.append(text)


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
    text = alerts.format_message(found[0])
    assert "PM2.5" in text and "30" in text and "15" in text and "Kadikoy" in text


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


def test_dry_run_when_telegram_env_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here
    transport = notify.make_transport()
    assert transport.name == "dry-run"
    lines = []
    notify.DryRunTransport(lines.append).send("hello")
    assert lines == ["hello"]


def test_telegram_transport_payload_and_token_not_leaked(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:SECRET")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200 if len(seen) == 1 else 401, json={"ok": True})

    transport = notify.make_transport(httpx.Client(transport=httpx.MockTransport(handler)))
    assert transport.name == "telegram"
    transport.send("hi")
    assert seen[0].url.path == "/bot123:SECRET/sendMessage"
    assert seen[0].content == b'{"chat_id":"42","text":"hi"}'
    with pytest.raises(RuntimeError) as error:
        transport.send("again")
    assert "SECRET" not in str(error.value) and "401" in str(error.value)


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
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(sys, "argv", ["x", "--db", str(path), "--skip-fetch"])
    monkeypatch.setattr(alerts, "MAX_AGE_HOURS", 10**6)  # fixture data is old
    assert cli.main() == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["transport"] == "dry-run" and summary["alerts_sent"] == 1
    assert "would send" in caplog.text
