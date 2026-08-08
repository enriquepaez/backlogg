"""Email sending — an ``EmailSender`` interface decoupled from business logic.

Two implementations are provided and selected at runtime by ``get_email_sender``:

- ``SmtpEmailSender`` — used when ``settings.SMTP_HOST`` is configured. Sends the
  message through a generic SMTP server using the standard library (``smtplib``
  + ``email.message.EmailMessage``); no third-party dependency.
- ``LoggingEmailSender`` — the dev/CI fallback used when no SMTP host is present.
  It logs the message (subject + recipient + link) instead of sending, so the
  app boots and the recovery flows work end-to-end without a mail server.

Security invariants:
- The SMTP password is never logged nor included in any exception message.
  Failures are logged with a generic message; the credentials stay inside the
  client.
- The service layer wraps ``send`` in a try/except, so a mail-server outage
  never breaks the HTTP response nor reveals whether an email exists.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage

from backlogg.core.config import settings

logger = logging.getLogger(__name__)


class EmailSender(ABC):
    """Abstract transport for transactional emails.

    Business code depends only on this interface, never on a concrete provider.
    """

    @abstractmethod
    async def send(self, *, to: str, subject: str, html: str, text: str) -> None:
        """Deliver a single email. Implementations must not raise credentials."""
        raise NotImplementedError


class LoggingEmailSender(EmailSender):
    """Fallback that logs the email instead of sending it.

    Used in dev/CI when ``SMTP_HOST`` is not set. The plaintext body (which
    contains the verification/reset link) is logged at INFO so a developer can
    follow the flow locally; no secret is ever logged.
    """

    async def send(self, *, to: str, subject: str, html: str, text: str) -> None:
        logger.info(
            "EMAIL (not sent — no SMTP_HOST configured) to=%s subject=%r body=%s",
            to,
            subject,
            text,
        )


class SmtpEmailSender(EmailSender):
    """SMTP-backed sender used when an SMTP host is configured.

    Uses only the standard library. Credentials (``SMTP_PASSWORD``) are kept
    inside the client and never appear in logs or error messages.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        from_email: str,
        starttls: bool,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_email = from_email
        self._starttls = starttls

    def _build_message(self, *, to: str, subject: str, html: str, text: str) -> EmailMessage:
        message = EmailMessage()
        message["From"] = self._from_email
        message["To"] = to
        message["Subject"] = subject
        # Plain text is the primary content; HTML is offered as an alternative.
        message.set_content(text)
        message.add_alternative(html, subtype="html")
        return message

    def _send_sync(self, *, to: str, subject: str, html: str, text: str) -> None:
        message = self._build_message(to=to, subject=subject, html=html, text=text)
        with smtplib.SMTP(self._host, self._port) as smtp:
            if self._starttls:
                smtp.starttls()
            if self._username or self._password:
                smtp.login(self._username, self._password)
            smtp.send_message(message)

    async def send(self, *, to: str, subject: str, html: str, text: str) -> None:
        # smtplib is synchronous; run it off the event loop.
        await asyncio.to_thread(self._send_sync, to=to, subject=subject, html=html, text=text)


def get_email_sender() -> EmailSender:
    """Return the configured EmailSender.

    ``SmtpEmailSender`` when ``SMTP_HOST`` is present, otherwise the logging
    fallback. Never raises — the app works with or without a mail server.
    """
    if settings.SMTP_HOST:
        return SmtpEmailSender(
            host=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USERNAME,
            password=settings.SMTP_PASSWORD,
            from_email=settings.SMTP_FROM_EMAIL,
            starttls=settings.SMTP_STARTTLS,
        )
    return LoggingEmailSender()
