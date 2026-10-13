import json
from pathlib import Path

import httpx
import pytest

from openaq_pipeline.client import OpenAQClient


@pytest.fixture
def fixture_data():
    def load(name):
        return json.loads((Path(__file__).parent / 'fixtures' / f'{name}.json').read_text())
    return load


@pytest.fixture
def routed_client(fixture_data):
    state = {'value': 12.3, 'requests': [], 'fail_sensor': None, 'fail_status': 400}

    def handler(request):
        state['requests'].append(request)
        assert request.headers['X-API-Key'] == 'test-key'
        assert request.headers['User-Agent'] == 'openaq-pipeline/0.1'
        assert request.url.params['page'] == '1'
        assert request.url.params['limit'] == '1000'
        if request.url.path == '/v3/locations':
            assert request.url.params['radius'] == '25000'
            city = 'istanbul' if request.url.params['coordinates'] == '41.0082,28.9784' else 'ankara'
            return httpx.Response(200, json=fixture_data(f'locations_{city}'))
        sensor = int(request.url.path.split('/')[3])
        if sensor == state['fail_sensor']:
            return httpx.Response(state['fail_status'], json={'error': 'failed'})
        names = {456: 'measurements_pm25', 457: 'measurements_no2', 556: 'measurements_ankara'}
        data = fixture_data(names[sensor])
        if sensor == 456:
            data['results'][0]['value'] = state['value']
        return httpx.Response(200, json=data)

    client = OpenAQClient('test-key', transport=httpx.MockTransport(handler), sleep=lambda _: None)
    yield client, state
    client.close()
