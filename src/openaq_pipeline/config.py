"""Pipeline configuration and local API key loading."""
import os
from pathlib import Path

BASE_URL = "https://api.openaq.org/v3"
CITIES = {"istanbul": (41.0082, 28.9784), "ankara": (39.9334, 32.8597)}
RADIUS_M = 25000
PARAMETERS = {"pm25", "no2"}


class MissingApiKey(ValueError):
    """No OpenAQ API key was configured."""


def api_key():
    key = os.environ.get("OPENAQ_API_KEY")
    if key:
        return key
    path = Path.cwd() / ".env"
    if path.is_file():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() == "OPENAQ_API_KEY":
                key = value.strip().strip("\"'")
                if key:
                    return key
    raise MissingApiKey(
        "Create a free API key at https://explore.openaq.org/register "
        "and put OPENAQ_API_KEY=... in .env."
    )
