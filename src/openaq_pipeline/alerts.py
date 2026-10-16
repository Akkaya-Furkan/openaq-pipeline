"""WHO threshold check on the stored series, de-duplicated per sensor and UTC day."""
import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

from . import guidelines

logger = logging.getLogger(__name__)
WINDOW_HOURS = 24
MIN_VALID_HOURS = 18  # a 24-hour mean needs 75% of the hours
MAX_AGE_HOURS = 6     # a sensor whose latest reading is older than this is not "now"


def init(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS alerts(
        sensor_id INTEGER REFERENCES sensors, day_utc TEXT, window_end TEXT, parameter TEXT,
        mean_value REAL, limit_value REAL, sent_utc TEXT, delivered INTEGER,
        PRIMARY KEY(sensor_id, day_utc))""")


def daily_means(conn):
    """24-hour mean ending at each sensor's latest reading, with its WHO limit and coverage."""
    frame = pd.read_sql_query(
        """SELECT m.sensor_id, m.parameter, m.datetime_utc, m.value, st.name, st.city
           FROM measurements m JOIN sensors s USING(sensor_id)
           JOIN stations st USING(location_id)
           WHERE m.is_missing=0 AND m.value IS NOT NULL""", conn)
    rows = []
    if not frame.empty:
        frame["ts"] = pd.to_datetime(frame.datetime_utc, utc=True, format="mixed")
    for sensor_id, group in frame.groupby("sensor_id") if not frame.empty else []:
        limit = guidelines.daily_limit(group.parameter.iloc[0])
        if limit is None:
            continue
        end = group.ts.max()
        window = group[(group.ts > end - timedelta(hours=WINDOW_HOURS)) & (group.ts <= end)]
        first = group.iloc[0]
        rows.append({"sensor_id": int(sensor_id), "parameter": first.parameter,
                     "station": first["name"], "city": first.city, "end": end,
                     "window_end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "mean": round(float(window.value.mean()), 1), "limit": limit,
                     "hours": len(window)})
    return pd.DataFrame(rows, columns=["sensor_id", "parameter", "station", "city", "end",
                                       "window_end", "mean", "limit", "hours"])


def exceedances(conn, now=None, max_age_hours=None):
    """Current 24-hour means above the WHO 24-hour AQG (enough coverage, fresh data only)."""
    now = now or datetime.now(timezone.utc)
    max_age_hours = MAX_AGE_HOURS if max_age_hours is None else max_age_hours
    means = daily_means(conn)
    found = []
    for item in means.to_dict("records"):
        if now - item.pop("end").to_pydatetime() > timedelta(hours=max_age_hours):
            continue
        if item["hours"] >= MIN_VALID_HOURS and item["mean"] > item["limit"]:
            found.append(item)
    return found


def format_message(item):
    label = guidelines.LABELS.get(item["parameter"], item["parameter"])
    return (f"WHO air-quality alert: {label} 24 h mean {item['mean']} µg/m³ exceeds the "
            f"WHO 2021 guideline of {item['limit']:g} µg/m³ ({item['mean'] / item['limit']:.1f}×)\n"
            f"{item['station']} ({item['city']}), sensor {item['sensor_id']}, "
            f"window ending {item['window_end']} ({item['hours']} hourly values)")


def check_and_notify(conn, transport, now=None):
    """Send one message per sensor and UTC day; a failed delivery is retried on the next run."""
    init(conn)
    sent = failed = skipped = 0
    for item in exceedances(conn, now):
        day = item["window_end"][:10]
        previous = conn.execute("SELECT delivered FROM alerts WHERE sensor_id=? AND day_utc=?",
                                (item["sensor_id"], day)).fetchone()
        if previous and previous[0]:
            skipped += 1
            continue
        try:
            transport.send(format_message(item))
            delivered = 1
            sent += 1
        except Exception as error:
            logger.error("alert delivery failed: %s", error)
            delivered = 0
            failed += 1
        if getattr(transport, "dry_run", False):
            continue  # nothing was delivered: do not suppress the real alert later
        with conn:
            conn.execute("INSERT OR REPLACE INTO alerts VALUES (?,?,?,?,?,?,?,?)",
                         (item["sensor_id"], day, item["window_end"], item["parameter"],
                          item["mean"], item["limit"],
                          (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                          delivered))
    return {"alerts_sent": sent, "alerts_failed": failed, "alerts_duplicate": skipped,
            "transport": transport.name}
