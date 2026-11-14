"""Canal privado: fuentes que necesitan usuario y contraseña.

Cómo trabajan las empresas privadas del rubro
---------------------------------------------
YPF, TGS, Pluspetrol, MetroGAS y muchas mineras compran por SAP Ariba u otros portales de
proveedores: primero hay que registrarse, y después la empresa INVITA a cada licitación por
correo. Las circulares y prórrogas también llegan por correo.

Por eso el canal privado tiene dos partes:

1. Correo de invitaciones (ya funciona): lee la casilla donde llegan las invitaciones de
   Ariba y de los portales, y arma una oportunidad por cada mail con su fecha de cierre y su
   link. Solo necesita los datos de la casilla en el archivo .env.

2. Portales con usuario (preparados, a completar): uno por empresa. Hasta que se carguen las
   credenciales aparecen en el tablero como "pendiente de credenciales". Cuando estén, hay
   que completar el método `leer_portal` mirando la pantalla real de cada portal. Antes de
   automatizar un ingreso, conviene revisar los términos de uso del portal: algunos no
   permiten accesos automáticos y en ese caso el correo de invitaciones es el camino.
"""
from __future__ import annotations

import email
import email.utils
import imaplib
import os
import re
from datetime import datetime, timedelta
from email.header import decode_header, make_header

from bs4 import BeautifulSoup

from ..modelo import Oportunidad
from ..texto import buscar_fechas, normalizar
from .base import Fuente, ResultadoFuente


# ---------------------------------------------------------------------------
# 1) Correo de invitaciones (IMAP)
# ---------------------------------------------------------------------------
def _texto_mail(msg: email.message.Message) -> str:
    partes = []
    for parte in msg.walk():
        tipo = parte.get_content_type()
        if tipo not in ("text/plain", "text/html") or parte.get_filename():
            continue
        carga = parte.get_payload(decode=True) or b""
        txt = carga.decode(parte.get_content_charset() or "utf-8", errors="replace")
        if tipo == "text/html":
            txt = BeautifulSoup(txt, "html.parser").get_text(" ")
        partes.append(txt)
    return re.sub(r"\s+", " ", " ".join(partes))


def oportunidad_desde_mail(asunto: str, remitente: str, cuerpo: str, recibido: datetime | None) -> Oportunidad:
    norm = normalizar(f"{asunto} {cuerpo}")
    cierre = None
    m = re.search(r"(fecha (de )?cierre|vence|vencimiento|due date|close date|fecha l[ií]mite|apertura)", cuerpo, re.I)
    if m:
        despues = [f for p, f in buscar_fechas(cuerpo) if p >= m.start()]
        cierre = despues[0] if despues else None
    links = re.findall(r"https?://[^\s\"'<>]+", cuerpo)
    link = next((l for l in links if "ariba" in l or "proveedor" in l or "supplier" in l), links[0] if links else "")
    todo = f"{asunto} {cuerpo}"
    evento = (re.search(r"Doc\d{6,}", todo)          # número de evento de Ariba
              or re.search(r"(RFP|RFQ|evento\s*n[°º.]?)\s*[\w\-/]+", todo, re.I))
    empresa = remitente.split("@")[-1].split(">")[0] if "@" in remitente else remitente
    return Oportunidad(
        fuente=f"Correo ({empresa})",
        titulo=asunto[:250],
        organismo=empresa,
        numero_proceso=evento.group(0).strip() if evento else "",
        tipo_contratacion="Invitación privada",
        estado="Circular" if re.search(r"circular|enmienda|modificaci|prorroga|addendum", norm) else "Invitación",
        fecha_publicacion=recibido,
        fecha_presentacion=cierre,
        fecha_apertura=cierre,
        link=link,
        texto=f"{asunto} {cuerpo[:3000]}",
        es_circular=bool(re.search(r"circular|enmienda|prorroga|addendum", norm)),
    )


