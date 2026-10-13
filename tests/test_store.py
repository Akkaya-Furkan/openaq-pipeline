import sqlite3
from datetime import datetime, timezone

import pytest

from openaq_pipeline import store, transform
from openaq_pipeline.pipeline import run

NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)


def test_pipeline_idempotent_and_updates(tmp_path, routed_client):
    client, state = routed_client
    path = tmp_path / 'data' / 'air.db'
    first = run(path, client=client, now=NOW)
    with sqlite3.connect(path) as conn:
        original_count = conn.execute('SELECT COUNT(*) FROM measurements').fetchone()[0]
    state['value'] = 15.5
    second = run(path, client=client, now=NOW)
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM measurements').fetchone()[0] == original_count == 5
        assert conn.execute('SELECT value FROM measurements WHERE sensor_id=456 AND datetime_utc=?',
                            ('2026-10-12T11:00:00Z',)).fetchone()[0] == 15.5
        assert conn.execute('SELECT COUNT(*) FROM runs').fetchone()[0] == 2
    assert first['rows_upserted'] == second['rows_upserted'] == 5


def test_schema_upserts_and_last_datetime(tmp_path, fixture_data):
    conn = store.init(tmp_path / 'nested' / 'air.db')
    try:
        assert conn.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        stations, sensors = transform.stations_and_sensors(fixture_data('locations_istanbul')['results'], 'istanbul')
        with conn:
            assert store.upsert_stations(conn, stations) == 1
            assert store.upsert_sensors(conn, sensors) == 2
            assert store.last_datetime(conn, 456) is None
            frame = transform.measurements(fixture_data('measurements_pm25')['results'], 456, 'Europe/Istanbul')
            assert store.upsert_measurements(conn, frame) == 2
            assert store.upsert_measurements(conn, frame) == 2
        assert store.last_datetime(conn, 456) == '2026-10-12T14:00:00Z'
        assert conn.execute('SELECT COUNT(*) FROM measurements').fetchone()[0] == 2
        assert conn.execute('SELECT value FROM measurements WHERE is_missing=1').fetchone()[0] is None
        assert any(row[2] == 'parameter' for row in conn.execute('PRAGMA index_info(measurements_parameter_datetime)'))
        with pytest.raises(sqlite3.IntegrityError), conn:
            conn.execute('INSERT INTO sensors(sensor_id, location_id) VALUES (999, 999)')
    finally:
        conn.close()
