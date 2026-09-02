from dataclasses import dataclass
from email.message import EmailMessage
import smtplib

from app.core.config import settings


class MailDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuthMail:
    recipient: str
    subject: str
    body: str


def send_auth_mail(message: AuthMail) -> None:
    """Deliver auth mail without logging recipients, links, or raw tokens."""
    if settings.mail_delivery_mode == "console":
        return
    if settings.mail_delivery_mode != "smtp" or not settings.smtp_host:
        raise MailDeliveryError("mail_adapter_unavailable")

    email = EmailMessage()
    email["From"] = settings.mail_from
    email["To"] = message.recipient
    email["Subject"] = message.subject
    email.set_content(message.body)

    last_error: Exception | None = None
    for _ in range(3):
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as client:
                if settings.smtp_starttls:
                    client.starttls()
                if settings.smtp_username and settings.smtp_password:
                    client.login(settings.smtp_username, settings.smtp_password)
                client.send_message(email)
            return
        except (OSError, smtplib.SMTPException) as exc:
            last_error = exc
    raise MailDeliveryError(type(last_error).__name__ if last_error else "mail_delivery_failed")
