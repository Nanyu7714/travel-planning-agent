from dataclasses import dataclass
from email.message import EmailMessage
from html import escape
import smtplib

from app.core.config import settings


class MailDeliveryError(RuntimeError):
    def __init__(self, code: str, attempt_count: int = 0):
        super().__init__(code)
        self.code = code
        self.attempt_count = attempt_count


@dataclass(frozen=True)
class MailDeliveryResult:
    status: str
    attempt_count: int


@dataclass(frozen=True)
class AuthMail:
    recipient: str
    subject: str
    body: str
    html_body: str | None = None


def email_layout(title: str, content: str, footer: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
  <body style="margin:0;padding:0;background:#f7f7f7;color:#3f3f3f;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f7f7f7;">
      <tr><td align="center" style="padding:32px 16px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:600px;background:#ffffff;border:1px solid #dddddd;border-radius:14px;overflow:hidden;">
          <tr><td style="padding:28px 32px 20px;border-bottom:1px solid #ebebeb;">
            <span style="display:inline-block;color:#ff385c;font-size:20px;font-weight:700;line-height:1.25;">行旅</span>
          </td></tr>
          <tr><td style="padding:32px;">
            <h1 style="margin:0 0 16px;color:#222222;font-size:22px;font-weight:600;line-height:1.3;">{escape(title)}</h1>
            {content}
          </td></tr>
          <tr><td style="padding:20px 32px 28px;border-top:1px solid #ebebeb;color:#6a6a6a;font-size:13px;line-height:1.5;">{footer}</td></tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>"""


def verification_email_html(code: str, expires_minutes: int) -> str:
    content = f"""
<p style="margin:0 0 24px;font-size:16px;line-height:1.5;">请输入下面的验证码，完成行旅账号的邮箱验证。</p>
<div style="margin:0 0 24px;padding:20px;border:1px solid #dddddd;border-radius:14px;background:#f7f7f7;color:#222222;font-size:32px;font-weight:700;letter-spacing:8px;line-height:1;text-align:center;">{escape(code)}</div>
<p style="margin:0;color:#6a6a6a;font-size:14px;line-height:1.5;">验证码将在 {expires_minutes} 分钟后失效。请勿将验证码告诉他人。</p>"""
    return email_layout("验证你的邮箱", content, "此邮件由行旅自动发送。如非本人操作，无需处理。")


def action_email_html(title: str, action_label: str, action_url: str, expires_minutes: int) -> str:
    safe_url = escape(action_url, quote=True)
    content = f"""
<p style="margin:0 0 24px;font-size:16px;line-height:1.5;">请点击下方按钮继续操作。链接将在 {expires_minutes} 分钟后失效，并且只能使用一次。</p>
<p style="margin:0 0 24px;text-align:center;"><a href="{safe_url}" style="display:inline-block;box-sizing:border-box;min-height:48px;padding:14px 24px;border-radius:8px;background:#ff385c;color:#ffffff;font-size:16px;font-weight:500;line-height:20px;text-align:center;text-decoration:none;">{escape(action_label)}</a></p>
<p style="margin:0 0 8px;color:#6a6a6a;font-size:13px;line-height:1.5;">如果按钮无法打开，请复制下面的链接到浏览器：</p>
<p style="margin:0;overflow-wrap:anywhere;word-break:break-word;"><a href="{safe_url}" style="color:#222222;font-size:13px;line-height:1.5;text-decoration:underline;">{safe_url}</a></p>"""
    return email_layout(title, content, "此邮件由行旅自动发送。如非本人操作，请不要点击链接。")


def send_auth_mail(message: AuthMail) -> MailDeliveryResult:
    """Deliver auth mail without logging recipients, links, or raw tokens."""
    if settings.mail_delivery_mode == "console":
        return MailDeliveryResult(status="simulated", attempt_count=0)
    if settings.mail_delivery_mode != "smtp" or not settings.smtp_host:
        raise MailDeliveryError("mail_adapter_unavailable")

    email = EmailMessage()
    email["From"] = settings.mail_from
    email["To"] = message.recipient
    email["Subject"] = message.subject
    email.set_content(message.body)
    if message.html_body:
        email.add_alternative(message.html_body, subtype="html")

    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as client:
                if settings.smtp_starttls:
                    client.starttls()
                if settings.smtp_username and settings.smtp_password:
                    client.login(settings.smtp_username, settings.smtp_password)
                client.send_message(email)
            return MailDeliveryResult(status="sent", attempt_count=attempt)
        except (OSError, smtplib.SMTPException) as exc:
            last_error = exc
    raise MailDeliveryError(type(last_error).__name__ if last_error else "mail_delivery_failed", attempt_count=3)
