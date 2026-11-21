"""Pruebas locales sin solicitudes de red para la paginacion de fuentes publicas."""
import unittest
from unittest.mock import patch
from claude.licitaciones.fuentes.paginas_web import PaginasWeb, paginas_enlazadas

class Response:
    def __init__(self, url, html, status=200):
        self.url, self.text, self.status_code = url, html, status
        self.headers = {"Content-Type": "text/html"}
    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))

class TestPaginacion(unittest.TestCase):
    def test_enlaces_paginacion_solo_mismo_host_https(self):
        html = '<a href="?page=2">2</a><a href="https://evil.example/?page=3">3</a><a href="javascript:alert(1)">Next</a>'
        self.assertEqual(paginas_enlazadas(html, "https://example.org/list"), ["https://example.org/list?page=2"])

    def test_recorrer_paginas_no_comprar(self):
        url = "https://example.org/list"
        paginas = {url: '<a href="?page=2">Next</a>', url + "?page=2": "<p>Fin</p>"}
        def get(destino, timeout):
            return Response(destino, paginas[destino])
        with patch("requests.Session") as session:
            session.return_value.get.side_effect = get
            resultado = PaginasWeb({"paginas_publicas": [{"nombre": "Prueba", "url": url}]}).obtener()
        self.assertIn("2 página(s)", resultado.detalle)
        self.assertEqual(resultado.estado, "ok")

    def test_mas_de_doce_enlaces_no_se_pierden(self):
        html = "".join(f'<a href="?page={i}">{i}</a>' for i in range(2, 20))
        self.assertEqual(len(paginas_enlazadas(html, "https://example.org/list")), 18)

    def test_limite_paginas_marca_parcial(self):
        url = "https://example.org/list"
        def get(destino, timeout):
            numero = int(destino.split("page=")[-1]) if "page=" in destino else 1
            return Response(destino, f'<a href="?page={numero+1}">Next</a>')
        with patch("requests.Session") as session:
            session.return_value.get.side_effect = get
            resultado = PaginasWeb({"max_paginas_por_fuente": 3, "paginas_publicas": [{"nombre": "Prueba", "url": url}]}).obtener()
        self.assertEqual(resultado.estado, "parcial")
        self.assertIn("3 página(s)", resultado.detalle)
        self.assertIn("enlaces pendientes=1", resultado.detalle)

    def test_error_secundario_marca_parcial(self):
        url = "https://example.org/list"
        def get(destino, timeout):
            if destino != url:
                import requests
                raise requests.Timeout("timeout")
            return Response(url, '<a href="?page=2">Next</a>')
        with patch("requests.Session") as session:
            session.return_value.get.side_effect = get
            resultado = PaginasWeb({"paginas_publicas": [{"nombre": "Prueba", "url": url}]}).obtener()
        self.assertEqual(resultado.estado, "parcial")
        self.assertIn("errores secundarios=1", resultado.detalle)

if __name__ == "__main__":
    unittest.main()
