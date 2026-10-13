# Air-quality data pipeline (OpenAQ)

**Question.** An idempotent ETL pipeline and dashboard for city air-quality measurements.

## Data
OpenAQ v3 API (official API, no scraping); PM2.5 and NO2 for selected Turkish cities.

## Approach
1. Extract: pagination, retry/backoff, rate limits, logging
2. Transform: unit and time-zone normalisation, missing-value flags (pandas)
3. Load: SQLite with idempotent upserts
4. Hourly scheduling, WHO-threshold alerts, Streamlit dashboard, tests with mocked API responses

## Deliverables
Pipeline runs with one command; dashboard screenshot; test alert delivered.

## Usage

Requires Python 3.11 or newer. Create a free OpenAQ API key at
https://explore.openaq.org/register, then create `.env` in the directory where
you run the pipeline:

```dotenv
OPENAQ_API_KEY=your-key
```

You can also set `OPENAQ_API_KEY` in the environment; it takes precedence over
`.env`. The key is never logged.

```bash
pip install -e .[dev]
python -m openaq_pipeline
```

The default run loads the last 48 hours of PM2.5 and NO2 within 25 km of Istanbul
and Ankara into `data/air.db`. Re-running updates existing sensor/timestamp rows
without duplicating them. Incremental runs overlap the latest stored timestamp
by one hour, within the requested time window.

```bash
python -m openaq_pipeline --db data/air.db --hours 48 --cities istanbul ankara -v
```

Each run prints a one-line JSON summary to stdout; logging goes to stderr.
A missing key prints setup instructions and exits with code 2.

| Table | Contents | Key |
| --- | --- | --- |
| `stations` | Station identity, city, locality, timezone, country, coordinates and update time | `location_id` |
| `sensors` | Station reference, parameter and original unit | `sensor_id` |
| `measurements` | UTC/local timestamps, raw and normalized values/units, missing flag | `(sensor_id, datetime_utc)` |
| `runs` | Start/finish times, status, station/sensor/row counts, missing count, gap hours and error | `run_id` |

Foreign keys are enabled, and measurements are indexed by parameter and UTC time.
`datetime_utc` comes from `period.datetimeTo.utc`: it is the **end of the averaging
hour**, stored as an ISO 8601 UTC string ending in `Z`. Local time is converted
using the station timezone.

Values are normalized to µg/m³. For NO2 at **25 °C and 1 atm**, the conversion
constant is **1 ppm = 1880 µg/m³**; equivalently, **1 ppb = 1.88 µg/m³**.
PM2.5 accepts `µg/m³`, `ug/m3` and `μg/m³`. Null, NaN, negative sentinel values
and unknown units remain in the database with `is_missing=1` and a null normalized
value. Unknown units also produce a warning. Gap hours count absent hourly slots
between the first and last fetched timestamps for each sensor.

Run the offline test suite:

```bash
.venv/bin/python -m pytest -q
```

The response shapes are validated by mocked tests and should be re-checked
against the live API on the first keyed run.

## Status

Day 1 (extract/transform/load) done; scheduling, alerts and dashboard next.
