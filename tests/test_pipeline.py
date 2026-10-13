import json
import sqlite3
import sys
from datetime import datetime, timezone

import httpx
import pytest

from openaq_pipeline import pipeline
from openaq_pipeline.__main__ import main

NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)


def test_end_to_end(tmp_path, routed_client):
    client, state = routed_client
    path = tmp_path / 'air.db'
    summary = pipeline.run(path, client=client, now=NOW)
    assert {key: summary[key] for key in ['status', 'stations', 'sensors', 'rows_upserted', 'missing', 'gap_hours', 'error']} == {
        'status': 'ok', 'stations': 2, 'sensors': 3, 'rows_upserted': 5, 'missing': 2, 'gap_hours': 2, 'error': None}
    assert summary['started_utc'].endswith('Z') and summary['finished_utc'].endswith('Z')
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT status, rows_upserted FROM runs').fetchall() == [('ok', 5)]
        assert conn.execute('SELECT COUNT(*) FROM stations').fetchone()[0] == 2
        assert conn.execute('SELECT COUNT(*) FROM sensors').fetchone()[0] == 3
    for request in state['requests']:
        if '/measurements' in request.url.path:
            assert request.url.params['datetime_from'] == '2026-10-11T00:00:00Z'
            assert request.url.params['datetime_to'] == '2026-10-13T00:00:00Z'


def test_overlap_and_window_floor(tmp_path, routed_client):
    client, state = routed_client
    path = tmp_path / 'air.db'
    pipeline.run(path, cities=('istanbul',), client=client, now=NOW)
    state['requests'].clear()
    pipeline.run(path, cities=('istanbul',), client=client, now=NOW)
    queries = {r.url.path: r.url.params for r in state['requests'] if '/measurements' in r.url.path}
    assert queries['/v3/sensors/456/measurements']['datetime_from'] == '2026-10-12T13:00:00Z'
    assert queries['/v3/sensors/457/measurements']['datetime_from'] == '2026-10-12T11:00:00Z'
    state['requests'].clear()
    pipeline.run(path, cities=('istanbul',), hours=4, client=client, now=NOW)
    for request in state['requests']:
        if '/measurements' in request.url.path:
            assert request.url.params['datetime_from'] == '2026-10-12T20:00:00Z'


def test_failed_run_is_recorded(tmp_path, routed_client):
    client, state = routed_client
    state['fail_sensor'] = 457
    path = tmp_path / 'air.db'
    with pytest.raises(httpx.HTTPStatusError):
        pipeline.run(path, client=client, now=NOW)
    with sqlite3.connect(path) as conn:
        status, count, error, finished = conn.execute('SELECT status, rows_upserted, error, finished_utc FROM runs').fetchone()
        assert status == 'error' and count == 2
        assert '400' in error and finished.endswith('Z')
        assert conn.execute('SELECT COUNT(*) FROM measurements').fetchone()[0] == 2


def test_missing_sensor_is_skipped(tmp_path, routed_client):
    client, state = routed_client
    state['fail_sensor'], state['fail_status'] = 457, 404
    summary = pipeline.run(tmp_path / 'air.db', client=client, now=NOW)
    assert summary['status'] == 'ok' and summary['sensors_skipped'] == 1
    with sqlite3.connect(tmp_path / 'air.db') as conn:
        assert conn.execute('SELECT status FROM runs').fetchone() == ('ok',)
        assert conn.execute('SELECT COUNT(*) FROM measurements WHERE sensor_id = 457').fetchone()[0] == 0


def test_sensor_write_rolls_back(tmp_path, routed_client, monkeypatch):
    client, _ = routed_client
    original = pipeline.store.upsert_measurements

    def failing_write(conn, frame):
        original(conn, frame)
        raise RuntimeError('write failed')

    monkeypatch.setattr(pipeline.store, 'upsert_measurements', failing_write)
    path = tmp_path / 'air.db'
    with pytest.raises(RuntimeError, match='write failed'):
        pipeline.run(path, client=client, now=NOW)
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM measurements').fetchone()[0] == 0
        assert conn.execute('SELECT status, error FROM runs').fetchone() == ('error', 'write failed')


def test_cli_missing_key(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('OPENAQ_API_KEY', raising=False)
    monkeypatch.setattr(sys, 'argv', ['openaq_pipeline'])
    assert main() == 2
    output = capsys.readouterr()
    assert not output.out
    assert 'OPENAQ_API_KEY=...' in output.err
    assert 'Traceback' not in output.err


def test_cli_json(monkeypatch, tmp_path, routed_client, capsys):
    client, _ = routed_client
    monkeypatch.setattr('openaq_pipeline.__main__.run', lambda **kwargs: pipeline.run(**kwargs, client=client, now=NOW))
    monkeypatch.setattr(sys, 'argv', ['openaq_pipeline', '--db', str(tmp_path / 'air.db'), '--hours', '48', '--cities', 'istanbul'])
    assert main() == 0
    output = capsys.readouterr().out
    assert len(output.splitlines()) == 1
    assert json.loads(output)['status'] == 'ok'
