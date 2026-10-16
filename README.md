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

## Scheduling (systemd --user)

`deploy/` holds `openaq-pipeline.service` (oneshot, wrapped in `systemd-inhibit --what=sleep`
so the machine does not suspend mid-run) and `openaq-pipeline.timer` (hourly, `Persistent=true`).
Install for this checkout (needs `pip install -e .[dev,dashboard]` in `.venv` first):

```bash
deploy/install.sh                       # renders the unit paths, enables the timer
systemctl --user list-timers openaq-pipeline.timer
systemctl --user start openaq-pipeline.service   # run once now
journalctl --user -u openaq-pipeline.service -n 50
```

The unit reads optional secrets from `~/.config/openaq-pipeline/env` (`KEY=value` lines,
`chmod 600`); a `.env` in the checkout also works. Timers only run while the user session
is active unless you enable lingering (`loginctl enable-linger $USER`).

## WHO threshold alerts (Telegram)

`python -m openaq_pipeline --alerts` runs the pipeline, then compares each sensor's **24-hour
mean** (hourly values ending at its latest reading; at least 18 valid hours, reading not older
than 6 h) with the WHO 2021 24-hour guideline. `--skip-fetch` evaluates stored data only.

| Parameter | WHO 2021 AQG (24 h) | Annual |
| --- | --- | --- |
| PM2.5 | 15 µg/m³ | 5 µg/m³ |
| PM10 | 45 µg/m³ | 15 µg/m³ |
| NO2 | 25 µg/m³ | 10 µg/m³ |
| O3 | 100 µg/m³ (8-hour) | 60 µg/m³ (peak season) |
| SO2 | 40 µg/m³ | |
| CO | 4 mg/m³ | |

Source: WHO global air quality guidelines 2021 (Geneva: World Health Organization, 2021), Table 0.1.
The values were cross-checked against the WHO guideline summary presented to the UNECE Air
Convention EPCAC panel, 29 Nov 2021
(https://iiasa.ac.at/sites/default/files/2025-02/WHO%20global%20air%20quality%20guidelines%202021_%20Setting%20ambitious%20goals%20for%20air%20quality%20to%20protect%20public%20health.pdf),
a PMC overview and a web search; the WHO publication's own PDF returned HTTP 403 to the
automated fetch, so the table itself was read from that summary. Short-term AQG levels are
99th percentiles (3-4 exceedance days a year), so one day above 15 µg/m³ is an alert, not
a violation. Only PM2.5 and NO2 are ingested; the other rows are in `guidelines.py` for later.

Delivery: set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in the environment (never in the
repo). Without them the alert text is only logged (`[dry-run] would send`) and nothing is
recorded as sent. At most one message per sensor and UTC day is sent; a failed delivery is
retried on the next run. Error messages never contain the bot token.

## Dashboard

```bash
.venv/bin/streamlit run src/openaq_pipeline/dashboard.py   # OPENAQ_DB overrides data/air.db
```

Shows the last run, sensors above the WHO 24-hour guideline, the latest value per sensor, and
hourly time series per parameter with the guideline as a flat reference line, with city,
parameter and sensor selectors. The database is opened read-only.

## Status

P9/1 (extract/transform/load) and P9/2 (timer, alerts, dashboard) done. Known gap: on the
first real runs Ankara returned no measurements (36 sensors, 0 rows), so the dashboard is
Istanbul-only until that is investigated.
