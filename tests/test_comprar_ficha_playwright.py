import unittest
from datetime import datetime, timedelta
from claude.licitaciones.fuentes.comprar_ficha_playwright import extraer_ficha

class FichaPlaywrightTest(unittest.TestCase):
    def test_apertura_no_es_cierre(self):
        html="<p>38/19-0564-LPU26</p><p>Fecha y hora acto de apertura</p><p>24/11/2026 07:00 Hrs.</p><p>Acepta prórroga</p><p>Sí</p>"
        d=extraer_ficha(html,"38/19-0564-LPU26")
        self.assertEqual(d["fecha_apertura"],"2026-11-24T07:00:00")
        self.assertIsNone(d["fecha_cierre"])
        self.assertFalse(d["vigencia_certificada"])
        self.assertFalse(d["prorroga_confirmada"])
    def test_cierre_futuro_etiquetado(self):
        f=(datetime.now()+timedelta(days=3)).strftime("%d/%m/%Y 15:00")
        html="<p>84/13-1677-LPR26</p><p>Fin de recepción de ofertas</p><p>"+f+"</p>"
        d=extraer_ficha(html,"84/13-1677-LPR26")
        self.assertTrue(d["vigencia_certificada"])
    def test_numero_distinto(self):
        self.assertFalse(extraer_ficha("<p>84/13-1677-LPR26</p>","84/13-1678-LPR26")["verificada"])
if __name__=="__main__":
    unittest.main()
