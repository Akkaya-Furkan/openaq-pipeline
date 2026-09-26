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

## Status
Planned — part of a 30-project computational biology and scientific software portfolio.
