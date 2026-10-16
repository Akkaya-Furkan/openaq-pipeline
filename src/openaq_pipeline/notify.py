"""Alert transports: Telegram, or a dry-run that only logs. Secrets come from the environment."""
import logging

import httpx

from . import config

logger = logging.getLogger(__name__)


class DryRunTransport:
    name = "dry-run"
    dry_run = True

    def __init__(self, printer=None):
        self.printer = printer or (lambda text: logger.warning("[dry-run] would send:\n%s", text))

    def send(self, text):
        self.printer(text)


class TelegramTransport:
    name = "telegram"

    def __init__(self, token, chat_id, http=None):
        self._token, self._chat_id = token, chat_id
        self._http = http or httpx.Client(timeout=15)

    def send(self, text):
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        try:
            response = self._http.post(url, json={"chat_id": self._chat_id, "text": text})
            response.raise_for_status()
        except httpx.HTTPError as error:
            # httpx error messages embed the URL, which contains the bot token
            status = getattr(getattr(error, "response", None), "status_code", None)
            raise RuntimeError(f"telegram sendMessage failed ({type(error).__name__}, "
                               f"status {status})") from None


def make_transport(http=None):
    token, chat_id = config.setting("TELEGRAM_BOT_TOKEN"), config.setting("TELEGRAM_CHAT_ID")
    if token and chat_id:
        return TelegramTransport(token, chat_id, http)
    logger.warning("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set: alerts are dry-run only")
    return DryRunTransport()
