"""SQLite schema and idempotent writes; callers control transactions."""
import sqlite3
from pathlib import Path

import pandas as pd

from .transform import STATION_COLUMNS, SENSOR_COLUMNS, MEASUREMENT_COLUMNS


def init(db_path):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS stations(
            location_id INTEGER PRIMARY KEY, name TEXT, city TEXT, locality TEXT,
            timezone TEXT, country TEXT, latitude REAL, longitude REAL, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS sensors(
            sensor_id INTEGER PRIMARY KEY, location_id INTEGER REFERENCES stations,
            parameter TEXT, unit_raw TEXT);
        CREATE TABLE IF NOT EXISTS measurements(
            sensor_id INTEGER REFERENCES sensors, datetime_utc TEXT, datetime_local TEXT,
            parameter TEXT, value_raw REAL, unit_raw TEXT, value REAL, unit TEXT,
            is_missing INTEGER, PRIMARY KEY(sensor_id, datetime_utc));
        CREATE INDEX IF NOT EXISTS measurements_parameter_datetime
            ON measurements(parameter, datetime_utc);
        CREATE TABLE IF NOT EXISTS runs(
            run_id INTEGER PRIMARY KEY AUTOINCREMENT, started_utc TEXT, finished_utc TEXT,
            status TEXT, stations INTEGER, sensors INTEGER, rows_upserted INTEGER,
            missing INTEGER, gap_hours INTEGER, error TEXT);
    ''')
    return conn


def _upsert(conn, table, df, columns, keys):
    updates = ', '.join(f'{column}=excluded.{column}' for column in columns if column not in keys)
    sql = (f"INSERT INTO {table} ({', '.join(columns)}) "
           f"VALUES ({', '.join('?' for _ in columns)}) "
           f"ON CONFLICT ({', '.join(keys)}) DO UPDATE SET {updates}")
    rows = [tuple(None if pd.isna(value) else value for value in row)
            for row in df[columns].itertuples(index=False, name=None)]
    return conn.executemany(sql, rows).rowcount


def upsert_stations(conn, df):
    return _upsert(conn, "stations", df, STATION_COLUMNS, ["location_id"])


def upsert_sensors(conn, df):
    return _upsert(conn, "sensors", df, SENSOR_COLUMNS, ["sensor_id"])


def upsert_measurements(conn, df):
    return _upsert(conn, "measurements", df, MEASUREMENT_COLUMNS, ["sensor_id", "datetime_utc"])


def last_datetime(conn, sensor_id):
    return conn.execute("SELECT MAX(datetime_utc) FROM measurements WHERE sensor_id=?",
                        (sensor_id,)).fetchone()[0]
