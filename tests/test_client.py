from datetime import datetime, timezone, timedelta

import httpx
import pytest

from openaq_pipeline.client import OpenAQClient
from openaq_pipeline.config import MissingApiKey, api_key


def test_pagination(fixture_data):
    items = fixture_data('measurements_units')['results'][:5]
    pages = []

    def handler(request):
        page = int(request.url.params['page'])
        pages.append(page)
        assert request.url.params['limit'] == '2'
        assert request.url.params['sensor'] == '456'
        return httpx.Response(200, json={'meta': {'found': '>1000'}, 'results': items[(page-1)*2:page*2]})

    client = OpenAQClient('test', transport=httpx.MockTransport(handler))
    try:
        assert list(client.paginate('/measurements', {'sensor': 456}, limit=2)) == items
        assert pages == [1, 2, 3]
    finally:
        client.close()


@pytest.mark.parametrize('statuses,headers,expected', [
    ([429, 200], {'Retry-After': '3'}, [3]),
    ([503, 503, 200], {}, [1, 2]),
    ([429, 200], {'x-ratelimit-reset': '4'}, [4]),
    ([429, 200], {'Retry-After': '3', 'x-ratelimit-reset': '4'}, [3]),
])
def test_retry(statuses, headers, expected, caplog):
    waits = []
    statuses = iter(statuses)
    client = OpenAQClient('secret-key', transport=httpx.MockTransport(
        lambda request: httpx.Response(next(statuses), headers=headers, json={'results': []})), sleep=waits.append)
    try:
        assert client.get('/locations', {}) == {'results': []}
        assert waits == expected
        assert 'secret-key' not in caplog.text
        assert 'status=' in caplog.text and 'wait=' in caplog.text
    finally:
        client.close()


def test_retry_exhaustion():
    calls, waits = [], []

    def handler(request):
        calls.append(request)
        return httpx.Response(503)

    client = OpenAQClient('test', transport=httpx.MockTransport(handler), max_retries=2, sleep=waits.append)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            client.get('/locations', {})
        assert len(calls) == 3
        assert waits == [1, 2]
    finally:
        client.close()


@pytest.mark.parametrize('exhaust', [False, True])
def test_transport_retry(exhaust):
    calls, waits = [], []

    def handler(request):
        calls.append(request)
        if exhaust or len(calls) == 1:
            raise httpx.ConnectError('offline connection failure', request=request)
        return httpx.Response(200, json={'results': []})

    client = OpenAQClient('test', transport=httpx.MockTransport(handler), max_retries=1, sleep=waits.append)
    try:
        if exhaust:
            with pytest.raises(httpx.ConnectError):
                client.get('/locations', {})
        else:
            assert client.get('/locations', {}) == {'results': []}
        assert len(calls) == 2
        assert waits == [1]
    finally:
        client.close()


@pytest.mark.parametrize('status', [401, 400, 403, 404])
def test_client_errors_do_not_retry(status):
    waits, calls = [], []

    def handler(request):
        calls.append(request)
        return httpx.Response(status)

    client = OpenAQClient('test', transport=httpx.MockTransport(handler), sleep=waits.append)
    try:
        with pytest.raises(httpx.HTTPStatusError, match='invalid or missing API key' if status == 401 else str(status)):
            client.get('/locations', {})
        assert waits == []
        assert len(calls) == 1
    finally:
        client.close()


def test_proactive_throttle():
    waits = []
    client = OpenAQClient('test', transport=httpx.MockTransport(lambda _: httpx.Response(
        200, headers={'x-ratelimit-remaining': '0', 'x-ratelimit-reset': '7'}, json={'results': []})), sleep=waits.append)
    try:
        assert client.get('/locations', {}) == {'results': []}
        assert waits == [7]
    finally:
        client.close()


def test_measurement_utc_query():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'results': []})

    client = OpenAQClient('test', transport=httpx.MockTransport(handler))
    start = datetime(2026, 10, 12, 13, tzinfo=timezone(timedelta(hours=3)))
    try:
        assert list(client.sensor_measurements(456, start, start + timedelta(hours=1))) == []
        assert requests[0].url.path == '/v3/sensors/456/measurements'
        assert requests[0].url.params['datetime_from'] == '2026-10-12T10:00:00Z'
        assert requests[0].url.params['datetime_to'] == '2026-10-12T11:00:00Z'
    finally:
        client.close()


def test_missing_key(monkeypatch, tmp_path):
    monkeypatch.delenv('OPENAQ_API_KEY', raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(MissingApiKey, match='https://explore.openaq.org/register'):
        api_key()


def test_dotenv_key_and_environment_precedence(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('OPENAQ_API_KEY', raising=False)
    (tmp_path / '.env').write_text('# comment\n\nOTHER=x\n OPENAQ_API_KEY = "file-key"\n')
    assert api_key() == 'file-key'
    monkeypatch.setenv('OPENAQ_API_KEY', 'env-key')
    assert api_key() == 'env-key'
