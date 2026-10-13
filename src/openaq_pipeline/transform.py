"""Defensive transformation of OpenAQ v3 response items."""
import logging
from datetime import datetime, timezone as utc_timezone
from zoneinfo import ZoneInfo

import pandas as pd

from .config import PARAMETERS

logger = logging.getLogger(__name__)
STATION_COLUMNS = ["location_id", "name", "city", "locality", "timezone", "country",
                   "latitude", "longitude", "updated_at"]
SENSOR_COLUMNS = ["sensor_id", "location_id", "parameter", "unit_raw"]
MEASUREMENT_COLUMNS = ["sensor_id", "datetime_utc", "datetime_local", "parameter",
                       "value_raw", "unit_raw", "value", "unit", "is_missing"]
MASS_UNITS = {"µg/m³", "ug/m3", "μg/m³"}
# NO2 conversion at 25 °C and 1 atm: 1 ppm = 1880 µg/m³; 1 ppb = 1.88 µg/m³.
NO2_PPM_FACTOR = 1880


def stations_and_sensors(location_items, city):
    stations, sensors = [], []
    for location in location_items:
        selected = []
        for sensor in location.get("sensors") or []:
            parameter = sensor.get("parameter") or {}
            if parameter.get("name") in PARAMETERS:
                selected.append({"sensor_id": sensor.get("id"),
                                 "location_id": location.get("id"),
                                 "parameter": parameter.get("name"),
                                 "unit_raw": parameter.get("units")})
        if not selected:
            continue
        coordinates = location.get("coordinates") or {}
        stations.append({"location_id": location.get("id"), "name": location.get("name"),
                         "city": city, "locality": location.get("locality"),
                         "timezone": location.get("timezone"),
                         "country": (location.get("country") or {}).get("code"),
                         "latitude": coordinates.get("latitude"),
                         "longitude": coordinates.get("longitude"),
                         "updated_at": datetime.now(utc_timezone.utc).isoformat().replace("+00:00", "Z")})
        sensors.extend(selected)
    return (pd.DataFrame(stations, columns=STATION_COLUMNS),
            pd.DataFrame(sensors, columns=SENSOR_COLUMNS))


def measurements(items, sensor_id, timezone):
    rows = []
    for item in items:
        parameter = item.get("parameter") or {}
        name, raw_unit = parameter.get("name"), parameter.get("units")
        raw_value = item.get("value")
        value = None
        valid_unit = raw_unit in MASS_UNITS or (name == "no2" and raw_unit in {"ppm", "ppb"})
        if not valid_unit:
            logger.warning("Unknown unit %r for parameter %r", raw_unit, name)
        if valid_unit and raw_value is not None and not pd.isna(raw_value):
            if raw_value >= 0:
                factor = NO2_PPM_FACTOR if name == "no2" and raw_unit == "ppm" else (
                    1.88 if name == "no2" and raw_unit == "ppb" else 1)
                value = raw_value * factor
        stamp = ((item.get("period") or {}).get("datetimeTo") or {}).get("utc")
        utc, local = None, None
        if stamp:
            instant = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            utc = instant.astimezone(utc_timezone.utc).isoformat().replace("+00:00", "Z")
            if timezone and pd.notna(timezone):
                local = instant.astimezone(ZoneInfo(timezone)).isoformat()
        rows.append({"sensor_id": sensor_id, "datetime_utc": utc, "datetime_local": local,
                     "parameter": name, "value_raw": raw_value, "unit_raw": raw_unit,
                     "value": value, "unit": "µg/m³" if valid_unit else None,
                     "is_missing": int(value is None)})
    return pd.DataFrame(rows, columns=MEASUREMENT_COLUMNS)


def gap_hours(df):
    if df.empty:
        return 0
    stamps = pd.to_datetime(df["datetime_utc"], utc=True, errors="coerce", format="mixed").dropna().drop_duplicates()
    if stamps.empty:
        return 0
    return max(0, int((stamps.max() - stamps.min()).total_seconds() // 3600) + 1 - len(stamps))
