import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock
from claude.licitaciones.modelo import Oportunidad
from claude.licitaciones.verificacion_comprar import motivo_descarte, ficha_oficial_verificada, _vigencia_en_ficha

class VerificacionComprarTest(unittest.TestCase):
    def op(self, titulo, **kwargs):
        return Oportunidad(fuente="COMPR.AR", titulo=titulo, numero_proceso="84-1234-LPR26", **kwargs)

    def test_adjudicado(self):
        self.assertEqual(motivo_descarte(self.op("UPS industrial", estado="Adjudicada")), "proceso_cerrado_o_adjudicado")

    def test_ups_informatica(self):
        self.assertEqual(motivo_descarte(self.op("UPS para computadoras")), "ups_informatica")

    def test_ups_industrial(self):
        self.assertIsNone(motivo_descarte(self.op("UPS industrial trifasica")))

    def test_plazo_vencido(self):
        self.assertEqual(motivo_descarte(self.op("Banco de baterias", fecha_presentacion=datetime.now()-timedelta(days=1))), "presentacion_vencida")

    def test_sin_ficha_no_se_publica(self):
        op=self.op("UPS industrial", link="https://comprar.gob.ar/default.aspx")
        ok, motivo=ficha_oficial_verificada(op, Mock())
        self.assertFalse(ok)
        self.assertEqual(motivo, "sin_ficha_individual")

    def test_ficha_numero_distinto(self):
        op=self.op("UPS industrial", link="https://comprar.gob.ar/Detalle.aspx?id=123")
        session=Mock()
        session.get.return_value.status_code=200
        session.get.return_value.url=op.link
        session.get.return_value.text="<html>Proceso 84-9999-LPR26</html>"
        ok, motivo=ficha_oficial_verificada(op, session)
        self.assertFalse(ok)
        self.assertEqual(motivo, "numero_no_coincide_en_ficha")

class VigenciaFichaTest(unittest.TestCase):
    def test_numero_sin_cierre_no_es_vigente(self):
        ok, motivo = _vigencia_en_ficha("<p>84-1234-LPR26</p>", "84-1234-LPR26")
        self.assertFalse(ok)
        self.assertEqual(motivo, "sin_cierre_oficial_identificable")

    def test_estado_adjudicado_descartado(self):
        html = "<p>84-1234-LPR26</p><table><tr><td>Estado</td><td>Adjudicada</td></tr></table>"
        ok, motivo = _vigencia_en_ficha(html, "84-1234-LPR26")
        self.assertFalse(ok)
        self.assertEqual(motivo, "estado_oficial_cerrado")

if __name__ == "__main__":
    unittest.main()
