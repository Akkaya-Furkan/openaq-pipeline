"""WHO global air quality guideline (AQG) levels, 2021 update.

Source: WHO global air quality guidelines: particulate matter (PM2.5 and PM10), ozone,
nitrogen dioxide, sulfur dioxide and carbon monoxide. Geneva: World Health Organization, 2021
(Table 0.1, recommended 2021 AQG levels). The short-term values are 99th percentiles of the
annual distribution (3-4 exceedance days per year); one day above them is not a breach of
the guideline, it is a day the guideline says should be rare.
"""

# parameter -> {averaging: (AQG level, unit)}; 24-hour values are the ones we can check
# against the hourly series, the annual ones are shown for context in the dashboard.
WHO_2021 = {
    "pm25": {"24h": (15.0, "µg/m³"), "annual": (5.0, "µg/m³")},
    "pm10": {"24h": (45.0, "µg/m³"), "annual": (15.0, "µg/m³")},
    "no2": {"24h": (25.0, "µg/m³"), "annual": (10.0, "µg/m³")},
    "o3": {"8h": (100.0, "µg/m³"), "peak_season": (60.0, "µg/m³")},
    "so2": {"24h": (40.0, "µg/m³")},
    "co": {"24h": (4.0, "mg/m³")},
}
LABELS = {"pm25": "PM2.5", "pm10": "PM10", "no2": "NO₂", "o3": "O₃", "so2": "SO₂", "co": "CO"}


def daily_limit(parameter):
    """WHO 24-hour guideline for a parameter in µg/m³, or None if there is none."""
    level = WHO_2021.get(parameter, {}).get("24h")
    return level[0] if level and level[1] == "µg/m³" else None
