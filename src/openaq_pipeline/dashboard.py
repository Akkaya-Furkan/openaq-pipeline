"""Streamlit dashboard: ``streamlit run src/openaq_pipeline/dashboard.py``."""
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from openaq_pipeline import alerts, guidelines, queries  # noqa: E402

st.set_page_config(page_title="Air quality (OpenAQ)", layout="wide")
db_path = st.sidebar.text_input("SQLite database", os.environ.get("OPENAQ_DB", "data/air.db"))
if not Path(db_path).is_file():
    st.error(f"Database not found: {db_path}. Run `python -m openaq_pipeline` first.")
    st.stop()
conn = queries.connect(db_path)
sensors = queries.stations(conn)
st.title("Air quality: Istanbul and Ankara")
run = queries.last_run(conn)
if run:
    st.caption(f"Last pipeline run {run['started_utc']} · {run['status']} · "
               f"{run['rows_upserted']} rows upserted. Values are hourly means, µg/m³, UTC.")

city = st.sidebar.multiselect("City", sorted(sensors.city.unique()), default=sorted(sensors.city.unique()))
parameter = st.sidebar.multiselect("Parameter", sorted(sensors.parameter.unique()),
                                   default=sorted(sensors.parameter.unique()))
subset = sensors[sensors.city.isin(city) & sensors.parameter.isin(parameter)]
labels = {row.sensor_id: f"{row.city} · {row['name']} · {guidelines.LABELS.get(row.parameter, row.parameter)}"
          for _, row in subset.iterrows()}
chosen = st.sidebar.multiselect("Stations / sensors", list(labels), format_func=labels.get,
                                default=list(labels)[:4])

means = alerts.daily_means(conn)
means = means[means.sensor_id.isin(subset.sensor_id)]
over = means[(means["mean"] > means["limit"]) & (means.hours >= alerts.MIN_VALID_HOURS)]
col1, col2, col3 = st.columns(3)
col1.metric("Sensors with data", len(subset))
col2.metric("24 h mean above WHO guideline", len(over))
col3.metric("Latest reading (UTC)", str(means.window_end.max()) if len(means) else "n/a")

st.subheader("Threshold exceedances (24 h mean vs WHO 2021 guideline)")
if over.empty:
    st.success("No sensor currently exceeds the WHO 24-hour guideline.")
else:
    table = over.assign(label=over.parameter.map(guidelines.LABELS))[
        ["city", "station", "label", "mean", "limit", "hours", "window_end"]]
    st.dataframe(table.rename(columns={"mean": "24h mean", "limit": "WHO 24h AQG",
                                       "hours": "valid hours"}), hide_index=True)

st.subheader("Latest measurements")
latest = queries.latest(conn)
latest = latest[latest.sensor_id.isin(subset.sensor_id)]
st.dataframe(latest.drop(columns="sensor_id"), hide_index=True)

st.subheader("Time series")
data = queries.series(conn, chosen)
if data.empty:
    st.info("Select at least one sensor in the sidebar.")
else:
    data["sensor"] = data.sensor_id.map(labels)
    for name, group in data.groupby("parameter"):
        st.markdown(f"**{guidelines.LABELS.get(name, name)}** (flat line: WHO 24 h guideline, "
                    f"{guidelines.daily_limit(name)} µg/m³)")
        wide = group.pivot_table(index="time", columns="sensor", values="value")
        limit = guidelines.daily_limit(name)
        if limit is not None:
            wide["WHO 24h guideline"] = limit
        st.line_chart(wide)
