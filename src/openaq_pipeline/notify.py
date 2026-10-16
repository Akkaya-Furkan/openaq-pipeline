"""Alert transports: e-mail over SMTP (STARTTLS), or a dry-run that only logs.

Credentials come from the environment (or ``.env``), never from the repository.
"""
import logging
import smtplib
import ssl
from email.message import EmailMessage

from . import config

logger = logging.getLogger(__name__)
REQUIRED = ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "ALERT_EMAIL_FROM", "ALERT_EMAIL_TO")


class DryRunTransport:
    name = "dry-run"
    dry_run = True

    def __init__(self, printer=None):
        self.printer = printer or (lambda text: logger.warning("[dry-run] would send e-mail:\n%s", text))

    def send(self, subject, body):
        self.printer(f"Subject: {subject}\n\n{body}")


class EmailTransport:
    name = "email"

    def __init__(self, host, port, user, password, sender, recipient, smtp=None):
        self._host, self._port, self._user, self._password = host, port, user, password
        self._sender, self._recipient = sender, recipient
        self._smtp = smtp  # factory (host, port) -> context-manager SMTP; injectable for tests

    def send(self, subject, body):
        message = EmailMessage()
        message["Subject"], message["From"], message["To"] = subject, self._sender, self._recipient
        message.set_content(body)
        try:
            if self._smtp:
                client = self._smtp(self._host, self._port)
            elif self._port == 465:
                client = smtplib.SMTP_SSL(self._host, self._port, timeout=30,
                                          context=ssl.create_default_context())
            else:
                client = smtplib.SMTP(self._host, self._port, timeout=30)
            with client:
                if not self._smtp and self._port != 465:
                    client.starttls(context=ssl.create_default_context())
                client.login(self._user, self._password)
                client.send_message(message)
        except (smtplib.SMTPException, OSError) as error:
            # never echo the exception text: it can carry server banners or the login name
            raise RuntimeError(f"smtp delivery failed ({type(error).__name__})") from None


def make_transport(smtp=None):
    values = {name: config.setting(name) for name in REQUIRED}
    missing = [name for name, value in values.items() if not value]
    if missing:
        logger.warning("E-mail not configured (missing %s): alerts are dry-run only, nothing is sent",
                       ", ".join(missing))
        return DryRunTransport()
    port = int(config.setting("SMTP_PORT") or 587)
    return EmailTransport(values["SMTP_HOST"], port, values["SMTP_USER"], values["SMTP_PASSWORD"],
                          values["ALERT_EMAIL_FROM"], values["ALERT_EMAIL_TO"], smtp)
