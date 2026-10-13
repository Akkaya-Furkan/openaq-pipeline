"""Offline-testable OpenAQ HTTP client."""
import logging
import time
from datetime import timezone

import httpx

from .config import BASE_URL

logger = logging.getLogger(__name__)


def utc_iso(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class OpenAQClient:
    def __init__(self, api_key, base_url=BASE_URL, transport=None,
                 max_retries=5, backoff=1.0, sleep=time.sleep):
        self.client = httpx.Client(
            base_url=base_url, transport=transport, timeout=30,
            headers={"X-API-Key": api_key, "User-Agent": "openaq-pipeline/0.1"},
        )
        self.max_retries = max_retries
        self.backoff = backoff
        self.sleep = sleep

    def close(self):
        self.client.close()

    def get(self, path, params):
        for attempt in range(self.max_retries + 1):
            response = None
            try:
                response = self.client.get(path, params=params)
                if response.status_code == 401:
                    raise httpx.HTTPStatusError(
                        "invalid or missing API key", request=response.request,
                        response=response,
                    )
                response.raise_for_status()
            except (httpx.TransportError, httpx.HTTPStatusError) as error:
                if isinstance(error, httpx.HTTPStatusError):
                    status = error.response.status_code
                    if status != 429 and not 500 <= status <= 599:
                        raise
                else:
                    status = "transport error"
                if attempt == self.max_retries:
                    raise
                headers = response.headers if response is not None else {}
                wait = None
                for header in ("Retry-After", "x-ratelimit-reset"):
                    try:
                        wait = max(0.0, float(headers[header]))
                        break
                    except (KeyError, ValueError):
                        pass
                if wait is None:
                    wait = self.backoff * 2**attempt
                logger.warning("Retry status=%s wait=%s seconds", status, wait)
                self.sleep(wait)
                continue
            if response.headers.get("x-ratelimit-remaining") == "0":
                self.sleep(float(response.headers.get("x-ratelimit-reset", "0")))
            return response.json()

    def paginate(self, path, params, limit=1000):
        page = 1
        while True:
            results = self.get(path, {**params, "limit": limit, "page": page})["results"]
            yield from results
            if len(results) < limit:
                return
            page += 1

    def locations_near(self, lat, lon, radius):
        return self.paginate("/locations", {
            "coordinates": f"{lat},{lon}", "radius": radius,
        })

    def sensor_measurements(self, sensor_id, datetime_from, datetime_to):
        return self.paginate(f"/sensors/{sensor_id}/measurements", {
            "datetime_from": utc_iso(datetime_from),
            "datetime_to": utc_iso(datetime_to),
        })
