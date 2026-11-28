"""Verificación conservadora de adjudicaciones en documentos oficiales."""
import re
from urllib.parse import urlparse
from .texto_base import normalizar
from .extraer import EN_EJECUCION, NO_INFO

def verificar(registro, nota, dominios=()):
    host = (urlparse(nota.link).hostname or "").lower()
    oficial = host.endswith(".gob.ar") or any(host == d or host.endswith("." + d) for d in dominios)
    if not oficial or not nota.texto or not registro.get("obra_identificada"):
        return False
    obra = normalizar(registro["obra"])
    empresa = normalizar(registro.get("epc") or "")
    if not empresa or empresa == normalizar(NO_INFO) or len(obra) < 5:
        return False
    for frase in re.split(r"(?<=[.!?])\s+|\n", nota.texto):
        n = normalizar(frase)
        if obra not in n or empresa not in n:
            continue
        if re.search(r"\b(no|pendiente|prevista|podria|adjudicara|preadjudic\w*|propuesta|impugn\w*|revoc\w*|anul\w*)\b", n):
            continue
        if not re.search(r"\b(adjudico|adjudicaron|fue adjudicad[ao]|ha sido adjudicad[ao]|adjudicase)\b", n):
            continue
        registro.update(tipo=EN_EJECUCION, estado="Adjudicación confirmada en fuente oficial",
                        adjudicacion_verificada=True, evidencia_adjudicacion={"fuente": nota.link, "frase": frase[:1500], "empresa": registro["epc"]})
        return True
    return False
