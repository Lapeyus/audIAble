"""Prueba del POC de TypeSafe contra un servidor simulado que aplica las reglas de la página de
imágenes de la documentación y responde con el formato documentado. No llama a la API real."""
import io
import json
import random
import subprocess
import sys
import tempfile
import threading
import unittest
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

RAIZ = Path(__file__).resolve().parents[1]
ERRORES = []


class ApiSimulada(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def responder(self, codigo, cuerpo):
        datos = json.dumps(cuerpo).encode()
        self.send_response(codigo)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def fallo(self, motivo):
        ERRORES.append(motivo)
        self.responder(400, {'error': motivo})

    def do_POST(self):
        if self.headers.get('Authorization') != 'Bearer clave-de-prueba':
            return self.fallo('sin Authorization: Bearer')
        if self.headers.get('TypeSafe-Danger-Zone-Images') != 'true':
            return self.fallo('falta la cabecera TypeSafe-Danger-Zone-Images')
        crudo = self.rfile.read(int(self.headers['Content-Length']))
        if len(crudo) > 32 * 1024 * 1024:
            return self.fallo('cuerpo de más de 32 MiB')
        mensaje = BytesParser(policy=default).parsebytes(
            b'Content-Type: ' + self.headers['Content-Type'].encode() + b'\r\n\r\n' + crudo)
        partes = list(mensaje.iter_parts())
        if not partes or partes[0].get_param('name', header='content-disposition') != 'request':
            return self.fallo('la primera parte no se llama request')
        peticion = json.loads(partes[0].get_content())
        imagenes = {}
        for parte in partes[1:]:
            nombre = parte.get_param('name', header='content-disposition')
            if nombre in imagenes or nombre == 'request':
                return self.fallo(f'parte repetida o reservada: {nombre}')
            if parte.get_content_type() not in ('image/png', 'image/jpeg', 'image/jpg', 'application/octet-stream'):
                return self.fallo(f'tipo de imagen no admitido: {parte.get_content_type()}')
            imagen = Image.open(io.BytesIO(parte.get_payload(decode=True)))
            ancho, alto = imagen.size
            if not (280 <= ancho <= 1568 and 280 <= alto <= 1568 and 78400 <= ancho * alto <= 2458624):
                return self.fallo(f'dimensiones fuera de rango: {imagen.size}')
            if imagen.format != 'JPEG' or imagen.info.get('progressive'):
                return self.fallo('no es JPEG baseline')
            imagenes[nombre] = imagen
        texto = json.dumps({k: v for k, v in peticion.items() if k != 'assets'})
        usadas = []
        for referencia, activo in peticion.get('assets', {}).items():
            if referencia not in texto:
                return self.fallo(f'activo sin referenciar: {referencia}')
            if activo.get('part') not in imagenes:
                return self.fallo(f'activo con parte inexistente: {activo}')
            usadas.append(activo['part'])
        if sorted(usadas) != sorted(imagenes):
            return self.fallo('partes huérfanas o compartidas')
        respuestas = {}
        for nombre, pregunta in peticion['questions'].items():
            if pregunta['type'] == 'noul':
                respuestas[nombre] = {'type': 'noul', 'noul': random.random()}
            elif pregunta['type'] == 'choice':
                opciones = list(pregunta['criteria'])
                elegida = random.choice(opciones)
                respuestas[nombre] = {'type': 'choice', 'choice': elegida, 'confidence': 0.8,
                                      'probabilities': {o: (0.8 if o == elegida else 0.2 / (len(opciones) - 1)) for o in opciones}}
            elif pregunta['type'] == 'box':
                if not peticion['model'].startswith(('jev-preview', 'jev-1.14')):
                    return self.fallo('Box necesita Jev 1.14')
                respuestas[nombre] = {'type': 'box', 'box': {'top': 0.2, 'bottom': 0.8, 'left': 0.1, 'right': 0.9},
                                      'confidence': 0.7}
        self.responder(200, {'model': peticion['model'], 'answers': respuestas,
                             'usage': {'input_tokens': 1000 * len(imagenes), 'output_tokens': 0}})


def pagina_sintetica(ruta, semilla, mano=False):
    rng = np.random.default_rng(semilla)
    imagen = np.full((1300, 900, 3), 240, np.uint8)
    for y in range(80, 1240, 34):
        cv2.putText(imagen, ' '.join(str(n) for n in rng.integers(100, 999, 9)), (40, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (30, 30, 30), 2)
    if mano:
        cv2.ellipse(imagen, (700, 700), (160, 260), 15, 0, 360, (120, 160, 210), -1)
    cv2.imwrite(str(ruta), imagen)


class PocTypeSafeTest(unittest.TestCase):
    def test_peticiones_cumplen_las_reglas_de_la_api(self):
        servidor = HTTPServer(('127.0.0.1', 0), ApiSimulada)
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        try:
            with tempfile.TemporaryDirectory() as temporal:
                temporal = Path(temporal)
                img, otra = temporal / 'imagenes', temporal / 'otra'
                (img / 'brutos').mkdir(parents=True)
                otra.mkdir()
                etiquetas = {}
                for n in range(1, 9):
                    pagina_sintetica(img / f'pag_{n}.png', n, mano=n % 3 == 0)
                    pagina_sintetica(otra / f'pag_{n}.png', n)
                    etiquetas[f'pag_{n}'] = {'estado': 'texto_plano', 'mano': n % 3 == 0}
                # un fotograma crudo vertical de móvil, para la pregunta Box
                fotograma = np.full((1920, 1080, 3), 90, np.uint8)
                fotograma[400:1500, 100:980] = 235
                cv2.imwrite(str(img / 'brutos' / 'toma_1.png'), fotograma)
                (temporal / 'etiquetas.json').write_text(json.dumps(etiquetas))
                salida = temporal / 'salida'
                proceso = subprocess.run(
                    [sys.executable, '-W', 'ignore', str(RAIZ / 'utiles' / 'poc-typesafe.py'), '--img', str(img),
                     '--otra-corrida', str(otra), '--etiquetas', str(temporal / 'etiquetas.json'), '--pares', '3',
                     '--tomas', '1', '--url', f'http://127.0.0.1:{servidor.server_port}/v1', '--salida', str(salida)],
                    capture_output=True, text=True, timeout=300,
                    env={'TYPESAFE_API_KEY': 'clave-de-prueba', 'PATH': '/usr/bin:/bin'})
                self.assertEqual(proceso.returncode, 0, proceso.stderr[-2000:])
                self.assertEqual(ERRORES, [])
                resultados = json.loads((salida / 'resultados.json').read_text())
                self.assertFalse([f for f in resultados['filas'] if 'error' in f])
                resumen = resultados['resumen']
                self.assertEqual(resumen['estado']['casos'], 8)
                self.assertEqual(resumen['mano']['casos'], 8)
                self.assertEqual(resumen['misma']['casos'], 6)
                self.assertTrue((salida / 'cajas.jpg').exists())
        finally:
            servidor.shutdown()



class BovedaTest(unittest.TestCase):
    """La lectura de la bóveda, con un gcloud falso que sirve un bundle inventado."""

    def test_encuentra_la_clave_por_nombre_sin_mostrarla(self):
        import os
        sys.path.insert(0, str(RAIZ))
        from nucleo import boveda
        with tempfile.TemporaryDirectory() as temporal:
            bundle = {'schemaVersion': 1, 'bundleId': 'vault-02', 'credentials': [
                {'name': 'GitHub', 'type': 'api_token', 'fields': [{'key': 'token', 'value': 'no-es-esta'}]},
                {'name': 'TypeSafe API', 'type': 'api_key', 'fields': [{'key': 'service', 'value': 'typesafe.ai'},
                                                                        {'key': 'api_key', 'value': 'clave-falsa-123'}]}]}
            (Path(temporal) / 'bundle.json').write_text(json.dumps(bundle))
            gcloud = Path(temporal) / 'gcloud'
            gcloud.write_text(f'#!/bin/sh\ncase "$*" in *vault-02*) cat "{temporal}/bundle.json";; *) exit 1;; esac\n')
            gcloud.chmod(0o755)
            antes = os.environ['PATH']
            os.environ['PATH'] = f'{temporal}:{antes}'
            try:
                self.assertEqual(boveda.leer_credencial('typesafe'), 'clave-falsa-123')
                with self.assertRaises(LookupError):
                    boveda.leer_credencial('no-existe')
            finally:
                os.environ['PATH'] = antes


if __name__ == '__main__':
    unittest.main()


class IlegiblesExcesivosTest(unittest.TestCase):
    """El guardarraíl del corrector contra páginas declaradas ilegibles enteras."""

    def cargar(self, carpeta):
        import importlib.util
        fuente = (RAIZ / 'pasos' / 'pre-ollama.py').read_text(encoding='utf-8')
        fuente = fuente[:fuente.rindex('\nif args.check:')]
        espacio = {'__file__': str(RAIZ / 'pasos' / 'pre-ollama.py'), '__name__': 'preollama'}
        argv = sys.argv
        sys.argv = ['pre-ollama.py', '--f', str(carpeta), '--m', 'claude', '--dryrun']
        try:
            exec(compile(fuente, 'pre-ollama.py', 'exec'), espacio)
        finally:
            sys.argv = argv
        return espacio

    def test_rechaza_pagina_entera_y_respeta_dudas_reales(self):
        with tempfile.TemporaryDirectory() as temporal:
            carpeta = Path(temporal)
            (carpeta / 'informes').mkdir()
            (carpeta / 'informes' / 'pag_7.fusion.json').write_text(json.dumps({'dudosos_fusion': 0}))
            (carpeta / 'informes' / 'pag_8.fusion.json').write_text(json.dumps({'dudosos_fusion': 6}))
            m = self.cargar(carpeta)
            borrador = 'Un texto de página con varias líneas bien leídas por el OCR.\n' * 10
            entera = ' '.join(['[ilegible]'] * 20)
            excesivo, marcas, dudosos = m['ilegibles_excesivos'](carpeta / 'pag_7.txt', borrador, entera)
            self.assertTrue(excesivo); self.assertEqual((marcas, dudosos), (20, 0))
            # con seis renglones dudosos, catorce marcas son creíbles; veinte no
            self.assertFalse(m['ilegibles_excesivos'](carpeta / 'pag_8.txt', borrador, ' '.join(['[ilegible]'] * 14))[0])
            self.assertTrue(m['ilegibles_excesivos'](carpeta / 'pag_8.txt', borrador, ' '.join(['[ilegible]'] * 20))[0])
            # pocas marcas nunca se rechazan, y sin informe manda el borrador
            self.assertFalse(m['ilegibles_excesivos'](carpeta / 'pag_7.txt', borrador, 'texto [ilegible] más [ilegible]')[0])
            self.assertFalse(m['ilegibles_excesivos'](carpeta / 'pag_9.txt', borrador + ' [ilegible]' * 5, ' '.join(['[ilegible]'] * 12))[0])


class InjertoTest(unittest.TestCase):
    """El injerto del borrador en los tramos que el agente marcó ilegibles."""

    def test_rellena_solo_lo_marcado_y_conserva_parrafos(self):
        fuente = (RAIZ / 'pasos' / 'pre-ollama.py').read_text(encoding='utf-8')
        fuente = fuente[:fuente.rindex('\nif args.check:')]
        espacio = {'__file__': str(RAIZ / 'pasos' / 'pre-ollama.py'), '__name__': 'preollama'}
        argv = sys.argv
        sys.argv = ['pre-ollama.py', '--f', '.', '--m', 'claude', '--dryrun']
        try:
            exec(compile(fuente, 'pre-ollama.py', 'exec'), espacio)
        finally:
            sys.argv = argv
        borrador = ('El cura Manuel le expuso su caso punto por punto. El Obispo no dejaba de manifestar su asombro, '
                    'pero seguia escuchando atentamente.\nSe hicieron los trámites de rigor y un día llegó la misiva del Papa.')
        agente = ('El cura Manuel le expuso su caso punto por punto. El Obispo no dejaba de manifestar su [ilegible], '
                  'pero seguía escuchando [ilegible].\n\nSe hicieron los trámites [ilegible] y un día llegó la misiva del Papa. [ilegible]')
        texto, injertos = espacio['injertar_borrador'](borrador, agente)
        self.assertEqual(injertos, 4)
        self.assertNotIn('[ilegible]', texto)
        self.assertIn('manifestar su asombro,', texto)          # relleno del OCR
        self.assertIn('pero seguía escuchando atentamente.', texto)  # la tilde la puso el agente, el resto el OCR
        self.assertIn('los trámites de rigor y', texto)
        self.assertEqual(texto.count('\n\n'), 1, texto)          # el párrafo del agente se conserva
        self.assertTrue(texto.endswith('misiva del Papa.'))     # la marca suelta del final desaparece
