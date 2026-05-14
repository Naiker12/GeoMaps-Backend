import asyncio
import html
import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SupportReplyEmail:
    to_email: str
    to_name: str
    case_id: str
    original_message: str
    reply_message: str


class EmailNotConfiguredError(RuntimeError):
    pass


class EmailService:
    def __init__(self) -> None:
        self.enabled = settings.SUPPORT_EMAIL_ENABLED
        self.smtp_host = settings.SMTP_HOST
        self.smtp_port = settings.SMTP_PORT
        self.smtp_username = settings.SMTP_USERNAME
        self.smtp_password = settings.SMTP_PASSWORD
        self.from_email = settings.SMTP_FROM_EMAIL or settings.SMTP_USERNAME
        self.from_name = settings.SMTP_FROM_NAME
        self.reply_to = settings.SUPPORT_REPLY_TO_EMAIL or self.from_email

    def _ensure_configured(self) -> None:
        if not self.enabled:
            raise EmailNotConfiguredError("El envio de correos de soporte esta deshabilitado")
        if not all([self.smtp_host, self.smtp_port, self.smtp_username, self.smtp_password, self.from_email]):
            raise EmailNotConfiguredError("Configuracion SMTP incompleta para soporte")

    async def send_support_reply(self, data: SupportReplyEmail) -> None:
        self._ensure_configured()
        await asyncio.to_thread(self._send_support_reply_sync, data)

    def _send_support_reply_sync(self, data: SupportReplyEmail) -> None:
        subject = f"Respuesta a tu solicitud GeoMaps #{data.case_id[:8]}"
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr((self.from_name, self.from_email or ""))
        message["To"] = formataddr((data.to_name, data.to_email))
        if self.reply_to:
            message["Reply-To"] = self.reply_to

        text_body = self._render_text(data)
        html_body = self._render_html(data)
        message.set_content(text_body)
        message.add_alternative(html_body, subtype="html")

        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(self.smtp_username or "", self.smtp_password or "")
            smtp.send_message(message)

        logger.info("Correo de soporte enviado a %s para caso %s", data.to_email, data.case_id)

    @staticmethod
    def _render_text(data: SupportReplyEmail) -> str:
        return (
            f"Hola {data.to_name},\n\n"
            "Gracias por contactar al equipo de soporte de GeoMaps. Revisamos tu solicitud y ya tenemos una respuesta para ti.\n\n"
            "RESPUESTA DEL EQUIPO\n"
            f"{data.reply_message}\n\n"
            "TU MENSAJE ORIGINAL\n"
            f"{data.original_message}\n\n"
            f"Caso: #{data.case_id[:8]}\n"
            "Puedes responder directamente a este correo si necesitas ampliar la informacion.\n\n"
            "Equipo de soporte GeoMaps"
        )

    @staticmethod
    def _render_html(data: SupportReplyEmail) -> str:
        safe_name = html.escape(data.to_name)
        safe_case = html.escape(data.case_id[:8])
        safe_reply = html.escape(data.reply_message).replace("\n", "<br />")
        safe_original = html.escape(data.original_message).replace("\n", "<br />")

        return f"""<!doctype html>
<html lang="es">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Respuesta de soporte GeoMaps</title>
  </head>
  <body style="margin:0;background:#edf4f1;font-family:Arial,Helvetica,sans-serif;color:#14201b;">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">
      El equipo de GeoMaps respondio tu solicitud de soporte.
    </div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#edf4f1;padding:34px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:680px;background:#ffffff;border:1px solid #d7e5df;border-radius:18px;overflow:hidden;box-shadow:0 18px 48px rgba(18,52,39,0.12);">
            <tr>
              <td style="background:#10261f;padding:30px 34px 28px;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                  <tr>
                    <td>
                      <div style="font-size:13px;font-weight:800;letter-spacing:0.16em;text-transform:uppercase;color:#74e3b3;">GeoMaps</div>
                      <h1 style="margin:12px 0 0;font-size:26px;line-height:1.25;color:#ffffff;font-weight:800;">Respuesta a tu solicitud de soporte</h1>
                    </td>
                    <td align="right" style="vertical-align:top;">
                      <span style="display:inline-block;border:1px solid rgba(116,227,179,0.45);border-radius:999px;padding:8px 12px;font-size:11px;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#b9f5dc;background:rgba(116,227,179,0.08);">Caso #{safe_case}</span>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:34px;">
                <p style="margin:0 0 14px;font-size:16px;line-height:1.7;color:#14201b;">Hola <strong>{safe_name}</strong>,</p>
                <p style="margin:0 0 26px;font-size:15px;line-height:1.75;color:#4a5d54;">Gracias por contactar al equipo de soporte de GeoMaps. Revisamos tu solicitud y te compartimos la respuesta oficial del equipo.</p>

                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 26px;border-collapse:separate;">
                  <tr>
                    <td style="background:#effbf5;border:1px solid #bcebd5;border-left:5px solid #0fbd79;border-radius:14px;padding:22px 24px;">
                      <div style="margin:0 0 10px;font-size:11px;font-weight:800;letter-spacing:0.14em;text-transform:uppercase;color:#08794f;">Respuesta del equipo</div>
                      <p style="margin:0;font-size:16px;line-height:1.75;color:#10241c;">{safe_reply}</p>
                    </td>
                  </tr>
                </table>

                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 24px;">
                  <tr>
                    <td style="border:1px solid #e1ebe7;border-radius:14px;padding:18px 20px;background:#fbfdfc;">
                      <div style="font-size:11px;font-weight:800;letter-spacing:0.14em;text-transform:uppercase;color:#687970;margin-bottom:10px;">Tu mensaje original</div>
                      <p style="margin:0;font-size:14px;line-height:1.7;color:#485951;">{safe_original}</p>
                    </td>
                  </tr>
                </table>

                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f6faf8;border-radius:14px;border:1px solid #e1ebe7;">
                  <tr>
                    <td style="padding:16px 18px;">
                      <div style="font-size:12px;font-weight:800;color:#14201b;margin-bottom:4px;">Seguimiento del caso</div>
                      <p style="margin:0;font-size:13px;line-height:1.7;color:#63756d;">Tu numero de caso es <strong>#{safe_case}</strong>. Si necesitas ampliar la informacion, responde directamente a este correo y el equipo podra continuar la revision.</p>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="background:#f8fbfa;border-top:1px solid #e1ebe7;padding:20px 34px;">
                <p style="margin:0 0 4px;font-size:13px;font-weight:800;color:#14201b;">Equipo de soporte GeoMaps</p>
                <p style="margin:0;font-size:12px;line-height:1.6;color:#6a7b73;">Geoportal y plataforma geoespacial. Este correo fue enviado porque registraste una solicitud de soporte en GeoMaps.</p>
              </td>
            </tr>
          </table>
          <p style="max-width:680px;margin:16px auto 0;font-size:11px;line-height:1.6;color:#82918b;text-align:center;">Por seguridad, nunca compartas contrasenas, codigos de acceso o informacion sensible por correo.</p>
        </td>
      </tr>
    </table>
  </body>
</html>"""


email_service = EmailService()
