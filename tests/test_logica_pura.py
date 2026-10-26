"""Pruebas de lógica pura: limpieza determinista, estimación, guardarraíles del corrector
y autodetección de modelos. Sin red, sin credenciales y sin servicios externos."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from nucleo import limpieza, estimacion, ollama_local, agentes, gemini, gcp  # noqa: E402


def cargar_pre_ollama(modelo='modelo-local-de-prueba'):
    """Carga pre-ollama.py hasta antes de su ejecución, como hacen las demás suites."""
    fuente = (RAIZ / 'pasos' / 'pre-ollama.py').read_text(encoding='utf-8')
    fuente = fuente[:fuente.rindex('\nif args.check:')]
    espacio = {'__file__': str(RAIZ / 'pasos' / 'pre-ollama.py'), '__name__': 'preollama'}
    argv = sys.argv
    sys.argv = ['pre-ollama.py', '--f', '.', '--m', modelo, '--dryrun']
    try:
        exec(compile(fuente, 'pre-ollama.py', 'exec'), espacio)
    finally:
        sys.argv = argv
    return espacio


class AbreviaturasTest(unittest.TestCase):
    def test_tabla_espanol(self):
        texto = limpieza.expandir_abreviaturas('El Dr. Pérez & la Sra. Ruiz, etc. Luego', 'es')
        self.assertIn('doctor Pérez', texto)
        self.assertIn('señora Ruiz', texto)
        self.assertIn(' y ', texto)
        self.assertIn('etcétera.', texto)

    def test_tabla_ingles_distingue_saint_y_street(self):
        texto = limpieza.expandir_abreviaturas('Mr. Holmes lives on Baker St. near St. Mary', 'en')
        self.assertIn('Mister Holmes', texto)
        self.assertIn('Baker Street', texto)
        self.assertIn('Saint Mary', texto)

    def test_idioma_sin_tabla_no_toca_el_texto(self):
        self.assertEqual(limpieza.expandir_abreviaturas('Dr. X & Y', 'fr'), 'Dr. X & Y')


class SaltosDeLineaTest(unittest.TestCase):
    def test_titulo_y_atribucion_conservan_el_corte_con_punto(self):
        texto = limpieza.puntuar_lineas('DÍA 42\n«La libertad».\nWilliam Wallace (Braveheart)')
        self.assertEqual(texto.split('\n\n'), ['DÍA 42.', '«La libertad».', 'William Wallace (Braveheart)'])

    def test_renglon_siguiente_en_minuscula_se_une(self):
        self.assertEqual(limpieza.puntuar_lineas('la casa estaba\nvacía y fría.'), 'la casa estaba vacía y fría.')

    def test_palabra_partida_por_guion_se_une(self):
        self.assertEqual(limpieza.limpiar_texto('El Dr. Pérez lle-\ngó tarde.\n'), 'El doctor Pérez llegó tarde.\n')


class FoliosYGuionesTest(unittest.TestCase):
    def test_quita_folios_aislados(self):
        texto = limpieza.quitar_numeros_pagina('16\nTexto de la página que sigue aquí.\nOtra línea\n- 17 -')
        self.assertEqual(texto, 'Texto de la página que sigue aquí.\nOtra línea')

    def test_inciso_entre_rayas_y_palabra_partida(self):
        texto = limpieza.arreglar_guiones('dijo -sin mirarme- que fa- llones')
        self.assertIn('sin mirarme,', texto)
        self.assertIn('fallones', texto)

    def test_pausas_conserva_suspensivos_y_colapsa_dobles(self):
        self.assertEqual(limpieza.normalizar_pausas('uno\ndos\n\n\ntres...  cuatro..'), 'uno dos\n\ntres... cuatro.')

    def test_colapsa_palabra_repetida_por_un_modelo_en_bucle(self):
        self.assertEqual(limpieza.colapsar_repeticiones('hola hola hola hola mundo'), 'hola mundo')


class EstimacionTest(unittest.TestCase):
    def test_parsear_paginas(self):
        self.assertEqual(estimacion.parsear_paginas('1-3, 5, 99', 10), [0, 1, 2, 4])
        self.assertEqual(estimacion.parsear_paginas('', 3), [0, 1, 2])

    def test_formatear_duracion(self):
        self.assertEqual(estimacion.formatear_duracion(45), '45 s')
        self.assertEqual(estimacion.formatear_duracion(125), '2 min 05 s')
        self.assertEqual(estimacion.formatear_duracion(7380), '2 h 03 min')

    def test_vision_descuenta_la_franquicia_gratuita(self):
        ritmos = estimacion.RITMOS
        calculo = estimacion.estimar(10, 20000, usar_ocr=True, motor_ocr='Google Cloud Vision', vision_gratis=4)
        ocr = next(e for e in calculo['etapas'] if e['etapa'] == 'OCR de Google Vision')
        self.assertAlmostEqual(ocr['coste'], 6 / 1000 * ritmos['vision_usd_por_1000'])
        self.assertEqual(calculo['audio_segundos'], 0)

    def test_motores_gratuitos_cuestan_cero_y_gemini_cobra(self):
        gratis = estimacion.estimar(10, 20000, nivel_limpieza='Reglas + corrección con LLM', motor_tts='Microsoft Edge')
        self.assertEqual(gratis['coste'], 0)
        self.assertAlmostEqual(gratis['audio_segundos'], 20000 / estimacion.RITMOS['audio_caracteres_s'])
        con_gemini = estimacion.estimar(10, 20000, nivel_limpieza='Solo corrección con LLM', llm_modelo='gemini-2.5-flash')
        precio = estimacion.CONFIG['GoogleLLM']['usd_por_1000_car']['gemini-2.5-flash']
        self.assertAlmostEqual(con_gemini['coste'], 20 * precio)
        self.assertNotIn('Limpieza determinista', [e['etapa'] for e in con_gemini['etapas']])

    def test_voz_de_google_cobra_por_caracter_segun_el_tipo(self):
        calculo = estimacion.estimar(1, 1000, motor_tts='Google Cloud', voz_gcp='en-US-Wavenet-C')
        precio = estimacion.CONFIG['TextToSpeechAPI']['Pricing']['WaveNet']
        self.assertAlmostEqual(calculo['coste'], 1000 * precio)

    def test_suma_de_etapas(self):
        calculo = estimacion.estimar(5, 9000, nivel_limpieza='Solo reglas deterministas', motor_tts='macOS local',
                                     por_divisiones=True)
        self.assertAlmostEqual(calculo['segundos'], sum(e['segundos'] for e in calculo['etapas']))


class GuardarrailesCorrectorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = cargar_pre_ollama()

    def test_trozos_no_superan_el_maximo_ni_parten_frases(self):
        texto = ('Primera frase del párrafo. ' * 30).strip() + '\n\n' + 'Otro párrafo corto.'
        trozos = self.m['dividir_en_trozos'](texto, 200)
        self.assertTrue(all(len(t) <= 200 for t in trozos))
        self.assertTrue(all(t.rstrip().endswith('.') for t in trozos))
        self.assertEqual(' '.join(' '.join(trozos).split()), ' '.join(texto.split()))

    def test_validar_acepta_reparacion_y_rechaza_invencion(self):
        original = 'El cura le expuso su caso pun to por punto y el obispo escuchaba con atención.'
        reparado = 'El cura le expuso su caso punto por punto y el obispo escuchaba con atención.'
        self.assertTrue(self.m['validar'](original, reparado)[0])
        inventado = 'Una historia distinta sobre dragones, castillos y caballeros que nadie había escrito.'
        self.assertFalse(self.m['validar'](original, inventado)[0])
        self.assertFalse(self.m['validar'](original, '')[0])

    def test_limpiar_respuesta_quita_preambulo_y_markdown(self):
        respuesta = 'Aquí está el texto corregido:\n**Hola** mundo\nsigue la frase.'
        self.assertEqual(self.m['limpiar_respuesta'](respuesta), 'Hola mundo sigue la frase.')


class ModelosTest(unittest.TestCase):
    MODELOS = [
        {'nombre': 'texto-grande', 'capacidades': ['completion'], 'familia': 'qwen', 'tamano': 30},
        {'nombre': 'texto-chico', 'capacidades': ['completion'], 'familia': 'qwen', 'tamano': 5},
        {'nombre': 'lector-ocr', 'capacidades': ['completion'], 'familia': 'deepseekocr', 'tamano': 3},
        {'nombre': 'vista', 'capacidades': ['completion', 'vision'], 'familia': 'gemma', 'tamano': 10},
    ]

    def test_orden_de_candidatos_por_tarea(self):
        with mock.patch.object(ollama_local, 'listar_modelos', return_value=self.MODELOS):
            self.assertEqual(ollama_local.modelos_para('http://x', 'ocr'), ['lector-ocr', 'vista'])
            self.assertEqual(ollama_local.modelos_para('http://x', 'texto'), ['texto-grande', 'vista', 'texto-chico'])
            self.assertEqual(ollama_local.modelos_para('http://x', 'figuras'), ['vista'])

    def test_elegir_modelo_autodetecta_si_falta_el_pedido(self):
        with mock.patch.object(ollama_local, 'listar_modelos', return_value=self.MODELOS):
            self.assertEqual(ollama_local.elegir_modelo('http://x', 'texto-chico', 'texto'), ('texto-chico', False))
            self.assertEqual(ollama_local.elegir_modelo('http://x', 'no-instalado', 'texto'), ('texto-grande', True))
        with mock.patch.object(ollama_local, 'listar_modelos', return_value=[]):
            with self.assertRaises(RuntimeError):
                ollama_local.elegir_modelo('http://x', 'cualquiera', 'texto')

    def test_clasificacion_de_motores(self):
        self.assertTrue(agentes.es_agente('claude'))
        self.assertFalse(agentes.es_agente('gemini-2.5-flash'))
        self.assertTrue(gemini.es_modelo_google('gemini-2.5-flash'))
        self.assertFalse(gemini.es_modelo_google('qwen3.8:27b-mlx'))
        self.assertFalse(gemini.es_modelo_google(None))


class CredencialesGoogleTest(unittest.TestCase):
    def setUp(self):
        self.antes = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')

    def tearDown(self):
        if self.antes is None:
            os.environ.pop('GOOGLE_APPLICATION_CREDENTIALS', None)
        else:
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = self.antes

    def test_llave_explicita_manda_y_una_inexistente_falla(self):
        with tempfile.NamedTemporaryFile(suffix='.json') as llave:
            self.assertTrue(gcp.preparar_credenciales(llave.name).startswith('llave JSON'))
            self.assertEqual(os.environ['GOOGLE_APPLICATION_CREDENTIALS'], str(Path(llave.name)))
        with self.assertRaises(FileNotFoundError):
            gcp.preparar_credenciales('/ruta/que/no/existe.json')

    def test_variable_valida_se_respeta(self):
        with tempfile.NamedTemporaryFile(suffix='.json') as llave:
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = llave.name
            self.assertTrue(gcp.preparar_credenciales().startswith('variable GOOGLE_APPLICATION_CREDENTIALS'))


if __name__ == '__main__':
    unittest.main()