class CorreoInvitaciones(Fuente):
    nombre = "Correo de invitaciones (Ariba y portales de proveedores)"
    publica = False
    credenciales = ["CORREO_IMAP_SERVIDOR", "CORREO_USUARIO", "CORREO_CLAVE"]

    def obtener(self) -> ResultadoFuente:
        faltan = self.faltan_credenciales()
        if faltan:
            return ResultadoFuente(self.nombre, "pendiente_credenciales", "Falta cargar en .env: " + ", ".join(faltan))
        cfg = self.config.get("correo", {})
        remitentes = cfg.get("remitentes", ["ariba.com"])
        dias = cfg.get("dias_hacia_atras", 30)
        desde = (datetime.now() - timedelta(days=dias)).strftime("%d-%b-%Y")
        ops = []
        try:
            imap = imaplib.IMAP4_SSL(os.environ["CORREO_IMAP_SERVIDOR"])
            imap.login(os.environ["CORREO_USUARIO"], os.environ["CORREO_CLAVE"])
            imap.select(cfg.get("carpeta", "INBOX"), readonly=True)
            for rem in remitentes:
                _, ids = imap.search(None, f'(SINCE {desde} FROM "{rem}")')
                for i in ids[0].split():
                    _, datos = imap.fetch(i, "(RFC822)")
                    msg = email.message_from_bytes(datos[0][1])
                    asunto = str(make_header(decode_header(msg.get("Subject", ""))))
                    try:
                        recibido = email.utils.parsedate_to_datetime(msg.get("Date")).replace(tzinfo=None)
                    except Exception:
                        recibido = None
                    ops.append(oportunidad_desde_mail(asunto, msg.get("From", ""), _texto_mail(msg), recibido))
            imap.logout()
        except Exception as e:
            return ResultadoFuente(self.nombre, "error", f"No se pudo leer el correo: {e}")
        return ResultadoFuente(self.nombre, "ok", f"{len(ops)} correos de invitación leídos", ops)


# ---------------------------------------------------------------------------
# 2) Portales con usuario (preparados para cuando estén las credenciales)
# ---------------------------------------------------------------------------
class PortalConUsuario(Fuente):
    publica = False
    empresa = ""
    url_portal = ""

    @property
    def nombre(self) -> str:  # type: ignore[override]
        return f"Portal de proveedores – {self.empresa}"

    def obtener(self) -> ResultadoFuente:
        faltan = self.faltan_credenciales()
        if faltan:
            return ResultadoFuente(self.nombre, "pendiente_credenciales",
                                   f"Falta cargar en .env: {', '.join(faltan)} · {self.url_portal}")
        try:
            ops = self.leer_portal()
        except NotImplementedError:
            return ResultadoFuente(self.nombre, "pendiente_credenciales",
                                   "Credenciales cargadas. Falta programar la lectura del portal (ver README).")
        except Exception as e:
            return ResultadoFuente(self.nombre, "error", str(e))
        return ResultadoFuente(self.nombre, "ok", f"{len(ops)} procesos", ops)

    def leer_portal(self) -> list[Oportunidad]:
        """Completar cuando haya usuario: iniciar sesión (por ejemplo con Playwright), ir al
        listado de eventos o licitaciones y devolver una Oportunidad por fila."""
        raise NotImplementedError


def _portal(clase: str, empresa: str, prefijo: str, url: str) -> type[PortalConUsuario]:
    return type(clase, (PortalConUsuario,), {
        "empresa": empresa, "url_portal": url,
        "credenciales": [f"{prefijo}_USUARIO", f"{prefijo}_CLAVE"],
    })


# Lista inicial: se agregan o quitan empresas en config.yaml (portales_privados).
PORTALES_CONOCIDOS = {
    "ariba": ("SAP Ariba (YPF, TGS, Pluspetrol, MetroGAS…)", "ARIBA", "https://supplier.ariba.com"),
    "cammesa": ("CAMMESA", "CAMMESA", "https://cammesaweb.cammesa.com"),
    "transener": ("Transener", "TRANSENER", "https://www.transener.com.ar"),
    "edenor": ("Edenor", "EDENOR", "https://www.edenor.com"),
    "edesur": ("Edesur", "EDESUR", "https://www.edesur.com.ar"),
    "genneia": ("Genneia", "GENNEIA", "https://www.genneia.com.ar"),
    "central_puerto": ("Central Puerto", "CENTRAL_PUERTO", "https://www.centralpuerto.com"),
    "mineras": ("Mineras (portal a definir)", "MINERAS", ""),
}


def portales_privados(config: dict) -> list[Fuente]:
    activos = config.get("portales_privados", list(PORTALES_CONOCIDOS))
    fuentes = []
    for clave in activos:
        if clave in PORTALES_CONOCIDOS:
            empresa, prefijo, url = PORTALES_CONOCIDOS[clave]
            fuentes.append(_portal(f"Portal_{prefijo}", empresa, prefijo, url)(config))
    return fuentes
