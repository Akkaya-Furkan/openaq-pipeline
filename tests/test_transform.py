import pandas as pd
import pytest

from openaq_pipeline.transform import measurements, stations_and_sensors, gap_hours


def test_units_missing_and_local_time(fixture_data, caplog):
    frame = measurements(fixture_data('measurements_units')['results'], 456, 'Europe/Istanbul')
    assert list(frame.columns) == ['sensor_id', 'datetime_utc', 'datetime_local', 'parameter',
                                   'value_raw', 'unit_raw', 'value', 'unit', 'is_missing']
    assert frame.value[:6].tolist() == pytest.approx([1, 1, 1, 18.8, 18.8, 5])
    assert frame.is_missing.tolist() == [0, 0, 0, 0, 0, 0, 1, 1, 1]
    assert frame.value[6:].isna().all()
    assert frame.value_raw.iloc[7] == -999
    assert frame.datetime_utc.iloc[0] == '2026-10-12T10:00:00Z'
    assert frame.datetime_local.iloc[0] == '2026-10-12T13:00:00+03:00'
    assert frame.unit[:6].tolist() == ['µg/m³'] * 6
    assert 'Unknown unit' in caplog.text


def test_sensor_filter(fixture_data):
    stations, sensors = stations_and_sensors(fixture_data('locations_istanbul')['results'], 'istanbul')
    assert stations.location_id.tolist() == [123]
    assert stations.country.tolist() == ['TR']
    assert stations.city.tolist() == ['istanbul']
    assert sensors.sensor_id.tolist() == [456, 457]
    assert sensors.parameter.tolist() == ['pm25', 'no2']


def test_missing_keys():
    stations, sensors = stations_and_sensors([{}, {'id': 1, 'sensors': [{}, {'id': 2, 'parameter': {'name': 'pm25'}}]}], 'istanbul')
    assert len(stations) == len(sensors) == 1
    assert pd.isna(stations.timezone.iloc[0])
    frame = measurements([{}, {'period': {}}, {'parameter': None, 'period': {'datetimeTo': None}}], 2, None)
    assert len(frame) == 3
    assert frame.is_missing.tolist() == [1, 1, 1]
    assert frame.datetime_utc.isna().all()
    assert frame.datetime_local.isna().all()


def test_nan_is_missing(fixture_data):
    item = fixture_data('measurements_pm25')['results'][0]
    item['value'] = float('nan')
    assert measurements([item], 456, 'Europe/Istanbul').is_missing.tolist() == [1]


def test_gap_hours(fixture_data):
    frame = measurements(fixture_data('measurements_pm25')['results'], 456, 'Europe/Istanbul')
    assert gap_hours(frame) == 2
    assert gap_hours(pd.concat([frame, frame])) == 2
    assert gap_hours(frame.iloc[:1]) == 0
    assert gap_hours(frame.iloc[:0]) == 0
