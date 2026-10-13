"""One-command incremental extraction, transformation and loading."""
import logging
from datetime import datetime, timedelta, timezone

import httpx

from . import config, store, transform
from .client import OpenAQClient, utc_iso

logger = logging.getLogger(__name__)


def run(db_path="data/air.db", cities=("istanbul", "ankara"), hours=48, client=None, now=None):
    now = now or datetime.now(timezone.utc)
    now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    summary = {"started_utc": utc_iso(datetime.now(timezone.utc)), "finished_utc": None,
               "status": "ok", "stations": 0, "sensors": 0, "rows_upserted": 0,
               "missing": 0, "gap_hours": 0, "sensors_skipped": 0, "error": None}
    conn = store.init(db_path)
    owned_client = client is None
    try:
        if client is None:
            client = OpenAQClient(config.api_key())
        for city in cities:
            lat, lon = config.CITIES[city]
            stations, sensors = transform.stations_and_sensors(
                client.locations_near(lat, lon, config.RADIUS_M), city)
            with conn:
                station_count = store.upsert_stations(conn, stations)
                sensor_count = store.upsert_sensors(conn, sensors)
            summary["stations"] += station_count
            summary["sensors"] += sensor_count
            timezones = dict(zip(stations.location_id, stations.timezone))
            for sensor in sensors.itertuples(index=False):
                with conn:
                    latest = store.last_datetime(conn, sensor.sensor_id)
                    start = now - timedelta(hours=hours)
                    if latest:
                        start = max(start, datetime.fromisoformat(latest.replace("Z", "+00:00"))
                                    - timedelta(hours=1))
                    try:
                        items = list(client.sensor_measurements(sensor.sensor_id, start, now))
                    except httpx.HTTPStatusError as error:
                        # a sensor listed under a location can be retired; skip it, keep the run
                        if error.response.status_code != 404:
                            raise
                        logger.warning("sensor %s not found, skipped", sensor.sensor_id)
                        summary["sensors_skipped"] += 1
                        continue
                    frame = transform.measurements(items, sensor.sensor_id,
                                                   timezones.get(sensor.location_id))
                    count = store.upsert_measurements(conn, frame)
                summary["rows_upserted"] += count
                summary["missing"] += int(frame.is_missing.sum())
                summary["gap_hours"] += transform.gap_hours(frame)
    except Exception as error:
        summary["status"] = "error"
        summary["error"] = str(error)
        raise
    finally:
        summary["finished_utc"] = utc_iso(datetime.now(timezone.utc))
        try:
            with conn:
                columns = [c for c in summary if c != "sensors_skipped"]
                conn.execute(f"INSERT INTO runs ({', '.join(columns)}) "
                             f"VALUES ({', '.join('?' for _ in columns)})", [summary[c] for c in columns])
        finally:
            conn.close()
            if owned_client and client is not None:
                client.close()
    return summary
