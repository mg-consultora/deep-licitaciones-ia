"""Avisos por correo y/o Telegram. Solo se avisa lo que pidió la usuaria: circulares nuevas y
cambios de fecha (y, si se activa en config.yaml, oportunidades nuevas), siempre con el link."""
from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText

import requests


def _texto(alertas: list[dict]) -> str:
    lineas = [f"• {a['tipo']}: {a['mensaje']}\n  {a['link'] or ''}" for a in alertas]
    return "Novedades en licitaciones seguidas:\n\n" + "\n\n".join(lineas)


def enviar(alertas: list[dict]) -> list[str]:
    """Devuelve los canales por los que salió el aviso (vacío si no hay ninguno configurado)."""
    if not alertas:
        return []
    canales = []
    cuerpo = _texto(alertas)
    if os.environ.get("SMTP_SERVIDOR") and os.environ.get("AVISAR_A"):
        msg = MIMEText(cuerpo, "plain", "utf-8")
        msg["Subject"] = f"Licitaciones: {len(alertas)} novedad(es)"
        msg["From"] = os.environ.get("SMTP_USUARIO", "")
        msg["To"] = os.environ["AVISAR_A"]
        with smtplib.SMTP(os.environ["SMTP_SERVIDOR"], int(os.environ.get("SMTP_PUERTO", "587"))) as s:
            s.starttls()
            s.login(os.environ["SMTP_USUARIO"], os.environ["SMTP_CLAVE"])
            s.send_message(msg)
        canales.append("correo")
    if os.environ.get("TELEGRAM_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
        url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendMessage"
        for i in range(0, len(cuerpo), 3500):
            requests.post(url, data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": cuerpo[i:i + 3500],
                                     "disable_web_page_preview": "true"}, timeout=30)
        canales.append("Telegram")
    return canales
