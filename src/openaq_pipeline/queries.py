"""Read-only queries for the dashboard (kept free of Streamlit so they can be tested)."""
import sqlite3

import pandas as pd


def connect(db_path):
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def stations(conn):
    return pd.read_sql_query(
        """SELECT s.sensor_id, s.parameter, st.location_id, st.name, st.city
           FROM sensors s JOIN stations st USING(location_id)
           WHERE s.sensor_id IN (SELECT DISTINCT sensor_id FROM measurements)
           ORDER BY st.city, st.name, s.parameter""", conn)


def series(conn, sensor_ids):
    if not sensor_ids:
        return pd.DataFrame(columns=["sensor_id", "parameter", "time", "value"])
    marks = ",".join("?" for _ in sensor_ids)
    frame = pd.read_sql_query(
        f"""SELECT sensor_id, parameter, datetime_utc, value FROM measurements
            WHERE is_missing=0 AND sensor_id IN ({marks}) ORDER BY datetime_utc""",
        conn, params=list(sensor_ids))
    frame["time"] = pd.to_datetime(frame.pop("datetime_utc"), utc=True, format="mixed")
    return frame


def latest(conn):
    frame = pd.read_sql_query(
        """SELECT m.sensor_id, st.city, st.name, m.parameter, m.datetime_utc, m.value
           FROM measurements m JOIN sensors s USING(sensor_id) JOIN stations st USING(location_id)
           WHERE m.is_missing=0 AND m.datetime_utc =
             (SELECT MAX(datetime_utc) FROM measurements
              WHERE sensor_id=m.sensor_id AND is_missing=0)
           ORDER BY st.city, st.name, m.parameter""", conn)
    return frame


def last_run(conn):
    row = conn.execute("SELECT started_utc, status, rows_upserted FROM runs "
                       "ORDER BY run_id DESC LIMIT 1").fetchone()
    return dict(zip(("started_utc", "status", "rows_upserted"), row)) if row else None
