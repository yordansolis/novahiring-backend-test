"""SMTP email sending — invitations (and health check)."""
import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

from config import get_settings

logger = logging.getLogger("nova.email")

_FALLBACK_HOSTS = ("smtp-relay.sendinblue.com",)


def _smtp_hosts(preferred: str) -> list[str]:
    hosts = [preferred]
    for extra in _FALLBACK_HOSTS:
        if extra not in hosts:
            hosts.append(extra)
    return hosts


def _open_smtp(host: str, port: int, timeout: int) -> smtplib.SMTP:
    smtp = smtplib.SMTP(host, port, timeout=timeout)
    smtp.ehlo()
    smtp.starttls(context=ssl.create_default_context())
    smtp.ehlo()
    return smtp


def smtp_configured() -> bool:
    settings = get_settings()
    return bool(settings.SMTP_USERNAME and settings.SMTP_PASSWORD and settings.SMTP_FROM_EMAIL)


def check_smtp_health() -> dict:
    settings = get_settings()
    if not smtp_configured():
        return {
            "status": "error",
            "host": settings.SMTP_HOST,
            "port": settings.SMTP_PORT,
            "error": (
                "SMTP no configurado. Añade SMTP_USERNAME, SMTP_PASSWORD y "
                "SMTP_FROM_EMAIL en el .env del backend."
            ),
        }
    last_error: str | None = None
    last_host = settings.SMTP_HOST
    for host in _smtp_hosts(settings.SMTP_HOST):
        try:
            with _open_smtp(host, settings.SMTP_PORT, timeout=8) as smtp:
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            return {
                "status": "ok",
                "host": host,
                "port": settings.SMTP_PORT,
                "error": None,
            }
        except Exception as exc:
            last_error = str(exc)
            last_host = host
    return {
        "status": "error",
        "host": last_host,
        "port": settings.SMTP_PORT,
        "error": last_error,
    }


def send_interview_invitation_email(
    to_email: str,
    candidate_name: str,
    job_title: str,
    username: str,
    password: str,
    login_url: str,
) -> None:
    settings = get_settings()
    if not smtp_configured():
        raise RuntimeError("SMTP no configurado")
    if not to_email:
        raise RuntimeError("El candidato no tiene email")

    subject = f"Invitación a entrevista — {job_title}"
    text = (
        f"Hola {candidate_name},\n\n"
        f"Has superado la primera fase para {job_title}.\n\n"
        f"Accede a tu entrevista:\n{login_url}\n\n"
        f"Usuario: {username}\n"
        f"Contraseña: {password}\n\n"
        "Este acceso caduca en 7 días.\n\n"
        "— NovaHiring\n"
    )
    safe_name = escape(candidate_name)
    safe_job = escape(job_title)
    safe_user = escape(username)
    safe_pass = escape(password)
    safe_url = escape(login_url)
    html = f"""
    <p>Hola {safe_name},</p>
    <p>Has superado la primera fase para <strong>{safe_job}</strong>.</p>
    <p><a href="{safe_url}">Acceder a la entrevista</a></p>
    <p>Usuario: <code>{safe_user}</code><br>Contraseña: <code>{safe_pass}</code></p>
    <p>Este acceso caduca en 7 días.</p>
    <p>— NovaHiring</p>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    msg["To"] = to_email
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    last_error: Exception | None = None
    for host in _smtp_hosts(settings.SMTP_HOST):
        try:
            with _open_smtp(host, settings.SMTP_PORT, timeout=20) as smtp:
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                smtp.sendmail(settings.SMTP_FROM_EMAIL, [to_email], msg.as_string())
            logger.info("[EMAIL SENT] invitation to %s via %s", to_email, host)
            return
        except Exception as exc:
            last_error = exc
            logger.warning("SMTP send via %s failed: %s", host, exc)
    raise last_error if last_error is not None else RuntimeError("SMTP send failed")
